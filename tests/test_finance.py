
import tempfile
import unittest
from pathlib import Path
from datetime import date

from portfolio.database import Database
from portfolio.portfolio_service import PortfolioService


class PortfolioCalculationsTest(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db")
        self.service = PortfolioService(self.db)
        self.asset_id = self.db.get_assets()[0]["id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_buy_and_unrealized_profit(self):
        self.db.add_transaction(
            self.asset_id, "COMPRA", "2026-01-01", 10, 100, 5
        )
        self.db.update_price(
            self.asset_id, 110, "Prueba", "2026-02-01"
        )

        position = self.service.positions()[0]

        self.assertAlmostEqual(position["quantity"], 10)
        self.assertAlmostEqual(position["remaining_cost"], 1005)
        self.assertAlmostEqual(position["unrealized"], 95)

    def test_sale_uses_average_cost_and_fee(self):
        self.db.add_transaction(
            self.asset_id, "COMPRA", "2026-01-01", 10, 100, 0
        )
        self.db.add_transaction(
            self.asset_id, "VENTA", "2026-02-01", 4, 120, 2
        )

        position = self.service.positions()[0]

        self.assertAlmostEqual(position["quantity"], 6)
        self.assertAlmostEqual(position["realized"], 78)

    def test_sale_cannot_exceed_available_quantity(self):
        self.db.add_transaction(
            self.asset_id, "COMPRA", "2026-01-01", 5, 100, 0
        )

        with self.assertRaises(ValueError):
            self.db.add_transaction(
                self.asset_id, "VENTA", "2026-02-01", 6, 120, 0
            )

    def test_sale_before_purchase_is_rejected(self):
        self.db.add_transaction(
            self.asset_id, "COMPRA", "2026-02-01", 5, 100, 0
        )

        with self.assertRaises(ValueError):
            self.db.add_transaction(
                self.asset_id, "VENTA", "2026-01-01", 1, 120, 0
            )

    def test_invalid_quantity_is_rejected(self):
        with self.assertRaises(ValueError):
            self.db.add_transaction(
                self.asset_id, "COMPRA", "2026-01-01", 0, 100, 0
            )

    def test_invalid_date_is_rejected(self):
        with self.assertRaises(ValueError):
            self.db.add_transaction(
                self.asset_id, "COMPRA", "fecha incorrecta", 1, 100, 0
            )

    def test_sale_commission_cannot_exceed_gross_value(self):
        with self.assertRaises(ValueError):
            self.db.add_transaction(
                self.asset_id, "VENTA", "2026-01-01", 1, 100, 101
            )

    def test_xirr_simple_one_year(self):
        result = self.service.xirr([
            (date(2025, 1, 1), -1000),
            (date(2026, 1, 1), 1100)
        ])

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.10, delta=0.002)

    def test_open_cost_differs_from_historical_purchases(self):
        self.db.add_transaction(
            self.asset_id, "COMPRA", "2026-01-01", 10, 100, 0
        )
        self.db.add_transaction(
            self.asset_id, "VENTA", "2026-02-01", 4, 120, 0
        )

        summary = self.service.summary()

        self.assertAlmostEqual(summary["accumulated_purchases"], 1000)
        self.assertAlmostEqual(summary["open_cost"], 600)

    def test_unknown_asset_is_rejected(self):
        with self.assertRaises(ValueError):
            self.db.add_transaction(
                999999, "COMPRA", "2026-01-01", 1, 100, 0
            )


if __name__ == "__main__":
    unittest.main()
