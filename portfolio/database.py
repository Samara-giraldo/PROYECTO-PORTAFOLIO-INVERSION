import sqlite3
import math
from contextlib import contextmanager


class Database:
    """
    Gestiona la base de datos SQLite del portafolio.

    Importante:
    - No elimina inversiones ni operaciones existentes.
    - Crea las tablas que falten.
    - Mantiene compatibilidad con la aplicación actual.
    """

    def __init__(self, db_path="portfolio_data.db"):
        self.db_path = str(db_path)
        self.initialize()

    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def connection(self):
        con = self.connect()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _number(value, field_name):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"El campo {field_name} debe ser numérico.")

        if not math.isfinite(number):
            raise ValueError(f"El campo {field_name} no es válido.")

        return number

    def initialize(self):
        with self.connection() as con:
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
                    operation TEXT NOT NULL
                        CHECK(operation IN ('COMPRA', 'VENTA')),
                    date TEXT NOT NULL,
                    quantity REAL NOT NULL CHECK(quantity > 0),
                    price REAL NOT NULL CHECK(price >= 0),
                    commission REAL NOT NULL DEFAULT 0
                        CHECK(commission >= 0),
                    FOREIGN KEY(asset_id) REFERENCES assets(id)
                );

                CREATE TABLE IF NOT EXISTS income_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL
                        CHECK(event_type IN ('DIVIDENDO', 'INTERES')),
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
            """)

            count = con.execute(
                "SELECT COUNT(*) FROM assets"
            ).fetchone()[0]

            # Solo crea activos de ejemplo si la tabla está vacía.
            # Nunca reemplaza ni elimina activos existentes.
            if count == 0:
                initial_assets = [
                    (
                        "Bancolombia",
                        "BCOLOMBIA (manual)",
                        "ACCION",
                        "COP",
                        "BVC",
                        0,
                        "Cotización local ingresada por el usuario"
                    ),
                    (
                        "Amazon",
                        "AMZN",
                        "ACCION",
                        "USD",
                        "NASDAQ",
                        0,
                        "Yahoo Finance mediante yfinance"
                    ),
                    (
                        "The Coca-Cola Company",
                        "KO",
                        "ACCION",
                        "USD",
                        "NYSE",
                        0,
                        "Yahoo Finance mediante yfinance"
                    ),
                    (
                        "Nike",
                        "NKE",
                        "ACCION",
                        "USD",
                        "NYSE",
                        0,
                        "Yahoo Finance mediante yfinance"
                    ),
                    (
                        "CDT de ejemplo",
                        "CDT-001",
                        "CDT",
                        "COP",
                        "Entidad financiera",
                        0,
                        "Datos contractuales ingresados por el usuario"
                    ),
                    (
                        "Bono de ejemplo",
                        "BONO-001",
                        "BONO",
                        "COP",
                        "Mercado de deuda",
                        0,
                        "Datos contractuales ingresados por el usuario"
                    ),
                    (
                        "TES de ejemplo",
                        "TES-001",
                        "TES",
                        "COP",
                        "Gobierno de Colombia",
                        0,
                        "Datos contractuales ingresados por el usuario"
                    ),
                ]

                con.executemany("""
                    INSERT INTO assets (
                        name,
                        symbol,
                        asset_type,
                        currency,
                        market,
                        current_price,
                        source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, initial_assets)

    def get_assets(self):
        with self.connection() as con:
            rows = con.execute("""
                SELECT *
                FROM assets
                ORDER BY id
            """).fetchall()

            return [dict(row) for row in rows]

    def add_asset(
        self,
        name,
        symbol,
        asset_type,
        currency,
        market,
        current_price=0,
        source="Manual"
    ):
        name = str(name).strip()
        symbol = str(symbol).strip().upper()
        current_price = self._number(current_price, "precio")

        if not name or not symbol:
            raise ValueError("El nombre y el símbolo son obligatorios.")

        if current_price < 0:
            raise ValueError("El precio no puede ser negativo.")

        with self.connection() as con:
            cursor = con.execute("""
                INSERT INTO assets (
                    name,
                    symbol,
                    asset_type,
                    currency,
                    market,
                    current_price,
                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                name,
                symbol,
                asset_type,
                currency,
                market,
                current_price,
                source
            ))

            return cursor.lastrowid

    def update_price(self, asset_id, price, source, date):
        price = self._number(price, "precio")

        if price < 0:
            raise ValueError("El precio no puede ser negativo.")

        with self.connection() as con:
            cursor = con.execute("""
                UPDATE assets
                SET current_price = ?, source = ?
                WHERE id = ?
            """, (price, str(source), int(asset_id)))

            if cursor.rowcount == 0:
                raise ValueError("No se encontró el activo seleccionado.")

            con.execute("""
                INSERT INTO price_history (
                    asset_id,
                    date,
                    price,
                    source
                )
                VALUES (?, ?, ?, ?)
            """, (
                int(asset_id),
                str(date),
                price,
                str(source)
            ))

    def get_transactions_for_asset(self, asset_id):
        with self.connection() as con:
            rows = con.execute("""
                SELECT *
                FROM transactions
                WHERE asset_id = ?
                ORDER BY date, id
            """, (int(asset_id),)).fetchall()

            return [dict(row) for row in rows]

    def add_transaction(
        self,
        asset_id,
        operation,
        date,
        quantity,
        price,
        commission
    ):
        operation = str(operation).upper()
        quantity = self._number(quantity, "cantidad")
        price = self._number(price, "precio")
        commission = self._number(commission, "comisión")

        if operation not in ("COMPRA", "VENTA"):
            raise ValueError("La operación debe ser COMPRA o VENTA.")

        if quantity <= 0:
            raise ValueError("La cantidad debe ser mayor que cero.")

        if price < 0 or commission < 0:
            raise ValueError("El precio y la comisión no pueden ser negativos.")

        asset_id = int(asset_id)

        with self.connection() as con:
            asset = con.execute(
                "SELECT id FROM assets WHERE id = ?",
                (asset_id,)
            ).fetchone()

            if asset is None:
                raise ValueError("El activo seleccionado no existe.")

            if operation == "VENTA":
                rows = con.execute("""
                    SELECT operation, quantity
                    FROM transactions
                    WHERE asset_id = ?
                    ORDER BY date, id
                """, (asset_id,)).fetchall()

                available = 0.0

                for row in rows:
                    if row["operation"] == "COMPRA":
                        available += float(row["quantity"])
                    else:
                        available -= float(row["quantity"])

                if quantity > available + 1e-9:
                    raise ValueError(
                        f"No tienes suficientes unidades. "
                        f"Disponibles: {available:.6f}."
                    )

            cursor = con.execute("""
                INSERT INTO transactions (
                    asset_id,
                    operation,
                    date,
                    quantity,
                    price,
                    commission
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                asset_id,
                operation,
                str(date),
                quantity,
                price,
                commission
            ))

            return cursor.lastrowid

    def add_income(
        self,
        asset_id,
        event_type,
        date,
        amount,
        description=""
    ):
        event_type = str(event_type).upper()
        amount = self._number(amount, "valor del ingreso")

        if event_type not in ("DIVIDENDO", "INTERES"):
            raise ValueError(
                "El tipo de ingreso debe ser DIVIDENDO o INTERES."
            )

        if amount < 0:
            raise ValueError("El ingreso no puede ser negativo.")

        with self.connection() as con:
            cursor = con.execute("""
                INSERT INTO income_events (
                    asset_id,
                    event_type,
                    date,
                    amount,
                    description
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                int(asset_id),
                event_type,
                str(date),
                amount,
                str(description)
            ))

            return cursor.lastrowid

    def get_transactions(self):
        with self.connection() as con:
            rows = con.execute("""
                SELECT
                    t.*,
                    a.name AS asset_name,
                    a.currency
                FROM transactions t
                JOIN assets a ON a.id = t.asset_id
                ORDER BY t.date, t.id
            """).fetchall()

            return [dict(row) for row in rows]

    def get_income_events(self):
        with self.connection() as con:
            rows = con.execute("""
                SELECT
                    e.*,
                    a.name AS asset_name,
                    a.currency
                FROM income_events e
                JOIN assets a ON a.id = e.asset_id
                ORDER BY e.date, e.id
            """).fetchall()

            return [dict(row) for row in rows]

    def get_price_history(self):
        with self.connection() as con:
            rows = con.execute("""
                SELECT
                    p.*,
                    a.name AS asset_name
                FROM price_history p
                JOIN assets a ON a.id = p.asset_id
                ORDER BY p.date, p.id
            """).fetchall()

            return [dict(row) for row in rows]

    def save_fixed_income_terms(
        self,
        asset_id,
        annual_rate_pct,
        rate_type,
        issue_date,
        maturity_date,
        payment_frequency,
        nominal_value,
        notes=""
    ):
        annual_rate_pct = self._number(
            annual_rate_pct,
            "tasa anual"
        )
        nominal_value = self._number(
            nominal_value,
            "valor nominal"
        )

        if annual_rate_pct < 0 or nominal_value < 0:
            raise ValueError(
                "La tasa y el valor nominal no pueden ser negativos."
            )

        with self.connection() as con:
            con.execute("""
                INSERT INTO fixed_income_terms (
                    asset_id,
                    annual_rate_pct,
                    rate_type,
                    issue_date,
                    maturity_date,
                    payment_frequency,
                    nominal_value,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    annual_rate_pct = excluded.annual_rate_pct,
                    rate_type = excluded.rate_type,
                    issue_date = excluded.issue_date,
                    maturity_date = excluded.maturity_date,
                    payment_frequency = excluded.payment_frequency,
                    nominal_value = excluded.nominal_value,
                    notes = excluded.notes
            """, (
                int(asset_id),
                annual_rate_pct,
                str(rate_type),
                str(issue_date),
                str(maturity_date),
                str(payment_frequency),
                nominal_value,
                str(notes)
            ))

    def get_fixed_income_terms(self):
        with self.connection() as con:
            rows = con.execute("""
                SELECT
                    f.*,
                    a.name AS asset_name,
                    a.asset_type
                FROM fixed_income_terms f
                JOIN assets a ON a.id = f.asset_id
                ORDER BY a.name
            """).fetchall()

            return [dict(row) for row in rows]

    def get_fee_settings(self):
        with self.connection() as con:
            rows = con.execute("""
                SELECT asset_id, fee_pct
                FROM asset_fee_settings
            """).fetchall()

            return {
                int(row["asset_id"]): float(row["fee_pct"])
                for row in rows
            }

    def save_fee_setting(self, asset_id, fee_pct):
        fee_pct = self._number(fee_pct, "comisión")

        if fee_pct < 0:
            raise ValueError("La comisión no puede ser negativa.")

        with self.connection() as con:
            con.execute("""
                INSERT INTO asset_fee_settings (
                    asset_id,
                    fee_pct
                )
                VALUES (?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    fee_pct = excluded.fee_pct
            """, (
                int(asset_id),
                fee_pct
            ))