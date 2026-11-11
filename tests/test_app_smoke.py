"""La aplicación Streamlit debe abrir y funcionar sin errores en distintos escenarios."""
import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from portfolio.database import Database
from portfolio.portfolio_service import PortfolioService
from tests.test_migration import build_legacy_db

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def run_app(db_path):
    os.environ["PORTFOLIO_DB_PATH"] = str(db_path)
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


class AppSmokeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "portfolio_data.db"

    def tearDown(self):
        os.environ.pop("PORTFOLIO_DB_PATH", None)
        self.temp.cleanup()

    def assert_clean(self, at):
        self.assertFalse(at.exception, [e.value for e in at.exception])

    def test_opens_with_empty_new_database(self):
        at = run_app(self.path)
        self.assert_clean(at)
        self.assertEqual(len(at.tabs), 8)

    def test_opens_with_legacy_database_and_keeps_data(self):
        build_legacy_db(self.path)
        at = run_app(self.path)
        self.assert_clean(at)
        # La base antigua se respaldó y se conservaron las 4 operaciones
        self.assertTrue(list((self.path.parent / "backups").glob("*.db")))
        self.assertEqual(len(Database(self.path).get_transactions()), 4)
        # Bancolombia sin precio debe avisarse como pendiente, no como pérdida
        warnings = " ".join(w.value for w in at.warning)
        self.assertIn("Bancolombia", warnings)

    def test_opens_with_data_priced_dividends_and_fixed_income(self):
        db = Database(self.path)
        service = PortfolioService(db)
        amzn = db.get_assets()[1]
        service.register_trade(amzn["id"], "COMPRA", "2026-01-05", 3, 180.0, 0.4)
        db.update_price(amzn["id"], 200.0, "Prueba", date_today())
        db.save_fx_rate(4100.0, date_today(), "Prueba")
        db.add_income(amzn["id"], "DIVIDENDO", "2026-03-01", 12.0, "", 1.2, 0.0)
        db.add_fixed_income_investment("CDT Test", "CDT-T", "CDT", "Banco", 2_000_000, 11.0,
                                       "Efectiva anual", "2026-01-01", "2027-01-01", "Al vencimiento")
        at = run_app(self.path)
        self.assert_clean(at)

    def test_pending_only_portfolio_renders_without_crashing(self):
        db = Database(self.path)
        service = PortfolioService(db)
        service.register_trade(db.get_assets()[0]["id"], "COMPRA", "2026-01-05", 10, 30000, 14875)
        at = run_app(self.path)
        self.assert_clean(at)

    def test_first_purchase_flow_creates_company_and_trade(self):
        Database(self.path)
        at = run_app(self.path)
        at.radio(key="op_0").set_value("COMPRA").run()
        at.radio(key="mode_0").set_value("Empresa nueva").run()
        at.text_input(key="new_name_0").set_value("Ecopetrol").run()
        at.text_input(key="new_symbol_0").set_value("ECOPETROL").run()
        at.number_input(key="qty_0").set_value(100).run()
        at.number_input(key="price_0").set_value(2500.0).run()
        at.checkbox(key="confirm_0").check().run()
        at.button(key="save_0").click().run()
        self.assert_clean(at)
        db = Database(self.path)
        names = [a["name"] for a in db.get_assets()]
        self.assertIn("Ecopetrol", names)
        txs = [t for t in db.get_transactions() if t["asset_name"] == "Ecopetrol"]
        self.assertEqual(len(txs), 1)
        self.assertEqual(txs[0]["quantity"], 100)
        # 100 * 2.500 = 250.000 COP -> estándar: 12.500 + IVA = 14.875
        self.assertAlmostEqual(txs[0]["commission"], 14875)
        self.assertEqual(txs[0]["commission_source"], "ESTIMADA")

    def test_sale_flow_rejects_selling_more_than_owned(self):
        db = Database(self.path)
        service = PortfolioService(db)
        service.register_trade(db.get_assets()[0]["id"], "COMPRA", "2026-01-05", 5, 30000, 0)
        at = run_app(self.path)
        at.radio(key="op_0").set_value("VENTA").run()
        at.number_input(key="qty_0").set_value(9).run()
        at.number_input(key="price_0").set_value(31000.0).run()
        at.checkbox(key="confirm_0").check().run()
        at.button(key="save_0").click().run()
        self.assert_clean(at)
        self.assertTrue(at.error)
        self.assertEqual(len(Database(self.path).get_transactions()), 1)


def date_today():
    from datetime import date
    return date.today().isoformat()


if __name__ == "__main__":
    unittest.main()
