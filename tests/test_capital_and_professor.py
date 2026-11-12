"""Capital inicial, efectivo, TRM por operación, ventas y el caso Nike de la hoja del profesor."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from portfolio.database import Database
from portfolio.fees import FeeConfig
from portfolio.portfolio_service import PortfolioService

APP = str(Path(__file__).resolve().parent.parent / "app.py")

# Datos de Prueba_portafolio.xlsx (Nike)
COMMISSION_COP = 24261.699          # comisión de compra de la hoja, en pesos
BUY_TRM, SELL_TRM = 4548.5, 3971.38
DIV1_TRM, DIV2_TRM = 4646.08, 4177.58


def load_nike(db, service, with_trm=True):
    nike = next(a for a in db.get_assets() if a["symbol"] == "NKE")
    fx = (lambda v: v) if with_trm else (lambda v: None)
    service.register_trade(nike["id"], "COMPRA", "2023-01-30", 20, 127.0,
                           COMMISSION_COP / BUY_TRM, "COMPROBANTE", fx_rate=fx(BUY_TRM))
    db.add_income(nike["id"], "DIVIDENDO", "2023-04-02", 6.8, "Dividendo 1", fx_rate=fx(DIV1_TRM))
    db.add_income(nike["id"], "DIVIDENDO", "2023-06-01", 6.8, "Dividendo 2", fx_rate=fx(DIV2_TRM))
    service.register_trade(nike["id"], "VENTA", "2023-06-22", 20, 110.0, 0.0,
                           "SIN_COMISION", fx_rate=fx(SELL_TRM))
    return nike


class ProfessorNikeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "p.db"))
        self.service = PortfolioService(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_matches_professor_sheet(self):
        nike = load_nike(self.db, self.service)
        s = self.service.summary(usd_cop=4000.0, valuation_date=date(2023, 7, 1))
        p = next(x for x in s["positions"] if x["id"] == nike["id"])
        self.assertAlmostEqual(p["total_buys_cop"], 11_553_190 + COMMISSION_COP, places=2)
        self.assertAlmostEqual(p["sell_proceeds_cop"], 8_737_036.0, places=1)
        self.assertAlmostEqual(p["income_net_cop"], 31593.344 + 28407.544, places=2)
        # Saldo final de la hoja (N9)
        self.assertAlmostEqual(s["profit"], -2_780_414.811, delta=0.5)
        self.assertAlmostEqual(s["realized"], -2_840_415.699, delta=0.5)
        self.assertEqual(p["quantity"], 0)

    def test_sale_detail_shows_how_many_bought_and_what_came_out(self):
        load_nike(self.db, self.service)
        p = next(x for x in self.service.positions(usd_cop=4000.0) if x["symbol"] == "NKE")
        sale = self.service.sales_log([p])[0]
        self.assertEqual(sale["quantity"], 20)
        self.assertAlmostEqual(sale["net_proceeds_cop"], 8_737_036.0, places=1)
        self.assertAlmostEqual(sale["cost_sold_cop"], 11_577_451.699, places=2)
        self.assertAlmostEqual(sale["result_cop"], -2_840_415.699, delta=0.5)
        lot = self.service.purchase_log([p])[0]
        self.assertEqual((lot["date"], lot["quantity"]), ("2023-01-30", 20))
        self.assertAlmostEqual(lot["cost_cop"], 11_577_451.699, places=2)

    def test_old_rows_without_trm_use_current_rate_and_are_flagged(self):
        load_nike(self.db, self.service, with_trm=False)
        s = self.service.summary(usd_cop=4000.0, valuation_date=date(2023, 7, 1))
        self.assertIn("Nike", s["fx_approx"])
        self.assertIn("aproxim", s["xirr_note"].lower())

    def test_usd_without_any_rate_stays_out_instead_of_zero(self):
        load_nike(self.db, self.service, with_trm=False)
        s = self.service.summary(usd_cop=None)
        self.assertIn("Nike", s["fx_missing"])
        self.assertIsNone(s["cash"])

    def test_trm_can_be_added_later(self):
        nike = load_nike(self.db, self.service, with_trm=False)
        for t in self.db.get_transactions():
            self.db.update_transaction_fx(t["id"], BUY_TRM if t["operation"] == "COMPRA" else SELL_TRM)
        with self.assertRaises(ValueError):
            self.db.update_transaction_fx(1, 0)
        s = self.service.summary(usd_cop=4000.0)
        self.assertEqual(self.db.get_transactions()[0]["fx_rate"], BUY_TRM)
        self.assertTrue(nike)
        # los dividendos siguen sin TRM: Nike aún es aproximado hasta corregirlos también
        self.assertIn("Nike", s["fx_approx"])
        for e in self.db.get_income_events():
            self.db.update_income_fx(e["id"], DIV1_TRM)
        self.assertEqual(self.service.summary(usd_cop=4000.0)["fx_approx"], [])


class CapitalAndCashTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "p.db"))
        self.service = PortfolioService(self.db)
        self.bcol = next(a for a in self.db.get_assets() if a["currency"] == "COP")

    def tearDown(self):
        self.temp.cleanup()

    def test_cash_is_unknown_until_capital_is_registered(self):
        s = self.service.summary()
        self.assertFalse(s["cash_configured"])
        self.assertIsNone(s["cash"])
        self.assertIsNone(s["net_worth"])

    def test_cash_after_buy_sell_and_dividend(self):
        self.db.add_cash_movement("CAPITAL_INICIAL", "2026-01-01", 10_000_000)
        # compra 100 @ 20.000 con comisión 14.875 -> sale 2.014.875
        self.service.register_trade(self.bcol["id"], "COMPRA", "2026-01-02", 100, 20000.0, 14875.0)
        self.db.update_price(self.bcol["id"], 21000.0, "manual", "2026-11-10")
        s = self.service.summary(valuation_date=date(2026, 11, 12))
        self.assertAlmostEqual(s["cash"], 10_000_000 - 2_014_875)
        self.assertAlmostEqual(s["market_value"], 2_100_000)
        self.assertAlmostEqual(s["net_worth"], 10_000_000 - 2_014_875 + 2_100_000)
        # vende 40 @ 22.000 con comisión 14.875 -> entran 865.125
        self.service.register_trade(self.bcol["id"], "VENTA", "2026-02-01", 40, 22000.0, 14875.0)
        self.db.add_income(self.bcol["id"], "DIVIDENDO", "2026-03-01", 50_000, "", 1_000, 500)
        s = self.service.summary(valuation_date=date(2026, 11, 12))
        self.assertAlmostEqual(s["cash"], 10_000_000 - 2_014_875 + 865_125 + 48_500)
        # no se cuentan las acciones no vendidas como efectivo y el patrimonio no las duplica
        self.assertAlmostEqual(s["net_worth"], s["cash"] + 60 * 21000)

    def test_contribution_withdrawal_and_negative_cash(self):
        self.db.add_cash_movement("CAPITAL_INICIAL", "2026-01-01", 1_000_000)
        self.db.add_cash_movement("APORTE", "2026-02-01", 500_000)
        self.db.add_cash_movement("RETIRO", "2026-03-01", 200_000)
        self.assertAlmostEqual(self.service.summary()["cash"], 1_300_000)
        self.service.register_trade(self.bcol["id"], "COMPRA", "2026-03-02", 100, 20000.0, 14875.0)
        s = self.service.summary()
        self.assertTrue(s["cash_negative"])

    def test_only_one_initial_capital_and_validation(self):
        self.db.add_cash_movement("CAPITAL_INICIAL", "2026-01-01", 1000)
        with self.assertRaises(ValueError):
            self.db.add_cash_movement("CAPITAL_INICIAL", "2026-01-02", 5000)
        with self.assertRaises(ValueError):
            self.db.add_cash_movement("APORTE", "2026-01-02", 0)
        with self.assertRaises(ValueError):
            self.db.add_cash_movement("OTRO", "2026-01-02", 10)

    def test_sale_estimate_if_sell_today(self):
        self.service.register_trade(self.bcol["id"], "COMPRA", "2026-01-02", 100, 20000.0, 14875.0)
        pos = self.service.positions()
        pend = self.service.sale_estimates(pos, FeeConfig())
        self.assertFalse(pend[0]["known"])           # sin precio: Pendiente, no cero
        self.db.update_price(self.bcol["id"], 21000.0, "manual", "2026-11-10")
        row = self.service.sale_estimates(self.service.positions(), FeeConfig())[0]
        self.assertAlmostEqual(row["gross"], 2_100_000)
        self.assertAlmostEqual(row["fee"], 14875)
        self.assertAlmostEqual(row["net"], 2_085_125)
        self.assertAlmostEqual(row["net_per_unit"], 20_851.25)
        self.assertAlmostEqual(row["avg_cost"], 20_148.75)
        self.assertAlmostEqual(row["result"], 2_085_125 - 2_014_875)

    def test_tes_market_value_and_sale(self):
        self.db.add_fixed_income_investment("TES 2030", "TES30", "TES", "Gobierno", 5_000_000, 9.0,
                                            "Fija", "2026-01-01", "2030-01-01", "Anual",
                                            nominal=5_200_000)
        terms = self.db.get_fixed_income_terms()[0]
        self.assertEqual(terms["nominal_value"], 5_200_000)
        row = self.service.sale_estimates(self.service.positions(), FeeConfig())[0]
        self.assertAlmostEqual(row["net"], 5_000_000)          # a costo registrado, sin inventar
        a = next(x for x in self.db.get_assets() if x["symbol"] == "TES30")
        self.db.update_price(a["id"], 5_150_000, "Cotización comisionista", "2026-11-10")
        pos = self.service.positions(today=date(2026, 11, 12))
        p = next(x for x in pos if x["symbol"] == "TES30")
        self.assertEqual(p["price_status"], "ACTUALIZADO")
        row = self.service.sale_estimates(pos, FeeConfig())[0]
        self.assertAlmostEqual(row["net"], 5_150_000)
        self.assertAlmostEqual(row["result"], 150_000)


class MigrationV3Test(unittest.TestCase):
    def test_old_db_gets_new_columns_and_keeps_data(self):
        from tests.test_migration import build_legacy_db
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio_data.db"
            build_legacy_db(path)
            before = len(Database(str(path)).get_transactions())
            db = Database(str(path))
            self.assertEqual(len(db.get_transactions()), before)
            self.assertIn("fx_rate", db.get_transactions()[0])
            self.assertEqual(db.get_cash_movements(), [])


class CapitalTabInAppTest(unittest.TestCase):
    def test_register_capital_from_the_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio_data.db"
            os.environ["PORTFOLIO_DB_PATH"] = str(path)
            try:
                at = AppTest.from_file(APP, default_timeout=60)
                at.run()
                self.assertFalse(at.exception)
                [w for w in at.tabs[1].number_input if w.label.startswith("Capital inicial")][0].set_value(5_000_000.0)
                [b for b in at.tabs[1].button if b.label == "Guardar capital inicial"][0].click().run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                moves = Database(str(path)).get_cash_movements()
                self.assertEqual(moves[0]["kind"], "CAPITAL_INICIAL")
                self.assertEqual(moves[0]["amount"], 5_000_000)
                self.assertTrue(any("Efectivo disponible" in m.value for m in at.tabs[1].markdown))
            finally:
                os.environ.pop("PORTFOLIO_DB_PATH", None)


class AppWithDataTest(unittest.TestCase):
    def test_app_opens_with_nike_capital_and_tes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio_data.db"
            db = Database(str(path))
            service = PortfolioService(db)
            load_nike(db, service)
            db.add_cash_movement("CAPITAL_INICIAL", "2023-01-01", 15_000_000)
            db.add_fixed_income_investment("TES 2030", "TES30", "TES", "Gobierno", 5_000_000, 9.0,
                                           "Fija", "2026-01-01", "2030-01-01", "Anual")
            db.save_fx_rate(4000.0, "2026-11-10", "manual")
            os.environ["PORTFOLIO_DB_PATH"] = str(path)
            try:
                at = AppTest.from_file(APP, default_timeout=60)
                at.run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                text = " ".join(m.value for m in at.tabs[1].markdown)
                self.assertIn("Efectivo disponible", text)
            finally:
                os.environ.pop("PORTFOLIO_DB_PATH", None)


if __name__ == "__main__":
    unittest.main()
