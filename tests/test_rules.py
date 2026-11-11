"""Reglas financieras: comisiones, formato, ventas, dividendos, precios y cotizaciones."""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from portfolio.database import Database, DuplicateIncomeError
from portfolio.fees import (FeeConfig, PLAN_CUSTOM, PLAN_PRO, compute_commission,
                            load_fee_config, save_fee_config)
from portfolio.formatting import fmt_cop, fmt_money, fmt_pct, fmt_qty, fmt_usd
from portfolio.market_data import MarketDataProvider, QuoteError
from portfolio.portfolio_service import PortfolioService


class FeeTest(unittest.TestCase):
    def test_standard_small_trade_is_flat_fee_plus_vat(self):
        r = compute_commission(1_000_000, "COP", FeeConfig())
        self.assertEqual((r.base, r.vat, r.total), (12500, 2375, 14875))
        self.assertTrue(r.is_estimate)

    def test_standard_exactly_5_million_still_flat(self):
        self.assertEqual(compute_commission(5_000_000, "COP", FeeConfig()).base, 12500)

    def test_standard_large_trade_is_percentage_plus_vat(self):
        r = compute_commission(6_000_000, "COP", FeeConfig())
        self.assertEqual((r.base, r.vat, r.total), (15000, 2850, 17850))

    def test_pro_has_lower_fee_and_minimum(self):
        cfg = FeeConfig(plan=PLAN_PRO)
        self.assertEqual(compute_commission(1_000_000, "COP", cfg).base, 6250)
        self.assertEqual(compute_commission(8_000_000, "COP", cfg).base, 10000)

    def test_usd_standard_and_pro(self):
        self.assertEqual(compute_commission(1000, "USD", FeeConfig()).total, 2.0)
        self.assertEqual(compute_commission(1000, "USD", FeeConfig(plan=PLAN_PRO)).total, 0.0)

    def test_asset_override_replaces_plan(self):
        r = compute_commission(1_000_000, "COP", FeeConfig(), asset_override_pct=0.5)
        self.assertEqual(r.total, 5000)

    def test_custom_plan_and_unknown_currency(self):
        cfg = FeeConfig(plan=PLAN_CUSTOM, custom_pct=1.0, custom_min=0)
        self.assertEqual(compute_commission(100_000, "COP", cfg).total, 1000)
        self.assertEqual(compute_commission(100, "EUR", FeeConfig()).total, 0.0)

    def test_zero_gross_has_no_fee(self):
        self.assertEqual(compute_commission(0, "COP", FeeConfig()).total, 0.0)

    def test_config_is_saved_in_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            save_fee_config(db, FeeConfig(plan=PLAN_PRO, vat_pct=21))
            loaded = load_fee_config(db)
            self.assertEqual((loaded.plan, loaded.vat_pct), (PLAN_PRO, 21))


class FormatTest(unittest.TestCase):
    def test_cop_has_no_decimals_and_dot_thousands(self):
        self.assertEqual(fmt_cop(1234567.89), "$ 1.234.568")
        self.assertEqual(fmt_cop(-1500), "-$ 1.500")
        self.assertEqual(fmt_cop(0), "$ 0")

    def test_usd_has_two_decimals(self):
        self.assertEqual(fmt_usd(1234.5), "US$ 1.234,50")
        self.assertEqual(fmt_money(2.0, "USD"), "US$ 2,00")

    def test_missing_value_is_pending_never_zero(self):
        self.assertEqual(fmt_cop(None), "Pendiente")
        self.assertEqual(fmt_usd(float("nan")), "Pendiente")

    def test_quantities(self):
        self.assertEqual(fmt_qty(10), "10")
        self.assertEqual(fmt_qty(10.0000000001), "10")
        self.assertEqual(fmt_qty(1500), "1.500")
        self.assertEqual(fmt_qty(2.5), "2,5")
        self.assertEqual(fmt_qty(0.123456), "0,123456")

    def test_percent(self):
        self.assertEqual(fmt_pct(12.345), "12,35 %")
        self.assertEqual(fmt_pct(-3.2), "-3,20 %")
        self.assertEqual(fmt_pct(None), "N/D")


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "t.db")
        self.service = PortfolioService(self.db)
        self.bancolombia, self.amazon = self.db.get_assets()[0], self.db.get_assets()[1]

    def tearDown(self):
        self.temp.cleanup()

    def pos(self, asset_id):
        return {p["id"]: p for p in self.service.positions()}[asset_id]


