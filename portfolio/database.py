import sqlite3
from pathlib import Path

class Database:
    """Crea las tablas y centraliza el acceso a SQLite."""

    def __init__(self, db_path="portfolio_data.db"):
        self.db_path = str(db_path)
        self.initialize()

    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self):
        with self.connect() as con:
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
            """)
            count = con.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
            if count == 0:
                initial_assets = [
                    ("Bancolombia", "BCOLOMBIA (manual)", "ACCION", "COP", "BVC", 0, "Cotización local ingresada por el usuario"),
                    ("Amazon", "AMZN", "ACCION", "USD", "NASDAQ", 0, "Yahoo Finance mediante yfinance"),
                    ("The Coca-Cola Company", "KO", "ACCION", "USD", "NYSE", 0, "Yahoo Finance mediante yfinance"),
                    ("Nike", "NKE", "ACCION", "USD", "NYSE", 0, "Yahoo Finance mediante yfinance"),
                    ("CDT de ejemplo", "CDT-001", "CDT", "COP", "Entidad financiera", 0, "Datos contractuales ingresados por el usuario"),
                    ("Bono de ejemplo", "BONO-001", "BONO", "COP", "Mercado de deuda", 0, "Datos contractuales ingresados por el usuario"),
                    ("TES de ejemplo", "TES-001", "TES", "COP", "Gobierno de Colombia", 0, "Datos contractuales ingresados por el usuario"),
                ]
                con.executemany("""
                    INSERT INTO assets(name,symbol,asset_type,currency,market,current_price,source)
                    VALUES(?,?,?,?,?,?,?)
                """, initial_assets)

    def get_assets(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM assets ORDER BY id")]

    def add_asset(self, name, symbol, asset_type, currency, market, current_price=0, source="Manual"):
        with self.connect() as con:
            con.execute("""
                INSERT INTO assets(name,symbol,asset_type,currency,market,current_price,source)
                VALUES(?,?,?,?,?,?,?)
            """, (name, symbol, asset_type, currency, market, current_price, source))

    def update_price(self, asset_id, price, source, date):
        with self.connect() as con:
            con.execute("UPDATE assets SET current_price=?, source=? WHERE id=?",
                        (float(price), source, int(asset_id)))
            con.execute("""
                INSERT INTO price_history(asset_id,date,price,source) VALUES(?,?,?,?)
            """, (int(asset_id), date, float(price), source))

    def add_transaction(self, asset_id, operation, date, quantity, price, commission):
        with self.connect() as con:
            con.execute("""
                INSERT INTO transactions(asset_id,operation,date,quantity,price,commission)
                VALUES(?,?,?,?,?,?)
            """, (asset_id, operation, date, quantity, price, commission))

    def add_income(self, asset_id, event_type, date, amount, description):
        with self.connect() as con:
            con.execute("""
                INSERT INTO income_events(asset_id,event_type,date,amount,description)
                VALUES(?,?,?,?,?)
            """, (asset_id, event_type, date, amount, description))

    def get_transactions(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("""
                SELECT t.*, a.name AS asset_name, a.currency
                FROM transactions t JOIN assets a ON a.id=t.asset_id
                ORDER BY t.date, t.id
            """)]

    def get_income_events(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("""
                SELECT e.*, a.name AS asset_name, a.currency
                FROM income_events e JOIN assets a ON a.id=e.asset_id
                ORDER BY e.date, e.id
            """)]

    def get_price_history(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("""
                SELECT p.*, a.name AS asset_name
                FROM price_history p JOIN assets a ON a.id=p.asset_id
                ORDER BY p.date
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
        with self.connect() as con:
            return {int(r["asset_id"]): float(r["fee_pct"])
                    for r in con.execute("SELECT asset_id, fee_pct FROM asset_fee_settings")}

    def save_fee_setting(self, asset_id, fee_pct):
        with self.connect() as con:
            con.execute("""
                INSERT INTO asset_fee_settings(asset_id, fee_pct) VALUES(?,?)
                ON CONFLICT(asset_id) DO UPDATE SET fee_pct=excluded.fee_pct
            """, (int(asset_id), float(fee_pct)))
