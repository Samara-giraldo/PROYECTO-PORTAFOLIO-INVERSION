from datetime import date, datetime

FIXED_INCOME_TYPES = ("CDT", "BONO", "TES")

# Estados del precio de un activo
PRICE_OK = "ACTUALIZADO"
PRICE_STALE = "DESACTUALIZADO"
PRICE_NO_DATE = "SIN FECHA"
PRICE_PENDING = "PENDIENTE"
PRICE_AT_COST = "A COSTO REGISTRADO"

STALE_AFTER_DAYS = 7
EPS = 1e-9


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def replay_transactions(rows):
    """Recorre las operaciones de UN activo en orden y calcula su posición.

    Método: costo promedio ponderado. El costo de compra incluye la comisión de compra;
    el ingreso de una venta es el valor bruto menos la comisión de venta.
    Si una venta supera lo que había en cartera, NO se detiene la aplicación: se vende
    solo lo disponible y se anota el problema en ``issues``.
    """
    quantity = 0.0
    remaining_cost = 0.0
    realized = 0.0
    total_buys = 0.0
    buy_fees = 0.0
    sell_fees = 0.0
    sell_proceeds = 0.0
    issues = []

    for tx in sorted(rows, key=lambda t: (t["date"], t["id"])):
        q, price, fee = float(tx["quantity"]), float(tx["price"]), float(tx["commission"])
        if tx["operation"] == "COMPRA":
            cost = q * price + fee
            quantity += q
            remaining_cost += cost
            total_buys += cost
            buy_fees += fee
        else:
            sold = q
            if q > quantity + EPS:
                issues.append(
                    f"La venta del {tx['date']} ({q:g} unidades) supera lo que había en "
                    f"cartera ({quantity:g}). Se calculó solo con lo disponible; revisa el registro.")
                sold = quantity
            if sold <= EPS:
                continue
            ratio = sold / q
            fee_used = fee * ratio
            average_cost = remaining_cost / quantity if quantity > EPS else 0.0
            cost_sold = average_cost * sold
            net_proceeds = sold * price - fee_used
            realized += net_proceeds - cost_sold
            sell_proceeds += net_proceeds
            sell_fees += fee_used
            quantity -= sold
            remaining_cost -= cost_sold
            if quantity < EPS:       # evita residuos de punto flotante al vender todo
                quantity = 0.0
                remaining_cost = 0.0

    return {
        "quantity": quantity, "remaining_cost": remaining_cost, "realized": realized,
        "total_buys": total_buys, "buy_fees": buy_fees, "sell_fees": sell_fees,
        "sell_proceeds": sell_proceeds, "issues": issues,
        "avg_cost": remaining_cost / quantity if quantity > EPS else None,
    }


