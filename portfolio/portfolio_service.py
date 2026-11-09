
from datetime import date


class PortfolioService:
    """Reglas de negocio y cálculos del portafolio."""

    def __init__(self, database):
        self.db = database

    def positions(self):
        assets = self.db.get_assets()
        transactions = self.db.get_transactions()
        result = []

        for asset in assets:
            rows = [
                tx for tx in transactions
                if int(tx["asset_id"]) == int(asset["id"])
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
                            "superan la cantidad comprada."
                        )

                    average_cost = (
                        remaining_cost / quantity
                        if quantity > 0 else 0.0
                    )

                    cost_sold = average_cost * q
                    net_proceeds = q * price - fee

                    realized += net_proceeds - cost_sold
                    quantity -= q
                    remaining_cost -= cost_sold

                    if abs(quantity) < 1e-9:
                        quantity = 0.0
                        remaining_cost = 0.0

            market_value = (
                quantity * float(asset["current_price"])
            )

            unrealized = market_value - remaining_cost

            result.append({
                **asset,
                "quantity": quantity,
                "remaining_cost": remaining_cost,
                "market_value": market_value,
                "realized": realized,
                "unrealized": unrealized,
                "total_buys": total_buys,
                "total_profit_before_income": realized + unrealized
            })

        return result

    @staticmethod
    def xirr(flows):
        """
        Calcula una tasa anualizada aproximada mediante bisección.
        Cada flujo debe ser una tupla (fecha, valor).
        """
        clean_flows = []

        for flow_date, value in flows:
            if isinstance(flow_date, str):
                try:
                    flow_date = date.fromisoformat(flow_date)
                except ValueError:
                    raise ValueError(
                        "Hay una fecha inválida en los flujos."
                    )

            numeric_value = float(value)

            if abs(numeric_value) > 1e-10:
                clean_flows.append(
                    (flow_date, numeric_value)
                )

        flows = clean_flows

        if not flows:
            return None

        if not any(value < 0 for _, value in flows):
            return None

        if not any(value > 0 for _, value in flows):
            return None

        start = min(
            flow_date for flow_date, _ in flows
        )

        def npv(rate):
            total = 0.0

            for flow_date, value in flows:
                years = (
                    (flow_date - start).days / 365.0
                )

                total += value / ((1 + rate) ** years)

            return total

        low = -0.9999
        high = 10.0

        try:
            f_low = npv(low)
            f_high = npv(high)
        except (OverflowError, ZeroDivisionError):
            return None

        if f_low * f_high > 0:
            return None

        for _ in range(300):
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

    def summary(self, usd_cop=None, valuation_date=None):
        """
        Resume el portafolio en COP.

        Si existen operaciones, ingresos o posiciones en USD,
        exige una TRM real suministrada por la aplicación.
        No inventa una tasa de cambio.
        """
        if isinstance(valuation_date, str):
            try:
                valuation_date = date.fromisoformat(
                    valuation_date
                )
            except ValueError:
                raise ValueError(
                    "La fecha de valoración debe tener "
                    "formato AAAA-MM-DD."
                )

        valuation_date = valuation_date or date.today()

        if usd_cop is not None:
            try:
                usd_cop = float(usd_cop)
            except (TypeError, ValueError):
                raise ValueError(
                    "Debes proporcionar una TRM numérica válida."
                )

            if usd_cop <= 0:
                raise ValueError(
                    "Debes proporcionar una TRM válida."
                )

        positions = self.positions()
        incomes = self.db.get_income_events()
        transactions = self.db.get_transactions()

        has_usd_activity = (
            any(
                tx["currency"] == "USD"
                for tx in transactions
            )
            or any(
                event["currency"] == "USD"
                for event in incomes
            )
            or any(
                p["currency"] == "USD"
                and (
                    abs(float(p["quantity"])) > 1e-9
                    or abs(float(p["market_value"])) > 1e-9
                    or abs(float(p["remaining_cost"])) > 1e-9
                )
                for p in positions
            )
        )

        if has_usd_activity and usd_cop is None:
            raise ValueError(
                "Hay movimientos o posiciones en USD. "
                "Actualiza la TRM antes de calcular el resumen."
            )

        def fx(currency):
            if currency == "USD":
                return (
                    usd_cop
                    if usd_cop is not None
                    else 1.0
                )

            return 1.0

        # Total histórico de compras, incluyendo comisiones.
        accumulated_purchases = sum(
            p["total_buys"] * fx(p["currency"])
            for p in positions
        )

        # Costo de las unidades que todavía permanecen en cartera.
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
            event["amount"] * fx(event["currency"])
            for event in incomes
        )

        fees = sum(
            tx["commission"] * fx(tx["currency"])
            for tx in transactions
        )

        profit = (
            realized
            + unrealized
            + income_total
        )

        accumulated = (
            profit / accumulated_purchases * 100
            if accumulated_purchases > 0
            else None
        )

        fixed = sum(
            p["market_value"] * fx(p["currency"])
            for p in positions
            if p["asset_type"] in ("CDT", "BONO", "TES")
        )

        variable = sum(
            p["market_value"] * fx(p["currency"])
            for p in positions
            if p["asset_type"] == "ACCION"
        )

        total_market = fixed + variable

        flows = []

        for tx in transactions:
            tx_date = date.fromisoformat(tx["date"])

            gross = (
                float(tx["quantity"])
                * float(tx["price"])
            )

            commission = float(tx["commission"])

            if tx["operation"] == "COMPRA":
                amount = -(gross + commission)
            else:
                amount = gross - commission

            flows.append((
                tx_date,
                amount * fx(tx["currency"])
            ))

        for event in incomes:
            flows.append((
                date.fromisoformat(event["date"]),
                float(event["amount"]) * fx(event["currency"])
            ))

        flows.append((
            valuation_date,
            market_value
        ))

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
            "accumulated_pct": accumulated,
            "xirr_pct": (
                tir * 100
                if tir is not None
                else None
            ),
            "fixed_value": fixed,
            "variable_value": variable,
            "fixed_pct": (
                fixed / total_market * 100
                if total_market
                else 0
            ),
            "variable_pct": (
                variable / total_market * 100
                if total_market
                else 0
            ),
            "positions": positions
        }
