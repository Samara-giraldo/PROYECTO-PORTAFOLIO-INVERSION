
import math
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path


class Database:
    """Administra la base de datos SQLite del portafolio."""

    def __init__(self, db_path="portfolio_data.db"):
        self.db_path = str(db_path)
        self.initialize()

    def connect(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    @contextmanager
    def connection(self):
        """Abre una conexión y garantiza que se cierre al terminar."""
        con = self.connect()
        try:
            with con:
                yield con
        finally:
            con.close()

    @staticmethod
    def _number(value, name, minimum=None):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} debe ser un número válido.")

        if not math.isfinite(number):
            raise ValueError(f"{name} debe ser un número finito.")

        if minimum is not None and number < minimum:
            raise ValueError(f"{name} no puede ser menor que {minimum}.")

        return number

    @staticmethod
    def _valid_date(value):
        try:
            date.fromisoformat(str(value))
        except (TypeError, ValueError):
            raise ValueError("La fecha debe tener formato AAAA-MM-DD.")
        return str(value)

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
                        CHECK(operation IN ('COMPRA','VENTA')),
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
                        CHECK(event_type IN ('DIVIDENDO','INTERES')),
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

            if count == 0:
                initial_assets = [
                    (
                        "Bancolombia", "BCOLOMBIA (manual)",
                        "ACCION", "COP", "BVC", 0,
                        "Cotización local ingresada por el usuario"
                    ),
                    (
                        "Amazon", "AMZN", "ACCION", "USD",
                        "NASDAQ", 0, "Yahoo Finance mediante yfinance"
                    ),
                    (
                        "The Coca-Cola Company", "KO", "ACCION",
                        "USD", "NYSE", 0,
                        "Yahoo Finance mediante yfinance"
                    ),
                    (
                        "Nike", "NKE", "ACCION", "USD",
                        "NYSE", 0, "Yahoo Finance mediante yfinance"
                    ),
                    (
                        "CDT de ejemplo", "CDT-001", "CDT",
                        "COP", "Entidad financiera", 0,
                        "Datos ingresados por el usuario"
                    ),
                    (
                        "Bono de ejemplo", "BONO-001", "BONO",
                        "COP", "Mercado de deuda", 0,
                        "Datos ingresados por el usuario"
                    ),
                    (
                        "TES de ejemplo", "TES-001", "TES",
                        "COP", "Gobierno de Colombia", 0,
                        "Datos ingresados por el usuario"
                    ),
                ]

                con.executemany("""
                    INSERT INTO assets(
                        name, symbol, asset_type, currency,
                        market, current_price, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, initial_assets)

    def get_assets(self):
        with self.connection() as con:
            return [
                dict(row)
                for row in con.execute(
                    "SELECT * FROM assets ORDER BY id"
                )
            ]

    def add_asset(
        self, name, symbol, asset_type, currency,
        market, current_price=0, source="Manual"
    ):
        name = str(name).strip()
        symbol = str(symbol).strip().upper()
        asset_type = str(asset_type).strip().upper()
        currency = str(currency).strip().upper()
        market = str(market).strip()

        if not name or not symbol or not market:
            raise ValueError("Nombre, símbolo y mercado son obligatorios.")

        if asset_type not in ("ACCION", "CDT", "BONO", "TES"):
            raise ValueError("Tipo de activo no válido.")

        if currency not in ("COP", "USD"):
            raise ValueError("La moneda debe ser COP o USD.")

        price = self._number(current_price, "El precio", 0)

        with self.connection() as con:
            existing = con.execute(
                "SELECT id FROM assets WHERE UPPER(symbol)=?",
                (symbol,)
            ).fetchone()

            if existing:
                raise ValueError("Ya existe un activo con ese símbolo.")

            con.execute("""
                INSERT INTO assets(
                    name, symbol, asset_type, currency,
                    market, current_price, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                name, symbol, asset_type, currency,
                market, price, str(source)
            ))

    def update_price(self, asset_id, price, source, date_value):
        asset_id = int(asset_id)
        price = self._number(price, "El precio", 0)
        date_value = self._valid_date(date_value)
        source = str(source).strip() or "Fuente no especificada"

        with self.connection() as con:
            asset = con.execute(
                "SELECT id FROM assets WHERE id=?",
                (asset_id,)
            ).fetchone()

            if not asset:
                raise ValueError("El activo seleccionado no existe.")

            con.execute("""
                UPDATE assets
                SET current_price=?, source=?
                WHERE id=?
            """, (price, source, asset_id))

            con.execute("""
                INSERT INTO price_history(asset_id, date, price, source)
                VALUES (?, ?, ?, ?)
            """, (asset_id, date_value, price, source))

    def _validate_transaction_history(
        self, asset_id, operation, date_value, quantity
    ):
        rows = self.get_transactions_for_asset(asset_id)

        rows.append({
            "operation": operation,
            "date": date_value,
            "quantity": quantity,
            "id": float("inf")
        })

        rows.sort(key=lambda row: (row["date"], row["id"]))

        available = 0.0

        for row in rows:
            q = float(row["quantity"])

            if row["operation"] == "COMPRA":
                available += q
            else:
                if q > available + 1e-9:
                    raise ValueError(
                        "La venta supera las unidades disponibles "
                        "en la fecha indicada."
                    )
                available -= q

    def get_transactions_for_asset(self, asset_id):
        with self.connection() as con:
            return [
                dict(row)
                for row in con.execute("""
                    SELECT *
                    FROM transactions
                    WHERE asset_id=?
                    ORDER BY date, id
                """, (int(asset_id),))
            ]

    def add_transaction(
        self, asset_id, operation, date, quantity, price, commission
    ):
        asset_id = int(asset_id)
        operation = str(operation).strip().upper()
        date = self._valid_date(date)
        quantity = self._number(quantity, "La cantidad", 0)
        price = self._number(price, "El precio", 0)
        commission = self._number(commission, "La comisión", 0)

        if quantity <= 0:
            raise ValueError("La cantidad debe ser mayor que cero.")

        if operation not in ("COMPRA", "VENTA"):
            raise ValueError("La operación debe ser COMPRA o VENTA.")

        gross = quantity * price

        if operation == "VENTA" and commission > gross:
            raise ValueError(
                "La comisión no puede superar el valor bruto de la venta."
            )

        with self.connection() as con:
            asset = con.execute(
                "SELECT id FROM assets WHERE id=?",
                (asset_id,)
            ).fetchone()

            if not asset:
                raise ValueError("El activo seleccionado no existe.")

            self._validate_transaction_history(
                asset_id, operation, date, quantity
            )

            con.execute("""
                INSERT INTO transactions(
                    asset_id, operation, date,
                    quantity, price, commission
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                asset_id, operation, date,
                quantity, price, commission
            ))

    def add_income(
        self, asset_id, event_type, date, amount, description=""
    ):
        asset_id = int(asset_id)
        event_type = str(event_type).strip().upper()
        date = self._valid_date(date)
        amount = self._number(amount, "El ingreso", 0)

        if event_type not in ("DIVIDENDO", "INTERES"):
            raise ValueError("Tipo de ingreso no válido.")

        if amount <= 0:
            raise ValueError("El ingreso debe ser mayor que cero.")

        with self.connection() as con:
            asset = con.execute(
                "SELECT id FROM assets WHERE id=?",
                (asset_id,)
            ).fetchone()

            if not asset:
                raise ValueError("El activo seleccionado no existe.")

            con.execute("""
                INSERT INTO income_events(
                    asset_id, event_type, date, amount, description
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                asset_id, event_type, date,
                amount, str(description)
            ))

    def get_transactions(self):
        with self.connection() as con:
            return [
                dict(row)
                for row in con.execute("""
                    SELECT t.*, a.name AS asset_name, a.currency
                    FROM transactions t
                    JOIN assets a ON a.id=t.asset_id
                    ORDER BY t.date, t.id
                """)
            ]

    def get_income_events(self):
        with self.connection() as con:
            return [
                dict(row)
                for row in con.execute("""
                    SELECT e.*, a.name AS asset_name, a.currency
                    FROM income_events e
                    JOIN assets a ON a.id=e.asset_id
                    ORDER BY e.date, e.id
                """)
            ]

    def get_price_history(self):
        with self.connection() as con:
            return [
                dict(row)
                for row in con.execute("""
                    SELECT p.*, a.name AS asset_name
                    FROM price_history p
                    JOIN assets a ON a.id=p.asset_id
                    ORDER BY p.date, p.id
                """)
            ]

    def save_fixed_income_terms(
        self, asset_id, annual_rate_pct, rate_type,
        issue_date, maturity_date, payment_frequency,
        nominal_value, notes=""
    ):
        asset_id = int(asset_id)
        annual_rate_pct = self._number(
            annual_rate_pct, "La tasa anual", 0
        )
        nominal_value = self._number(
            nominal_value, "El valor nominal", 0
        )
        issue_date = self._valid_date(issue_date)
        maturity_date = self._valid_date(maturity_date)

        if maturity_date <= issue_date:
            raise ValueError(
                "El vencimiento debe ser posterior a la fecha inicial."
            )

        with self.connection() as con:
            con.execute("""
                INSERT INTO fixed_income_terms(
                    asset_id, annual_rate_pct, rate_type,
                    issue_date, maturity_date, payment_frequency,
                    nominal_value, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    annual_rate_pct=excluded.annual_rate_pct,
                    rate_type=excluded.rate_type,
                    issue_date=excluded.issue_date,
                    maturity_date=excluded.maturity_date,
                    payment_frequency=excluded.payment_frequency,
                    nominal_value=excluded.nominal_value,
                    notes=excluded.notes
            """, (
                asset_id, annual_rate_pct, str(rate_type),
                issue_date, maturity_date, str(payment_frequency),
                nominal_value, str(notes)
            ))

    def get_fixed_income_terms(self):
        with self.connection() as con:
            return [
                dict(row)
                for row in con.execute("""
                    SELECT f.*, a.name AS asset_name, a.asset_type
                    FROM fixed_income_terms f
                    JOIN assets a ON a.id=f.asset_id
                    ORDER BY a.name
                """)
            ]

    def get_fee_settings(self):
        with self.connection() as con:
            return {
                int(row["asset_id"]): float(row["fee_pct"])
                for row in con.execute(
                    "SELECT asset_id, fee_pct FROM asset_fee_settings"
                )
            }

    def save_fee_setting(self, asset_id, fee_pct):
        asset_id = int(asset_id)
        fee_pct = self._number(fee_pct, "La comisión", 0)

        if fee_pct > 10:
            raise ValueError("La comisión no puede superar el 10%.")

        with self.connection() as con:
            con.execute("""
                INSERT INTO asset_fee_settings(asset_id, fee_pct)
                VALUES (?, ?)
                ON CONFLICT(asset_id)
                DO UPDATE SET fee_pct=excluded.fee_pct
            """, (asset_id, fee_pct))

