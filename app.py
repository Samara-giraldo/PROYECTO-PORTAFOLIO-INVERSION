from datetime import date
import math
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from portfolio.database import Database
from portfolio.portfolio_service import PortfolioService
from portfolio.market_data import MarketDataProvider

# ---------------------------------------------------------------------
# PORTAFOLIO DE INVERSIÓN | Interfaz visual inspirada en apps bursátiles
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="PORTAFOLIO DE INVERSIÓN",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap');
:root { --navy:#101b35; --navy2:#172747; --blue:#246BFD; --cyan:#21B8A6;
        --bg:#F3F6FB; --card:#FFFFFF; --muted:#75819A; --line:#E6EBF3;
        --green:#159B72; --red:#E05260; }
html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
.stApp { background:var(--bg); color:#17233D; }
[data-testid="stHeader"] { background:rgba(243,246,251,.92); }
.block-container { padding-top:1.5rem; padding-bottom:2.5rem; max-width:1500px; }
section[data-testid="stSidebar"] { background:var(--navy); }
section[data-testid="stSidebar"] * { color:#F5F7FC !important; }
section[data-testid="stSidebar"] [data-baseweb="input"] input,
section[data-testid="stSidebar"] [data-baseweb="select"] > div {
 background:#223253 !important; color:#fff !important; border-color:#344566 !important; }
h1 { color:var(--navy); font-weight:800; letter-spacing:-1.2px; }
h2,h3 { color:var(--navy); font-weight:700; }
div[data-testid="stMetric"] {
 background:#fff; border:1px solid var(--line); border-radius:16px;
 padding:17px 18px; box-shadow:0 4px 18px rgba(22,39,71,.045);
}
div[data-testid="stMetricLabel"] { color:var(--muted); font-weight:600; }
div[data-testid="stMetricValue"] { color:var(--navy); font-weight:800; }
div[data-testid="stMetricDelta"] { font-weight:700; }
div.stButton > button, div.stFormSubmitButton > button {
 background:var(--blue); color:#fff; border:0; border-radius:10px;
 padding:.55rem 1.05rem; font-weight:700; min-height:42px;
}
div.stButton > button:hover, div.stFormSubmitButton > button:hover {
 background:#1557D8; color:#fff; border:0;
}
button[data-baseweb="tab"] { font-weight:700; color:#68758E; padding:14px 16px; }
button[data-baseweb="tab"][aria-selected="true"] { color:var(--blue); }
div[data-testid="stTabs"] [data-baseweb="tab-highlight"] { background:var(--blue); }
div[data-testid="stTabs"] [data-baseweb="tab-border"] { background:var(--line); }
div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
div[data-testid="stExpander"] { background:#fff; border:1px solid var(--line); border-radius:12px; }
div[data-testid="stAlert"] { border-radius:12px; }
small, .muted { color:var(--muted); }
.hero {
 background:linear-gradient(115deg,#101B35 0%,#1B3767 62%,#246BFD 100%);
 border-radius:20px; padding:26px 30px; color:white; margin-bottom:20px;
 box-shadow:0 10px 30px rgba(16,27,53,.14);
}
.hero h1 { color:#fff; margin:0; font-size:2rem; }
.hero p { color:#D7E2F6; margin:.45rem 0 0 0; }
.section-label { color:#75819A; text-transform:uppercase; letter-spacing:1.2px;
 font-size:.72rem; font-weight:800; margin:8px 0 10px; }
.panel {
 background:#fff; border:1px solid var(--line); border-radius:16px;
 padding:18px 20px; box-shadow:0 4px 18px rgba(22,39,71,.035);
}
.tag { display:inline-block; background:#EAF1FF; color:#246BFD; padding:4px 9px;
 border-radius:20px; font-size:.75rem; font-weight:700; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius:14px; }
</style>
""", unsafe_allow_html=True)

db = Database()
service = PortfolioService(db)
market = MarketDataProvider()

def cop(v):
    return f"$ {float(v or 0):,.0f} COP"

def pct(v):
    return "—" if v is None else f"{float(v):.2f}%"

def fx(currency, usd_cop):
    return usd_cop if currency == "USD" else 1.0

def to_cop(value, currency, usd_cop):
    return float(value or 0) * fx(currency, usd_cop)

def asset_text(a):
    return f'{a["name"]}  |  {a["symbol"]}  |  {a["currency"]}'

def safe_frame(data, columns=None):
    frame = pd.DataFrame(data)
    if columns:
        frame = frame[columns]
    return frame

def position_map():
    return {p["id"]: p for p in service.positions()}

def add_fixed_asset(name, symbol, kind, currency, market_name, capital,
                    annual_rate, rate_type, opened, maturity, frequency, notes):
    db.add_asset(name, symbol, kind, currency, market_name, capital, "Registro del inversionista")
    created = db.get_assets()[-1]
    db.save_fixed_income_terms(
        created["id"], annual_rate, rate_type, opened.isoformat(),
        maturity.isoformat(), frequency, capital, notes
    )
    db.add_transaction(created["id"], "COMPRA", opened.isoformat(), 1.0, capital, 0.0)
    return created

# ------------------------- Cabecera y controles -------------------------
st.markdown("""
<div class="hero">
  <h1>PORTAFOLIO DE INVERSIÓN</h1>
  <p>Administrador financiero personal · Acciones · Renta fija · Dividendos · Rentabilidad</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## Panel de control")
    st.caption("Parámetros generales de valoración")
    usd_cop = st.number_input("TRM / USD a COP", min_value=1.0, value=4000.0,
                              step=10.0, help="Actualiza este valor para convertir activos en dólares a pesos.")
    st.caption("La tasa es editable y se aplica a toda la valoración del portafolio.")
    st.divider()
    st.markdown("### Comisiones por empresa")
    st.caption("Se guardan en la base de datos y se aplican automáticamente a nuevas operaciones.")
    assets_sidebar = db.get_assets()
    saved_fees = db.get_fee_settings()
    fee_defaults = {
        "Bancolombia": 0.50, "Amazon": 0.50,
        "The Coca-Cola Company": 0.50, "Nike": 0.50,
    }
    for a in assets_sidebar:
        if a["asset_type"] == "ACCION":
            default_fee = saved_fees.get(a["id"], fee_defaults.get(a["name"], 0.50))
            fee = st.number_input(
                f'{a["name"]} (%)', min_value=0.0, max_value=10.0,
                value=float(default_fee), step=0.05, key=f'fee_{a["id"]}'
            )
            if abs(fee - saved_fees.get(a["id"], fee_defaults.get(a["name"], 0.50))) > 1e-9:
                db.save_fee_setting(a["id"], fee)
    st.divider()
    st.caption("Los porcentajes iniciales son ilustrativos. Configura las tarifas reales de tu intermediario.")

assets = db.get_assets()
stocks = [a for a in assets if a["asset_type"] == "ACCION"]
fixed_assets = [a for a in assets if a["asset_type"] in ("CDT", "BONO", "TES")]
summary = service.summary(usd_cop)
positions = service.positions()
pos_by_id = {p["id"]: p for p in positions}

# ------------------------- Navegación -------------------------
tabs = st.tabs([
    "Resumen general",
    "Consultar acciones",
    "Compra y venta",
    "CDT",
    "TES y bonos",
    "Dividendos",
    "Rentabilidad",
    "Historial",
])

# ========================= RESUMEN =========================
with tabs[0]:
    st.markdown('<div class="section-label">Vista consolidada</div>', unsafe_allow_html=True)
    total_gain = summary["profit"]
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Capital invertido", cop(summary["invested"]))
    c2.metric("Valor actual", cop(summary["market_value"]))
    c3.metric("Ganancia / pérdida total", cop(total_gain),
              delta=f'{summary["accumulated_pct"]:.2f}%' if summary["accumulated_pct"] is not None else None)
    c4.metric("Rentabilidad efectiva anual", pct(summary["xirr_pct"]))
    c5,c6,c7,c8 = st.columns(4)
    c5.metric("Ganancia realizada", cop(summary["realized"]))
    c6.metric("Ganancia / pérdida pendiente", cop(summary["unrealized"]))
    c7.metric("Dividendos e intereses", cop(summary["income"]))
    c8.metric("Comisiones pagadas", cop(summary["fees"]))

    st.markdown('<div class="section-label">Composición y resultados</div>', unsafe_allow_html=True)
    left,right = st.columns([1,1])
    with left:
        st.markdown("#### Distribución del portafolio")
        mix = pd.DataFrame([
            {"Tipo":"Acciones","Valor":summary["variable_value"]},
            {"Tipo":"CDT, TES y bonos","Valor":summary["fixed_value"]},
        ])
        mix = mix[mix["Valor"] > 0]
        if not mix.empty:
            fig = px.pie(mix, names="Tipo", values="Valor", hole=.66,
                         color_discrete_sequence=["#246BFD","#21B8A6"])
            fig.update_layout(margin=dict(l=5,r=5,t=10,b=5), legend_title=None,
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("La distribución aparecerá cuando registres tus primeras inversiones.")
    with right:
        st.markdown("#### De dónde viene el resultado")
        result_chart = pd.DataFrame([
            {"Concepto":"Ganancia realizada","Valor":summary["realized"]},
            {"Concepto":"Ganancia no realizada","Valor":summary["unrealized"]},
            {"Concepto":"Dividendos e intereses","Valor":summary["income"]},
        ])
        fig = px.bar(result_chart, x="Concepto", y="Valor", color="Concepto",
                     color_discrete_sequence=["#246BFD","#21B8A6","#8B78E6"])
        fig.update_layout(showlegend=False, margin=dict(l=5,r=5,t=10,b=5),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Posiciones del inversionista")
    open_pos = [p for p in positions if p["quantity"] > 0]
    if open_pos:
        rows=[]
        for p in open_pos:
            rows.append({
                "Activo":p["name"], "Tipo":p["asset_type"], "Cantidad":p["quantity"],
                "Precio actual":p["current_price"], "Moneda":p["currency"],
                "Valor actual COP":to_cop(p["market_value"],p["currency"],usd_cop),
                "Costo restante COP":to_cop(p["remaining_cost"],p["currency"],usd_cop),
                "Resultado COP":to_cop(p["unrealized"],p["currency"],usd_cop),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Aún no hay inversiones abiertas. Registra una compra de acciones o una inversión de renta fija.")
    st.caption("La valoración en COP usa la tasa USD/COP indicada en el panel lateral.")

# ========================= CONSULTAR ACCIONES =========================
with tabs[1]:
    st.markdown("### Acciones disponibles y cotizaciones")
    st.write("Consulta el precio guardado, la cantidad que posees y el valor de cada posición.")
    if stocks:
        table=[]
        for a in stocks:
            p=pos_by_id[a["id"]]
            table.append({
                "Empresa":a["name"], "Símbolo":a["symbol"], "Mercado":a["market"],
                "Precio guardado":a["current_price"], "Moneda":a["currency"],
                "Acciones en cartera":p["quantity"],
                "Valor actual COP":to_cop(p["market_value"],a["currency"],usd_cop),
                "Resultado no realizado COP":to_cop(p["unrealized"],a["currency"],usd_cop),
                "Fuente":a["source"],
            })
        st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
        st.divider()
        selected_stock=st.selectbox("Selecciona la acción para consultar o actualizar",
                                    stocks, format_func=asset_text, key="quote_stock")
        p=pos_by_id[selected_stock["id"]]
        m1,m2,m3=st.columns(3)
        m1.metric("Precio actual guardado",f'{selected_stock["current_price"]:,.2f} {selected_stock["currency"]}')
        m2.metric("Cantidad en cartera",f'{p["quantity"]:,.6f}')
        m3.metric("Valor de posición COP",cop(to_cop(p["market_value"],selected_stock["currency"],usd_cop)))
        col1,col2=st.columns(2)
        with col1:
            if selected_stock["symbol"] in ("AMZN","KO","NKE"):
                if st.button("Actualizar cotización desde Yahoo Finance", key="refresh_quote"):
                    try:
                        price,source=market.fetch_yfinance_price(selected_stock["symbol"])
                        db.update_price(selected_stock["id"],price,source,market.today())
                        st.success(f'Cotización actualizada: {price:,.2f} {selected_stock["currency"]}.')
                        st.rerun()
                    except RuntimeError as exc:
                        st.error(str(exc))
            else:
                st.info("La cotización local de Bancolombia se actualiza manualmente.")
        with col2:
            with st.form("manual_quote_form"):
                manual_price=st.number_input("Ingresar precio manual",min_value=0.0,
                    value=float(selected_stock["current_price"]),step=1.0)
                manual_source=st.text_input("Fuente de la cotización",value="Ingreso manual")
                if st.form_submit_button("Guardar nuevo precio"):
                    db.update_price(selected_stock["id"],manual_price,
                                    manual_source.strip() or "Ingreso manual",market.today())
                    st.success("Nuevo precio guardado. El anterior permanece en el historial.")
                    st.rerun()
    else:
        st.info("No hay acciones registradas.")

    with st.expander("Agregar una acción al catálogo"):
        with st.form("new_stock_form"):
            new_company=st.text_input("Nombre de la empresa")
            new_ticker=st.text_input("Símbolo bursátil")
            new_currency=st.selectbox("Moneda",["COP","USD"])
            new_market=st.text_input("Mercado",value="Manual")
            initial_quote=st.number_input("Precio inicial",min_value=0.0,value=0.0)
            initial_fee=st.number_input("Comisión (%) para esta empresa",min_value=0.0,max_value=10.0,value=0.50,step=0.05)
            if st.form_submit_button("Agregar empresa"):
                if not new_company.strip() or not new_ticker.strip():
                    st.error("Completa el nombre y el símbolo.")
                elif any(a["symbol"].upper()==new_ticker.strip().upper() for a in assets):
                    st.error("Ya existe un activo con ese símbolo.")
                else:
                    db.add_asset(new_company.strip(),new_ticker.strip().upper(),"ACCION",
                                 new_currency,new_market.strip() or "Manual",initial_quote,"Ingreso manual")
                    created=db.get_assets()[-1]
                    db.save_fee_setting(created["id"],initial_fee)
                    st.success("Empresa agregada al catálogo.")
                    st.rerun()

# ========================= COMPRA Y VENTA =========================
with tabs[2]:
    st.markdown("### Registrar compra o venta de acciones")
    st.write("La comisión se calcula según la empresa seleccionada y se guarda junto con la operación.")
    if stocks:
        with st.form("trade_form"):
            selected=st.selectbox("Empresa",stocks,format_func=asset_text)
            action=st.radio("Tipo de operación",["COMPRA","VENTA"],horizontal=True)
            trade_date=st.date_input("Fecha",value=date.today())
            qty=st.number_input("Cantidad de acciones",min_value=0.000001,value=1.0,step=1.0,format="%.6f")
            price=st.number_input(f'Precio por acción ({selected["currency"]})',
                                  min_value=0.0,value=float(selected["current_price"]),step=0.01)
            fee_pct=db.get_fee_settings().get(selected["id"],fee_defaults.get(selected["name"],0.50))
            gross=qty*price
            fee_amount=gross*fee_pct/100
            if action=="COMPRA":
                estimated=gross+fee_amount
                st.info(f"Comisión {selected['name']}: {fee_pct:.2f}% · Comisión estimada: {estimated-gross:,.2f} {selected['currency']} · Total a invertir: {estimated:,.2f} {selected['currency']}")
            else:
                estimated=gross-fee_amount
                st.info(f"Comisión {selected['name']}: {fee_pct:.2f}% · Comisión estimada: {fee_amount:,.2f} {selected['currency']} · Neto estimado de venta: {estimated:,.2f} {selected['currency']}")
            confirmed=st.checkbox("Confirmo que deseo registrar esta operación.")
            save_trade=st.form_submit_button("Guardar operación")
            if save_trade:
                if not confirmed:
                    st.error("Debes confirmar la operación.")
                elif qty<=0:
                    st.error("La cantidad debe ser mayor que cero.")
                elif action=="VENTA" and qty>pos_by_id[selected["id"]]["quantity"]+1e-9:
                    st.error(f'No tienes suficientes acciones. Disponibles: {pos_by_id[selected["id"]]["quantity"]:,.6f}.')
                else:
                    db.add_transaction(selected["id"],action,trade_date.isoformat(),qty,price,fee_amount)
                    st.success("Operación registrada correctamente.")
                    st.rerun()
        st.caption("El precio de esta operación no cambia cuando se actualiza la cotización de mercado.")
    else:
        st.info("Agrega primero una acción en la pestaña Consultar acciones.")

# ========================= CDT =========================
with tabs[3]:
    st.markdown("### Inversiones en CDT")
    cdt_list=[a for a in fixed_assets if a["asset_type"]=="CDT"]
    cdt_positions=[p for p in positions if p["asset_type"]=="CDT" and p["quantity"]>0]
    if cdt_positions:
        st.dataframe(pd.DataFrame([{
            "CDT":p["name"],"Capital registrado COP":to_cop(p["remaining_cost"],p["currency"],usd_cop),
            "Valor actual COP":to_cop(p["market_value"],p["currency"],usd_cop),
            "Resultado COP":to_cop(p["unrealized"],p["currency"],usd_cop),
        } for p in cdt_positions]),use_container_width=True,hide_index=True)
    else:
        st.info("Todavía no hay CDT registrados.")
    with st.expander("Registrar un nuevo CDT",expanded=not bool(cdt_list)):
        with st.form("new_cdt_form"):
            cdt_name=st.text_input("Nombre o entidad del CDT")
            cdt_code=st.text_input("Código de referencia")
            cdt_capital=st.number_input("Capital invertido (COP)",min_value=1.0,value=1000000.0,step=100000.0)
            cdt_rate=st.number_input("Tasa efectiva anual (%)",min_value=0.0,value=10.0,step=0.1)
            cdt_rate_type=st.selectbox("Modalidad de tasa",["Efectiva anual","Nominal anual","Fija","Variable"])
            cdt_start=st.date_input("Fecha de apertura",value=date.today(),key="cdt_start")
            cdt_end=st.date_input("Fecha de vencimiento",value=date.today(),key="cdt_end")
            cdt_frequency=st.selectbox("Pago de intereses",["Al vencimiento","Mensual","Trimestral","Semestral","Anual"])
            cdt_notes=st.text_area("Observaciones y condiciones")
            if st.form_submit_button("Registrar CDT"):
                if not cdt_name.strip() or not cdt_code.strip():
                    st.error("Ingresa el nombre y el código.")
                elif cdt_end<=cdt_start:
                    st.error("El vencimiento debe ser posterior a la apertura.")
                elif any(a["symbol"].upper()==cdt_code.strip().upper() for a in assets):
                    st.error("Ese código ya está registrado.")
                else:
                    add_fixed_asset(cdt_name.strip(),cdt_code.strip().upper(),"CDT","COP",
                                    "Entidad financiera",cdt_capital,cdt_rate,cdt_rate_type,
                                    cdt_start,cdt_end,cdt_frequency,cdt_notes)
                    st.success("CDT registrado y capital contabilizado como inversión.")
                    st.rerun()
    terms=[t for t in db.get_fixed_income_terms() if t["asset_type"]=="CDT"]
    if terms:
        st.markdown("#### Condiciones de tus CDT")
        st.dataframe(pd.DataFrame(terms)[["asset_name","annual_rate_pct","rate_type","issue_date","maturity_date","payment_frequency","nominal_value","notes"]],
                     use_container_width=True,hide_index=True)

# ========================= TES Y BONOS =========================
with tabs[4]:
    st.markdown("### TES y bonos")
    tes_bonds=[a for a in fixed_assets if a["asset_type"] in ("TES","BONO")]
    tes_positions=[p for p in positions if p["asset_type"] in ("TES","BONO") and p["quantity"]>0]
    if tes_positions:
        st.dataframe(pd.DataFrame([{
            "Instrumento":p["name"],"Tipo":p["asset_type"],
            "Valor registrado COP":to_cop(p["remaining_cost"],p["currency"],usd_cop),
            "Valor actual COP":to_cop(p["market_value"],p["currency"],usd_cop),
            "Resultado COP":to_cop(p["unrealized"],p["currency"],usd_cop),
        } for p in tes_positions]),use_container_width=True,hide_index=True)
    else:
        st.info("Todavía no hay TES o bonos registrados.")
    with st.expander("Registrar TES o bono",expanded=not bool(tes_bonds)):
        with st.form("new_bond_form"):
            bond_type=st.selectbox("Instrumento",["TES","BONO"])
            bond_name=st.text_input("Nombre del instrumento")
            bond_code=st.text_input("Código o referencia")
            bond_capital=st.number_input("Capital invertido / valor de compra (COP)",min_value=1.0,value=1000000.0,step=100000.0)
            bond_rate=st.number_input("Tasa anual (%)",min_value=0.0,value=0.0,step=0.1)
            bond_rate_type=st.selectbox("Tipo de tasa",["Fija","Variable","UVR / indexada","Descuento / cero cupón"])
            bond_start=st.date_input("Fecha de compra / emisión",value=date.today(),key="bond_start")
            bond_end=st.date_input("Fecha de vencimiento",value=date.today(),key="bond_end")
            bond_frequency=st.selectbox("Frecuencia de cupón",["Semestral","Anual","Trimestral","Mensual","Al vencimiento","Sin cupón"])
            bond_notes=st.text_area("Emisor, tasa de referencia, condiciones y notas")
            if st.form_submit_button("Registrar instrumento"):
                if not bond_name.strip() or not bond_code.strip():
                    st.error("Ingresa el nombre y el código.")
                elif bond_end<=bond_start:
                    st.error("El vencimiento debe ser posterior a la fecha de compra.")
                elif any(a["symbol"].upper()==bond_code.strip().upper() for a in assets):
                    st.error("Ese código ya está registrado.")
                else:
                    add_fixed_asset(bond_name.strip(),bond_code.strip().upper(),bond_type,"COP",
                                    "Gobierno / emisor",bond_capital,bond_rate,bond_rate_type,
                                    bond_start,bond_end,bond_frequency,bond_notes)
                    st.success(f"{bond_type} registrado correctamente.")
                    st.rerun()
    terms=[t for t in db.get_fixed_income_terms() if t["asset_type"] in ("TES","BONO")]
    if terms:
        st.markdown("#### Condiciones registradas")
        st.dataframe(pd.DataFrame(terms)[["asset_name","asset_type","annual_rate_pct","rate_type","issue_date","maturity_date","payment_frequency","nominal_value","notes"]],
                     use_container_width=True,hide_index=True)
    st.warning("El sistema registra capital, tasa, vencimiento y pagos recibidos. La valoración de mercado de TES y bonos debe actualizarse con una cotización real; no se inventan precios ni cupones.")

# ========================= DIVIDENDOS =========================
with tabs[5]:
    st.markdown("### Dividendos e intereses recibidos")
    all_assets=db.get_assets()
    with st.form("income_register"):
        income_asset=st.selectbox("Inversión que generó el ingreso",all_assets,format_func=asset_text)
        income_kind=st.selectbox("Tipo de ingreso",["DIVIDENDO","INTERES"])
        income_day=st.date_input("Fecha de pago",value=date.today(),key="income_day")
        income_value=st.number_input(f'Valor recibido ({income_asset["currency"]})',min_value=0.0,value=0.0,step=1000.0)
        income_note=st.text_input("Descripción / periodo / referencia")
        if st.form_submit_button("Registrar ingreso"):
            if income_value<=0:
                st.error("El valor debe ser mayor que cero.")
            else:
                db.add_income(income_asset["id"],income_kind,income_day.isoformat(),income_value,income_note)
                st.success("Ingreso registrado.")
                st.rerun()
    income_rows=db.get_income_events()
    if income_rows:
        income_table=pd.DataFrame([{
            "Fecha":e["date"],"Activo":e["asset_name"],"Tipo":e["event_type"],
            "Valor recibido":e["amount"],"Moneda":e["currency"],
            "Valor COP":to_cop(e["amount"],e["currency"],usd_cop),"Descripción":e["description"]
        } for e in income_rows])
        st.dataframe(income_table,use_container_width=True,hide_index=True)
        st.metric("Total de ingresos recibidos COP",cop(sum(to_cop(e["amount"],e["currency"],usd_cop) for e in income_rows)))
    else:
        st.info("No se han registrado dividendos ni intereses.")

# ========================= RENTABILIDAD =========================
with tabs[6]:
    st.markdown("### Rendimiento del portafolio")
    r1,r2,r3,r4=st.columns(4)
    r1.metric("Rentabilidad acumulada",pct(summary["accumulated_pct"]))
    r2.metric("Rentabilidad efectiva anual (XIRR)",pct(summary["xirr_pct"]))
    r3.metric("Ganancia / pérdida total",cop(summary["profit"]))
    r4.metric("Comisiones acumuladas",cop(summary["fees"]))
    st.markdown("#### Resultado por activo")
    rows=[]
    for p in positions:
        if p["total_buys"]>0 or p["quantity"]>0:
            rows.append({
                "Activo":p["name"],
                "Ganancia realizada COP":to_cop(p["realized"],p["currency"],usd_cop),
                "Ganancia no realizada COP":to_cop(p["unrealized"],p["currency"],usd_cop),
                "Valor actual COP":to_cop(p["market_value"],p["currency"],usd_cop),
            })
    if rows:
        chart=pd.DataFrame(rows)
        fig=go.Figure()
        fig.add_trace(go.Bar(name="Realizada",x=chart["Activo"],y=chart["Ganancia realizada COP"],marker_color="#246BFD"))
        fig.add_trace(go.Bar(name="No realizada",x=chart["Activo"],y=chart["Ganancia no realizada COP"],marker_color="#21B8A6"))
        fig.update_layout(barmode="group",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                         legend_title=None,margin=dict(l=5,r=5,t=10,b=5))
        st.plotly_chart(fig,use_container_width=True)
        st.dataframe(chart,use_container_width=True,hide_index=True)
    else:
        st.info("Registra inversiones para visualizar el rendimiento.")
    price_history=db.get_price_history()
    if price_history:
        hist=pd.DataFrame(price_history)
        hist["date"]=pd.to_datetime(hist["date"])
        st.markdown("#### Evolución de precios guardados")
        fig=px.line(hist,x="date",y="price",color="asset_name",markers=True,
                    hover_data=["source"],color_discrete_sequence=["#246BFD","#21B8A6","#8B78E6","#E3A43B"])
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                         legend_title=None,margin=dict(l=5,r=5,t=10,b=5))
        st.plotly_chart(fig,use_container_width=True)
    st.caption("La rentabilidad acumulada es una medida del resultado total frente a las compras acumuladas. La XIRR estima una tasa anualizada usando fechas y flujos de caja; puede no existir si faltan flujos positivos y negativos o no hay una solución válida.")

# ========================= HISTORIAL =========================
with tabs[7]:
    st.markdown("### Historial de actividad")
    tx=db.get_transactions()
    if tx:
        trade_hist=pd.DataFrame([{
            "Fecha":t["date"],"Activo":t["asset_name"],"Operación":t["operation"],
            "Cantidad":t["quantity"],"Precio":t["price"],"Moneda":t["currency"],
            "Comisión":t["commission"],"Valor bruto":t["quantity"]*t["price"]
        } for t in tx])
        st.markdown("#### Compras y ventas")
        st.dataframe(trade_hist,use_container_width=True,hide_index=True)
    else:
        st.info("No hay operaciones registradas.")
    if income_rows:
        st.markdown("#### Ingresos")
        st.dataframe(pd.DataFrame(income_rows),use_container_width=True,hide_index=True)
    if price_history:
        st.markdown("#### Actualizaciones de precios")
        st.dataframe(pd.DataFrame(price_history),use_container_width=True,hide_index=True)

st.divider()
st.caption("PORTAFOLIO DE INVERSIÓN · Herramienta de seguimiento y formación. No ejecuta órdenes reales ni constituye asesoría financiera. Verifica precios, comisiones, impuestos y condiciones contractuales con tu intermediario y fuentes oficiales.")
