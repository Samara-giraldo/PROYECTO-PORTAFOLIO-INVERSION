
from datetime import date


class PortfolioService:
    """Calcula posiciones, costos y resultados del portafolio."""

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

                elif tx["operation"] == "VENTA":
                    if q > quantity + 1e-9:
                        raise ValueError(
                            f"Las ventas de {asset['name']} superan "
                            "la cantidad comprada."
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
                        quantity = 0
                        remaining_cost = 0

            current_price = float(asset["current_price"] or 0)
            has_price = (
                asset.get("price_status") == "DISPONIBLE"
                and current_price > 0
            )

            market_value = quantity * current_price if has_price else None
            unrealized = (
                market_value - remaining_cost
                if market_value is not None else None
            )

            result.append({
                **asset,
                "quantity": quantity,
                "remaining_cost": remaining_cost,
                "market_value": market_value,
                "realized": realized,
                "unrealized": unrealized,
                "total_buys": total_buys,
                "has_price": has_price,
                "total_profit_before_income": (
                    realized + unrealized
                    if unrealized is not None else None
                )
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
                value / ((1 + rate) ** ((d - start).days / 365.0))
                for d, value in flows
            )

        low, high = -0.9999, 10.0
        f_low, f_high = npv(low), npv(high)

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

        invested = sum(
            p["total_buys"] * fx(p["currency"])
            for p in positions
        )

        realized = sum(
            p["realized"] * fx(p["currency"])
            for p in positions
        )

        # No se interpreta un precio desconocido como cero.
        priced_positions = [p for p in positions if p["has_price"]]

        market_value = sum(
            p["market_value"] * fx(p["currency"])
            for p in priced_positions
        )

        unrealized = sum(
            p["unrealized"] * fx(p["currency"])
            for p in priced_positions
        )

        income_total = sum(
            e["amount"] * fx(e["currency"])
            for e in incomes
        )

        fees = sum(
            t["commission"] * fx(t["currency"])
            for t in transactions
        )

        profit = realized + unrealized + income_total

        accumulated = (
            profit / invested * 100 if invested > 0 else None
        )

        fixed_value = sum(
            p["market_value"] * fx(p["currency"])
            for p in priced_positions
            if p["asset_type"] in ("CDT", "BONO", "TES")
        )

        variable_value = sum(
            p["market_value"] * fx(p["currency"])
            for p in priced_positions
            if p["asset_type"] == "ACCION"
        )

        total_market = fixed_value + variable_value

        flows = []

        for tx in transactions:
            tx_date = date.fromisoformat(tx["date"])
            gross = float(tx["quantity"]) * float(tx["price"])

            if tx["operation"] == "COMPRA":
                amount = -(gross + float(tx["commission"]))
            else:
                amount = gross - float(tx["commission"])

            flows.append((tx_date, amount * fx(tx["currency"])))

        for event in incomes:
            flows.append((
                date.fromisoformat(event["date"]),
                float(event["amount"]) * fx(event["currency"])
            ))

        # La TIR solo se calcula si todas las posiciones abiertas
        # tienen una cotización registrada.
        all_open_positions_priced = all(
            p["quantity"] <= 0 or p["has_price"]
            for p in positions
        )

        if all_open_positions_priced:
            flows.append((valuation_date, market_value))
            tir = self.xirr(flows)
        else:
            tir = None

        return {
            "invested": invested,
            "market_value": market_value,
            "realized": realized,
            "unrealized": unrealized,
            "income": income_total,
            "fees": fees,
            "profit": profit,
            "accumulated_pct": accumulated,
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
            "pending_quotes": sum(
                1 for p in positions
                if p["quantity"] > 0 and not p["has_price"]
            )
        }