class TradeTest(BaseCase):
    def test_weighted_average_cost_includes_commission(self):
        aid = self.bancolombia["id"]
        self.db.add_transaction(aid, "COMPRA", "2026-01-01", 10, 100, 10)   # costo 1010
        self.db.add_transaction(aid, "COMPRA", "2026-01-02", 10, 120, 20)   # costo 1220
        p = self.pos(aid)
        self.assertAlmostEqual(p["quantity"], 20)
        self.assertAlmostEqual(p["remaining_cost"], 2230)
        self.assertAlmostEqual(p["avg_cost"], 111.5)

    def test_partial_sale_realized_and_remaining_cost(self):
        aid = self.bancolombia["id"]
        self.db.add_transaction(aid, "COMPRA", "2026-01-01", 10, 100, 10)   # prom 101
        self.db.add_transaction(aid, "VENTA", "2026-02-01", 4, 130, 5)
        p = self.pos(aid)
        self.assertAlmostEqual(p["quantity"], 6)
        self.assertAlmostEqual(p["remaining_cost"], 606)
        self.assertAlmostEqual(p["realized"], (4 * 130 - 5) - 4 * 101)
        self.assertAlmostEqual(p["buy_fees"], 10)
        self.assertAlmostEqual(p["sell_fees"], 5)

    def test_selling_everything_leaves_exactly_zero(self):
        aid = self.bancolombia["id"]
        self.db.add_transaction(aid, "COMPRA", "2026-01-01", 3, 33.33, 1.1)
        self.db.add_transaction(aid, "COMPRA", "2026-01-02", 7, 41.17, 0.7)
        self.db.add_transaction(aid, "VENTA", "2026-02-01", 10, 50, 1)
        p = self.pos(aid)
        self.assertEqual(p["quantity"], 0.0)
        self.assertEqual(p["remaining_cost"], 0.0)
        self.assertEqual(p["market_value"], 0.0)     # sin acciones no depende del precio

    def test_register_trade_rejects_oversell(self):
        aid = self.bancolombia["id"]
        self.service.register_trade(aid, "COMPRA", "2026-01-01", 5, 100, 0)
        with self.assertRaises(ValueError):
            self.service.register_trade(aid, "VENTA", "2026-02-01", 6, 100, 0)
        self.assertEqual(len(self.db.get_transactions()), 1)      # no se guardó

    def test_register_trade_rejects_backdated_sale_before_purchase(self):
        aid = self.bancolombia["id"]
        self.service.register_trade(aid, "COMPRA", "2026-03-01", 5, 100, 0)
        with self.assertRaises(ValueError):
            self.service.register_trade(aid, "VENTA", "2026-01-01", 1, 100, 0)

    def test_inconsistent_legacy_data_does_not_crash(self):
        aid = self.bancolombia["id"]
        self.db.add_transaction(aid, "COMPRA", "2026-01-01", 5, 100, 0)
        self.db.add_transaction(aid, "VENTA", "2026-02-01", 8, 100, 0)   # dato malo antiguo
        p = self.pos(aid)
        self.assertEqual(p["quantity"], 0.0)
        self.assertTrue(p["issues"])
        self.assertTrue(self.service.summary(4000.0)["issues"])

    def test_register_requires_positive_price(self):
        with self.assertRaises(ValueError):
            self.service.register_trade(self.bancolombia["id"], "COMPRA", "2026-01-01", 1, 0, 0)

    def test_first_purchase_creates_company_and_trade_together(self):
        asset_id, tx_id = self.service.register_first_purchase(
            {"name": "Apple", "symbol": "aapl", "currency": "USD", "market": "NASDAQ",
             "yahoo_symbol": "AAPL"}, "2026-05-01", 3, 150.0, 0.3)
        a = self.db.get_asset(asset_id)
        self.assertEqual((a["symbol"], a["yahoo_symbol"], a["current_price"]), ("AAPL", "AAPL", 0))
        p = self.pos(asset_id)
        self.assertAlmostEqual(p["quantity"], 3)
        self.assertIsNone(p["market_value"])            # sin cotización: pendiente
        self.assertEqual(p["price_status"], "PENDIENTE")

    def test_first_purchase_failure_leaves_no_orphan_company(self):
        before = len(self.db.get_assets())
        with self.assertRaises(ValueError):
            self.service.register_first_purchase(
                {"name": "X", "symbol": "XX", "currency": "USD", "market": "M"},
                "2026-05-01", 3, 0, 0)
        self.assertEqual(len(self.db.get_assets()), before)

    def test_first_purchase_rejects_duplicate_symbol(self):
        with self.assertRaises(ValueError):
            self.service.register_first_purchase(
                {"name": "Otra Amazon", "symbol": "amzn", "currency": "USD", "market": "M"},
                "2026-05-01", 1, 100, 0)

    def test_commission_can_be_corrected_from_receipt(self):
        aid = self.bancolombia["id"]
        tx = self.service.register_trade(aid, "COMPRA", "2026-01-01", 10, 1000, 14875, "ESTIMADA")
        self.db.update_transaction_commission(tx, 14000)
        row = self.db.get_transactions()[0]
        self.assertEqual((row["commission"], row["commission_source"]), (14000, "COMPROBANTE"))
        self.assertAlmostEqual(self.pos(aid)["remaining_cost"], 10 * 1000 + 14000)


