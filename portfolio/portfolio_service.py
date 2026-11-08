
from datetime import date


class PortfolioService:
    """Calcula posiciones, resultados y rentabilidad del portafolio."""

    def __init__(self, database):
        self.db = database

    def positions(self):
        assets = self.db.get_assets()
        transactions = self.db.get_transactions()
        result = []

        for asset in assets:
            rows = [
                tx for tx in transactions
                if tx["asset_id"] == asset["id"]
            ]

            quantity = 0.0
            remaining_cost = 0.0
            realized = 0.0
            total_buys = 0.0

            for tx in rows:
                q = float(tx["quantity"])
                price = float(tx["price"])
                fee = float(tx["commission"])

                if tx["operation"] == "COMPRA":
                    cost = q * price + fee
                    quantity += q
                    remaining_cost += cost
                    total_buys += cost

                else:
                    if q > quantity + 1e-9:
                        raise ValueError(
                            f"Las ventas de {asset['name']} "
                            "superan las unidades compradas."
                        )

                    average_cost = (
                        remaining_cost / quantity if quantity > 0 else 0
                    )

                    cost_sold = average_cost * q
                    net_proceeds = q * price - fee

                    realized += net_proceeds - cost_sold
                    quantity -= q
                    remaining_cost -= cost_sold

                    if abs(quantity) < 1e-9:
                        quantity = 0.0
                        remaining_cost = 0.0

            current_price = float(asset["current_price"])
            market_value = quantity * current_price
            unrealized = market_value - remaining_cost

            result.append({
                **asset,
                "quantity": quantity,
                "remaining_cost": remaining_cost,
                "market_value": market_value,
                "realized": realized,
                "unrealized": unrealized,
                "total_buys": total_buys,
                "total_profit_before_income": realized + unrealized,
            })

        return result

    @staticmethod
    def xirr(flows):
        """Calcula una tasa anualizada aproximada por bisección."""

        flows = [
            (d, float(value))
            for d, value in flows
            if abs(float(value)) > 1e-10
        ]

        if (
            not flows
            or not any(value < 0 for _, value in flows)
            or not any(value > 0 for _, value in flows)
        ):
            return None

        start = min(d for d, _ in flows)

        def npv(rate):
            return sum(
                value / (
                    (1 + rate) ** ((d - start).days / 365.0)
                )
                for d, value in flows
            )

        low = -0.9999
        high = 10.0

        f_low = npv(low)
        f_high = npv(high)

        if f_low * f_high > 0:
            return None

        for _ in range(250):
            mid = (low + high) / 2
            f_mid = npv(mid)

            if abs(f_mid) < 1e-7:
                return mid

            if f_low * f_mid <= 0:
                high = mid
                f_high = f_mid
            else:
                low = mid
                f_low = f_mid

        return (low + high) / 2

    def summary(self, usd_cop=4000.0, valuation_date=None):
        valuation_date = valuation_date or date.today()
        positions = self.positions()
        incomes = self.db.get_income_events()
        transactions = self.db.get_transactions()

        def fx(currency):
            return float(usd_cop) if currency == "USD" else 1.0

        accumulated_purchases = sum(
            p["total_buys"] * fx(p["currency"])
            for p in positions
        )

        open_cost = sum(
            p["remaining_cost"] * fx(p["currency"])
            for p in positions
        )

        market_value = sum(
            p["market_value"] * fx(p["currency"])
            for p in positions
        )

        realized = sum(
            p["realized"] * fx(p["currency"])
            for p in positions
        )

        unrealized = sum(
            p["unrealized"] * fx(p["currency"])
            for p in positions
        )

        income_total = sum(
            float(event["amount"]) * fx(event["currency"])
            for event in incomes
        )

        fees = sum(
            float(tx["commission"]) * fx(tx["currency"])
            for tx in transactions
        )

        profit = realized + unrealized + income_total

        accumulated_pct = (
            profit / accumulated_purchases * 100
            if accumulated_purchases > 0 else None
        )

        fixed_value = sum(
            p["market_value"] * fx(p["currency"])
            for p in positions
            if p["asset_type"] in ("CDT", "BONO", "TES")
        )

        variable_value = sum(
            p["market_value"] * fx(p["currency"])
            for p in positions
            if p["asset_type"] == "ACCION"
        )

        total_market = fixed_value + variable_value

        flows = []

        for tx in transactions:
            tx_date = date.fromisoformat(tx["date"])
            gross = float(tx["quantity"]) * float(tx["price"])
            commission = float(tx["commission"])

            if tx["operation"] == "COMPRA":
                amount = -(gross + commission)
            else:
                amount = gross - commission

            flows.append((tx_date, amount * fx(tx["currency"])))

        for event in incomes:
            flows.append((
                date.fromisoformat(event["date"]),
                float(event["amount"]) * fx(event["currency"])
            ))

        flows.append((valuation_date, market_value))
        tir = self.xirr(flows)

        return {
            "invested": accumulated_purchases,
            "accumulated_purchases": accumulated_purchases,
            "open_cost": open_cost,
            "market_value": market_value,
            "realized": realized,
            "unrealized": unrealized,
            "income": income_total,
            "fees": fees,
            "profit": profit,
            "accumulated_pct": accumulated_pct,
            "xirr_pct": tir * 100 if tir is not None else None,
            "fixed_value": fixed_value,
            "variable_value": variable_value,
            "fixed_pct": (
                fixed_value / total_market * 100 if total_market else 0
            ),
            "variable_pct": (
                variable_value / total_market * 100 if total_market else 0
            ),
            "positions": positions,
        }
