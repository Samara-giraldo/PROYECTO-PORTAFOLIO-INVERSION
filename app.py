from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from portfolio.database import Database
from portfolio.portfolio_service import PortfolioService
from portfolio.market_data import MarketDataProvider


# ============================================================
# CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="Portafolio de inversión",
    page_icon="📈",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background: #080D16;
    color: #F1F5F9;
}
[data-testid="stHeader"] {
    background: #080D16;
}
[data-testid="stSidebar"] {
    background: #101827;
}
[data-testid="stSidebar"] * {
    color: #F1F5F9 !important;
}
h1, h2, h3, h4, p, label, span {
    color: #F1F5F9;
}
div[data-testid="stMetric"] {
    background: #121C2B;
    border: 1px solid #253247;
    border-radius: 14px;
    padding: 16px;
}
div[data-testid="stMetricLabel"] {
    color: #AAB8CA;
}
div[data-testid="stMetricValue"] {
    color: #FFFFFF;
}
.stButton button, .stFormSubmitButton button {
    background: #16A36A;
    color: white;
    border: 0;
    border-radius: 9px;
    font-weight: 700;
    min-height: 40px;
}
.stButton button:hover, .stFormSubmitButton button:hover {
    background: #128354;
    color: white;
}
div[data-testid="stDataFrame"] {
    border: 1px solid #253247;
    border-radius: 10px;
}
div[data-testid="stExpander"] {
    background: #111B2A;
    border: 1px solid #253247;
    border-radius: 10px;
}
button[data-baseweb="tab"] {
    color: #AAB8CA;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #25D18A;
}
.hero {
    background: linear-gradient(110deg, #101C2E, #123D32);
    border: 1px solid #245644;
    border-radius: 18px;
    padding: 25px;
    margin-bottom: 22px;
}
.hero h1 {
    color: white;
    margin: 0;
}
.hero p {
    color: #B7DCCB;
    margin-bottom: 0;
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# INICIALIZACIÓN
# ============================================================

db = Database()
service = PortfolioService(db)
market = MarketDataProvider()


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def cop(value):
    if value is None:
        return "Pendiente"
    return f"$ {float(value):,.0f} COP"


def money(value, currency):
    if value is None:
        return "Pendiente"
    return f"{float(value):,.2f} {currency}"


def pct(value):
    if value is None:
        return "—"
    return f"{float(value):.2f}%"


def to_cop(value, currency, usd_cop):
    if value is None:
        return None

    factor = usd_cop if currency == "USD" else 1
    return float(value) * factor


def asset_text(asset):
    return (
        f'{asset["name"]} | {asset["symbol"]} | '
        f'{asset["currency"]}'
    )


def add_fixed_asset(
    name, symbol, kind, currency, market_name, capital,
    annual_rate, rate_type, opened, maturity, frequency, notes
):
    db.add_asset(
        name,
        symbol,
        kind,
        currency,
        market_name,
        capital,
        "Capital registrado por el inversionista"
    )

    created = db.get_assets()[-1]

    db.save_fixed_income_terms(
        created["id"],
        annual_rate,
        rate_type,
        opened.isoformat(),
        maturity.isoformat(),
        frequency,
        capital,
        notes
    )

    db.add_transaction(
        created["id"],
        "COMPRA",
        opened.isoformat(),
        1,
        capital,
        0
    )


@st.cache_data(ttl=3600, show_spinner=False)
def get_trm_cached():
    """Conserva la consulta de TRM durante una hora."""
    provider = MarketDataProvider()
    return provider.fetch_trm()


def get_yahoo_quote(symbol):
    """Consulta una cotización de Yahoo Finance."""
    provider = MarketDataProvider()
    return provider.fetch_yfinance_price(symbol)


# ============================================================
# TRM AUTOMÁTICA
# ============================================================

trm_error = None

try:
    usd_cop, trm_date, trm_source = get_trm_cached()
except Exception as exc:
    usd_cop = 4000.0
    trm_date = "No disponible"
    trm_source = "Valor provisional"
    trm_error = str(exc)


# ============================================================
# ENCABEZADO
# ============================================================

st.markdown("""
<div class="hero">
    <h1>PORTAFOLIO DE INVERSIÓN</h1>
    <p>Seguimiento de acciones, renta fija, dividendos y rentabilidad.</p>
</div>
""", unsafe_allow_html=True)


# ============================================================
# PANEL LATERAL
# ============================================================

with st.sidebar:
    st.title("Panel de control")

    st.subheader("TRM del dólar")

    st.metric(
        "1 dólar estadounidense",
        f"$ {usd_cop:,.2f} COP"
    )

    st.caption(f"Fecha de vigencia: {trm_date}")
    st.caption(f"Fuente: {trm_source}")

    if trm_error:
        st.warning(
            "No fue posible actualizar la TRM. Se está usando "
            "un valor provisional de $4.000 COP. "
            "Revisa tu conexión a internet."
        )

    if st.button("Actualizar TRM"):
        get_trm_cached.clear()
        st.rerun()

    st.divider()

    st.subheader("Comisiones por empresa")

    assets_sidebar = db.get_assets()
    saved_fees = db.get_fee_settings()

    for asset in assets_sidebar:
        if asset["asset_type"] == "ACCION":
            fee_default = saved_fees.get(asset["id"], 0.50)

            fee = st.number_input(
                f'{asset["name"]} (%)',
                min_value=0.0,
                max_value=10.0,
                value=float(fee_default),
                step=0.05,
                key=f'fee_{asset["id"]}'
            )

            if abs(fee - fee_default) > 0.000001:
                db.save_fee_setting(asset["id"], fee)

    st.divider()

    st.caption(
        "Las comisiones son configurables. Introduce las tarifas "
        "que realmente te cobra tu intermediario."
    )


# ============================================================
# DATOS
# ============================================================

assets = db.get_assets()

stocks = [
    a for a in assets
    if a["asset_type"] == "ACCION"
]

fixed_assets = [
    a for a in assets
    if a["asset_type"] in ("CDT", "BONO", "TES")
]

positions = service.positions()
summary = service.summary(usd_cop)

position_by_id = {
    p["id"]: p for p in positions
}

fee_settings = db.get_fee_settings()


# ============================================================
# PESTAÑAS
# ============================================================

tabs = st.tabs([
    "Resumen",
    "Acciones",
    "Compra y venta",
    "CDT",
    "TES y bonos",
    "Dividendos",
    "Rentabilidad",
    "Historial"
])


# ============================================================
# 1. RESUMEN
# ============================================================

with tabs[0]:
    st.subheader("Resumen general")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Capital comprado", cop(summary["invested"]))
    c2.metric("Valor de mercado conocido", cop(summary["market_value"]))
    c3.metric("Ganancia / pérdida", cop(summary["profit"]))
    c4.metric("Rentabilidad acumulada", pct(summary["accumulated_pct"]))

    c5, c6, c7, c8 = st.columns(4)

    c5.metric("Ganancia realizada", cop(summary["realized"]))
    c6.metric("Ganancia no realizada", cop(summary["unrealized"]))
    c7.metric("Dividendos e intereses", cop(summary["income"]))
    c8.metric("Comisiones registradas", cop(summary["fees"]))

    if summary["pending_quotes"] > 0:
        st.warning(
            f'Hay {summary["pending_quotes"]} posición(es) sin cotización. '
            "El valor de mercado y la rentabilidad anualizada pueden "
            "estar incompletos."
        )

    st.divider()

    st.subheader("Distribución del portafolio")

    distribution = pd.DataFrame([
        {
            "Tipo": "Acciones",
            "Valor": summary["variable_value"]
        },
        {
            "Tipo": "CDT, TES y bonos",
            "Valor": summary["fixed_value"]
        }
    ])

    distribution = distribution[distribution["Valor"] > 0]

    if not distribution.empty:
        fig = px.pie(
            distribution,
            names="Tipo",
            values="Valor",
            hole=0.6
        )

        fig.update_layout(
            paper_bgcolor="#080D16",
            plot_bgcolor="#080D16",
            font_color="white"
        )

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(
            "La distribución aparecerá cuando registres inversiones "
            "con valor disponible."
        )

    st.divider()

    st.subheader("Tus posiciones")

    open_positions = [
        p for p in positions
        if p["quantity"] > 0
    ]

    if open_positions:
        rows = []

        for p in open_positions:
            rows.append({
                "Activo": p["name"],
                "Tipo": p["asset_type"],
                "Cantidad": p["quantity"],
                "Precio actual": (
                    money(p["current_price"], p["currency"])
                    if p["has_price"] else "Pendiente"
                ),
                "Valor actual COP": to_cop(
                    p["market_value"], p["currency"], usd_cop
                ),
                "Costo restante COP": to_cop(
                    p["remaining_cost"], p["currency"], usd_cop
                ),
                "Resultado COP": to_cop(
                    p["unrealized"], p["currency"], usd_cop
                ),
                "Fecha de cotización": (
                    p.get("price_date") or "Sin fecha"
                    if p["has_price"] else "Pendiente"
                )
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )

    else:
        st.info("Aún no has registrado inversiones.")


# ============================================================
# 2. ACCIONES
# ============================================================

with tabs[1]:
    st.subheader("Acciones y cotizaciones")

    if stocks:
        stock_rows = []

        for asset in stocks:
            p = position_by_id[asset["id"]]

            stock_rows.append({
                "Empresa": asset["name"],
                "Símbolo": asset["symbol"],
                "Mercado": asset["market"],
                "Precio": (
                    money(asset["current_price"], asset["currency"])
                    if p["has_price"] else "Pendiente"
                ),
                "Cantidad": p["quantity"],
                "Valor COP": to_cop(
                    p["market_value"], asset["currency"], usd_cop
                ),
                "Resultado COP": to_cop(
                    p["unrealized"], asset["currency"], usd_cop
                ),
                "Fuente": asset["source"],
                "Fecha": asset.get("price_date") or "Sin fecha"
            })

        st.dataframe(
            pd.DataFrame(stock_rows),
            use_container_width=True,
            hide_index=True
        )

        st.divider()

        selected_stock = st.selectbox(
            "Selecciona una acción",
            stocks,
            format_func=asset_text,
            key="quote_stock"
        )

        selected_position = position_by_id[selected_stock["id"]]

        m1, m2, m3 = st.columns(3)

        m1.metric(
            "Precio guardado",
            money(
                selected_stock["current_price"],
                selected_stock["currency"]
            ) if selected_position["has_price"] else "Pendiente"
        )

        m2.metric(
            "Cantidad en cartera",
            f'{selected_position["quantity"]:,.0f}'
        )

        m3.metric(
            "Valor de posición",
            cop(to_cop(
                selected_position["market_value"],
                selected_stock["currency"],
                usd_cop
            ))
        )

        st.caption(
            f'Fuente: {selected_stock["source"]} · '
            f'Fecha: {selected_stock.get("price_date") or "Sin fecha"}'
        )

        col1, col2 = st.columns(2)

        with col1:
            if selected_stock["currency"] == "USD":
                if st.button(
                    "Actualizar cotización desde Yahoo Finance",
                    key="refresh_quote"
                ):
                    try:
                        price, source, quote_date = get_yahoo_quote(
                            selected_stock["symbol"]
                        )

                        db.update_price(
                            selected_stock["id"],
                            price,
                            source,
                            quote_date
                        )

                        st.success(
                            f"Cotización guardada: "
                            f"{price:,.2f} {selected_stock['currency']}"
                        )

                        st.rerun()

                    except Exception as error:
                        st.error(str(error))
            else:
                st.info(
                    "Esta acción está en COP. Registra el precio "
                    "consultado en tu intermediario o fuente de mercado."
                )

        with col2:
            with st.form("manual_quote_form"):
                manual_price = st.number_input(
                    f'Precio manual ({selected_stock["currency"]})',
                    min_value=0.000001,
                    value=max(
                        float(selected_stock["current_price"] or 0),
                        0.000001
                    ),
                    step=1.0,
                    format="%.2f"
                )

                manual_source = st.text_input(
                    "Fuente del precio",
                    value="Ingreso manual"
                )

                quote_day = st.date_input(
                    "Fecha de la cotización",
                    value=date.today()
                )

                if st.form_submit_button("Guardar cotización"):
                    db.update_price(
                        selected_stock["id"],
                        manual_price,
                        manual_source.strip() or "Ingreso manual",
                        quote_day.isoformat()
                    )

                    st.success("Cotización guardada.")
                    st.rerun()

    else:
        st.info("No tienes acciones registradas.")

    with st.expander("Agregar una acción al catálogo"):
        with st.form("new_stock_form"):
            company = st.text_input("Nombre de la empresa")
            ticker = st.text_input("Símbolo bursátil")
            currency = st.selectbox("Moneda", ["COP", "USD"])
            stock_market = st.text_input("Mercado", value="Manual")

            initial_fee = st.number_input(
                "Comisión estimada (%)",
                min_value=0.0,
                max_value=10.0,
                value=0.50,
                step=0.05
            )

            if st.form_submit_button("Agregar empresa"):
                if not company.strip() or not ticker.strip():
                    st.error("Escribe el nombre y el símbolo.")

                elif any(
                    a["symbol"].upper() == ticker.strip().upper()
                    for a in assets
                ):
                    st.error("Ese símbolo ya está registrado.")

                else:
                    db.add_asset(
                        company.strip(),
                        ticker.strip().upper(),
                        "ACCION",
                        currency,
                        stock_market.strip() or "Manual",
                        0,
                        "Pendiente de cotización"
                    )

                    new_asset = db.get_assets()[-1]

                    db.save_fee_setting(
                        new_asset["id"],
                        initial_fee
                    )

                    st.success("Acción agregada.")
                    st.rerun()


# ============================================================
# 3. COMPRA Y VENTA
# ============================================================

with tabs[2]:
    st.subheader("Registrar compra o venta")

    if stocks:
        # La selección está FUERA del formulario.
        # Así Streamlit puede reaccionar cuando cambias de empresa.
        selected = st.selectbox(
            "Selecciona la empresa",
            stocks,
            format_func=asset_text,
            key="trade_selected_stock"
        )

        selected_id = selected["id"]

        # Detecta si cambiaste de empresa.
        previous_id = st.session_state.get(
            "previous_trade_asset_id"
        )

        if previous_id != selected_id:
            st.session_state["previous_trade_asset_id"] = selected_id

            # Para activos en USD intenta traer el último cierre.
            if selected["currency"] == "USD":
                try:
                    with st.spinner(
                        f'Consultando precio de {selected["name"]}...'
                    ):
                        price, source, quote_date = get_yahoo_quote(
                            selected["symbol"]
                        )

                    db.update_price(
                        selected_id,
                        price,
                        source,
                        quote_date
                    )

                    # Actualiza también los datos locales.
                    selected["current_price"] = price
                    selected["source"] = source
                    selected["price_date"] = quote_date
                    selected["price_status"] = "DISPONIBLE"

                    st.success(
                        f"Precio actualizado: "
                        f"{price:,.2f} {selected['currency']} "
                        f"(cierre del {quote_date})."
                    )

                except Exception as error:
                    st.warning(
                        "No se pudo consultar automáticamente el precio. "
                        "Se conserva el último precio guardado. "
                        f"Detalle: {error}"
                    )

            else:
                st.info(
                    "Para esta acción colombiana se conserva el último "
                    "precio registrado. No hay una conexión automática "
                    "de mercado confirmada para este símbolo."
                )

            # El campo de precio empieza con el valor actualizado.
            st.session_state[
                f"trade_price_{selected_id}"
            ] = float(selected["current_price"] or 0)

        # Recupera la posición de la empresa seleccionada.
        current_position = service.positions()

        current_position = next(
            p for p in current_position
            if p["id"] == selected_id
        )

        current_fee = db.get_fee_settings().get(
            selected_id,
            0.50
        )

        st.caption(
            f'Último precio guardado: '
            f'{money(selected["current_price"], selected["currency"])} · '
            f'Fuente: {selected.get("source", "Sin fuente")} · '
            f'Fecha: {selected.get("price_date") or "Sin fecha"}'
        )

        with st.form("trade_form"):
            operation = st.radio(
                "Tipo de operación",
                ["COMPRA", "VENTA"],
                horizontal=True
            )

            trade_day = st.date_input(
                "Fecha de operación",
                value=date.today()
            )

            # Cantidad entera: evita mostrar 1,000000.
            quantity = st.number_input(
                "Cantidad de acciones",
                min_value=1,
                value=1,
                step=1,
                format="%d"
            )

            # El valor inicial viene de la cotización guardada.
            price = st.number_input(
                f'Precio por acción ({selected["currency"]})',
                min_value=0.0,
                value=float(
                    st.session_state.get(
                        f"trade_price_{selected_id}",
                        selected["current_price"] or 0
                    )
                ),
                step=0.01,
                format="%.2f",
                key=f"trade_price_{selected_id}"
            )

            gross = quantity * price
            commission = gross * current_fee / 100

            if operation == "COMPRA":
                st.info(
                    f"Valor de compra: {gross:,.2f} "
                    f"{selected['currency']} · "
                    f"Comisión estimada: {commission:,.2f} · "
                    f"Total: {gross + commission:,.2f} "
                    f"{selected['currency']}"
                )

            else:
                st.info(
                    f"Valor de venta: {gross:,.2f} "
                    f"{selected['currency']} · "
                    f"Comisión estimada: {commission:,.2f} · "
                    f"Neto: {gross - commission:,.2f} "
                    f"{selected['currency']}"
                )

            confirmed = st.checkbox(
                "Confirmo que los datos de esta operación son correctos."
            )

            save_trade = st.form_submit_button(
                "Guardar operación"
            )

            if save_trade:
                available = current_position["quantity"]

                if not confirmed:
                    st.error("Debes confirmar la operación.")

                elif quantity <= 0:
                    st.error("La cantidad debe ser mayor que cero.")

                elif price <= 0:
                    st.error("El precio debe ser mayor que cero.")

                elif (
                    operation == "VENTA"
                    and quantity > available + 1e-9
                ):
                    st.error(
                        f"No tienes suficientes acciones. "
                        f"Disponibles: {available:,.0f}."
                    )

                else:
                    db.add_transaction(
                        selected_id,
                        operation,
                        trade_day.isoformat(),
                        quantity,
                        price,
                        commission
                    )

                    st.success("Operación registrada correctamente.")
                    st.rerun()

        st.caption(
            "El precio de compra o venta queda guardado en el historial. "
            "Actualizar una cotización no modifica operaciones anteriores."
        )

    else:
        st.info(
            "Primero agrega una acción en la pestaña Acciones."
        )


# ============================================================
# 4. CDT
# ============================================================

with tabs[3]:
    st.subheader("Inversiones en CDT")

    cdt_positions = [
        p for p in positions
        if p["asset_type"] == "CDT" and p["quantity"] > 0
    ]

    if cdt_positions:
        st.dataframe(
            pd.DataFrame([
                {
                    "CDT": p["name"],
                    "Capital registrado COP": cop(
                        to_cop(
                            p["remaining_cost"],
                            p["currency"],
                            usd_cop
                        )
                    ),
                    "Valor registrado COP": cop(
                        to_cop(
                            p["market_value"],
                            p["currency"],
                            usd_cop
                        )
                    )
                }
                for p in cdt_positions
            ]),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Todavía no has registrado CDT.")

    with st.expander("Registrar un CDT"):
        with st.form("cdt_form"):
            name = st.text_input("Nombre o entidad")
            code = st.text_input("Código de referencia")

            capital = st.number_input(
                "Capital invertido COP",
                min_value=1.0,
                value=1000000.0,
                step=100000.0
            )

            rate = st.number_input(
                "Tasa efectiva anual (%)",
                min_value=0.0,
                value=10.0,
                step=0.1
            )

            rate_type = st.selectbox(
                "Modalidad de tasa",
                [
                    "Efectiva anual",
                    "Nominal anual",
                    "Fija",
                    "Variable"
                ]
            )

            opened = st.date_input(
                "Fecha de apertura",
                value=date.today(),
                key="cdt_open"
            )

            maturity = st.date_input(
                "Fecha de vencimiento",
                value=date.today(),
                key="cdt_maturity"
            )

            frequency = st.selectbox(
                "Pago de intereses",
                [
                    "Al vencimiento",
                    "Mensual",
                    "Trimestral",
                    "Semestral",
                    "Anual"
                ]
            )

            notes = st.text_area("Observaciones")

            if st.form_submit_button("Registrar CDT"):
                if not name.strip() or not code.strip():
                    st.error("Completa el nombre y el código.")

                elif maturity <= opened:
                    st.error(
                        "El vencimiento debe ser posterior a la apertura."
                    )

                elif any(
                    a["symbol"].upper() == code.strip().upper()
                    for a in assets
                ):
                    st.error("Ese código ya está registrado.")

                else:
                    add_fixed_asset(
                        name.strip(),
                        code.strip().upper(),
                        "CDT",
                        "COP",
                        "Entidad financiera",
                        capital,
                        rate,
                        rate_type,
                        opened,
                        maturity,
                        frequency,
                        notes
                    )

                    st.success("CDT registrado.")
                    st.rerun()

    cdt_terms = [
        t for t in db.get_fixed_income_terms()
        if t["asset_type"] == "CDT"
    ]

    if cdt_terms:
        st.subheader("Condiciones registradas")

        st.dataframe(
            pd.DataFrame(cdt_terms),
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# 5. TES Y BONOS
# ============================================================

with tabs[4]:
    st.subheader("TES y bonos")

    fixed_positions = [
        p for p in positions
        if p["asset_type"] in ("TES", "BONO")
        and p["quantity"] > 0
    ]

    if fixed_positions:
        st.dataframe(
            pd.DataFrame([
                {
                    "Instrumento": p["name"],
                    "Tipo": p["asset_type"],
                    "Capital registrado COP": cop(
                        to_cop(
                            p["remaining_cost"],
                            p["currency"],
                            usd_cop
                        )
                    ),
                    "Valor actual COP": cop(
                        to_cop(
                            p["market_value"],
                            p["currency"],
                            usd_cop
                        )
                    )
                }
                for p in fixed_positions
            ]),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Todavía no tienes TES o bonos registrados.")

    with st.expander("Registrar TES o bono"):
        with st.form("bond_form"):
            kind = st.selectbox("Instrumento", ["TES", "BONO"])
            name = st.text_input("Nombre del instrumento")
            code = st.text_input("Código o referencia")

            capital = st.number_input(
                "Capital invertido COP",
                min_value=1.0,
                value=1000000.0,
                step=100000.0
            )

            rate = st.number_input(
                "Tasa anual (%)",
                min_value=0.0,
                value=0.0,
                step=0.1
            )

            rate_type = st.selectbox(
                "Tipo de tasa",
                [
                    "Fija",
                    "Variable",
                    "UVR / indexada",
                    "Descuento / cero cupón"
                ]
            )

            opened = st.date_input(
                "Fecha de compra o emisión",
                value=date.today(),
                key="bond_open"
            )

            maturity = st.date_input(
                "Vencimiento",
                value=date.today(),
                key="bond_maturity"
            )

            frequency = st.selectbox(
                "Frecuencia de cupón",
                [
                    "Semestral",
                    "Anual",
                    "Trimestral",
                    "Mensual",
                    "Al vencimiento",
                    "Sin cupón"
                ]
            )

            notes = st.text_area("Emisor y condiciones")

            if st.form_submit_button("Registrar instrumento"):
                if not name.strip() or not code.strip():
                    st.error("Completa el nombre y el código.")

                elif maturity <= opened:
                    st.error(
                        "El vencimiento debe ser posterior a la compra."
                    )

                elif any(
                    a["symbol"].upper() == code.strip().upper()
                    for a in assets
                ):
                    st.error("Ese código ya está registrado.")

                else:
                    add_fixed_asset(
                        name.strip(),
                        code.strip().upper(),
                        kind,
                        "COP",
                        "Gobierno / emisor",
                        capital,
                        rate,
                        rate_type,
                        opened,
                        maturity,
                        frequency,
                        notes
                    )

                    st.success("Instrumento registrado.")
                    st.rerun()

    st.warning(
        "Registrar un TES o bono no significa que tengamos su precio "
        "de mercado actualizado. La valoración debe actualizarse con "
        "una cotización real. La tasa contractual tampoco equivale "
        "automáticamente a la rentabilidad obtenida."
    )

    terms = [
        t for t in db.get_fixed_income_terms()
        if t["asset_type"] in ("TES", "BONO")
    ]

    if terms:
        st.subheader("Condiciones registradas")

        st.dataframe(
            pd.DataFrame(terms),
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# 6. DIVIDENDOS E INTERESES
# ============================================================

with tabs[5]:
    st.subheader("Dividendos e intereses")

    if assets:
        with st.form("income_form"):
            income_asset = st.selectbox(
                "Inversión que generó el ingreso",
                assets,
                format_func=asset_text
            )

            income_type = st.selectbox(
                "Tipo de ingreso",
                ["DIVIDENDO", "INTERES"]
            )

            income_date = st.date_input(
                "Fecha de pago",
                value=date.today()
            )

            amount = st.number_input(
                f'Valor recibido ({income_asset["currency"]})',
                min_value=0.0,
                value=0.0,
                step=1000.0
            )

            description = st.text_input(
                "Descripción o periodo"
            )

            if st.form_submit_button("Registrar ingreso"):
                if amount <= 0:
                    st.error("El valor debe ser mayor que cero.")

                else:
                    db.add_income(
                        income_asset["id"],
                        income_type,
                        income_date.isoformat(),
                        amount,
                        description
                    )

                    st.success("Ingreso registrado.")
                    st.rerun()

    income_rows = db.get_income_events()

    if income_rows:
        income_table = pd.DataFrame([
            {
                "Fecha": e["date"],
                "Activo": e["asset_name"],
                "Tipo": e["event_type"],
                "Valor recibido": e["amount"],
                "Moneda": e["currency"],
                "Valor COP": to_cop(
                    e["amount"],
                    e["currency"],
                    usd_cop
                ),
                "Descripción": e["description"]
            }
            for e in income_rows
        ])

        st.dataframe(
            income_table,
            use_container_width=True,
            hide_index=True
        )

        total_income_cop = sum(
            to_cop(
                e["amount"],
                e["currency"],
                usd_cop
            )
            for e in income_rows
        )

        st.metric(
            "Total de ingresos registrados",
            cop(total_income_cop)
        )

    else:
        st.info("No has registrado dividendos ni intereses.")


# ============================================================
# 7. RENTABILIDAD
# ============================================================

with tabs[6]:
    st.subheader("Rentabilidad del portafolio")

    r1, r2, r3, r4 = st.columns(4)

    r1.metric(
        "Rentabilidad acumulada",
        pct(summary["accumulated_pct"])
    )

    r2.metric(
        "Rentabilidad anualizada estimada",
        pct(summary["xirr_pct"])
    )

    r3.metric(
        "Ganancia / pérdida",
        cop(summary["profit"])
    )

    r4.metric(
        "Comisiones",
        cop(summary["fees"])
    )

    if summary["pending_quotes"] > 0:
        st.warning(
            "La rentabilidad anualizada no se muestra porque existen "
            "posiciones abiertas sin cotización."
        )

    st.subheader("Resultado por inversión")

    result_rows = []

    for p in positions:
        if p["total_buys"] > 0 or p["quantity"] > 0:
            result_rows.append({
                "Activo": p["name"],
                "Ganancia realizada COP": to_cop(
                    p["realized"],
                    p["currency"],
                    usd_cop
                ),
                "Ganancia no realizada COP": to_cop(
                    p["unrealized"],
                    p["currency"],
                    usd_cop
                ),
                "Valor actual COP": to_cop(
                    p["market_value"],
                    p["currency"],
                    usd_cop
                )
            })

    if result_rows:
        result_df = pd.DataFrame(result_rows)

        st.dataframe(
            result_df,
            use_container_width=True,
            hide_index=True
        )

        chart_df = result_df.melt(
            id_vars="Activo",
            value_vars=[
                "Ganancia realizada COP",
                "Ganancia no realizada COP"
            ],
            var_name="Tipo de resultado",
            value_name="Valor COP"
        )

        chart_df = chart_df.dropna()

        if not chart_df.empty:
            fig = px.bar(
                chart_df,
                x="Activo",
                y="Valor COP",
                color="Tipo de resultado",
                barmode="group"
            )

            fig.update_layout(
                paper_bgcolor="#080D16",
                plot_bgcolor="#080D16",
                font_color="white"
            )

            st.plotly_chart(
                fig,
                use_container_width=True
            )

    else:
        st.info("Registra operaciones para consultar resultados.")

    price_history = db.get_price_history()

    if price_history:
        st.subheader("Historial de cotizaciones")

        history_df = pd.DataFrame(price_history)
        history_df["date"] = pd.to_datetime(history_df["date"])

        fig = px.line(
            history_df,
            x="date",
            y="price",
            color="asset_name",
            markers=True,
            hover_data=["source"]
        )

        fig.update_layout(
            paper_bgcolor="#080D16",
            plot_bgcolor="#080D16",
            font_color="white"
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )


# ============================================================
# 8. HISTORIAL
# ============================================================

with tabs[7]:
    st.subheader("Historial de actividad")

    transactions = db.get_transactions()

    if transactions:
        st.markdown("#### Compras y ventas")

        transaction_df = pd.DataFrame([
            {
                "Fecha": t["date"],
                "Activo": t["asset_name"],
                "Operación": t["operation"],
                "Cantidad": t["quantity"],
                "Precio": t["price"],
                "Moneda": t["currency"],
                "Comisión": t["commission"],
                "Valor bruto": t["quantity"] * t["price"]
            }
            for t in transactions
        ])

        st.dataframe(
            transaction_df,
            use_container_width=True,
            hide_index=True
        )

    else:
        st.info("No hay compras o ventas registradas.")

    if income_rows:
        st.markdown("#### Dividendos e intereses")

        st.dataframe(
            pd.DataFrame(income_rows),
            use_container_width=True,
            hide_index=True
        )

    if price_history:
        st.markdown("#### Cambios de cotizaciones")

        st.dataframe(
            pd.DataFrame(price_history),
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# PIE DE PÁGINA
# ============================================================

st.divider()

st.caption(
    "PORTAFOLIO DE INVERSIÓN · Herramienta de seguimiento personal. "
    "No ejecuta órdenes de compra o venta. Los precios de Yahoo Finance "
    "corresponden al último cierre disponible y no necesariamente son "
    "precios en tiempo real. La TRM es la tasa oficial publicada para "
    "su fecha de vigencia. Verifica comisiones, impuestos y cotizaciones "
    "con tu intermediario."
)