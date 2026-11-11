import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# Versión del esquema. Cada vez que se agregan columnas o tablas nuevas se sube
# este número. Se guarda dentro del propio archivo .db (PRAGMA user_version).
SCHEMA_VERSION = 2

DEFAULT_DB_PATH = "portfolio_data.db"


class DuplicateIncomeError(ValueError):
    """Se intentó registrar dos veces el mismo dividendo o interés."""


class Database:
    """Crea las tablas y centraliza el acceso a SQLite.

    Reglas de seguridad de los datos:
    * Nunca borra tablas ni registros.
    * Las migraciones solo AGREGAN columnas o tablas.
    * Antes de migrar una base que ya existe, guarda una copia de seguridad
      en la carpeta ``backups`` (junto al archivo .db).
    """

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.environ.get("PORTFOLIO_DB_PATH", DEFAULT_DB_PATH)
        self.db_path = str(db_path)
        self.last_backup_path = None
        self.initialize()

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------
    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # Copias de seguridad
    # ------------------------------------------------------------------
    def backup(self, label="manual"):
        """Guarda una copia completa de la base en ``backups/``. Devuelve la ruta."""
        source = Path(self.db_path)
        if not source.exists() or source.stat().st_size == 0:
            return None
        folder = source.resolve().parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = folder / f"{source.stem}_{label}_{stamp}.db"
        counter = 1
        while target.exists():
            target = folder / f"{source.stem}_{label}_{stamp}_{counter}.db"
            counter += 1
        origin = sqlite3.connect(self.db_path)
        destination = sqlite3.connect(str(target))
        try:
            origin.backup(destination)  # copia consistente aunque la base esté en uso
        finally:
            destination.close()
            origin.close()
        self.last_backup_path = str(target)
        return str(target)

    def _needs_migration(self):
        """True si el archivo ya existe, tiene tablas y su versión es anterior."""
        path = Path(self.db_path)
        if not path.exists() or path.stat().st_size == 0:
            return False
        con = sqlite3.connect(self.db_path)
        try:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            tables = con.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
        finally:
            con.close()
        return tables > 0 and version < SCHEMA_VERSION

    # ------------------------------------------------------------------
    # Creación y migración del esquema
    # ------------------------------------------------------------------
    @staticmethod
    def _columns(con, table):
        return {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}

    def _add_column_if_missing(self, con, table, column, definition):
        if column not in self._columns(con, table):
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def initialize(self):
        if self._needs_migration():
            self.backup(label="antes_de_migrar")

        with self.connect() as con:
            # --- Tablas originales (no se modifican; solo se crean si faltan) ---
            con.executescript("""
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                currency TEXT NOT NULL,
                market TEXT NOT NULL,
                current_price REAL NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'Manual'
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER NOT NULL,
                operation TEXT NOT NULL CHECK(operation IN ('COMPRA','VENTA')),
                date TEXT NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                price REAL NOT NULL CHECK(price >= 0),
                commission REAL NOT NULL DEFAULT 0 CHECK(commission >= 0),
                FOREIGN KEY(asset_id) REFERENCES assets(id)
            );
            CREATE TABLE IF NOT EXISTS income_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER NOT NULL,
                event_type TEXT NOT NULL CHECK(event_type IN ('DIVIDENDO','INTERES')),
                date TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount >= 0),
                description TEXT DEFAULT '',
                FOREIGN KEY(asset_id) REFERENCES assets(id)
            );
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                price REAL NOT NULL CHECK(price >= 0),
                source TEXT NOT NULL,
                FOREIGN KEY(asset_id) REFERENCES assets(id)
            );
            CREATE TABLE IF NOT EXISTS fixed_income_terms (
                asset_id INTEGER PRIMARY KEY,
                annual_rate_pct REAL NOT NULL,
                rate_type TEXT NOT NULL,
                issue_date TEXT NOT NULL,
                maturity_date TEXT NOT NULL,
                payment_frequency TEXT NOT NULL,
                nominal_value REAL NOT NULL,
                notes TEXT DEFAULT '',
                FOREIGN KEY(asset_id) REFERENCES assets(id)
            );
            CREATE TABLE IF NOT EXISTS asset_fee_settings (
                asset_id INTEGER PRIMARY KEY,
                fee_pct REAL NOT NULL DEFAULT 0,
                FOREIGN KEY(asset_id) REFERENCES assets(id)
            );
            -- --- Tablas nuevas (versión 2) ---
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS fx_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                rate REAL NOT NULL CHECK(rate > 0),
                rate_date TEXT NOT NULL,
                source TEXT NOT NULL,
                fetched_at TEXT
            );
            """)

            # --- Columnas nuevas en tablas existentes (solo se agregan) ---
            self._add_column_if_missing(con, "assets", "price_date", "TEXT")
            self._add_column_if_missing(con, "assets", "yahoo_symbol", "TEXT")
            self._add_column_if_missing(con, "transactions", "commission_source",
                                        "TEXT NOT NULL DEFAULT 'SIN_DATO'")
            self._add_column_if_missing(con, "transactions", "notes", "TEXT DEFAULT ''")
            self._add_column_if_missing(con, "income_events", "withholding",
                                        "REAL NOT NULL DEFAULT 0")
            self._add_column_if_missing(con, "income_events", "fees",
                                        "REAL NOT NULL DEFAULT 0")
            self._add_column_if_missing(con, "price_history", "fetched_at", "TEXT")

            # --- Rellenos seguros de datos antiguos ---
            # Precio sin fecha: se toma la fecha del último registro del historial.
            con.execute("""
                UPDATE assets SET price_date = (
                    SELECT MAX(p.date) FROM price_history p WHERE p.asset_id = assets.id
                )
                WHERE price_date IS NULL AND current_price > 0
            """)
            # Los tres símbolos que la app ya consultaba con yfinance.
            con.execute("""
                UPDATE assets SET yahoo_symbol = symbol
                WHERE yahoo_symbol IS NULL AND currency = 'USD'
                  AND asset_type = 'ACCION' AND symbol IN ('AMZN','KO','NKE')
            """)

            # Base completamente nueva: solo las 4 empresas del proyecto, SIN precio
            # (queda "pendiente" hasta que haya una cotización real) y sin ejemplos falsos.
            count = con.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
            if count == 0:
                initial_assets = [
                    ("Bancolombia", "BCOLOMBIA (manual)", "ACCION", "COP", "BVC", None),
                    ("Amazon", "AMZN", "ACCION", "USD", "NASDAQ", "AMZN"),
                    ("The Coca-Cola Company", "KO", "ACCION", "USD", "NYSE", "KO"),
                    ("Nike", "NKE", "ACCION", "USD", "NYSE", "NKE"),
                ]
                con.executemany("""
                    INSERT INTO assets(name,symbol,asset_type,currency,market,
                                       current_price,source,yahoo_symbol)
                    VALUES(?,?,?,?,?,0,'Sin cotización',?)
                """, [(n, s, t, c, m, y) for n, s, t, c, m, y in initial_assets])

            con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # ------------------------------------------------------------------
    # Activos
    # ------------------------------------------------------------------
    def get_assets(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM assets ORDER BY id")]

    def get_asset(self, asset_id):
        with self.connect() as con:
            row = con.execute("SELECT * FROM assets WHERE id=?", (int(asset_id),)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _insert_asset(con, name, symbol, asset_type, currency, market,
                      current_price=0, source="Manual", price_date=None, yahoo_symbol=None):
        cur = con.execute("""
            INSERT INTO assets(name,symbol,asset_type,currency,market,current_price,
                               source,price_date,yahoo_symbol)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (name, symbol, asset_type, currency, market, float(current_price or 0),
              source, price_date, yahoo_symbol))
        return cur.lastrowid

    def add_asset(self, name, symbol, asset_type, currency, market,
                  current_price=0, source="Manual", price_date=None, yahoo_symbol=None):
        """Crea un activo y devuelve su id."""
        with self.connect() as con:
            return self._insert_asset(con, name, symbol, asset_type, currency, market,
                                      current_price, source, price_date, yahoo_symbol)

    def set_yahoo_symbol(self, asset_id, yahoo_symbol):
        with self.connect() as con:
            con.execute("UPDATE assets SET yahoo_symbol=? WHERE id=?",
                        (yahoo_symbol or None, int(asset_id)))

    def update_price(self, asset_id, price, source, date, fetched_at=None):
        """Guarda una cotización real con su fuente y fecha. El precio debe ser > 0."""
        price = float(price)
        if not price > 0:
            raise ValueError("El precio debe ser mayor que cero. Un precio faltante "
                             "no se registra como cero.")
        fetched_at = fetched_at or datetime.now().isoformat(timespec="seconds")
        with self.connect() as con:
            con.execute("UPDATE assets SET current_price=?, source=?, price_date=? WHERE id=?",
                        (price, source, date, int(asset_id)))
            con.execute("""
                INSERT INTO price_history(asset_id,date,price,source,fetched_at)
                VALUES(?,?,?,?,?)
            """, (int(asset_id), date, price, source, fetched_at))

    # ------------------------------------------------------------------
    # Operaciones
    # ------------------------------------------------------------------
    @staticmethod
    def _insert_transaction(con, asset_id, operation, date, quantity, price, commission,
                            commission_source="ESTIMADA", notes=""):
        cur = con.execute("""
            INSERT INTO transactions(asset_id,operation,date,quantity,price,commission,
                                     commission_source,notes)
            VALUES(?,?,?,?,?,?,?,?)
        """, (int(asset_id), operation, date, float(quantity), float(price),
              float(commission), commission_source, notes or ""))
        return cur.lastrowid

    def add_transaction(self, asset_id, operation, date, quantity, price, commission,
                        commission_source="ESTIMADA", notes=""):
        with self.connect() as con:
            return self._insert_transaction(con, asset_id, operation, date, quantity,
                                            price, commission, commission_source, notes)

    def add_asset_and_transaction(self, asset, transaction):
        """Crea una empresa nueva y su primera operación en un solo paso.

        Si algo falla, no queda guardada ni la empresa ni la operación.
        ``asset`` y ``transaction`` son diccionarios con los argumentos de
        ``_insert_asset`` y ``_insert_transaction`` (sin asset_id).
        """
        with self.connect() as con:
            asset_id = self._insert_asset(con, **asset)
            tx_id = self._insert_transaction(con, asset_id, **transaction)
            return asset_id, tx_id

    def add_fixed_income_investment(self, name, symbol, asset_type, market, capital,
                                    annual_rate, rate_type, opened, maturity, frequency,
                                    notes="", currency="COP"):
        """Registra un CDT/TES/bono: activo + condiciones + compra, todo junto."""
        with self.connect() as con:
            asset_id = self._insert_asset(
                con, name, symbol, asset_type, currency, market, float(capital),
                "Capital registrado por el inversionista", opened)
            con.execute("""
                INSERT INTO fixed_income_terms(
                    asset_id,annual_rate_pct,rate_type,issue_date,maturity_date,
                    payment_frequency,nominal_value,notes
                ) VALUES(?,?,?,?,?,?,?,?)
            """, (asset_id, annual_rate, rate_type, opened, maturity, frequency,
                  float(capital), notes))
            self._insert_transaction(con, asset_id, "COMPRA", opened, 1.0, capital, 0.0,
                                     "SIN_COMISION", "Capital inicial")
            return asset_id

    def update_transaction_commission(self, transaction_id, commission,
                                      source="COMPROBANTE"):
        """Corrige la comisión de una operación con el valor real del comprobante."""
        commission = float(commission)
        if commission < 0:
            raise ValueError("La comisión no puede ser negativa.")
        with self.connect() as con:
            cur = con.execute(
                "UPDATE transactions SET commission=?, commission_source=? WHERE id=?",
                (commission, source, int(transaction_id)))
            if cur.rowcount == 0:
                raise ValueError("No existe esa operación.")

    def get_transactions(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("""
                SELECT t.*, a.name AS asset_name, a.currency
                FROM transactions t JOIN assets a ON a.id=t.asset_id
                ORDER BY t.date, t.id
            """)]

    # ------------------------------------------------------------------
    # Dividendos e intereses
    # ------------------------------------------------------------------
    def add_income(self, asset_id, event_type, date, amount, description,
                   withholding=0.0, fees=0.0, allow_duplicate=False):
        """Registra un dividendo o interés.

        ``amount`` es el valor BRUTO. Lo recibido neto es amount - withholding - fees.
        Si ya existe un pago igual (mismo activo, tipo, fecha y valor) lanza
        DuplicateIncomeError, para no contarlo dos veces.
        """
        amount, withholding, fees = float(amount), float(withholding or 0), float(fees or 0)
        if amount <= 0:
            raise ValueError("El valor debe ser mayor que cero.")
        if withholding < 0 or fees < 0:
            raise ValueError("La retención y los costos no pueden ser negativos.")
        if withholding + fees > amount + 1e-9:
            raise ValueError("La retención y los costos no pueden superar el valor bruto.")
        with self.connect() as con:
            if not allow_duplicate:
                existing = con.execute("""
                    SELECT id FROM income_events
                    WHERE asset_id=? AND event_type=? AND date=? AND ABS(amount-?) < 0.005
                """, (int(asset_id), event_type, date, amount)).fetchone()
                if existing:
                    raise DuplicateIncomeError(
                        "Ya hay un ingreso igual (mismo activo, tipo, fecha y valor). "
                        "No se guardó para no contarlo dos veces.")
            cur = con.execute("""
                INSERT INTO income_events(asset_id,event_type,date,amount,description,
                                          withholding,fees)
                VALUES(?,?,?,?,?,?,?)
            """, (int(asset_id), event_type, date, amount, description or "",
                  withholding, fees))
            return cur.lastrowid

    def update_income_costs(self, income_id, withholding, fees):
        """Corrige retención y costos de un dividendo/interés con los valores del comprobante."""
        withholding, fees = float(withholding), float(fees)
        if withholding < 0 or fees < 0:
            raise ValueError("La retención y los costos no pueden ser negativos.")
        with self.connect() as con:
            row = con.execute("SELECT amount FROM income_events WHERE id=?",
                              (int(income_id),)).fetchone()
            if row is None:
                raise ValueError("No existe ese ingreso.")
            if withholding + fees > float(row["amount"]) + 1e-9:
                raise ValueError("La retención y los costos no pueden superar el valor bruto.")
            con.execute("UPDATE income_events SET withholding=?, fees=? WHERE id=?",
                        (withholding, fees, int(income_id)))

    def get_income_events(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("""
                SELECT e.*, a.name AS asset_name, a.currency,
                       (e.amount - e.withholding - e.fees) AS net_amount
                FROM income_events e JOIN assets a ON a.id=e.asset_id
                ORDER BY e.date, e.id
            """)]

    # ------------------------------------------------------------------
    # Historial de precios, renta fija y comisiones por empresa
    # ------------------------------------------------------------------
    def get_price_history(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("""
                SELECT p.*, a.name AS asset_name
                FROM price_history p JOIN assets a ON a.id=p.asset_id
                ORDER BY p.date, p.id
            """)]

    def save_fixed_income_terms(self, asset_id, annual_rate_pct, rate_type,
                                issue_date, maturity_date, payment_frequency,
                                nominal_value, notes=""):
        with self.connect() as con:
            con.execute("""
                INSERT INTO fixed_income_terms(
                    asset_id,annual_rate_pct,rate_type,issue_date,maturity_date,
                    payment_frequency,nominal_value,notes
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    annual_rate_pct=excluded.annual_rate_pct,
                    rate_type=excluded.rate_type,
                    issue_date=excluded.issue_date,
                    maturity_date=excluded.maturity_date,
                    payment_frequency=excluded.payment_frequency,
                    nominal_value=excluded.nominal_value,
                    notes=excluded.notes
            """, (asset_id, annual_rate_pct, rate_type, issue_date,
                  maturity_date, payment_frequency, nominal_value, notes))

    def get_fixed_income_terms(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("""
                SELECT f.*, a.name AS asset_name, a.asset_type
                FROM fixed_income_terms f
                JOIN assets a ON a.id=f.asset_id
                ORDER BY a.name
            """)]

    def get_fee_settings(self):
        """Porcentajes personalizados por empresa (anulan el plan general)."""
        with self.connect() as con:
            return {int(r["asset_id"]): float(r["fee_pct"])
                    for r in con.execute("SELECT asset_id, fee_pct FROM asset_fee_settings")}

    def save_fee_setting(self, asset_id, fee_pct):
        with self.connect() as con:
            con.execute("""
                INSERT INTO asset_fee_settings(asset_id, fee_pct) VALUES(?,?)
                ON CONFLICT(asset_id) DO UPDATE SET fee_pct=excluded.fee_pct
            """, (int(asset_id), float(fee_pct)))

    def delete_fee_setting(self, asset_id):
        """Quita el porcentaje personalizado de una empresa (no toca operaciones)."""
        with self.connect() as con:
            con.execute("DELETE FROM asset_fee_settings WHERE asset_id=?", (int(asset_id),))

    # ------------------------------------------------------------------
    # Configuración general y tasa de cambio
    # ------------------------------------------------------------------
    def get_setting(self, key, default=None):
        with self.connect() as con:
            row = con.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key, value):
        with self.connect() as con:
            con.execute("""
                INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """, (key, str(value), datetime.now().isoformat(timespec="seconds")))

    def get_json_setting(self, key, default=None):
        raw = self.get_setting(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except ValueError:
            return default

    def set_json_setting(self, key, value):
        self.set_setting(key, json.dumps(value, ensure_ascii=False))

    def save_fx_rate(self, rate, rate_date, source, pair="USD/COP"):
        rate = float(rate)
        if not rate > 0:
            raise ValueError("La tasa de cambio debe ser mayor que cero.")
        with self.connect() as con:
            con.execute("""
                INSERT INTO fx_rates(pair,rate,rate_date,source,fetched_at)
                VALUES(?,?,?,?,?)
            """, (pair, rate, rate_date, source, datetime.now().isoformat(timespec="seconds")))

    def get_latest_fx_rate(self, pair="USD/COP"):
        """Última tasa guardada (con su fuente y fecha) o None si nunca se guardó."""
        with self.connect() as con:
            row = con.execute("""
                SELECT * FROM fx_rates WHERE pair=? ORDER BY rate_date DESC, id DESC LIMIT 1
            """, (pair,)).fetchone()
            return dict(row) if row else None

    def get_fx_history(self, pair="USD/COP"):
        with self.connect() as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM fx_rates WHERE pair=? ORDER BY rate_date, id", (pair,))]