class PriceTest(BaseCase):
    def test_pending_price_is_not_a_loss(self):
        aid = self.amazon["id"]
        self.db.add_transaction(aid, "COMPRA", "2026-01-01", 2, 180, 1)
        p = self.pos(aid)
        self.assertIsNone(p["market_value"])
        self.assertIsNone(p["unrealized"])
        self.assertIsNone(p["total_result"])
        s = self.service.summary(4000.0)
        self.assertEqual(s["pending_assets"], ["Amazon"])
        self.assertEqual(s["unrealized"], 0)
        self.assertEqual(s["market_value"], 0)
        self.assertAlmostEqual(s["pending_cost"], 361 * 4000)

    def test_quote_saves_source_and_date(self):
        aid = self.amazon["id"]
        self.db.update_price(aid, 201.5, "Yahoo Finance (prueba)", "2026-11-06")
        a = self.db.get_asset(aid)
        self.assertEqual((a["current_price"], a["source"], a["price_date"]),
                         (201.5, "Yahoo Finance (prueba)", "2026-11-06"))
        hist = self.db.get_price_history()[-1]
        self.assertEqual((hist["price"], hist["source"], hist["date"]),
                         (201.5, "Yahoo Finance (prueba)", "2026-11-06"))
        self.assertTrue(hist["fetched_at"])

    def test_zero_price_is_refused(self):
        with self.assertRaises(ValueError):
            self.db.update_price(self.amazon["id"], 0, "x", "2026-01-01")

    def test_price_status_by_age(self):
        aid = self.amazon["id"]
        self.db.add_transaction(aid, "COMPRA", "2026-01-01", 1, 100, 0)
        self.db.update_price(aid, 110, "x", "2026-11-05")
        fresh = {p["id"]: p for p in self.service.positions(today=date(2026, 11, 8))}[aid]
        stale = {p["id"]: p for p in self.service.positions(today=date(2026, 12, 8))}[aid]
        self.assertEqual(fresh["price_status"], "ACTUALIZADO")
        self.assertEqual(stale["price_status"], "DESACTUALIZADO")

    def test_unrealized_gain_and_loss(self):
        aid = self.amazon["id"]
        self.db.add_transaction(aid, "COMPRA", "2026-01-01", 10, 100, 5)
        self.db.update_price(aid, 90, "x", "2026-11-05")
        p = self.pos(aid)
        self.assertAlmostEqual(p["unrealized"], 900 - 1005)
        self.db.update_price(aid, 120, "x", "2026-11-06")
        self.assertAlmostEqual(self.pos(aid)["unrealized"], 1200 - 1005)


