"""La base de datos antigua (esquema original) debe seguir funcionando sin perder nada."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from portfolio.database import Database, SCHEMA_VERSION
from portfolio.portfolio_service import PortfolioService

# Esquema EXACTO que usaba la versión anterior de la aplicación.
LEGACY_SCHEMA = """
CREATE TABLE assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL, currency TEXT NOT NULL, market TEXT NOT NULL,
    current_price REAL NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'Manual');
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id INTEGER NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN ('COMPRA','VENTA')), date TEXT NOT NULL,
    quantity REAL NOT NULL CHECK(quantity > 0), price REAL NOT NULL CHECK(price >= 0),
    commission REAL NOT NULL DEFAULT 0 CHECK(commission >= 0),
    FOREIGN KEY(asset_id) REFERENCES assets(id));
CREATE TABLE income_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('DIVIDENDO','INTERES')), date TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount >= 0), description TEXT DEFAULT '',
    FOREIGN KEY(asset_id) REFERENCES assets(id));
CREATE TABLE price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id INTEGER NOT NULL, date TEXT NOT NULL,
    price REAL NOT NULL CHECK(price >= 0), source TEXT NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES assets(id));
CREATE TABLE fixed_income_terms (
    asset_id INTEGER PRIMARY KEY, annual_rate_pct REAL NOT NULL, rate_type TEXT NOT NULL,
    issue_date TEXT NOT NULL, maturity_date TEXT NOT NULL, payment_frequency TEXT NOT NULL,
    nominal_value REAL NOT NULL, notes TEXT DEFAULT '',
    FOREIGN KEY(asset_id) REFERENCES assets(id));
CREATE TABLE asset_fee_settings (
    asset_id INTEGER PRIMARY KEY, fee_pct REAL NOT NULL DEFAULT 0,
    FOREIGN KEY(asset_id) REFERENCES assets(id));