class PortfolioService:
    """Reglas de negocio y cálculos del portafolio."""

    def __init__(self, database):
        self.db = database

    # ------------------------------------------------------------------
    # Validaciones antes de guardar
    # ------------------------------------------------------------------
    def validate_trade(self, asset_id, operation, date_iso, quantity):
        """Lanza ValueError si la operación dejaría las cantidades en negativo.

        Revisa también las ventas con fecha posterior (por ejemplo, al registrar una
        compra o venta con fecha atrasada).
        """
        if operation not in ("COMPRA", "VENTA"):
            raise ValueError("La operación debe ser COMPRA o VENTA.")
        if not float(quantity) > 0:
            raise ValueError("La cantidad debe ser mayor que cero.")
        if _parse_date(date_iso) is None:
            raise ValueError("La fecha no es válida.")
        if operation == "COMPRA":
            return
        existing = [t for t in self.db.get_transactions() if t["asset_id"] == int(asset_id)]
        before = len(replay_transactions(existing)["issues"])
        hypothetical = existing + [{
            "id": 10**12, "operation": operation, "date": date_iso,
            "quantity": float(quantity), "price": 0.0, "commission": 0.0}]
        after = replay_transactions(hypothetical)["issues"]
        if len(after) > before:
            available = replay_transactions(
                [t for t in existing if t["date"] <= date_iso])["quantity"]
            raise ValueError(
                f"No puedes vender {float(quantity):g} unidades con fecha {date_iso}: "
                f"en esa fecha solo tenías {available:g}, o la venta dejaría inconsistentes "
                f"otras operaciones posteriores.")

    def register_trade(self, asset_id, operation, date_iso, quantity, price, commission,
                       commission_source="ESTIMADA", notes=""):
        if not float(price) > 0:
            raise ValueError("El precio por acción debe ser mayor que cero.")
        if float(commission) < 0:
            raise ValueError("La comisión no puede ser negativa.")
        self.validate_trade(asset_id, operation, date_iso, quantity)
        return self.db.add_transaction(asset_id, operation, date_iso, quantity, price,
                                       commission, commission_source, notes)

    def register_first_purchase(self, asset, date_iso, quantity, price, commission,
                                commission_source="ESTIMADA", notes=""):
        """Empresa nueva + primera compra en un solo paso. ``asset`` es un diccionario
        con name, symbol, asset_type, currency, market y (opcional) yahoo_symbol."""
        name = (asset.get("name") or "").strip()
        symbol = (asset.get("symbol") or "").strip().upper()
        if not name or not symbol:
            raise ValueError("Completa el nombre de la empresa y su símbolo.")
        if any(a["symbol"].upper() == symbol for a in self.db.get_assets()):
            raise ValueError(f"Ya existe un activo con el símbolo {symbol}. Selecciónalo en la lista.")
        if not float(price) > 0:
            raise ValueError("El precio por acción debe ser mayor que cero.")
        if not float(quantity) > 0:
            raise ValueError("La cantidad debe ser mayor que cero.")
        if _parse_date(date_iso) is None:
            raise ValueError("La fecha no es válida.")
        asset_args = {
            "name": name, "symbol": symbol, "asset_type": asset.get("asset_type", "ACCION"),
            "currency": asset["currency"], "market": (asset.get("market") or "Manual").strip(),
            "current_price": 0, "source": "Sin cotización",
            "yahoo_symbol": (asset.get("yahoo_symbol") or "").strip() or None,
        }
        tx_args = {"operation": "COMPRA", "date": date_iso, "quantity": float(quantity),
                   "price": float(price), "commission": float(commission),
                   "commission_source": commission_source, "notes": notes}
        return self.db.add_asset_and_transaction(asset_args, tx_args)

    # ------------------------------------------------------------------
    # Posiciones
    # ------------------------------------------------------------------
    @staticmethod
    def _price_info(asset, quantity, today):
        """Decide si el precio del activo es utilizable y en qué estado está."""
        price = float(asset.get("current_price") or 0)
        price_date = asset.get("price_date")
        fixed = asset["asset_type"] in FIXED_INCOME_TYPES
        if not price > 0:
            return None, price_date, PRICE_PENDING, None
        if fixed:
            return price, price_date, PRICE_AT_COST, None
        parsed = _parse_date(price_date)
        if parsed is None:
            return price, price_date, PRICE_NO_DATE, None
        age = (today - parsed).days
        status = PRICE_STALE if age > STALE_AFTER_DAYS else PRICE_OK
        return price, price_date, status, age

    def positions(self, today=None):
        today = today or date.today()
        assets = self.db.get_assets()
        transactions = self.db.get_transactions()
        incomes = self.db.get_income_events()
        result = []
        for asset in assets:
            rows = [t for t in transactions if t["asset_id"] == asset["id"]]
            calc = replay_transactions(rows)
            quantity = calc["quantity"]
            price, price_date, status, age = self._price_info(asset, quantity, today)

            if quantity <= EPS:
                market_value, unrealized = 0.0, 0.0     # sin acciones: no depende del precio
                valuation_known = True
            elif price is None:
                market_value, unrealized = None, None   # PENDIENTE: nunca se vuelve cero
                valuation_known = False
            else:
                market_value = quantity * price
                unrealized = market_value - calc["remaining_cost"]
                valuation_known = True

            income_net = sum(float(e["net_amount"]) for e in incomes if e["asset_id"] == asset["id"])
            income_gross = sum(float(e["amount"]) for e in incomes if e["asset_id"] == asset["id"])
            total_result = (calc["realized"] + (unrealized or 0.0) + income_net
                            if valuation_known else None)

            result.append({
                **asset,
                "quantity": quantity,
                "remaining_cost": calc["remaining_cost"],
                "avg_cost": calc["avg_cost"],
                "market_value": market_value,
                "realized": calc["realized"],
                "unrealized": unrealized,
                "total_buys": calc["total_buys"],
                "buy_fees": calc["buy_fees"],
                "sell_fees": calc["sell_fees"],
                "fees_total": calc["buy_fees"] + calc["sell_fees"],
                "income_net": income_net,
                "income_gross": income_gross,
                "price": price,
                "price_date": price_date,
                "price_status": status,
                "price_age_days": age,
                "valuation_known": valuation_known,
                "issues": calc["issues"],
                "total_result": total_result,
                "total_profit_before_income": (calc["realized"] + (unrealized or 0.0)
                                               if valuation_known else None),
            })
        return result

    # ------------------------------------------------------------------
    # TIR
    # ------------------------------------------------------------------
    def xirr(self, flows):
        """Calcula TIR anualizada mediante búsqueda por bisección."""
        flows = [(d, float(v)) for d, v in flows if abs(float(v)) > 1e-10]
        if not flows or not any(v < 0 for _, v in flows) or not any(v > 0 for _, v in flows):
            return None
        start = min(d for d, _ in flows)

        def npv(rate):
            return sum(value / ((1 + rate) ** ((d - start).days / 365.0))
                       for d, value in flows)

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
                high, f_high = mid, f_mid
            else:
                low, f_low = mid, f_mid
        return (low + high) / 2

    # ------------------------------------------------------------------
    # Resumen consolidado en COP
    # ------------------------------------------------------------------
    def summary(self, usd_cop=None, valuation_date=None):
        """Resume el portafolio en COP.

        * Un activo con precio PENDIENTE no se cuenta como pérdida: se deja fuera de las
          cifras de valoración y se lista en ``pending_assets``.
        * Si hay activos en USD y no se conoce la tasa USD/COP, esos activos se dejan fuera
          de los totales y se listan en ``fx_missing``.
        """
        valuation_date = valuation_date or date.today()
        positions = self.positions(today=valuation_date)
        incomes = self.db.get_income_events()
        transactions = self.db.get_transactions()
        have_fx = usd_cop is not None and float(usd_cop) > 0

        def rate(currency):
            if currency == "COP":
                return 1.0
            if currency == "USD" and have_fx:
                return float(usd_cop)
            return None

        pending_assets, fx_missing, issues = [], [], []
        convertible = []   # posiciones que se pueden convertir a COP (con o sin precio)
        known = []         # además, tienen un valor actual conocido
        for p in positions:
            issues.extend(f"{p['name']}: {msg}" for msg in p["issues"])
            used = p["total_buys"] > 0 or p["quantity"] > EPS or p["income_gross"] > 0
            if not used:
                continue
            if rate(p["currency"]) is None:
                fx_missing.append(p["name"])
                continue
            convertible.append(p)
            if not p["valuation_known"]:
                pending_assets.append(p["name"])
                continue
            known.append(p)

        def cop(p, key):
            return float(p[key] or 0.0) * rate(p["currency"])

        def conv(amount, currency):
            r = rate(currency)
            return None if r is None else float(amount) * r

        # Hechos que NO dependen del precio actual: ventas ya hechas, dividendos y comisiones.
        realized = sum(cop(p, "realized") for p in convertible)
        income_gross = sum(v for v in (conv(e["amount"], e["currency"]) for e in incomes) if v is not None)
        income_net = sum(v for v in (conv(e["net_amount"], e["currency"]) for e in incomes) if v is not None)
        income_deductions = income_gross - income_net
        fees = sum(v for v in (conv(t["commission"], t["currency"]) for t in transactions) if v is not None)

        # Valoración: solo posiciones con precio conocido (un precio faltante no es cero)
        open_cost = sum(cop(p, "remaining_cost") for p in known)
        market_value = sum(cop(p, "market_value") for p in known)
        unrealized = sum(cop(p, "unrealized") for p in known)
        profit = realized + unrealized + income_net

        # Rentabilidad %: se calcula solo sobre activos con precio conocido, para que el
        # numerador y el denominador hablen de lo mismo.
        invested = sum(cop(p, "total_buys") for p in known)
        profit_known = sum(cop(p, "realized") + cop(p, "unrealized") + cop(p, "income_net") for p in known)
        accumulated = (profit_known / invested * 100) if invested > 0 else None

        # Pendientes: se informa su costo, pero no se les inventa un valor
        pending_cost = sum(cop(p, "remaining_cost") for p in convertible if not p["valuation_known"])

        fixed = sum(cop(p, "market_value") for p in known if p["asset_type"] in FIXED_INCOME_TYPES)
        variable = sum(cop(p, "market_value") for p in known if p["asset_type"] == "ACCION")
        total_market = fixed + variable

        # XIRR: solo si TODO se puede valorar; de lo contrario sería un número engañoso
        partial = bool(pending_assets or fx_missing)
        tir, xirr_note = None, None
        if partial:
            xirr_note = "No se calcula mientras haya activos sin precio o sin tasa de cambio."
        else:
            flows = []
            for t in transactions:
                gross = float(t["quantity"]) * float(t["price"])
                amount = (gross + float(t["commission"]) if t["operation"] == "COMPRA"
                          else gross - float(t["commission"]))
                signed = -amount if t["operation"] == "COMPRA" else amount
                flows.append((_parse_date(t["date"]) or valuation_date, signed * rate(t["currency"])))
            for e in incomes:
                flows.append((_parse_date(e["date"]) or valuation_date,
                              float(e["net_amount"]) * rate(e["currency"])))
            flows.append((valuation_date, market_value))
            tir = self.xirr(flows)
            xirr_note = ("Los flujos en USD se convierten con la tasa actual, no con la tasa "
                         "del día de cada operación; es una aproximación.")
            if tir is None:
                xirr_note = "No existe una tasa válida con los flujos actuales."

        return {
            "invested": invested, "open_cost": open_cost, "market_value": market_value,
            "realized": realized, "unrealized": unrealized,
            "income": income_net, "income_gross": income_gross,
            "income_deductions": income_deductions,
            "fees": fees, "profit": profit, "profit_known": profit_known,
            "accumulated_pct": accumulated,
            "xirr_pct": tir * 100 if tir is not None else None, "xirr_note": xirr_note,
            "fixed_value": fixed, "variable_value": variable,
            "fixed_pct": fixed / total_market * 100 if total_market else 0,
            "variable_pct": variable / total_market * 100 if total_market else 0,
            "pending_assets": pending_assets, "pending_cost": pending_cost,
            "fx_missing": fx_missing, "partial": partial, "issues": issues,
            "positions": positions,
        }

    # ------------------------------------------------------------------
    # Renta fija (referencial)
    # ------------------------------------------------------------------
    def fixed_income_overview(self, today=None):
        """Estado de CDT, TES y bonos según las condiciones que registró el usuario.

        El valor estimado al vencimiento SOLO se calcula para tasas efectivas anuales con
        pago de intereses al vencimiento. Es una proyección bruta (antes de retención e
        impuestos), no un valor de mercado.
        """
        today = today or date.today()
        positions = {p["id"]: p for p in self.positions(today=today)}
        rows = []
        for t in self.db.get_fixed_income_terms():
            p = positions.get(t["asset_id"])
            if p is None:
                continue
            issue, maturity = _parse_date(t["issue_date"]), _parse_date(t["maturity_date"])
            capital = float(p["remaining_cost"]) if p["quantity"] > EPS else float(t["nominal_value"])
            held = p["quantity"] > EPS
            status = "Redimido" if not held else (
                "Vencido, sin redimir" if maturity and maturity < today else "Vigente")
            days_left = (maturity - today).days if (maturity and held) else None

            projection = None
            interest_est = None
            if (t["rate_type"] == "Efectiva anual" and t["payment_frequency"] == "Al vencimiento"
                    and issue and maturity and maturity > issue):
                years = (maturity - issue).days / 365.0
                interest_est = capital * ((1 + float(t["annual_rate_pct"]) / 100) ** years - 1)
                projection = capital + interest_est
            rows.append({
                "asset_id": t["asset_id"], "name": t["asset_name"], "asset_type": t["asset_type"],
                "currency": p["currency"], "capital": capital, "held": held, "status": status,
                "annual_rate_pct": t["annual_rate_pct"], "rate_type": t["rate_type"],
                "issue_date": t["issue_date"], "maturity_date": t["maturity_date"],
                "payment_frequency": t["payment_frequency"], "days_to_maturity": days_left,
                "est_interest_at_maturity": interest_est, "est_value_at_maturity": projection,
                "interest_received": p["income_net"], "notes": t.get("notes", ""),
            })
        return rows
