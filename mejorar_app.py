
from pathlib import Path

APP = Path(__file__).with_name("app.py")

if not APP.exists():
    raise SystemExit("No encuentro app.py en esta carpeta.")

original = APP.read_text(encoding="utf-8")
text = original

old_money = '''def money(value, currency="COP"):
    value = float(value or 0)

    if currency == "USD":
        return f"US$ {value:,.2f}"

    return f"$ {value:,.0f} COP"'''

new_money = '''def money(value, currency="COP"):
    value = float(value or 0)

    if currency == "USD":
        number = f"{value:,.2f}"
        number = number.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"US$ {number}"

    return f"$ {value:,.0f} COP".replace(",", ".")'''

if old_money not in text:
    raise SystemExit("No reconocí la función money(). No hice cambios.")

text = text.replace(old_money, new_money, 1)

# Eliminar el formulario separado de agregar empresas.
catalog = text.find('    with st.expander("Agregar una acción"):')
trade_marker = text.find("# 3. COMPRA Y VENTA")

if catalog < 0 or trade_marker < 0 or catalog > trade_marker:
    raise SystemExit("No encontré la sección de empresas. No hice cambios.")

text = text[:catalog] + text[trade_marker:]

# Sustituir la sección completa de compra y venta.
start = text.find("with tabs[2]:", text.find("# 3. COMPRA Y VENTA"))
end = text.find("# 4. CDT", start)

if start < 0 or end < 0:
    raise SystemExit("No encontré la sección completa de compra y venta.")

new_trade = r'''with tabs[2]:

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


'''

text = text[:start] + new_trade + text[end:]

# Quitar decimales innecesarios de las cantidades visibles.
text = text.replace(
    'f\'{p["quantity"]:,.6f}\'',
    'f\'{p["quantity"]:,.0f}\''
)

# Guardar respaldo antes de modificar.
backup = APP.with_name("app_antes_mejoras.py")
backup.write_text(original, encoding="utf-8")

APP.write_text(text, encoding="utf-8")

print("Aplicación actualizada.")
print("Se creó app_antes_mejoras.py como respaldo.")
print("La base de datos y el historial no fueron modificados.")