"""


def build_legacy_db(path):
    con = sqlite3.connect(path)
    con.executescript(LEGACY_SCHEMA)
    con.executemany(
        "INSERT INTO assets(name,symbol,asset_type,currency,market,current_price,source) VALUES(?,?,?,?,?,?,?)",
        [("Bancolombia", "BCOLOMBIA (manual)", "ACCION", "COP", "BVC", 0, "Manual"),
         ("Amazon", "AMZN", "ACCION", "USD", "NASDAQ", 200.0, "Yahoo Finance mediante yfinance"),
         ("Mi CDT", "CDT-9", "CDT", "COP", "Banco", 5000000, "Registro del inversionista")])
    con.executemany(
        "INSERT INTO transactions(asset_id,operation,date,quantity,price,commission) VALUES(?,?,?,?,?,?)",
        [(1, "COMPRA", "2026-01-10", 100, 30000, 14875),
         (2, "COMPRA", "2026-01-15", 2, 180.0, 1.0),
         (2, "VENTA", "2026-03-01", 1, 210.0, 1.0),
         (3, "COMPRA", "2026-02-01", 1, 5000000, 0)])
    con.execute("INSERT INTO income_events(asset_id,event_type,date,amount,description) "
                "VALUES(1,'DIVIDENDO','2026-04-01',50000,'Dividendo trimestral')")
    con.execute("INSERT INTO price_history(asset_id,date,price,source) VALUES(2,'2026-05-02',200.0,'Yahoo')")
    con.execute("INSERT INTO fixed_income_terms VALUES(3,11.5,'Efectiva anual','2026-02-01','2027-02-01','Al vencimiento',5000000,'')")
    con.execute("INSERT INTO asset_fee_settings VALUES(2,0.35)")
    con.commit()
    con.close()


def table_rows(path, table):
    con = sqlite3.connect(path)
    try:
        return con.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
    finally:
        con.close()


class LegacyMigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "portfolio_data.db"
        build_legacy_db(self.path)
        self.before = {t: table_rows(self.path, t) for t in
                       ("assets", "transactions", "income_events", "price_history",
                        "fixed_income_terms", "asset_fee_settings")}

    def tearDown(self):
        self.temp.cleanup()

    def test_original_rows_are_all_preserved(self):
        Database(self.path)
        for table, old_rows in self.before.items():
            new_rows = table_rows(self.path, table)
            self.assertEqual(len(new_rows), len(old_rows), f"cambió el número de filas en {table}")
            # Las columnas originales conservan exactamente los mismos valores.
            for old, new in zip(old_rows, new_rows):
                self.assertEqual(tuple(new[:len(old)]) if table != "assets" else tuple(new[:len(old)]),
                                 tuple(old), f"cambió un dato en {table}")

    def test_backup_is_created_and_identical_to_original(self):
        db = Database(self.path)
        self.assertIsNotNone(db.last_backup_path)
        backup = Path(db.last_backup_path)
        self.assertTrue(backup.exists())
        self.assertEqual(backup.parent.name, "backups")
        for table, old_rows in self.before.items():
            self.assertEqual(table_rows(backup, table), old_rows)

    def test_new_columns_added_and_version_set(self):
        Database(self.path)
        con = sqlite3.connect(self.path)
        cols = lambda t: {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
        self.assertTrue({"price_date", "yahoo_symbol"} <= cols("assets"))
        self.assertTrue({"commission_source", "notes"} <= cols("transactions"))
        self.assertTrue({"withholding", "fees"} <= cols("income_events"))
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        con.close()

    def test_no_fake_assets_are_added_to_existing_db(self):
        Database(self.path)
        self.assertEqual(len(table_rows(self.path, "assets")), 3)

    def test_price_date_backfilled_from_history(self):
        db = Database(self.path)
        amazon = [a for a in db.get_assets() if a["symbol"] == "AMZN"][0]
        self.assertEqual(amazon["price_date"], "2026-05-02")
        self.assertEqual(amazon["yahoo_symbol"], "AMZN")

    def test_second_start_does_not_create_another_backup(self):
        Database(self.path)
        second = Database(self.path)
        self.assertIsNone(second.last_backup_path)
        self.assertEqual(len(list((self.path.parent / "backups").glob("*.db"))), 1)

    def test_old_data_still_reads_and_calculates(self):
        db = Database(self.path)
        service = PortfolioService(db)
        positions = {p["name"]: p for p in service.positions()}
        # Bancolombia: precio 0 en la base antigua => PENDIENTE, no pérdida
        self.assertIsNone(positions["Bancolombia"]["market_value"])
        self.assertIsNone(positions["Bancolombia"]["unrealized"])
        self.assertEqual(positions["Bancolombia"]["price_status"], "PENDIENTE")
        self.assertAlmostEqual(positions["Bancolombia"]["remaining_cost"], 100 * 30000 + 14875)
        # Amazon: 2 compradas, 1 vendida; costo promedio (180*2+1)/2 = 180.5
        amazon = positions["Amazon"]
        self.assertAlmostEqual(amazon["quantity"], 1)
        self.assertAlmostEqual(amazon["remaining_cost"], 180.5)
        self.assertAlmostEqual(amazon["realized"], (210 - 1) - 180.5)
        self.assertAlmostEqual(amazon["unrealized"], 200 - 180.5)
        # Los dividendos antiguos (sin retención) cuentan completos y una sola vez
        self.assertAlmostEqual(positions["Bancolombia"]["income_net"], 50000)
        # La comisión por empresa guardada sigue allí
        self.assertEqual(db.get_fee_settings(), {2: 0.35})

    def test_summary_excludes_pending_asset_instead_of_showing_loss(self):
        db = Database(self.path)
        summary = PortfolioService(db).summary(usd_cop=4000.0)
        self.assertIn("Bancolombia", summary["pending_assets"])
        self.assertTrue(summary["partial"])
        self.assertIsNone(summary["xirr_pct"])
        # El valor actual NO incluye el costo de Bancolombia como pérdida
        self.assertGreaterEqual(summary["unrealized"], 0)


if __name__ == "__main__":
    unittest.main()
