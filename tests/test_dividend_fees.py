"""Costo de Trii por dividendos: estimación, corrección con comprobante y flujo en la app."""
import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from portfolio.database import Database
from portfolio.fees import FeeConfig, compute_commission, compute_dividend_fee
from portfolio.portfolio_service import PortfolioService

APP = str(Path(__file__).resolve().parent.parent / "app.py")


class DividendFeeTest(unittest.TestCase):
    def test_one_percent_of_received_amount(self):
        r = compute_dividend_fee(100000, 10000, "COP")      # recibido 90.000 -> 1 % = 900
        self.assertEqual(r.total, 900)
        self.assertTrue(r.is_estimate)

    def test_minimum_200_applies(self):
        self.assertEqual(compute_dividend_fee(5000, 0, "COP").total, 200)

    def test_usd_has_no_invented_fee(self):
        self.assertEqual(compute_dividend_fee(10, 0, "USD").total, 0)

    def test_nothing_received_means_no_fee(self):
        self.assertEqual(compute_dividend_fee(1000, 1000, "COP").total, 0)

    def test_optional_vat_and_custom_values(self):
        cfg = FeeConfig(div_fee_pct=2.0, div_fee_min=500.0, div_fee_add_vat=True)
        self.assertEqual(compute_dividend_fee(100000, 0, "COP", cfg).total, 2380)  # 2.000 + 19 %

    def test_trade_fee_descriptions_use_colombian_separators(self):
        text = compute_commission(1_000_000, "COP").description
        self.assertIn("12.500", text)
        self.assertNotIn("12,500", text)

    def test_old_saved_config_without_dividend_fields_still_loads(self):
        cfg = FeeConfig.from_dict({"plan": "PRO", "vat_pct": 19.0})
        self.assertEqual(cfg.div_fee_pct, 1.0)


class IncomeCorrectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "portfolio_data.db")
        self.service = PortfolioService(self.db)
        self.asset = self.db.get_assets()[0]
        self.service.register_trade(self.asset["id"], "COMPRA", "2026-01-01", 10, 30000, 0)

    def tearDown(self):
        self.temp.cleanup()

    def test_correction_updates_net_and_is_counted_once(self):
        iid = self.db.add_income(self.asset["id"], "DIVIDENDO", "2026-04-01", 100000, "", 0, 900)
        self.db.update_income_costs(iid, 10000, 1234)
        events = self.db.get_income_events()
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["net_amount"], 88766)
        self.assertAlmostEqual(self.service.summary(4000.0)["income"], 88766)

    def test_correction_rejects_invalid_values(self):
        iid = self.db.add_income(self.asset["id"], "DIVIDENDO", "2026-04-01", 1000, "")
        with self.assertRaises(ValueError):
            self.db.update_income_costs(iid, 900, 200)
        with self.assertRaises(ValueError):
            self.db.update_income_costs(iid, -1, 0)
        with self.assertRaises(ValueError):
            self.db.update_income_costs(9999, 0, 0)


class DividendFlowInAppTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "portfolio_data.db"
        db = Database(self.path)
        PortfolioService(db).register_trade(db.get_assets()[0]["id"], "COMPRA", "2026-01-01",
                                            10, 30000, 0)
        os.environ["PORTFOLIO_DB_PATH"] = str(self.path)

    def tearDown(self):
        os.environ.pop("PORTFOLIO_DB_PATH", None)
        self.temp.cleanup()

    def test_dividend_registered_with_estimated_trii_cost(self):
        at = AppTest.from_file(APP, default_timeout=60)
        at.run()
        self.assertFalse(at.exception)
        gross = [w for w in at.tabs[5].number_input if w.label.startswith("Valor bruto")][0]
        gross.set_value(100000.0)   # en un formulario, valor y clic van en la misma ejecución
        [b for b in at.tabs[5].button if b.label == "Registrar ingreso"][0].click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        events = Database(self.path).get_income_events()
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["fees"], 1000)           # 1 % de 100.000
        self.assertIn("estimado", events[0]["description"])
        # Registrarlo otra vez con los mismos datos NO debe duplicarlo
        at.run()
        [w for w in at.tabs[5].number_input if w.label.startswith("Valor bruto")][0].set_value(100000.0)
        [b for b in at.tabs[5].button if b.label == "Registrar ingreso"][0].click().run()
        self.assertTrue([e for e in at.error if "no se guardó" in e.value.lower()])
        self.assertEqual(len(Database(self.path).get_income_events()), 1)


if __name__ == "__main__":
    unittest.main()
