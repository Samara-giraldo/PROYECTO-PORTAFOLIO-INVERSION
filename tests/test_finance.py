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
        self.db.add_transaction(self.asset_id, "COMPRA", "2026-01-01", 10, 100, 5)
        self.db.update_price(self.asset_id, 110, "Prueba", "2026-02-01")
        position = self.service.positions()[0]
        self.assertAlmostEqual(position["quantity"], 10)
        self.assertAlmostEqual(position["remaining_cost"], 1005)
        self.assertAlmostEqual(position["unrealized"], 95)

    def test_sale_uses_average_cost_and_fee(self):
        self.db.add_transaction(self.asset_id, "COMPRA", "2026-01-01", 10, 100, 0)
        self.db.add_transaction(self.asset_id, "VENTA", "2026-02-01", 4, 120, 2)
        position = self.service.positions()[0]
        self.assertAlmostEqual(position["quantity"], 6)
        self.assertAlmostEqual(position["realized"], 78)

    def test_xirr_simple_one_year(self):
        result = self.service.xirr([
            (date(2025,1,1), -1000),
            (date(2026,1,1), 1100)
        ])
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.10, delta=0.002)

if __name__ == "__main__":
    unittest.main()