class IncomeTest(BaseCase):
    def test_duplicate_dividend_is_rejected_and_counted_once(self):
        aid = self.bancolombia["id"]
        self.db.add_income(aid, "DIVIDENDO", "2026-04-01", 50000, "T1")
        with self.assertRaises(DuplicateIncomeError):
            self.db.add_income(aid, "DIVIDENDO", "2026-04-01", 50000, "T1 otra vez")
        self.assertEqual(len(self.db.get_income_events()), 1)
        self.assertAlmostEqual(self.service.summary(4000.0)["income"], 50000)

    def test_duplicate_can_be_forced_on_purpose(self):
        aid = self.bancolombia["id"]
        self.db.add_income(aid, "DIVIDENDO", "2026-04-01", 50000, "")
        self.db.add_income(aid, "DIVIDENDO", "2026-04-01", 50000, "", allow_duplicate=True)
        self.assertEqual(len(self.db.get_income_events()), 2)

    def test_net_dividend_discounts_withholding_and_fees(self):
        aid = self.bancolombia["id"]
        self.db.add_transaction(aid, "COMPRA", "2026-01-01", 1, 100, 0)
        self.db.add_income(aid, "DIVIDENDO", "2026-04-01", 100000, "", withholding=10000, fees=2000)
        e = self.db.get_income_events()[0]
        self.assertAlmostEqual(e["net_amount"], 88000)
        s = self.service.summary(4000.0)
        self.assertAlmostEqual(s["income"], 88000)
        self.assertAlmostEqual(s["income_gross"], 100000)
        self.assertAlmostEqual(s["income_deductions"], 12000)

    def test_invalid_income_values(self):
        aid = self.bancolombia["id"]
        with self.assertRaises(ValueError):
            self.db.add_income(aid, "DIVIDENDO", "2026-04-01", 0, "")
        with self.assertRaises(ValueError):
            self.db.add_income(aid, "DIVIDENDO", "2026-04-01", 100, "", withholding=200)

    def test_income_enters_total_profit_once(self):
        aid = self.bancolombia["id"]
        self.db.add_transaction(aid, "COMPRA", "2026-01-01", 10, 1000, 0)
        self.db.update_price(aid, 1100, "x", "2026-11-05")
        self.db.add_income(aid, "DIVIDENDO", "2026-04-01", 500, "")
        s = self.service.summary(4000.0)
        self.assertAlmostEqual(s["profit"], 1000 + 500)        # no realizada + dividendo
        self.assertAlmostEqual(s["accumulated_pct"], 1500 / 10000 * 100)


class SummaryTest(BaseCase):
    def test_usd_needs_exchange_rate(self):
        aid = self.amazon["id"]
        self.db.add_transaction(aid, "COMPRA", "2026-01-01", 2, 100, 0)
        self.db.update_price(aid, 110, "x", "2026-11-05")
        without = self.service.summary(usd_cop=None)
        self.assertEqual(without["fx_missing"], ["Amazon"])
        self.assertEqual(without["market_value"], 0)
        with_fx = self.service.summary(usd_cop=4000.0)
        self.assertEqual(with_fx["fx_missing"], [])
        self.assertAlmostEqual(with_fx["market_value"], 220 * 4000)
        self.assertAlmostEqual(with_fx["unrealized"], 20 * 4000)

    def test_pending_asset_still_counts_realized_and_dividends(self):
        """Ventas ya hechas y dividendos no dependen del precio actual: siempre cuentan."""
        aid = self.bancolombia["id"]
        self.db.add_transaction(aid, "COMPRA", "2026-01-01", 10, 1000, 0)
        self.db.add_transaction(aid, "VENTA", "2026-02-01", 4, 1200, 0)   # realizada 800
        self.db.add_income(aid, "DIVIDENDO", "2026-04-01", 300, "")
        s = self.service.summary(4000.0)
        self.assertEqual(s["pending_assets"], ["Bancolombia"])
        self.assertAlmostEqual(s["realized"], 800)
        self.assertAlmostEqual(s["income"], 300)
        self.assertAlmostEqual(s["unrealized"], 0)          # no se inventa
        self.assertAlmostEqual(s["profit"], 800 + 300)      # las tarjetas suman
        self.assertIsNone(s["accumulated_pct"])             # sin activos valorables no hay %
        self.db.update_price(aid, 1100, "x", "2026-11-05")
        s = self.service.summary(4000.0)
        self.assertEqual(s["pending_assets"], [])
        self.assertAlmostEqual(s["unrealized"], 6 * 1100 - 6000)
        self.assertAlmostEqual(s["profit"], 800 + 600 + 300)

    def test_empty_portfolio_summary_does_not_fail(self):
        s = self.service.summary(4000.0)
        self.assertIsNone(s["accumulated_pct"])
        self.assertIsNone(s["xirr_pct"])
        self.assertEqual(s["market_value"], 0)

    def test_xirr_computed_when_everything_is_priced(self):
        aid = self.bancolombia["id"]
        self.db.add_transaction(aid, "COMPRA", "2025-01-01", 10, 1000, 0)
        self.db.update_price(aid, 1100, "x", "2026-01-01")
        s = self.service.summary(valuation_date=date(2026, 1, 1))
        self.assertAlmostEqual(s["xirr_pct"], 10.0, delta=0.3)

    def test_fixed_income_registration_and_projection(self):
        aid = self.db.add_fixed_income_investment(
            "CDT Banco X", "CDT-X", "CDT", "Banco", 10_000_000, 12.0, "Efectiva anual",
            "2026-01-01", "2027-01-01", "Al vencimiento")
        p = self.pos(aid)
        self.assertAlmostEqual(p["market_value"], 10_000_000)       # a costo
        self.assertEqual(p["price_status"], "A COSTO REGISTRADO")
        row = [r for r in self.service.fixed_income_overview(today=date(2026, 7, 1))
               if r["asset_id"] == aid][0]
        self.assertEqual(row["status"], "Vigente")
        self.assertAlmostEqual(row["est_interest_at_maturity"], 1_200_000, delta=5000)
        # redención: venta de 1 unidad por el total recibido
        self.service.register_trade(aid, "VENTA", "2027-01-01", 1, 11_200_000, 0)
        p = self.pos(aid)
        self.assertAlmostEqual(p["realized"], 1_200_000)
        self.assertEqual(p["quantity"], 0.0)

    def test_variable_rate_has_no_invented_projection(self):
        aid = self.db.add_fixed_income_investment(
            "TES", "TES-1", "TES", "Gobierno", 1_000_000, 9.0, "Fija",
            "2026-01-01", "2030-01-01", "Semestral")
        row = [r for r in self.service.fixed_income_overview() if r["asset_id"] == aid][0]
        self.assertIsNone(row["est_value_at_maturity"])


