from datetime import date, datetime

from portfolio.fees import compute_commission

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
    lots = []     # cada compra: cuánto y cuándo se invirtió
    sales = []    # cada venta: cuánto salió neto y cuánto costaron esas acciones

    for tx in sorted(rows, key=lambda t: (t["date"], t["id"])):
        q, price, fee = float(tx["quantity"]), float(tx["price"]), float(tx["commission"])
        if tx["operation"] == "COMPRA":
            cost = q * price + fee
            quantity += q
            remaining_cost += cost
            total_buys += cost
            buy_fees += fee
            lots.append({"date": tx["date"], "id": tx["id"], "quantity": q, "price": price,
                         "fee": fee, "cost": cost, "unit_cost": cost / q if q else None})
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
            sales.append({"date": tx["date"], "id": tx["id"], "quantity": sold, "price": price,
                          "gross": sold * price, "fee": fee_used, "net_proceeds": net_proceeds,
                          "avg_cost": average_cost, "cost_sold": cost_sold,
                          "result": net_proceeds - cost_sold,
                          "result_pct": ((net_proceeds - cost_sold) / cost_sold * 100
                                         if cost_sold > EPS else None)})
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
        "lots": lots, "sales": sales,
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
                       commission_source="ESTIMADA", notes="", fx_rate=None):
        if not float(price) > 0:
            raise ValueError("El precio por acción debe ser mayor que cero.")
        if float(commission) < 0:
            raise ValueError("La comisión no puede ser negativa.")
        self.validate_trade(asset_id, operation, date_iso, quantity)
        if fx_rate is not None and not float(fx_rate) > 0:
            raise ValueError("La TRM debe ser mayor que cero.")
        return self.db.add_transaction(asset_id, operation, date_iso, quantity, price,
                                       commission, commission_source, notes, fx_rate)

    def register_first_purchase(self, asset, date_iso, quantity, price, commission,
                                commission_source="ESTIMADA", notes="", fx_rate=None):
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
                   "commission_source": commission_source, "notes": notes,
                   "fx_rate": fx_rate}
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
        if fixed and str(asset.get("source") or "").startswith("Capital registrado"):
            return price, price_date, PRICE_AT_COST, None   # nunca se ha puesto un valor de mercado
        parsed = _parse_date(price_date)
        if parsed is None:
            return price, price_date, PRICE_NO_DATE, None
        age = (today - parsed).days
        status = PRICE_STALE if age > STALE_AFTER_DAYS else PRICE_OK
        return price, price_date, status, age

    @staticmethod
    def _row_rate(row, currency, usd_cop):
        """TRM de una fila: la guardada con la operación o, si no hay, la tasa actual."""
        if currency == "COP":
            return 1.0
        own = row.get("fx_rate")
        if own and float(own) > 0:
            return float(own)
        if currency == "USD" and usd_cop and float(usd_cop) > 0:
            return float(usd_cop)
        return None

    def positions(self, today=None, usd_cop=None):
        """Posición de cada activo en su moneda y también en COP.

        En COP cada compra, venta y dividendo usa la TRM de SU día cuando está guardada
        (como hace la hoja del profesor). Si una fila antigua no tiene TRM, se usa la tasa
        actual y el activo queda marcado como aproximado (``fx_approx``).
        """
        today = today or date.today()
        assets = self.db.get_assets()
        transactions = self.db.get_transactions()
        incomes = self.db.get_income_events()
        have_now = bool(usd_cop and float(usd_cop) > 0)
        result = []
        for asset in assets:
            rows = [t for t in transactions if t["asset_id"] == asset["id"]]
            calc = replay_transactions(rows)
            quantity = calc["quantity"]
            price, price_date, status, age = self._price_info(asset, quantity, today)
            cur = asset["currency"]

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

            my_income = [e for e in incomes if e["asset_id"] == asset["id"]]
            income_net = sum(float(e["net_amount"]) for e in my_income)
            income_gross = sum(float(e["amount"]) for e in my_income)
            total_result = (calc["realized"] + (unrealized or 0.0) + income_net
                            if valuation_known else None)

            # ---- versión en pesos con la TRM de cada operación
            rates = [self._row_rate(t, cur, usd_cop) for t in rows]
            inc_rates = [self._row_rate(e, cur, usd_cop) for e in my_income]
            cop_ok = all(r is not None for r in rates + inc_rates)
            fx_approx = cur != "COP" and any(
                not (t.get("fx_rate") and float(t["fx_rate"]) > 0) for t in rows + my_income)
            cop = {}
            if cop_ok:
                conv_rows = [{**t, "price": float(t["price"]) * r,
                              "commission": float(t["commission"]) * r}
                             for t, r in zip(rows, rates)]
                c = replay_transactions(conv_rows)
                now = 1.0 if cur == "COP" else (float(usd_cop) if have_now else None)
                mv_cop = (0.0 if quantity <= EPS else
                          (market_value * now if (market_value is not None and now) else None))
                cop = {
                    "remaining_cost_cop": c["remaining_cost"], "realized_cop": c["realized"],
                    "total_buys_cop": c["total_buys"], "buy_fees_cop": c["buy_fees"],
                    "sell_fees_cop": c["sell_fees"], "sell_proceeds_cop": c["sell_proceeds"],
                    "avg_cost_cop": c["avg_cost"], "lots_cop": c["lots"], "sales_cop": c["sales"],
                    "income_net_cop": sum(float(e["net_amount"]) * r for e, r in zip(my_income, inc_rates)),
                    "income_gross_cop": sum(float(e["amount"]) * r for e, r in zip(my_income, inc_rates)),
                    "market_value_cop": mv_cop,
                    "unrealized_cop": (None if mv_cop is None else mv_cop - c["remaining_cost"]),
                    "mv_cop_ok": quantity <= EPS or now is not None,
                }
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
                "lots": calc["lots"],
                "sales": calc["sales"],
                "total_result": total_result,
                "total_profit_before_income": (calc["realized"] + (unrealized or 0.0)
                                               if valuation_known else None),
                "cop_ok": cop_ok, "fx_approx": fx_approx,
                **cop,
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
        * Si hay activos en USD sin tasa USD/COP (ni la guardada en cada operación ni la
          actual), esos activos se dejan fuera de los totales y se listan en ``fx_missing``.
        * Cada compra, venta y dividendo en USD usa la TRM de su día si está guardada.
        """
        valuation_date = valuation_date or date.today()
        positions = self.positions(today=valuation_date, usd_cop=usd_cop)
        incomes = self.db.get_income_events()
        transactions = self.db.get_transactions()
        movements = self.db.get_cash_movements()

        pending_assets, fx_missing, fx_approx, issues = [], [], [], []
        convertible = []   # posiciones que se pueden convertir a COP (con o sin precio)
        known = []         # además, tienen un valor actual conocido
        for p in positions:
            issues.extend(f"{p['name']}: {msg}" for msg in p["issues"])
            used = p["total_buys"] > 0 or p["quantity"] > EPS or p["income_gross"] > 0
            if not used:
                continue
            if not p["cop_ok"] or (p["quantity"] > EPS and not p["mv_cop_ok"]):
                fx_missing.append(p["name"])
                continue
            if p["fx_approx"]:
                fx_approx.append(p["name"])
            convertible.append(p)
            if not p["valuation_known"]:
                pending_assets.append(p["name"])
                continue
            known.append(p)

        def cop(p, key):
            return float(p.get(key + "_cop") or 0.0)

        def row_cop(row, amount, currency):
            r = self._row_rate(row, currency, usd_cop)
            return None if r is None else float(amount) * r

        # Hechos que NO dependen del precio actual: ventas ya hechas, dividendos y comisiones.
        realized = sum(cop(p, "realized") for p in convertible)
        income_gross = sum(cop(p, "income_gross") for p in convertible)
        income_net = sum(cop(p, "income_net") for p in convertible)
        income_deductions = income_gross - income_net
        fees = sum(v for v in (row_cop(t, t["commission"], t["currency"]) for t in transactions)
                   if v is not None)

        # Valoración: solo posiciones con precio conocido (un precio faltante no es cero)
        open_cost = sum(cop(p, "remaining_cost") for p in known)
        market_value = sum(cop(p, "market_value") for p in known)
        unrealized = sum(cop(p, "unrealized") for p in known)
        profit = realized + unrealized + income_net

        # Rentabilidad %: solo sobre activos con precio conocido (numerador y denominador
        # hablan de lo mismo).
        invested = sum(cop(p, "total_buys") for p in known)
        profit_known = sum(cop(p, "realized") + cop(p, "unrealized") + cop(p, "income_net")
                           for p in known)
        accumulated = (profit_known / invested * 100) if invested > 0 else None

        # Pendientes: se informa su costo, pero no se les inventa un valor
        pending_cost = sum(cop(p, "remaining_cost") for p in convertible if not p["valuation_known"])

        fixed = sum(cop(p, "market_value") for p in known if p["asset_type"] in FIXED_INCOME_TYPES)
        variable = sum(cop(p, "market_value") for p in known if p["asset_type"] == "ACCION")
        total_market = fixed + variable

        # ---- Efectivo y patrimonio -------------------------------------------------
        # efectivo = capital inicial + aportes - retiros - compras (con comisión)
        #            + ventas netas + dividendos/intereses netos
        # Las acciones que no se han vendido NO son efectivo: están en "valor de mercado".
        initial = sum(float(m["amount"]) for m in movements if m["kind"] == "CAPITAL_INICIAL")
        contributions = sum(float(m["amount"]) for m in movements if m["kind"] == "APORTE")
        withdrawals = sum(float(m["amount"]) for m in movements if m["kind"] == "RETIRO")
        cash_configured = bool(movements)
        cash_in_sales = sum(cop(p, "sell_proceeds") for p in convertible)
        cash_out_buys = sum(cop(p, "total_buys") for p in convertible)
        cash = initial + contributions - withdrawals - cash_out_buys + cash_in_sales + income_net
        cash_known = cash_configured and not fx_missing
        cash_negative = cash_known and cash < -0.5
        total_assets_pending = bool(pending_assets or fx_missing)
        net_worth = (cash + market_value) if (cash_known and not total_assets_pending) else None
        money_in = initial + contributions - withdrawals

        # XIRR: solo si TODO se puede valorar; de lo contrario sería un número engañoso
        partial = total_assets_pending
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
                flows.append((_parse_date(t["date"]) or valuation_date,
                              signed * self._row_rate(t, t["currency"], usd_cop)))
            for e in incomes:
                flows.append((_parse_date(e["date"]) or valuation_date,
                              float(e["net_amount"]) * self._row_rate(e, e["currency"], usd_cop)))
            flows.append((valuation_date, market_value))
            tir = self.xirr(flows)
            if fx_approx:
                xirr_note = ("Algunas operaciones en USD no tienen la TRM de su día y usan la "
                             "tasa actual (" + ", ".join(fx_approx) + "); es una aproximación.")
            else:
                xirr_note = "Cada operación en USD usa la TRM de su día."
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
            "fx_missing": fx_missing, "fx_approx": fx_approx, "partial": partial,
            "issues": issues, "positions": positions,
            # efectivo y patrimonio
            "cash_configured": cash_configured, "initial_capital": initial,
            "contributions": contributions, "withdrawals": withdrawals,
            "money_in": money_in, "cash_out_buys": cash_out_buys,
            "cash_in_sales": cash_in_sales, "cash": cash if cash_known else None,
            "cash_negative": cash_negative, "net_worth": net_worth,
            "net_worth_vs_money_in": (net_worth - money_in) if net_worth is not None else None,
        }

    # ------------------------------------------------------------------
    # Compras, ventas y "si vendo hoy"
    # ------------------------------------------------------------------
    def purchase_log(self, positions):
        """Una fila por compra: cuánto y cuándo se invirtió (en la moneda del activo y en COP)."""
        rows = []
        for p in positions:
            cop_lots = p.get("lots_cop") or [None] * len(p["lots"])
            for lot, lc in zip(p["lots"], cop_lots):
                rows.append({"asset_id": p["id"], "name": p["name"], "currency": p["currency"],
                             "asset_type": p["asset_type"], **lot,
                             "cost_cop": lc["cost"] if lc else None})
        return sorted(rows, key=lambda r: (r["date"], r["id"]))

    def sales_log(self, positions):
        """Una fila por venta: a cuánto salió y a cuánto había costado."""
        rows = []
        for p in positions:
            cop_sales = p.get("sales_cop") or [None] * len(p["sales"])
            for sale, sc in zip(p["sales"], cop_sales):
                rows.append({"asset_id": p["id"], "name": p["name"], "currency": p["currency"],
                             "asset_type": p["asset_type"], **sale,
                             "net_proceeds_cop": sc["net_proceeds"] if sc else None,
                             "cost_sold_cop": sc["cost_sold"] if sc else None,
                             "result_cop": sc["result"] if sc else None})
        return sorted(rows, key=lambda r: (r["date"], r["id"]))

    def sale_estimates(self, positions, fee_config=None, overrides=None, usd_cop=None):
        """Qué pasaría si vendieras HOY todo lo que tienes de cada activo.

        Es una ESTIMACIÓN: usa el último precio guardado y la comisión estimada de venta.
        Acciones: neto = cantidad × precio − comisión estimada. Renta fija (CDT/TES/bono):
        neto = valor registrado hoy (sin comisión: ingrésala si tu comisionista la cobra).
        Un activo sin precio queda "Pendiente"; nunca se toma como cero.
        """
        overrides = overrides or {}
        rows = []
        for p in positions:
            if p["quantity"] <= EPS:
                continue
            fixed = p["asset_type"] in FIXED_INCOME_TYPES
            row = {"asset_id": p["id"], "name": p["name"], "asset_type": p["asset_type"],
                   "currency": p["currency"], "quantity": p["quantity"],
                   "avg_cost": p["avg_cost"], "remaining_cost": p["remaining_cost"],
                   "price": p["price"], "price_date": p["price_date"],
                   "price_status": p["price_status"], "known": p["price"] is not None}
            if p["price"] is None:
                rows.append(row)
                continue
            gross = p["quantity"] * p["price"]
            if fixed:
                fee, fee_note = 0.0, "Sin comisión estimada (renta fija)"
            else:
                res = compute_commission(gross, p["currency"], fee_config,
                                         overrides.get(p["id"]))
                fee, fee_note = res.total, res.description
            net = gross - fee
            result = net - p["remaining_cost"]
            row.update({
                "gross": gross, "fee": fee, "fee_note": fee_note, "net": net,
                "net_per_unit": net / p["quantity"], "result": result,
                "result_pct": (result / p["remaining_cost"] * 100
                               if p["remaining_cost"] > EPS else None),
                "income_net": p["income_net"], "fx_approx": p["fx_approx"],
            })
            if p["currency"] == "COP":
                row.update({"net_cop": net, "result_cop": result,
                            "cost_cop": p["remaining_cost"]})
            elif p.get("cop_ok") and usd_cop:
                row.update({"net_cop": net * float(usd_cop),
                            "result_cop": net * float(usd_cop) - p["remaining_cost_cop"],
                            "cost_cop": p["remaining_cost_cop"]})
            rows.append(row)
        return rows

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
