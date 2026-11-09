from pathlib import Path
from datetime import datetime
import shutil
import re

APP = Path('app.py')
MARKET = Path('portfolio') / 'market_data.py'
REQ = Path('requirements.txt')
for file in (APP, MARKET):
    if not file.exists():
        raise SystemExit(f'No encuentro {file}. Ejecuta el archivo desde la carpeta principal del proyecto.')

app = APP.read_text(encoding='utf-8')
backup = Path('backups_paso2')
backup.mkdir(exist_ok=True)
stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
shutil.copy2(APP, backup / f'app_{stamp}.py')
shutil.copy2(MARKET, backup / f'market_data_{stamp}.py')
if REQ.exists():
    shutil.copy2(REQ, backup / f'requirements_{stamp}.txt')

# Fuente oficial TRM y último cierre diario de Yahoo Finance.
new_market = '''from datetime import date, datetime
import requests


class MarketDataProvider:
    """Consulta TRM oficial y último cierre diario; no ofrece precios en vivo."""
    TRM_URL = "https://www.datos.gov.co/resource/32sa-8pi3.json"

    def fetch_trm(self):
        params = {"$select": "valor,vigenciadesde", "$order": "vigenciadesde DESC", "$limit": "1"}
        try:
            response = requests.get(
                self.TRM_URL, params=params,
                headers={"User-Agent": "PortfolioPersonal/1.0", "Accept": "application/json"},
                timeout=20,
            )
            response.raise_for_status()
            rows = response.json()
            if not rows:
                raise ValueError("La fuente oficial no devolvió registros.")
            value = float(rows[0]["valor"])
            raw_date = rows[0]["vigenciadesde"]
            if value <= 0:
                raise ValueError("La TRM recibida no es válida.")
            parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            return {
                "value": value,
                "date": parsed.date().isoformat(),
                "source": "Datos Abiertos Colombia · Superintendencia Financiera de Colombia",
            }
        except Exception as exc:
            raise RuntimeError(f"No fue posible consultar la TRM oficial: {exc}") from exc

    def fetch_yfinance_price(self, symbol):
        """Devuelve precio, fuente y fecha del último cierre diario disponible."""
        ticker_symbol = str(symbol or "").strip().upper()
        if not ticker_symbol:
            raise ValueError("El símbolo bursátil está vacío.")
        try:
            import yfinance as yf
            history = yf.Ticker(ticker_symbol).history(
                period="10d", interval="1d", auto_adjust=False, actions=False
            )
            if history is None or history.empty or "Close" not in history:
                raise ValueError("Yahoo Finance no devolvió cotizaciones para ese símbolo.")
            closes = history["Close"].dropna()
            if closes.empty:
                raise ValueError("No hay precios de cierre disponibles.")
            price = float(closes.iloc[-1])
            if price <= 0:
                raise ValueError("El precio recibido no es válido.")
            quote_date = closes.index[-1].date().isoformat()
            source = f"Yahoo Finance · último cierre diario ({quote_date}); no es precio en tiempo real"
            return price, source, quote_date
        except Exception as exc:
            raise RuntimeError(f"No fue posible consultar {ticker_symbol} en Yahoo Finance: {exc}") from exc

    @staticmethod
    def today():
        return date.today().isoformat()
'''

# Add the bulk updater immediately under the stock section heading.
anchor = '''    st.subheader("Acciones y cotizaciones")

    if stocks:'''
bulk = '''    st.subheader("Acciones y cotizaciones")

    if "quote_update_report" in st.session_state:
        st.info(st.session_state.pop("quote_update_report"))

    if st.button("Actualizar todas mis acciones en USD", key="refresh_all_usd"):
        eligible = [asset for asset in stocks if asset["currency"] == "USD"]
        updated_count = 0
        failures = []
        for asset in eligible:
            try:
                price, source, quote_date = market.fetch_yfinance_price(asset["symbol"])
                db.update_price(asset["id"], price, source, quote_date)
                updated_count += 1
            except Exception as exc:
                failures.append(f'{asset["name"]} ({asset["symbol"]}): {exc}')
        report = f"Actualizadas {updated_count} de {len(eligible)} acciones en USD."
        if failures:
            report += " Fallos: " + " | ".join(failures)
        if not eligible:
            report = "No tienes acciones en USD registradas."
        st.session_state["quote_update_report"] = report
        st.rerun()

    if stocks:'''
if 'Actualizar todas mis acciones en USD' not in app:
    if anchor not in app:
        raise SystemExit('No identifiqué la sección Acciones y cotizaciones de tu app.py. No se guardaron cambios.')
    app = app.replace(anchor, bulk, 1)

# Upgrade the individual quote button from a two-value return to price/source/date.
old_quote = '''                    price, source = market.fetch_yfinance_price(
                        selected["symbol"]
                    )

                    db.update_price(
                        selected["id"],
                        price,
                        source,
                        market.today()
                    )'''
new_quote = '''                    price, source, quote_date = market.fetch_yfinance_price(
                        selected["symbol"]
                    )

                    db.update_price(
                        selected["id"],
                        price,
                        source,
                        quote_date
                    )'''
if old_quote in app:
    app = app.replace(old_quote, new_quote, 1)
elif 'price, source, quote_date = market.fetch_yfinance_price(' not in app:
    raise SystemExit('No encontré el bloque de cotización individual. No se guardaron cambios.')

# Make the scope of automatic lookup generic for any USD-listed stock.
old_cond = 'if selected["currency"] == "USD":'
# Existing local app already uses this condition; no ticker allow-list is needed.

# Ensure all code is syntactically valid before writing either source file.
compile(app, str(APP), 'exec')
compile(new_market, str(MARKET), 'exec')
APP.write_text(app, encoding='utf-8')
MARKET.write_text(new_market, encoding='utf-8')

if REQ.exists():
    requirements = REQ.read_text(encoding='utf-8')
    if not re.search(r'(?im)^requests([<=>~!].*)?$', requirements):
        REQ.write_text(requirements.rstrip() + '\nrequests>=2.31\n', encoding='utf-8')

print('PASO 2 APLICADO. Sintaxis de app.py y market_data.py verificada.')
print('- TRM oficial de Datos Abiertos Colombia.')
print('- Actualización de todas las acciones en USD con un botón.')
print('- Precio, fuente y fecha real del último cierre guardados en el historial.')
print('- Acciones colombianas permanecen manuales hasta contar con fuente verificada.')
print(f'Respaldos creados en: {backup.resolve()}')
print('No se borró ni modificó portfolio_data.db ni el historial de operaciones.')