class QuoteTest(unittest.TestCase):
    @staticmethod
    def history(prices, dates):
        return pd.DataFrame({"Close": prices}, index=pd.to_datetime(dates))

    def test_quote_returns_price_date_and_source(self):
        provider = MarketDataProvider()
        hist = self.history([100.0, 102.5], ["2026-11-05", "2026-11-06"])
        with mock.patch.object(provider, "_download", return_value=(hist, "USD")):
            q = provider.fetch_quote("KO", expected_currency="USD")
        self.assertEqual((q.price, q.price_date), (102.5, "2026-11-06"))
        self.assertIn("no es tiempo real", q.source)
        self.assertFalse(q.realtime)

    def test_empty_response_raises_instead_of_zero(self):
        provider = MarketDataProvider()
        with mock.patch.object(provider, "_download", return_value=(pd.DataFrame({"Close": []}), None)):
            with self.assertRaises(QuoteError):
                provider.fetch_quote("NOEXISTE")

    def test_currency_mismatch_is_refused(self):
        provider = MarketDataProvider()
        hist = self.history([10.0], ["2026-11-06"])
        with mock.patch.object(provider, "_download", return_value=(hist, "USD")):
            with self.assertRaises(QuoteError):
                provider.fetch_quote("CIB", expected_currency="COP")

    def test_network_failure_is_reported(self):
        provider = MarketDataProvider()
        with mock.patch.object(provider, "_download", side_effect=OSError("sin internet")):
            with self.assertRaises(QuoteError):
                provider.fetch_quote("KO")

    def test_fx_quote_and_storage(self):
        provider = MarketDataProvider()
        hist = self.history([3900.0, 3950.25], ["2026-11-05", "2026-11-06"])
        with mock.patch.object(provider, "_download", return_value=(hist, None)):
            q = provider.fetch_usd_cop()
        self.assertEqual(q.price_date, "2026-11-06")
        self.assertIn("no es la TRM oficial", q.source)
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            self.assertIsNone(db.get_latest_fx_rate())
            db.save_fx_rate(q.price, q.price_date, q.source)
            self.assertEqual(db.get_latest_fx_rate()["rate"], 3950.25)
            with self.assertRaises(ValueError):
                db.save_fx_rate(0, "2026-11-06", "x")


if __name__ == "__main__":
    unittest.main()
