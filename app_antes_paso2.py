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
    page_title="Mi portafolio de inversión",
    page_icon="📈",
    layout="wide"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

.stApp {
    background: #F3F6FB;
    color: #17233D;
}

.block-container {
    max-width: 1500px;
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}

h1, h2, h3 {
    color: #101B35;
    font-weight: 800;
}

div[data-testid="stMetric"] {
    background: white;
    border: 1px solid #E6EBF3;
    border-radius: 14px;
    padding: 16px;
}

div.stButton > button,
div.stFormSubmitButton > button {
    background: #246BFD;
    color: white;
    border: 0;
    border-radius: 9px;
    min-height: 40px;
    font-weight: 700;
}

.hero {
    background: linear-gradient(115deg, #101B35, #1B3767, #246BFD);
    padding: 26px 30px;
    border-radius: 18px;
    color: white;
    margin-bottom: 20px;
}

.hero h1 {
    color: white;
    margin: 0;
}

.hero p {
    color: #D7E2F6;
    margin-bottom: 0;
}

section[data-testid="stSidebar"] {
    background: #101B35;
}

section[data-testid="stSidebar"] * {
    color: white;
}
</style>
""", unsafe_allow_html=True)


db = Database()
service = PortfolioService(db)
market = MarketDataProvider()


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def money(value, currency="COP"):
    value = float(value or 0)

    if currency == "USD":
        number = f"{value:,.2f}"
        number = number.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"US$ {number}"

    return f"$ {value:,.0f} COP".replace(",", ".")


def percent(value):
    if value is None:
        return "—"

    return f"{float(value):.2f}%"


def asset_label(asset):
    return (
        f'{asset["name"]} | '
        f'{asset["symbol"]} | '
        f'{asset["currency"]}'
    )


def to_cop(value, currency, trm):
    value = float(value or 0)

    if currency == "USD":
        return value * trm

    return value


def trii_standard_commission(gross_cop):
    """
    Tarifa estándar Trii para acciones colombianas:

    Hasta $5.000.000:
        $12.500 + IVA

    Por encima de $5.000.000:
        0,25% + IVA

    El resultado se calcula por operación.
    """
    gross_cop = float(gross_cop)

    if gross_cop <= 0:
        return 0.0

    if gross_cop <= 5_000_000:
        base = 12_500.0
    else:
        base = gross_cop * 0.0025

    iva = base * 0.19

    return base + iva


def create_fixed_asset(
    name,
    symbol,
    kind,
    capital,
    annual_rate,
    rate_type,
    opened,
    maturity,
    frequency,
    notes
):
    db.add_asset(
        name=name,
        symbol=symbol,
        asset_type=kind,
        currency="COP",
        market="Colombia",
        current_price=capital,
        source="Capital registrado por el inversionista"
    )

    created = next(
        a for a in db.get_assets()
        if a["symbol"].upper() == symbol.upper()
    )

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
        1.0,
        capital,
        0.0
    )

    return created


def refresh_assets():
    return db.get_assets()


# ============================================================
# CABECERA
# ============================================================

st.markdown("""
<div class="hero">
    <h1>MI PORTAFOLIO DE INVERSIÓN</h1>
    <p>
        Seguimiento de acciones, renta fija, dividendos,
        comisiones y rentabilidad.
    </p>
</div>
""", unsafe_allow_html=True)


# ============================================================
# TRM
# ============================================================

if "trm_value" not in st.session_state:
    try:
        trm_data = market.fetch_trm()
        st.session_state.trm_value = trm_data["value"]
        st.session_state.trm_date = trm_data["date"]
        st.session_state.trm_source = trm_data["source"]
    except Exception:
        st.session_state.trm_value = None
        st.session_state.trm_date = None
        st.session_state.trm_source = None


with st.sidebar:
    st.title("Panel de control")
    st.caption("Tasa de cambio")

    if st.button("Actualizar TRM oficial", use_container_width=True):
        try:
            trm_data = market.fetch_trm()
            st.session_state.trm_value = trm_data["value"]
            st.session_state.trm_date = trm_data["date"]
            st.session_state.trm_source = trm_data["source"]
            st.success("TRM actualizada.")
        except Exception as exc:
            st.error(str(exc))

    if st.session_state.trm_value is not None:
        st.metric(
            "TRM USD/COP",
            money(st.session_state.trm_value)
        )
        st.caption(
            f'Fecha publicada: {st.session_state.trm_date}'
        )
        st.caption(st.session_state.trm_source)

        trm = float(st.session_state.trm_value)

    else:
        st.warning(
            "No fue posible consultar la TRM. "
            "Ingresa una tasa manual para continuar."
        )

        trm = st.number_input(
            "TRM manual",
            min_value=1.0,
            value=4000.0,
            step=10.0
        )

        st.caption(
            "Esta tasa manual es un dato ingresado por ti, "
            "no una cotización oficial."
        )

    st.divider()
    st.caption("Intermediario configurado: Trii estándar")
    st.caption(
        "Las comisiones se estiman según el tarifario. "
        "Verifica el cobro definitivo en tu comprobante de Trii."
    )


# ============================================================
# DATOS GENERALES
# ============================================================

assets = refresh_assets()

stocks = [
    a for a in assets
    if a["asset_type"] == "ACCION"
]

fixed_assets = [
    a for a in assets
    if a["asset_type"] in ("CDT", "BONO", "TES")
]

positions = service.positions()

position_by_id = {
    p["id"]: p for p in positions
}

summary = service.summary(trm)

income_rows = db.get_income_events()
price_history = db.get_price_history()


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

    st.subheader("Resumen de tu patrimonio")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Capital invertido",
        money(summary["invested"])
    )

    c2.metric(
        "Valor actual",
        money(summary["market_value"])
    )

    c3.metric(
        "Ganancia / pérdida",
        money(summary["profit"])
    )

    c4.metric(
        "Rentabilidad anualizada",
        percent(summary["xirr_pct"])
    )

    c5, c6, c7, c8 = st.columns(4)

    c5.metric(
        "Ganancia realizada",
        money(summary["realized"])
    )

    c6.metric(
        "Ganancia pendiente",
        money(summary["unrealized"])
    )

    c7.metric(
        "Dividendos e intereses",
        money(summary["income"])
    )

    c8.metric(
        "Comisiones pagadas",
        money(summary["fees"])
    )

    st.divider()

    left, right = st.columns(2)

    with left:
        st.markdown("#### Distribución del portafolio")

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

        distribution = distribution[
            distribution["Valor"] > 0
        ]

        if not distribution.empty:
            fig = px.pie(
                distribution,
                names="Tipo",
                values="Valor",
                hole=0.60
            )

            st.plotly_chart(
                fig,
                use_container_width=True
            )
        else:
            st.info("Todavía no hay inversiones registradas.")

    with right:
        st.markdown("#### Resultado de las inversiones")

        results = pd.DataFrame([
            {
                "Concepto": "Ganancia realizada",
                "Valor": summary["realized"]
            },
            {
                "Concepto": "Ganancia pendiente",
                "Valor": summary["unrealized"]
            },
            {
                "Concepto": "Ingresos",
                "Valor": summary["income"]
            }
        ])

        fig = px.bar(
            results,
            x="Concepto",
            y="Valor",
            color="Concepto"
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

    st.markdown("#### Posiciones abiertas")

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
                "Precio": p["current_price"],
                "Moneda": p["currency"],
                "Valor COP": to_cop(
                    p["market_value"],
                    p["currency"],
                    trm
                ),
                "Costo COP": to_cop(
                    p["remaining_cost"],
                    p["currency"],
                    trm
                ),
                "Resultado COP": to_cop(
                    p["unrealized"],
                    p["currency"],
                    trm
                )
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )

    else:
        st.info("No tienes posiciones abiertas.")


# ============================================================
# 2. ACCIONES
# ============================================================

with tabs[1]:

    st.subheader("Acciones y cotizaciones")

    if stocks:
        rows = []

        for asset in stocks:
            p = position_by_id[asset["id"]]

            rows.append({
                "Empresa": asset["name"],
                "Símbolo": asset["symbol"],
                "Mercado": asset["market"],
                "Precio": asset["current_price"],
                "Moneda": asset["currency"],
                "Cantidad": p["quantity"],
                "Valor COP": to_cop(
                    p["market_value"],
                    asset["currency"],
                    trm
                ),
                "Fuente": asset["source"]
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )

        selected = st.selectbox(
            "Selecciona una acción",
            stocks,
            format_func=asset_label
        )

        p = position_by_id[selected["id"]]

        a, b, c = st.columns(3)

        a.metric(
            "Precio guardado",
            money(
                selected["current_price"],
                selected["currency"]
            )
        )

        b.metric(
            "Cantidad",
            f'{p["quantity"]:,.0f}'
        )

        c.metric(
            "Valor aproximado en COP",
            money(
                to_cop(
                    p["market_value"],
                    selected["currency"],
                    trm
                )
            )
        )

        st.divider()

        if selected["currency"] == "USD":
            if st.button("Actualizar último cierre desde Yahoo Finance"):
                try:
                    price, source = market.fetch_yfinance_price(
                        selected["symbol"]
                    )

                    db.update_price(
                        selected["id"],
                        price,
                        source,
                        market.today()
                    )

                    st.success("Precio actualizado.")
                    st.rerun()

                except Exception as exc:
                    st.error(str(exc))

        else:
            st.info(
                "Para acciones colombianas, registra el precio "
                "consultado en Trii. Esta aplicación no tiene "
                "acceso directo a la cuenta ni a la API privada de Trii."
            )

        with st.form("manual_price_form"):
            st.markdown("#### Registrar precio consultado")

            manual_price = st.number_input(
                f'Precio en {selected["currency"]}',
                min_value=0.0,
                value=float(selected["current_price"]),
                step=1.0
            )

            manual_source = st.text_input(
                "Fuente",
                value="Trii - precio consultado manualmente"
            )

            if st.form_submit_button("Guardar precio"):
                if manual_price <= 0:
                    st.error("El precio debe ser mayor que cero.")
                else:
                    db.update_price(
                        selected["id"],
                        manual_price,
                        manual_source,
                        market.today()
                    )

                    st.success("Precio guardado en el historial.")
                    st.rerun()

    else:
        st.info("No hay acciones registradas.")

    st.divider()

# 3. COMPRA Y VENTA
# ============================================================

with tabs[2]:

    st.subheader("Registrar una compra o una venta")
    st.write(
        "Registra aquí una operación que ya realizaste en Trii. "
        "Esta aplicación lleva tus cuentas, pero no ejecuta órdenes."
    )

    NEW_COMPANY = "➕ Es mi primera compra de esta empresa"
    options = [asset_label(a) for a in stocks]

    choice = st.selectbox(
        "¿Qué empresa compraste o vendiste?",
        [NEW_COMPANY] + options,
        key="trade_company_choice"
    )

    is_new = choice == NEW_COMPANY
    selected = None

    if is_new:
        st.info(
            "Si la empresa todavía no aparece, regístrala aquí. "
            "Su primera compra quedará guardada al mismo tiempo."
        )

        c1, c2 = st.columns(2)

        with c1:
            company_name = st.text_input(
                "Nombre de la empresa",
                placeholder="Ej. Apple",
                key="new_trade_company"
            )

            company_symbol = st.text_input(
                "Símbolo bursátil",
                placeholder="Ej. AAPL",
                key="new_trade_symbol"
            ).strip().upper()

        with c2:
            company_currency = st.selectbox(
                "Moneda",
                ["COP", "USD"],
                key="new_trade_currency"
            )

            default_market = (
                "BVC" if company_currency == "COP" else "NASDAQ"
            )

            company_market = st.text_input(
                "Bolsa o mercado",
                value=default_market,
                key="new_trade_market"
            )

    else:
        selected = next(
            a for a in stocks if asset_label(a) == choice
        )

        company_currency = selected["currency"]

        st.caption(
            f"Empresa seleccionada: "
            f"**{selected['name']} ({selected['symbol']})**"
        )

    st.divider()

    operation = st.radio(
        "¿Qué hiciste?",
        ["COMPRA", "VENTA"],
        horizontal=True,
        format_func=lambda x: (
            "Compré acciones" if x == "COMPRA" else "Vendí acciones"
        ),
        key="trade_operation"
    )

    left, right = st.columns(2)

    with left:
        trade_date = st.date_input(
            "Fecha de la operación",
            value=date.today(),
            key="trade_date_simple"
        )

        quantity = st.number_input(
            "Cantidad de acciones",
            min_value=1,
            value=1,
            step=1,
            format="%d",
            help="Escribe unidades enteras: por ejemplo, 2."
        )

    default_price = (
        0.0 if is_new else float(selected["current_price"] or 0)
    )

    with right:
        price = st.number_input(
            f"Precio unitario: cuánto costó UNA acción ({company_currency})",
            min_value=0.0,
            value=default_price,
            step=1.0 if company_currency == "COP" else 0.01,
            format="%.0f" if company_currency == "COP" else "%.2f",
            help="Copia el precio de una sola acción de tu comprobante."
        )

    gross = int(quantity) * float(price)

    if company_currency == "COP":
        commission = trii_standard_commission(gross)

        st.caption(
            "Comisión estimada con la tarifa estándar de Trii. "
            "Comprueba el cobro definitivo en tu comprobante."
        )

    else:
        commission = st.number_input(
            "Comisión de esta operación (USD)",
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.2f"
        )

    total = (
        gross + commission
        if operation == "COMPRA"
        else gross - commission
    )

    st.markdown("#### Resumen antes de guardar")

    a, b, c = st.columns(3)

    a.metric("Cantidad", f"{int(quantity)} acciones")
    a.metric("Precio por acción", money(price, company_currency))

    b.metric("Valor de las acciones", money(gross, company_currency))
    b.metric("Comisión estimada", money(commission, company_currency))

    c.metric(
        "Total que pagaste" if operation == "COMPRA"
        else "Neto que recibiste",
        money(total, company_currency)
    )

    if st.button(
        "Guardar compra" if operation == "COMPRA" else "Guardar venta",
        type="primary",
        key="save_trade_simple"
    ):

        try:
            if price <= 0:
                st.error("Escribe el precio real de UNA acción.")

            elif is_new and (
                not company_name.strip() or not company_symbol
            ):
                st.error("Completa el nombre y el símbolo.")

            elif is_new and any(
                a["symbol"].upper() == company_symbol
                for a in assets
            ):
                st.error(
                    "Ese símbolo ya existe. Selecciona la empresa de la lista."
                )

            elif is_new and operation == "VENTA":
                st.error(
                    "Primero debes registrar una compra de esa empresa."
                )

            elif (
                not is_new
                and operation == "VENTA"
                and int(quantity) >
                position_by_id[selected["id"]]["quantity"] + 1e-9
            ):
                st.error("No tienes suficientes acciones para esa venta.")

            else:
                if is_new:
                    db.add_asset(
                        company_name.strip(),
                        company_symbol,
                        "ACCION",
                        company_currency,
                        company_market.strip() or "Mercado no especificado",
                        0.0,
                        "Sin cotización actual verificada"
                    )

                    selected = next(
                        a for a in db.get_assets()
                        if a["symbol"].upper() == company_symbol
                    )

                db.add_transaction(
                    selected["id"],
                    operation,
                    trade_date.isoformat(),
                    int(quantity),
                    float(price),
                    float(commission)
                )

                st.success(
                    "Operación guardada. Tu portafolio se actualizará."
                )

                st.rerun()

        except Exception as exc:
            st.error(f"No se pudo guardar la operación: {exc}")

    st.caption(
        "Esta pantalla registra operaciones que ya hiciste en Trii. "
        "No ejecuta compras reales."
    )


# 4. CDT
# ============================================================

with tabs[3]:

    st.subheader("Certificados de Depósito a Término")

    cdt_assets = [
        a for a in fixed_assets
        if a["asset_type"] == "CDT"
    ]

    cdt_positions = [
        p for p in positions
        if p["asset_type"] == "CDT"
        and p["quantity"] > 0
    ]

    if cdt_positions:
        st.dataframe(
            pd.DataFrame([
                {
                    "CDT": p["name"],
                    "Capital restante": money(p["remaining_cost"]),
                    "Valor registrado": money(p["market_value"]),
                    "Resultado": money(p["unrealized"])
                }
                for p in cdt_positions
            ]),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No tienes CDT registrados.")

    with st.expander("Registrar un CDT"):

        with st.form("cdt_form"):

            name = st.text_input("Entidad o nombre del CDT")
            symbol = st.text_input("Código de referencia")
            capital = st.number_input(
                "Capital invertido COP",
                min_value=1.0,
                value=1_000_000.0,
                step=100_000.0
            )

            rate = st.number_input(
                "Tasa efectiva anual (%)",
                min_value=0.0,
                value=10.0,
                step=0.1
            )

            rate_type = st.selectbox(
                "Modalidad",
                ["Efectiva anual", "Nominal anual", "Fija", "Variable"]
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

            notes = st.text_area("Condiciones y observaciones")

            if st.form_submit_button("Guardar CDT"):

                symbol = symbol.strip().upper()

                if not name.strip() or not symbol:
                    st.error("Completa el nombre y el código.")

                elif maturity <= opened:
                    st.error("El vencimiento debe ser posterior a la apertura.")

                elif any(
                    a["symbol"].upper() == symbol
                    for a in assets
                ):
                    st.error("Ese código ya está registrado.")

                else:
                    create_fixed_asset(
                        name.strip(),
                        symbol,
                        "CDT",
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

    terms = [
        t for t in db.get_fixed_income_terms()
        if t["asset_type"] == "CDT"
    ]

    if terms:
        st.markdown("#### Condiciones registradas")

        st.dataframe(
            pd.DataFrame(terms),
            use_container_width=True,
            hide_index=True
        )

    st.caption(
        "El capital se registra como inversión. La tasa y el vencimiento "
        "son datos contractuales ingresados por ti; el valor mostrado "
        "no sustituye una liquidación bancaria oficial."
    )


# ============================================================
# 5. TES Y BONOS
# ============================================================

with tabs[4]:

    st.subheader("TES y bonos")

    bond_positions = [
        p for p in positions
        if p["asset_type"] in ("TES", "BONO")
        and p["quantity"] > 0
    ]

    if bond_positions:
        st.dataframe(
            pd.DataFrame([
                {
                    "Instrumento": p["name"],
                    "Tipo": p["asset_type"],
                    "Capital restante": money(p["remaining_cost"]),
                    "Valor registrado": money(p["market_value"]),
                    "Resultado": money(p["unrealized"])
                }
                for p in bond_positions
            ]),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No tienes TES o bonos registrados.")

    with st.expander("Registrar TES o bono"):

        with st.form("bond_form"):

            kind = st.selectbox(
                "Tipo de instrumento",
                ["TES", "BONO"]
            )

            name = st.text_input("Nombre del instrumento")
            symbol = st.text_input("Código o referencia")

            capital = st.number_input(
                "Valor de compra COP",
                min_value=1.0,
                value=1_000_000.0,
                step=100_000.0
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
                "Fecha de vencimiento",
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

            notes = st.text_area(
                "Emisor, condiciones y observaciones"
            )

            if st.form_submit_button("Guardar instrumento"):

                symbol = symbol.strip().upper()

                if not name.strip() or not symbol:
                    st.error("Completa el nombre y el código.")

                elif maturity <= opened:
                    st.error("El vencimiento debe ser posterior a la compra.")

                elif any(
                    a["symbol"].upper() == symbol
                    for a in assets
                ):
                    st.error("Ese código ya está registrado.")

                else:
                    create_fixed_asset(
                        name.strip(),
                        symbol,
                        kind,
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

    terms = [
        t for t in db.get_fixed_income_terms()
        if t["asset_type"] in ("TES", "BONO")
    ]

    if terms:
        st.markdown("#### Condiciones registradas")

        st.dataframe(
            pd.DataFrame(terms),
            use_container_width=True,
            hide_index=True
        )

    st.warning(
        "La aplicación no tiene una fuente licenciada de precios de "
        "mercado para valorar automáticamente todos los TES y bonos. "
        "El valor registrado no debe interpretarse como precio de mercado."
    )


# ============================================================
# 6. DIVIDENDOS E INTERESES
# ============================================================

with tabs[5]:

    st.subheader("Dividendos e intereses recibidos")

    all_assets = db.get_assets()

    if all_assets:

        with st.form("income_form"):

            selected = st.selectbox(
                "Activo que generó el ingreso",
                all_assets,
                format_func=asset_label
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
                f'Valor recibido ({selected["currency"]})',
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
                        selected["id"],
                        income_type,
                        income_date.isoformat(),
                        amount,
                        description
                    )

                    st.success("Ingreso registrado.")
                    st.rerun()

    if income_rows:

        income_table = pd.DataFrame([
            {
                "Fecha": e["date"],
                "Activo": e["asset_name"],
                "Tipo": e["event_type"],
                "Valor": e["amount"],
                "Moneda": e["currency"],
                "Valor COP": to_cop(
                    e["amount"],
                    e["currency"],
                    trm
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

        total_income = sum(
            to_cop(e["amount"], e["currency"], trm)
            for e in income_rows
        )

        st.metric(
            "Total de ingresos registrados",
            money(total_income)
        )

    else:
        st.info("Todavía no has registrado ingresos.")


# ============================================================
# 7. RENTABILIDAD
# ============================================================

with tabs[6]:

    st.subheader("Rentabilidad del portafolio")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Rentabilidad acumulada",
        percent(summary["accumulated_pct"])
    )

    c2.metric(
        "Rentabilidad anualizada",
        percent(summary["xirr_pct"])
    )

    c3.metric(
        "Ganancia / pérdida",
        money(summary["profit"])
    )

    c4.metric(
        "Comisiones acumuladas",
        money(summary["fees"])
    )

    result_rows = []

    for p in positions:

        if p["total_buys"] > 0 or p["quantity"] > 0:

            result_rows.append({
                "Activo": p["name"],
                "Ganancia realizada COP": to_cop(
                    p["realized"],
                    p["currency"],
                    trm
                ),
                "Ganancia pendiente COP": to_cop(
                    p["unrealized"],
                    p["currency"],
                    trm
                ),
                "Valor actual COP": to_cop(
                    p["market_value"],
                    p["currency"],
                    trm
                )
            })

    if result_rows:

        result_df = pd.DataFrame(result_rows)

        fig = go.Figure()

        fig.add_trace(go.Bar(
            name="Ganancia realizada",
            x=result_df["Activo"],
            y=result_df["Ganancia realizada COP"]
        ))

        fig.add_trace(go.Bar(
            name="Ganancia pendiente",
            x=result_df["Activo"],
            y=result_df["Ganancia pendiente COP"]
        ))

        fig.update_layout(
            barmode="group",
            title="Resultado por activo"
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

        st.dataframe(
            result_df,
            use_container_width=True,
            hide_index=True
        )

    else:
        st.info("Registra inversiones para calcular la rentabilidad.")

    if price_history:

        history = pd.DataFrame(price_history)
        history["date"] = pd.to_datetime(history["date"])

        st.markdown("#### Historial de precios guardados")

        fig = px.line(
            history,
            x="date",
            y="price",
            color="asset_name",
            markers=True,
            hover_data=["source"]
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

    st.caption(
        "La rentabilidad acumulada compara el resultado registrado "
        "con las compras acumuladas. La XIRR es una estimación anualizada "
        "basada en fechas y flujos de caja. No garantiza rendimientos futuros."
    )


# ============================================================
# 8. HISTORIAL
# ============================================================

with tabs[7]:

    st.subheader("Historial de actividad")

    transactions = db.get_transactions()

    if transactions:

        transaction_table = pd.DataFrame([
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

        st.markdown("#### Compras y ventas")

        st.dataframe(
            transaction_table,
            use_container_width=True,
            hide_index=True
        )

    else:
        st.info("No hay operaciones registradas.")

    if income_rows:

        st.markdown("#### Dividendos e intereses")

        st.dataframe(
            pd.DataFrame(income_rows),
            use_container_width=True,
            hide_index=True
        )

    if price_history:

        st.markdown("#### Actualizaciones de precios")

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
    "MI PORTAFOLIO DE INVERSIÓN | Herramienta de seguimiento personal. "
    "No ejecuta órdenes de compra o venta, no se conecta a tu cuenta Trii "
    "y no constituye asesoría financiera. Verifica las tarifas y "
    "comprobantes definitivos con tu intermediario."
)