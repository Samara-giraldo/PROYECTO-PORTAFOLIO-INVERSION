from datetime import date, datetime
from html import escape

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from portfolio.database import Database, DuplicateIncomeError
from portfolio.fees import (FeeConfig, PLANS, PLAN_CUSTOM, PLAN_LABELS, PLAN_PRO,
                            TARIFFS_NOTE, compute_commission, compute_dividend_fee,
                            load_fee_config,
                            save_fee_config)
from portfolio.formatting import (fmt_cop, fmt_money, fmt_number, fmt_pct, fmt_qty)
from portfolio.market_data import MarketDataProvider, QuoteError
from portfolio.portfolio_service import (FIXED_INCOME_TYPES, PRICE_NO_DATE, PRICE_PENDING,
                                         PRICE_STALE, PortfolioService)

# ---------------------------------------------------------------------
# PORTAFOLIO DE INVERSIÓN | Tema oscuro. Verde = ganancia, rojo = pérdida.
# ---------------------------------------------------------------------
st.set_page_config(page_title="PORTAFOLIO DE INVERSIÓN", page_icon=None,
                   layout="wide", initial_sidebar_state="expanded")

GREEN, RED, BLUE, MUTED = "#22C55E", "#EF4444", "#3B82F6", "#94A3B8"

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
.stApp { background:#0B0F14; color:#F5F7FA; }
[data-testid="stHeader"] { background:rgba(11,15,20,.92); }
.block-container { padding-top:1.4rem; padding-bottom:2.5rem; max-width:1500px; }
section[data-testid="stSidebar"] { background:#0F151C; border-right:1px solid #1E2A38; }
h1,h2,h3,h4 { color:#F5F7FA; font-weight:700; letter-spacing:-.3px; }
.hero { background:linear-gradient(115deg,#0F151C 0%,#14213A 70%,#1D3B7A 100%);
    border:1px solid #1E2A38; border-radius:18px; padding:24px 28px; margin-bottom:18px; }
.hero h1 { margin:0; font-size:1.9rem; letter-spacing:-1px; }
.hero p { color:#B6C2D4; margin:.4rem 0 0 0; }
.section-label { color:#94A3B8; text-transform:uppercase; letter-spacing:1.2px;
    font-size:.72rem; font-weight:800; margin:10px 0 8px; }
.card { background:#131A22; border:1px solid #243040; border-radius:14px;
    padding:15px 18px; min-height:104px; margin-bottom:10px; }
.card .lbl { color:#94A3B8; font-size:.8rem; font-weight:600; }
.card .val { font-size:1.45rem; font-weight:800; margin-top:4px; color:#F5F7FA; }
.card .sub { color:#94A3B8; font-size:.74rem; margin-top:4px; line-height:1.3; }
.card.pos .val { color:#22C55E; } .card.neg .val { color:#EF4444; }
.card.pending .val { color:#F59E0B; font-size:1.2rem; }
div.stButton > button, div.stFormSubmitButton > button, div.stDownloadButton > button {
    background:#3B82F6; color:#fff; border:0; border-radius:10px; font-weight:700; min-height:40px; }
div.stButton > button:hover, div.stFormSubmitButton > button:hover { background:#2563EB; color:#fff; border:0; }
button[data-baseweb="tab"] { font-weight:700; padding:12px 14px; }
div[data-testid="stDataFrame"] { border:1px solid #243040; border-radius:12px; overflow:hidden; }
div[data-testid="stExpander"] { background:#131A22; border:1px solid #243040; border-radius:12px; }
div[data-testid="stAlert"] { border-radius:12px; }
</style>
""", unsafe_allow_html=True)

db = Database()
service = PortfolioService(db)
market = MarketDataProvider()
fee_config = load_fee_config(db)

# ------------------------------------------------------------------ helpers
def tone_of(value):
    if value is None:
        return "pending"
    return "pos" if value > 0.5 else ("neg" if value < -0.5 else "")


def card(col, label, value, tone="", sub=""):
    sub_html = f'<div class="sub">{escape(sub)}</div>' if sub else ""
    col.markdown(f'<div class="card {tone}"><div class="lbl">{escape(label)}</div>'
                 f'<div class="val">{escape(value)}</div>{sub_html}</div>', unsafe_allow_html=True)


def flash(kind, message):
    st.session_state["flash"] = (kind, message)


def show_flash():
    item = st.session_state.pop("flash", None)
    if item:
        getattr(st, item[0])(item[1])


def style_table(frame, pnl_cols=()):
    """Tabla con verde/rojo en las columnas de resultado."""
    def colour(value):
        text = str(value)
        if text.startswith("-"):
            return f"color:{RED};font-weight:600"
        if text and text[0] in "$U+" and text.replace("US", "").strip() not in ("$ 0", "$ 0,00"):
            return f"color:{GREEN};font-weight:600"
        return ""
    cols = [c for c in pnl_cols if c in frame.columns]
    if not cols:
        return frame
    styler = frame.style
    mapper = styler.map if hasattr(styler, "map") else styler.applymap
    return mapper(colour, subset=cols)


def show_table(rows, pnl_cols=()):
    st.dataframe(style_table(pd.DataFrame(rows), pnl_cols), hide_index=True)


def dark(fig, height=340):
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=5, r=5, t=30, b=5),
                      legend_title=None, height=height, font=dict(color="#F5F7FA"))
    return fig


# Tasa USD/COP guardada (con fuente y fecha). Si no hay ninguna, NO se inventa.
fx_row = db.get_latest_fx_rate()
usd_cop = fx_row["rate"] if fx_row else None


def to_cop(value, currency):
    if value is None:
        return None
    if currency == "COP":
        return float(value)
    if currency == "USD" and usd_cop:
        return float(value) * usd_cop
    return None


def cop_cell(value, currency):
    converted = to_cop(value, currency)
    if value is not None and converted is None:
        return "Sin tasa USD/COP"
    return fmt_cop(converted)


def asset_label(a):
    return f'{a["name"]}  |  {a["symbol"]}  |  {a["currency"]}'


def refresh_quote(asset):
    """Consulta Yahoo para un activo y guarda precio + fecha + fuente. Devuelve (ok, texto)."""
    try:
        quote = market.fetch_quote(asset["yahoo_symbol"], expected_currency=asset["currency"])
        db.update_price(asset["id"], quote.price, quote.source, quote.price_date, market.now())
        return True, (f'{asset["name"]}: {fmt_money(quote.price, asset["currency"])} '
                      f'(cierre del {quote.price_date}).')
    except (QuoteError, ValueError) as exc:
        return False, f'{asset["name"]}: {exc}'


# ------------------------------------------------------------------ cabecera
st.markdown("""
<div class="hero">
  <h1>PORTAFOLIO DE INVERSIÓN</h1>
  <p>Administrador financiero personal · Acciones · Renta fija · Dividendos · Rentabilidad</p>
</div>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ barra lateral
with st.sidebar:
    st.markdown("## Panel de control")

    st.markdown("### Tasa de cambio USD/COP")
    if fx_row:
        st.metric("USD/COP", fmt_number(fx_row["rate"], 2))
        st.caption(f'Fuente: {fx_row["source"]} · Fecha: {fx_row["rate_date"]}')
        try:
            if (date.today() - date.fromisoformat(fx_row["rate_date"])).days > 7:
                st.warning("La tasa tiene más de 7 días. Actualízala.")
        except ValueError:
            pass
    else:
        st.warning("Aún no hay tasa USD/COP. Sin ella, las acciones en dólares no se "
                   "suman en pesos.")
    with st.expander("Actualizar tasa"):
        if st.button("Consultar tasa de mercado (Yahoo)", key="fx_fetch"):
            try:
                q = market.fetch_usd_cop()
                db.save_fx_rate(q.price, q.price_date, q.source)
                flash("success", f"Tasa guardada: {fmt_number(q.price, 2)} (fecha {q.price_date}).")
                st.rerun()
            except (QuoteError, ValueError) as exc:
                st.error(str(exc))
        st.caption("Esa tasa es de mercado, no la TRM oficial. Para la TRM oficial, ingrésala:")
        with st.form("fx_manual"):
            fx_val = st.number_input("USD/COP", min_value=0.0, value=None, step=1.0,
                                     placeholder="Ej.: valor de la TRM del día")
            fx_day = st.date_input("Fecha de la tasa", value=date.today())
            fx_src = st.text_input("Fuente", value="TRM oficial (ingreso manual)")
            if st.form_submit_button("Guardar tasa"):
                if not fx_val or fx_val <= 0:
                    st.error("Ingresa una tasa mayor que cero.")
                else:
                    db.save_fx_rate(fx_val, fx_day.isoformat(), fx_src.strip() or "Ingreso manual")
                    flash("success", "Tasa guardada.")
                    st.rerun()
    st.divider()

    st.markdown("### Comisiones")
    st.caption("Son ESTIMACIONES. La comisión real es la del comprobante y se puede corregir en Historial.")
    plan = st.selectbox("Plan", PLANS, index=PLANS.index(fee_config.plan),
                        format_func=lambda p: PLAN_LABELS[p])
    with st.expander("Ver y editar tarifas"):
        st.caption(TARIFFS_NOTE)
        vat = st.number_input("IVA sobre la comisión (%)", 0.0, 50.0, float(fee_config.vat_pct), 0.5)
        co_std_pct = st.number_input("Colombia estándar: % de la operación", 0.0, 5.0, float(fee_config.co_std_pct), 0.005, format="%g")
        co_std_min = st.number_input("Colombia estándar: mínimo (COP)", 0.0, 1e6, float(fee_config.co_std_min), 500.0, format="%g")
        co_pro_pct = st.number_input("Colombia Pro: % de la operación", 0.0, 5.0, float(fee_config.co_pro_pct), 0.005, format="%g")
        co_pro_min = st.number_input("Colombia Pro: mínimo (COP)", 0.0, 1e6, float(fee_config.co_pro_min), 250.0, format="%g")
        us_std_pct = st.number_input("EE. UU. estándar: % de la operación", 0.0, 5.0, float(fee_config.us_std_pct), 0.01, format="%g")
        us_pro_pct = st.number_input("EE. UU. Pro: % de la operación", 0.0, 5.0, float(fee_config.us_pro_pct), 0.01, format="%g")
        us_vat = st.checkbox("Sumar IVA en operaciones de EE. UU.", value=bool(fee_config.us_add_vat))
        st.markdown("**Costo de Trii por dividendos (acciones en COP)**")
        div_pct = st.number_input("% del dividendo recibido", 0.0, 10.0, float(fee_config.div_fee_pct), 0.05, format="%g", key="d_pct")
        div_min = st.number_input("Mínimo por dividendo (COP)", 0.0, 1e6, float(fee_config.div_fee_min), 50.0, format="%g", key="d_min")
        div_vat = st.checkbox("Sumar IVA al costo de dividendos", value=bool(fee_config.div_fee_add_vat))
        st.markdown("**Plan personalizado**")
        custom_pct = st.number_input("% de la operación", 0.0, 10.0, float(fee_config.custom_pct), 0.05, format="%g", key="c_pct")
        custom_min = st.number_input("Mínimo por operación", 0.0, 1e6, float(fee_config.custom_min), 500.0, format="%g", key="c_min")
        custom_vat = st.checkbox("Sumar IVA en el plan personalizado", value=bool(fee_config.custom_add_vat))
    new_config = FeeConfig(plan=plan, vat_pct=vat, co_std_pct=co_std_pct, co_std_min=co_std_min,
                           co_pro_pct=co_pro_pct, co_pro_min=co_pro_min, us_std_pct=us_std_pct,
                           us_pro_pct=us_pro_pct, us_add_vat=us_vat,
                           div_fee_pct=div_pct, div_fee_min=div_min, div_fee_add_vat=div_vat, custom_pct=custom_pct,
                           custom_min=custom_min, custom_add_vat=custom_vat)
    if new_config != fee_config:
        save_fee_config(db, new_config)
        fee_config = new_config

    overrides = db.get_fee_settings()
    with st.expander("Porcentaje especial por empresa"):
        st.caption("Si lo defines, reemplaza al plan para esa empresa (es un porcentaje total).")
        stock_rows = [a for a in db.get_assets() if a["asset_type"] == "ACCION"]
        for a in stock_rows:
            if a["id"] in overrides:
                st.write(f'**{a["name"]}**: {fmt_number(overrides[a["id"]], 2)} %')
        if stock_rows:
            sel = st.selectbox("Empresa", [a["id"] for a in stock_rows], key="ov_asset",
                               format_func=lambda i: next(a["name"] for a in stock_rows if a["id"] == i))
            pct_val = st.number_input("Porcentaje (%)", 0.0, 10.0, float(overrides.get(sel, 0.5)), 0.05, format="%g", key="ov_pct")
            b1, b2 = st.columns(2)
            if b1.button("Guardar", key="ov_save"):
                db.save_fee_setting(sel, pct_val)
                st.rerun()
            if b2.button("Quitar", key="ov_del"):
                db.delete_fee_setting(sel)
                st.rerun()
    st.divider()

    st.markdown("### Datos")
    if st.button("Crear copia de seguridad ahora", key="backup_now"):
        path = db.backup("manual")
        st.success(f"Copia guardada en: {path}") if path else st.info("No hay datos que respaldar.")
    if db.last_backup_path:
        st.caption(f"Al abrir la app se actualizó la base de datos y se guardó antes una copia en: {db.last_backup_path}")

# ------------------------------------------------------------------ datos comunes
show_flash()
assets = db.get_assets()
stocks = [a for a in assets if a["asset_type"] == "ACCION"]
summary = service.summary(usd_cop)
positions = summary["positions"]
pos_by_id = {p["id"]: p for p in positions}
overrides = db.get_fee_settings()
income_rows = db.get_income_events()
price_history = db.get_price_history()
asset_by_id = {a["id"]: a for a in assets}

tabs = st.tabs(["Resumen general", "Consultar acciones", "Compra y venta", "CDT",
                "TES y bonos", "Dividendos", "Rentabilidad", "Historial"])

# ========================= RESUMEN =========================
with tabs[0]:
    if summary["pending_assets"]:
        st.warning("Falta el precio de: **" + ", ".join(summary["pending_assets"]) +
                   "**. No se cuentan como pérdida: quedan fuera del valor actual y de la "
                   "rentabilidad hasta que registres una cotización (pestaña Consultar acciones).")
    if summary["fx_missing"]:
        st.warning("Falta la tasa USD/COP para: **" + ", ".join(summary["fx_missing"]) +
                   "**. Guárdala en el panel lateral.")
    for issue in summary["issues"]:
        st.error(issue)

    st.markdown('<div class="section-label">Vista consolidada (COP)</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    card(c1, "Valor actual de lo que conservo", fmt_cop(summary["market_value"]), "",
         "Solo posiciones con precio conocido")
    card(c2, "Costo de lo que conservo", fmt_cop(summary["open_cost"]), "",
         "Incluye comisiones de compra" +
         (f' · Aparte, sin precio: {fmt_cop(summary["pending_cost"])}' if summary["pending_assets"] else ""))
    card(c3, "Ganancia / pérdida no realizada", fmt_cop(summary["unrealized"]),
         tone_of(summary["unrealized"]), "Valor actual menos costo")
    card(c4, "Ganancia / pérdida realizada", fmt_cop(summary["realized"]),
         tone_of(summary["realized"]), "Por ventas, ya descontadas comisiones")
    c5, c6, c7, c8 = st.columns(4)
    card(c5, "Dividendos e intereses (netos)", fmt_cop(summary["income"]), tone_of(summary["income"]),
         f'Bruto {fmt_cop(summary["income_gross"])}')
    card(c6, "Comisiones pagadas", fmt_cop(summary["fees"]), "",
         "Ya incluidas en costo y resultados; no se restan otra vez")
    card(c7, "Resultado total", fmt_cop(summary["profit"]), tone_of(summary["profit"]),
         "Realizada + no realizada + dividendos" +
         (" · sin el no realizado de los activos sin precio" if summary["partial"] else ""))
    xirr_sub = f'Anualizada (TIR): {fmt_pct(summary["xirr_pct"])}' if summary["xirr_pct"] is not None else "TIR anualizada: N/D"
    card(c8, "Rentabilidad total", fmt_pct(summary["accumulated_pct"], signed=True),
         tone_of(summary["accumulated_pct"]),
         xirr_sub + (" · solo activos con precio" if summary["partial"] else ""))
    with st.expander("¿Cómo se calculan estas cifras?"):
        st.markdown(
            "- **Costo de lo que conservo**: lo que pagaste por las acciones que aún tienes, más sus comisiones de compra, con *costo promedio ponderado*.\n"
            "- **No realizada**: valor actual (cantidad × último precio) menos ese costo. Solo existe si hay un precio real.\n"
            "- **Realizada**: al vender, ingreso neto (precio × cantidad − comisión de venta) menos el costo promedio de lo vendido.\n"
            "- **Dividendos netos**: bruto menos retención y costos que hayas registrado.\n"
            "- **Rentabilidad total**: (realizada + no realizada + dividendos netos) ÷ total comprado de los activos con precio conocido.\n"
            "- Un activo **sin precio** nunca se toma como cero: se marca *Pendiente* y se deja fuera de estas cifras.")

    st.markdown('<div class="section-label">Composición y resultados</div>', unsafe_allow_html=True)
    left, right = st.columns(2)
    with left:
        st.markdown("#### Distribución del portafolio")
        mix = pd.DataFrame([{"Tipo": "Acciones", "Valor": summary["variable_value"]},
                            {"Tipo": "CDT, TES y bonos", "Valor": summary["fixed_value"]}])
        mix = mix[mix["Valor"] > 0]
        if mix.empty:
            st.info("La distribución aparecerá cuando tengas posiciones con precio conocido.")
        else:
            fig = px.pie(mix, names="Tipo", values="Valor", hole=.62,
                         color_discrete_sequence=[BLUE, "#8B5CF6"])
            st.plotly_chart(dark(fig), key="chart_mix")
    with right:
        st.markdown("#### De dónde viene el resultado")
        parts = pd.DataFrame([
            {"Concepto": "Realizada", "Valor": summary["realized"]},
            {"Concepto": "No realizada", "Valor": summary["unrealized"]},
            {"Concepto": "Dividendos e intereses", "Valor": summary["income"]}])
        if (parts["Valor"].abs() < 0.5).all():
            st.info("Todavía no hay resultados para mostrar.")
        else:
            parts["Color"] = parts["Valor"].apply(lambda v: GREEN if v >= 0 else RED)
            fig = go.Figure(go.Bar(x=parts["Concepto"], y=parts["Valor"], marker_color=parts["Color"],
                                   text=[fmt_cop(v) for v in parts["Valor"]], textposition="outside"))
            st.plotly_chart(dark(fig), key="chart_parts")

    st.markdown("#### Posiciones abiertas")
    open_pos = [p for p in positions if p["quantity"] > 1e-9]
    if open_pos:
        rows = []
        for p in open_pos:
            pct_unreal = (p["unrealized"] / p["remaining_cost"] * 100
                          if p["unrealized"] is not None and p["remaining_cost"] > 0 else None)
            rows.append({
                "Activo": p["name"], "Tipo": p["asset_type"], "Cantidad": fmt_qty(p["quantity"]),
                "Costo promedio": fmt_money(p["avg_cost"], p["currency"]),
                "Precio actual": fmt_money(p["price"], p["currency"]),
                "Fecha del precio": p["price_date"] or "—", "Estado del precio": p["price_status"],
                "Valor actual": fmt_money(p["market_value"], p["currency"]),
                "Costo restante": fmt_money(p["remaining_cost"], p["currency"]),
                "Resultado no realizado": fmt_money(p["unrealized"], p["currency"]),
                "Resultado %": fmt_pct(pct_unreal, signed=True),
                "Valor actual (COP)": cop_cell(p["market_value"], p["currency"]),
            })
        show_table(rows, pnl_cols=("Resultado no realizado", "Resultado %"))
    else:
        st.info("Aún no hay posiciones abiertas. Registra una compra en la pestaña Compra y venta.")
    st.caption("CDT, TES y bonos se valoran a su costo registrado: la app no inventa precios de mercado para ellos.")

# ========================= CONSULTAR ACCIONES =========================
with tabs[1]:
    st.markdown("### Acciones y cotizaciones")
    st.info("Los precios de Yahoo Finance son el **último cierre diario**, no un precio en tiempo real. "
            "Cada precio guardado muestra su fuente y su fecha. Si un símbolo no existe en Yahoo "
            "(frecuente en acciones colombianas), registra el precio visto en Trii.")
    if stocks:
        table = []
        for a in stocks:
            p = pos_by_id[a["id"]]
            table.append({
                "Empresa": a["name"], "Símbolo": a["symbol"], "Mercado": a["market"],
                "Cantidad": fmt_qty(p["quantity"]), "Precio": fmt_money(p["price"], a["currency"]),
                "Moneda": a["currency"], "Fecha del precio": p["price_date"] or "—",
                "Estado": p["price_status"], "Fuente": a["source"] if p["price"] else "—",
                "Valor actual (COP)": cop_cell(p["market_value"], a["currency"]),
                "No realizado (COP)": cop_cell(p["unrealized"], a["currency"]),
            })
        show_table(table, pnl_cols=("No realizado (COP)",))

        linked = [a for a in stocks if a.get("yahoo_symbol")]
        if linked and st.button("Actualizar todas desde Yahoo Finance", key="refresh_all"):
            results = [refresh_quote(a) for a in linked]
            for ok, text in results:
                (st.success if ok else st.error)(text)
            st.rerun() if all(ok for ok, _ in results) else None
        st.divider()

        picked = st.selectbox("Acción a consultar o actualizar", [a["id"] for a in stocks],
                              format_func=lambda i: asset_label(asset_by_id[i]), key="quote_stock")
        sel = asset_by_id[picked]
        p = pos_by_id[picked]
        m1, m2, m3 = st.columns(3)
        card(m1, "Precio guardado", fmt_money(p["price"], sel["currency"]),
             "pending" if p["price"] is None else "",
             f'{p["price_status"]} · {p["price_date"] or "sin fecha"}')
        card(m2, "Cantidad en cartera", fmt_qty(p["quantity"]))
        card(m3, "Valor de la posición", fmt_money(p["market_value"], sel["currency"]),
             "pending" if p["market_value"] is None else "")
        if p["price_status"] in (PRICE_STALE, PRICE_NO_DATE):
            st.warning("Este precio está desactualizado o no tiene fecha. Actualízalo antes de confiar en el resultado.")
        if p["price"] is not None:
            st.caption(f'Fuente: {sel["source"]}')

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Consultar en Yahoo Finance**")
            if sel.get("yahoo_symbol"):
                st.caption(f'Símbolo en Yahoo: {sel["yahoo_symbol"]}')
                if st.button("Actualizar cotización", key="refresh_one"):
                    ok, text = refresh_quote(sel)
                    flash("success" if ok else "error", text)
                    st.rerun()
                if st.button("Quitar el símbolo de Yahoo", key="unlink_yahoo"):
                    db.set_yahoo_symbol(sel["id"], None)
                    st.rerun()
            else:
                st.caption("Esta acción no tiene símbolo de Yahoo. Puedes probar uno (por ejemplo, AMZN). "
                           "Solo se guarda si Yahoo responde con precio y la misma moneda.")
                trial = st.text_input("Símbolo en Yahoo Finance", key="yahoo_trial")
                if st.button("Probar y guardar", key="yahoo_try"):
                    try:
                        quote = market.fetch_quote(trial, expected_currency=sel["currency"])
                        db.set_yahoo_symbol(sel["id"], trial.strip())
                        db.update_price(sel["id"], quote.price, quote.source, quote.price_date, market.now())
                        flash("success", f'Símbolo guardado. Precio: {fmt_money(quote.price, sel["currency"])} (cierre del {quote.price_date}).')
                        st.rerun()
                    except (QuoteError, ValueError) as exc:
                        st.error(f"{exc}  Usa el precio manual.")
        with col2:
            st.markdown("**Registrar precio manual**")
            with st.form("manual_quote_form"):
                manual_price = st.number_input(f'Precio por acción ({sel["currency"]})', min_value=0.0,
                                               value=None, step=0.01, placeholder="Precio visto en Trii u otra fuente")
                manual_day = st.date_input("Fecha del precio", value=date.today())
                manual_source = st.text_input("Fuente", value="Trii (consulta manual)")
                if st.form_submit_button("Guardar precio"):
                    if not manual_price or manual_price <= 0:
                        st.error("Ingresa un precio mayor que cero.")
                    else:
                        db.update_price(sel["id"], manual_price, manual_source.strip() or "Ingreso manual",
                                        manual_day.isoformat(), market.now())
                        flash("success", "Precio guardado. El anterior permanece en el historial.")
                        st.rerun()
    else:
        st.info("Todavía no hay acciones. Registra tu primera compra en la pestaña Compra y venta.")

# ========================= COMPRA Y VENTA =========================
with tabs[2]:
    st.markdown("### Registrar compra o venta de acciones")
    nonce = st.session_state.setdefault("trade_nonce", 0)
    k = lambda name: f"{name}_{nonce}"

    operation = st.radio("Tipo de operación", ["COMPRA", "VENTA"], horizontal=True, key=k("op"))
    sellable = [a for a in stocks if pos_by_id[a["id"]]["quantity"] > 1e-9]

    mode = "existing"
    if operation == "COMPRA":
        mode = "new" if st.radio("Empresa", ["Ya registrada", "Empresa nueva"], horizontal=True,
                                 key=k("mode")) == "Empresa nueva" else "existing"
        if not stocks:
            mode = "new"
            st.caption("Aún no tienes empresas: registra la primera aquí mismo.")
    candidates = stocks if operation == "COMPRA" else sellable

    asset, new_asset = None, None
    if mode == "new":
        n1, n2 = st.columns(2)
        new_name = n1.text_input("Nombre de la empresa", key=k("new_name"))
        new_symbol = n2.text_input("Símbolo bursátil (como aparece en Trii)", key=k("new_symbol"))
        n3, n4, n5 = st.columns(3)
        new_currency = n3.selectbox("Moneda del precio", ["COP", "USD"], key=k("new_cur"))
        new_market = n4.text_input("Mercado", value="BVC", key=k("new_market"))
        new_yahoo = n5.text_input("Símbolo en Yahoo Finance (opcional)", key=k("new_yahoo"),
                                  help="Ejemplo: AMZN. Déjalo vacío si no sabes cuál es; podrás ingresar el precio manualmente.")
        new_asset = {"name": new_name, "symbol": new_symbol, "asset_type": "ACCION",
                     "currency": new_currency, "market": new_market, "yahoo_symbol": new_yahoo}
        currency = new_currency
    else:
        if not candidates:
            st.info("No tienes acciones para vender." if operation == "VENTA" else "No hay empresas registradas.")
        else:
            picked = st.selectbox("Empresa", [a["id"] for a in candidates], key=k("asset"),
                                  format_func=lambda i: asset_label(asset_by_id[i]) +
                                  (f'  ·  disponibles: {fmt_qty(pos_by_id[i]["quantity"])}' if operation == "VENTA" else ""))
            asset = asset_by_id[picked]
        currency = asset["currency"] if asset else "COP"

    if mode == "new" or asset:
        d1, d2, d3 = st.columns(3)
        trade_date = d1.date_input("Fecha de la operación", value=date.today(), key=k("date"))
        qty = d2.number_input("Cantidad de acciones", min_value=0.0, value=None, step=1.0,
                              format="%g", placeholder="Ej.: 10", key=k("qty"))
        default_price = (asset.get("current_price") if asset and asset.get("current_price", 0) > 0 else None)
        price = d3.number_input(f"Precio por acción ({currency})", min_value=0.0, value=default_price,
                                step=0.01, placeholder="Precio de la operación", key=k("price"))
        if asset and default_price:
            st.caption("El precio se sugirió con la última cotización guardada; cámbialo por el precio real de tu operación.")

        gross = (qty or 0) * (price or 0)
        override = overrides.get(asset["id"]) if asset else None
        est = compute_commission(gross, currency, fee_config, override)
        st.markdown(f"**Valor bruto:** {fmt_money(gross, currency)}")
        if gross > 0:
            detail = (f"Base {fmt_money(est.base, currency)} + IVA {fmt_money(est.vat, currency)} = "
                      if est.vat else "")
            st.info(f"Comisión estimada: {detail}**{fmt_money(est.total, currency)}** · {est.description}. "
                    "Es una estimación: la real está en tu comprobante.")
        use_receipt = st.checkbox("Ya tengo el comprobante: usar la comisión real", key=k("receipt"))
        if use_receipt:
            commission = st.number_input(f"Comisión real cobrada, IVA incluido ({currency})", min_value=0.0,
                                         value=float(est.total), step=1.0 if currency == "COP" else 0.01,
                                         key=k("real_fee"))
            fee_source = "COMPROBANTE"
        else:
            commission, fee_source = est.total, "ESTIMADA"
        total = gross + commission if operation == "COMPRA" else gross - commission
        label = "Total a invertir (con comisión)" if operation == "COMPRA" else "Neto estimado de la venta"
        st.markdown(f"**{label}:** {fmt_money(total, currency)}")

        confirmed = st.checkbox("Confirmo que deseo registrar esta operación.", key=k("confirm"))
        if st.button("Guardar operación", key=k("save")):
            try:
                if not confirmed:
                    st.error("Debes confirmar la operación.")
                elif not qty or qty <= 0:
                    st.error("Ingresa una cantidad mayor que cero.")
                elif not price or price <= 0:
                    st.error("Ingresa el precio por acción (mayor que cero).")
                elif mode == "new":
                    asset_id, _ = service.register_first_purchase(
                        new_asset, trade_date.isoformat(), qty, price, commission, fee_source)
                    saved = db.get_asset(asset_id)
                    extra = " El precio actual queda pendiente hasta que registres una cotización."
                    if saved.get("yahoo_symbol"):
                        ok, text = refresh_quote(saved)
                        extra = f" Cotización: {text}" if ok else f" No se pudo consultar Yahoo ({text}); registra el precio manualmente."
                    st.session_state["trade_nonce"] = nonce + 1
                    flash("success", f'Empresa y primera compra registradas: {saved["name"]}.{extra}')
                    st.rerun()
                else:
                    service.register_trade(asset["id"], operation, trade_date.isoformat(), qty, price,
                                           commission, fee_source)
                    st.session_state["trade_nonce"] = nonce + 1
                    flash("success", "Operación registrada correctamente.")
                    st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        st.caption("El precio de la operación queda guardado en su propio registro y no cambia cuando se actualiza la cotización.")

# ========================= RENTA FIJA (CDT y TES/bonos) =========================
def fixed_income_tab(kinds, singular, default_rate_types, default_frequencies, market_name, key):
    overview = [r for r in service.fixed_income_overview() if r["asset_type"] in kinds]
    if overview:
        rows = [{
            "Nombre": r["name"], "Tipo": r["asset_type"], "Estado": r["status"],
            "Capital": fmt_money(r["capital"], r["currency"]),
            "Tasa": f'{fmt_number(r["annual_rate_pct"], 2)} % ({r["rate_type"]})',
            "Apertura": r["issue_date"], "Vencimiento": r["maturity_date"],
            "Días para vencer": "—" if r["days_to_maturity"] is None else fmt_number(r["days_to_maturity"], 0),
            "Intereses est. al vencimiento": fmt_money(r["est_interest_at_maturity"], r["currency"], missing="No calculable"),
            "Valor est. al vencimiento": fmt_money(r["est_value_at_maturity"], r["currency"], missing="No calculable"),
            "Intereses recibidos": fmt_money(r["interest_received"], r["currency"]),
            "Pago de intereses": r["payment_frequency"],
        } for r in overview]
        show_table(rows)
        st.caption("Estimado = tasa efectiva anual aplicada al capital, con pago al vencimiento y antes de retención e impuestos. "
                   "Para otras modalidades no se calcula, para no inventar cifras. Se valoran a costo registrado.")
    else:
        st.info(f"Todavía no hay {singular} registrados.")

    with st.expander(f"Registrar {singular}", expanded=not overview):
        with st.form(f"new_{key}_form"):
            kind = st.selectbox("Instrumento", list(kinds)) if len(kinds) > 1 else kinds[0]
            name = st.text_input("Nombre o entidad")
            code = st.text_input("Código o referencia")
            capital = st.number_input("Capital invertido (COP)", min_value=0.0, value=None, step=100000.0,
                                      placeholder="Valor invertido")
            rate = st.number_input("Tasa anual (%)", min_value=0.0, value=None, step=0.1, placeholder="Ej.: la tasa de tu título")
            rate_type = st.selectbox("Modalidad de tasa", default_rate_types)
            start = st.date_input("Fecha de apertura / compra", value=date.today(), key=f"{key}_start")
            end = st.date_input("Fecha de vencimiento", value=date.today(), key=f"{key}_end")
            freq = st.selectbox("Pago de intereses", default_frequencies)
            notes = st.text_area("Observaciones y condiciones")
            if st.form_submit_button(f"Registrar {singular}"):
                if not name.strip() or not code.strip():
                    st.error("Ingresa el nombre y el código.")
                elif not capital or capital <= 0:
                    st.error("Ingresa el capital invertido.")
                elif rate is None:
                    st.error("Ingresa la tasa anual (puede ser 0 si no aplica).")
                elif end <= start:
                    st.error("El vencimiento debe ser posterior a la apertura.")
                elif any(a["symbol"].upper() == code.strip().upper() for a in db.get_assets()):
                    st.error("Ese código ya está registrado.")
                else:
                    db.add_fixed_income_investment(name.strip(), code.strip().upper(), kind, market_name,
                                                   capital, rate, rate_type, start.isoformat(),
                                                   end.isoformat(), freq, notes)
                    flash("success", f"{singular.capitalize()} registrado: el capital se contabiliza como inversión.")
                    st.rerun()

    held = [r for r in overview if r["held"]]
    if held:
        with st.expander("Registrar redención (vencimiento o venta)"):
            st.caption("Registra el TOTAL recibido (capital + intereses de ese pago). Si lo registras aquí, "
                       "no lo vuelvas a registrar como interés en Dividendos, para no contarlo dos veces. "
                       "Los intereses que recibiste durante la vida del título sí van en Dividendos (tipo INTERES).")
            with st.form(f"redeem_{key}_form"):
                rid = st.selectbox("Inversión", [r["asset_id"] for r in held],
                                   format_func=lambda i: next(r["name"] for r in held if r["asset_id"] == i))
                r_day = st.date_input("Fecha de la redención", value=date.today(), key=f"{key}_rday")
                r_amount = st.number_input("Total recibido (COP)", min_value=0.0, value=None, step=100000.0,
                                           placeholder="Valor recibido")
                if st.form_submit_button("Registrar redención"):
                    if not r_amount or r_amount <= 0:
                        st.error("Ingresa el valor recibido.")
                    else:
                        try:
                            service.register_trade(rid, "VENTA", r_day.isoformat(), 1.0, r_amount, 0.0,
                                                   "SIN_COMISION", "Redención")
                            flash("success", "Redención registrada.")
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))


with tabs[3]:
    st.markdown("### Inversiones en CDT")
    fixed_income_tab(("CDT",), "CDT", ["Efectiva anual", "Nominal anual", "Fija", "Variable"],
                     ["Al vencimiento", "Mensual", "Trimestral", "Semestral", "Anual"],
                     "Entidad financiera", "cdt")

with tabs[4]:
    st.markdown("### TES y bonos")
    fixed_income_tab(("TES", "BONO"), "TES o bono", ["Fija", "Variable", "UVR / indexada", "Descuento / cero cupón"],
                     ["Semestral", "Anual", "Trimestral", "Mensual", "Al vencimiento", "Sin cupón"],
                     "Gobierno / emisor", "bond")
    st.warning("La app registra capital, tasa, vencimiento y pagos recibidos. El precio de mercado de TES y bonos "
               "debe venir de una cotización real; no se inventan precios ni cupones.")

# ========================= DIVIDENDOS =========================
with tabs[5]:
    st.markdown("### Dividendos e intereses recibidos")
    if not assets:
        st.info("Primero registra una inversión.")
    else:
        st.caption("Registra el valor BRUTO y, si aparecen en tu comprobante, la retención y otros costos. "
                   "Según trii.co/faq, Trii cobra por recibir un dividendo el 1 % del valor recibido "
                   "(mínimo $200) y además puede haber retención en la fuente. La app puede estimar ese "
                   "costo: es una estimación, usa los valores reales de tu comprobante.")
        with st.form("income_register"):
            inc_id = st.selectbox("Inversión que generó el ingreso", [a["id"] for a in assets],
                                  format_func=lambda i: asset_label(asset_by_id[i]))
            inc_kind = st.selectbox("Tipo de ingreso", ["DIVIDENDO", "INTERES"])
            inc_day = st.date_input("Fecha de pago", value=date.today(), key="income_day")
            inc_gross = st.number_input("Valor bruto (en la moneda del activo)", min_value=0.0, value=None,
                                        step=1000.0, placeholder="Valor antes de descuentos")
            i1, i2 = st.columns(2)
            inc_ret = i1.number_input("Retención en la fuente (si aplica)", min_value=0.0, value=0.0, step=100.0)
            inc_fee = i2.number_input("Otros costos (si aplican)", min_value=0.0, value=0.0, step=100.0)
            inc_est = st.checkbox("Si dejé «Otros costos» en 0, estimar el costo de Trii por dividendos "
                                  "(solo acciones en COP)", value=True)
            inc_note = st.text_input("Descripción / periodo / referencia")
            inc_dup = st.checkbox("Es un pago distinto aunque tenga la misma fecha y valor que otro")
            if st.form_submit_button("Registrar ingreso"):
                if not inc_gross or inc_gross <= 0:
                    st.error("El valor debe ser mayor que cero.")
                else:
                    try:
                        fee_used, note_used = inc_fee, inc_note
                        chosen_asset = asset_by_id[inc_id]
                        if (inc_est and inc_fee == 0 and inc_kind == "DIVIDENDO"
                                and chosen_asset["asset_type"] == "ACCION"):
                            est_div = compute_dividend_fee(inc_gross, inc_ret, chosen_asset["currency"], fee_config)
                            fee_used = est_div.total
                            if fee_used > 0:
                                note_used = (inc_note + " · " if inc_note else "") + "Costo de Trii estimado (corregible con el comprobante)"
                        db.add_income(inc_id, inc_kind, inc_day.isoformat(), inc_gross, note_used,
                                      inc_ret, fee_used, allow_duplicate=inc_dup)
                        flash("success", "Ingreso registrado." + (
                            f" Costo estimado de Trii: {fmt_money(fee_used, chosen_asset['currency'])}." if fee_used > inc_fee else ""))
                        st.rerun()
                    except (DuplicateIncomeError, ValueError) as exc:
                        st.error(str(exc))
    if income_rows:
        show_table([{
            "Fecha": e["date"], "Activo": e["asset_name"], "Tipo": e["event_type"],
            "Bruto": fmt_money(e["amount"], e["currency"]),
            "Retención y costos": fmt_money(e["withholding"] + e["fees"], e["currency"]),
            "Neto": fmt_money(e["net_amount"], e["currency"]),
            "Neto (COP)": cop_cell(e["net_amount"], e["currency"]), "Descripción": e["description"],
        } for e in income_rows])
        t1, t2 = st.columns(2)
        card(t1, "Total neto recibido (COP)", fmt_cop(summary["income"]), tone_of(summary["income"]))
        card(t2, "Retenciones y costos (COP)", fmt_cop(summary["income_deductions"]), "")
        frame = pd.DataFrame([{"Mes": e["date"][:7], "Activo": e["asset_name"],
                               "Neto COP": to_cop(e["net_amount"], e["currency"])} for e in income_rows])
        frame = frame.dropna(subset=["Neto COP"])
        if not frame.empty:
            fig = px.bar(frame, x="Mes", y="Neto COP", color="Activo", barmode="stack",
                         color_discrete_sequence=[GREEN, BLUE, "#8B5CF6", "#F59E0B"])
            st.plotly_chart(dark(fig), key="chart_income")
    else:
        st.info("No se han registrado dividendos ni intereses.")

# ========================= RENTABILIDAD =========================
with tabs[6]:
    st.markdown("### Rendimiento del portafolio")
    if summary["partial"]:
        st.warning("Las cifras son parciales: hay activos sin precio o sin tasa de cambio (ver pestaña Resumen). "
                   "La TIR anualizada no se calcula hasta completar los datos.")
    r1, r2, r3, r4 = st.columns(4)
    card(r1, "Rentabilidad total", fmt_pct(summary["accumulated_pct"], signed=True), tone_of(summary["accumulated_pct"]))
    card(r2, "Rentabilidad anualizada (TIR)", fmt_pct(summary["xirr_pct"], signed=True),
         tone_of(summary["xirr_pct"]) if summary["xirr_pct"] is not None else "", summary["xirr_note"] or "")
    card(r3, "Resultado total", fmt_cop(summary["profit"]), tone_of(summary["profit"]))
    card(r4, "Comisiones acumuladas", fmt_cop(summary["fees"]), "", "Ya incluidas en los resultados")

    st.markdown("#### Resultado por activo")
    rows, chart_rows = [], []
    for p in positions:
        if p["total_buys"] <= 0 and p["quantity"] <= 1e-9:
            continue
        total = p["total_result"]
        pct_total = (total / p["total_buys"] * 100) if total is not None and p["total_buys"] > 0 else None
        rows.append({
            "Activo": p["name"], "Moneda": p["currency"],
            "Total comprado": fmt_money(p["total_buys"], p["currency"]),
            "Realizada": fmt_money(p["realized"], p["currency"]),
            "No realizada": fmt_money(p["unrealized"], p["currency"]),
            "Dividendos netos": fmt_money(p["income_net"], p["currency"]),
            "Resultado total": fmt_money(total, p["currency"]),
            "Rentabilidad": fmt_pct(pct_total, signed=True),
            "Comisiones": fmt_money(p["fees_total"], p["currency"]),
        })
        total_cop = to_cop(total, p["currency"])
        if total_cop is not None:
            chart_rows.append({"Activo": p["name"], "Resultado COP": total_cop})
    if rows:
        show_table(rows, pnl_cols=("Realizada", "No realizada", "Dividendos netos", "Resultado total", "Rentabilidad"))
        if chart_rows:
            chart = pd.DataFrame(chart_rows)
            chart["Color"] = chart["Resultado COP"].apply(lambda v: GREEN if v >= 0 else RED)
            fig = go.Figure(go.Bar(x=chart["Activo"], y=chart["Resultado COP"], marker_color=chart["Color"],
                                   text=[fmt_cop(v) for v in chart["Resultado COP"]], textposition="outside"))
            fig.update_layout(title="Resultado total por activo (COP)")
            st.plotly_chart(dark(fig), key="chart_asset_result")
        else:
            st.info("El gráfico aparecerá cuando haya activos con precio conocido.")
    else:
        st.info("Registra inversiones para visualizar el rendimiento.")

    hist = pd.DataFrame(price_history)
    if not hist.empty:
        hist["date"] = pd.to_datetime(hist["date"])
        st.markdown("#### Evolución de precios guardados")
        fig = px.line(hist, x="date", y="price", color="asset_name", markers=True, hover_data=["source"],
                      color_discrete_sequence=[BLUE, GREEN, "#8B5CF6", "#F59E0B"])
        st.plotly_chart(dark(fig), key="chart_prices")
    fx_hist = pd.DataFrame(db.get_fx_history())
    if len(fx_hist) >= 2:
        fx_hist["rate_date"] = pd.to_datetime(fx_hist["rate_date"])
        st.markdown("#### Tasa USD/COP guardada")
        fig = px.line(fx_hist, x="rate_date", y="rate", markers=True, color_discrete_sequence=[BLUE])
        st.plotly_chart(dark(fig, 260), key="chart_fx")
    st.caption("Rentabilidad total = resultado total ÷ total comprado. La TIR anualizada (XIRR) usa las fechas reales de cada flujo; "
               "puede no existir si faltan flujos positivos y negativos. Los flujos en USD se convierten con la tasa actual.")

# ========================= HISTORIAL =========================
SOURCE_LABELS = {"ESTIMADA": "Estimada", "COMPROBANTE": "Real (comprobante)",
                 "SIN_COMISION": "Sin comisión", "SIN_DATO": "Sin dato (registro anterior)"}
with tabs[7]:
    st.markdown("### Historial de actividad")
    tx = db.get_transactions()
    if tx:
        trade_rows = [{
            "N.º": t["id"], "Fecha": t["date"], "Activo": t["asset_name"], "Operación": t["operation"],
            "Cantidad": fmt_qty(t["quantity"]), "Precio": fmt_money(t["price"], t["currency"]),
            "Valor bruto": fmt_money(t["quantity"] * t["price"], t["currency"]),
            "Comisión": fmt_money(t["commission"], t["currency"]),
            "Origen de la comisión": SOURCE_LABELS.get(t.get("commission_source"), t.get("commission_source")),
            "Moneda": t["currency"],
        } for t in tx]
        st.markdown("#### Compras y ventas")
        show_table(trade_rows)
        csv = pd.DataFrame(trade_rows).to_csv(index=False).encode("utf-8-sig")
        st.download_button("Descargar operaciones (CSV)", csv, "operaciones.csv", "text/csv")
        with st.expander("Corregir una comisión con el comprobante"):
            fixable = [t for t in tx if t["asset_id"] and t.get("commission_source") != "SIN_COMISION"]
            if fixable:
                tid = st.selectbox("Operación", [t["id"] for t in reversed(fixable)], key="fix_tx",
                                   format_func=lambda i: next(
                                       f'N.º {t["id"]} · {t["date"]} · {t["asset_name"]} · {t["operation"]} · comisión actual {fmt_money(t["commission"], t["currency"])}'
                                       for t in fixable if t["id"] == i))
                chosen = next(t for t in fixable if t["id"] == tid)
                new_fee = st.number_input(f'Comisión real del comprobante, IVA incluido ({chosen["currency"]})',
                                          min_value=0.0, value=float(chosen["commission"]),
                                          step=1.0 if chosen["currency"] == "COP" else 0.01, key=f"fix_fee_{tid}")
                if st.button("Guardar comisión real", key="fix_save"):
                    db.update_transaction_commission(tid, new_fee)
                    flash("success", "Comisión corregida. Los cálculos se actualizaron.")
                    st.rerun()
    else:
        st.info("No hay operaciones registradas.")
    if income_rows:
        st.markdown("#### Ingresos")
        show_table([{"N.º": e["id"], "Fecha": e["date"], "Activo": e["asset_name"], "Tipo": e["event_type"],
                     "Bruto": fmt_money(e["amount"], e["currency"]),
                     "Retención": fmt_money(e["withholding"], e["currency"]),
                     "Costos": fmt_money(e["fees"], e["currency"]),
                     "Neto": fmt_money(e["net_amount"], e["currency"]),
                     "Descripción": e["description"]} for e in income_rows])
        with st.expander("Corregir retención y costos de un ingreso con el comprobante"):
            iid = st.selectbox("Ingreso", [e["id"] for e in reversed(income_rows)], key="fix_inc",
                               format_func=lambda i: next(
                                   f'N.º {e["id"]} · {e["date"]} · {e["asset_name"]} · {e["event_type"]} · bruto {fmt_money(e["amount"], e["currency"])}'
                                   for e in income_rows if e["id"] == i))
            inc = next(e for e in income_rows if e["id"] == iid)
            f1, f2 = st.columns(2)
            fix_ret = f1.number_input(f'Retención real ({inc["currency"]})', min_value=0.0,
                                      value=float(inc["withholding"]), key=f"fix_ret_{iid}")
            fix_fee = f2.number_input(f'Otros costos reales ({inc["currency"]})', min_value=0.0,
                                      value=float(inc["fees"]), key=f"fix_ifee_{iid}")
            if st.button("Guardar valores reales", key="fix_inc_save"):
                try:
                    db.update_income_costs(iid, fix_ret, fix_fee)
                    flash("success", "Ingreso corregido. Los cálculos se actualizaron.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    if price_history:
        st.markdown("#### Cotizaciones guardadas")
        show_table([{"Fecha del precio": h["date"], "Activo": h["asset_name"],
                     "Precio": fmt_money(h["price"], asset_by_id[h["asset_id"]]["currency"]),
                     "Fuente": h["source"], "Consultado": h.get("fetched_at") or "—"}
                    for h in reversed(price_history)])
    fx_all = db.get_fx_history()
    if fx_all:
        st.markdown("#### Tasas USD/COP guardadas")
        show_table([{"Fecha": f["rate_date"], "Tasa": fmt_number(f["rate"], 2), "Fuente": f["source"]}
                    for f in reversed(fx_all)])

st.divider()
st.caption("PORTAFOLIO DE INVERSIÓN · Herramienta de seguimiento y formación. No ejecuta órdenes reales ni constituye "
           "asesoría financiera. Verifica precios, comisiones, impuestos y condiciones con tu intermediario y fuentes oficiales.")
