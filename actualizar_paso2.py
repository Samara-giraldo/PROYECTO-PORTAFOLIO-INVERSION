
from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app.py"
PORTFOLIO = ROOT / "portfolio"
MARKET = PORTFOLIO / "market_data.py"

if not APP.exists() or not PORTFOLIO.exists():
    raise SystemExit(
        "No encuentro app.py o la carpeta portfolio. "
        "Guarda este actualizador en la carpeta principal."
    )

original_app = APP.read_text(encoding="utf-8")
original_market = (
    MARKET.read_text(encoding="utf-8")
    if MARKET.exists() else None
)

# ---------------------------------------------------------
# 1. CORREGIR LOS COLORES DE LOS TEXTOS
# ---------------------------------------------------------

css = """
/* FIX PASO 2: CONTRASTE Y LEGIBILIDAD */

.stApp, .stAppViewContainer, section.main,
section.main p, section.main li, section.main label,
section.main [data-testid="stWidgetLabel"],
section.main [data-testid="stWidgetLabel"] p,
section.main [data-testid="stCaptionContainer"] p,
section.main [data-testid="stMarkdownContainer"] p,
section.main [data-testid="stMarkdownContainer"] li,
section.main [data-testid="stRadio"] label,
section.main [data-testid="stCheckbox"] label {
    color: #17233D !important;
}

section.main input,
section.main textarea,
section.main [data-baseweb="input"] input,
section.main [data-baseweb="textarea"] textarea {
    color: #17233D !important;
    -webkit-text-fill-color: #17233D !important;
    background-color: #FFFFFF !important;
    caret-color: #17233D !important;
}

section.main [data-baseweb="select"] > div {
    color: #17233D !important;
    background-color: #FFFFFF !important;
}

section.main [data-baseweb="select"] input,
section.main [data-baseweb="select"] span {
    color: #17233D !important;
    -webkit-text-fill-color: #17233D !important;
}

section.main button[data-baseweb="tab"] {
    color: #42516B !important;
}

section.main button[data-baseweb="tab"][aria-selected="true"] {
    color: #246BFD !important;
}

section.main [data-testid="stMetricLabel"],
section.main [data-testid="stMetricLabel"] p {
    color: #68758E !important;
}

section.main [data-testid="stMetricValue"],
section.main [data-testid="stMetricValue"] div {
    color: #101B35 !important;
    -webkit-text-fill-color: #101B35 !important;
}

/* La barra lateral mantiene su fondo oscuro */
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"],
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
    color: #F5F7FC !important;
}

section[data-testid="stSidebar"] input {
    color: #17233D !important;
    -webkit-text-fill-color: #17233D !important;
    background-color: #FFFFFF !important;
}
"""

app = original_app

if "/* FIX PASO 2: CONTRASTE Y LEGIBILIDAD */" not in app:
    if app.count("</style>") != 1:
        raise SystemExit(
            "No reconocí el bloque de estilos. No se modificó app.py."
        )

    app = app.replace("</style>", css + "\n</style>", 1)

# ---------------------------------------------------------
# 2. GUARDAR LA FECHA REAL DEL ÚLTIMO CIERRE
# ---------------------------------------------------------

old_call = """                    price, source = market.fetch_yfinance_price(
                        selected["symbol"]
                    )

                    db.update_price(
                        selected["id"],
                        price,
                        source,
                        market.today()
                    )"""

new_call = """                    price, source, quote_date = market.fetch_yfinance_price(
                        selected["symbol"]
                    )

                    db.update_price(
                        selected["id"],
                        price,
                        source,
                        quote_date
                    )"""

if old_call in app:
    app = app.replace(old_call, new_call, 1)
elif "price, source, quote_date = market.fetch_yfinance_price" not in app:
    raise SystemExit(
        "No reconocí la sección de actualización de precios. "
        "No se modificó app.py."
    )

app = app.replace(
    "Actualizar último cierre desde Yahoo Finance",
    "Actualizar último cierre disponible desde Yahoo Finance"
)

# ---------------------------------------------------------
# 3. NUEVO MÓDULO DE DATOS DE MERCADO
# ---------------------------------------------------------

market_code = r'''
from datetime import date, datetime

import requests


class MarketDataProvider:
    """
    Consulta dos fuentes:

    1. TRM publicada en Datos Abiertos Colombia.
    2. Último cierre disponible de Yahoo Finance.

    Yahoo Finance no garantiza cotizaciones en tiempo real.
    """

    TRM_URL = (
        "https://www.datos.gov.co/resource/32sa-8pi3.json"
    )

    def fetch_trm(self):
        params = {
            "$select": "valor,vigenciadesde",
            "$order": "vigenciadesde DESC",
            "$limit": "1",
        }

        headers = {
            "User-Agent": "PersonalPortfolioApp/1.0",
            "Accept": "application/json",
        }

        try:
            response = requests.get(
                self.TRM_URL,
                params=params,
                headers=headers,
                timeout=20,
            )

            response.raise_for_status()
            rows = response.json()

            if not rows:
                raise ValueError(
                    "La fuente oficial no devolvió registros."
                )

            value = float(rows[0]["valor"])
            raw_date = rows[0]["vigenciadesde"]

            if value <= 0:
                raise ValueError("La TRM recibida no es válida.")

            parsed = datetime.fromisoformat(
                raw_date.replace("Z", "+00:00")
            )

            return {
                "value": value,
                "date": parsed.date().isoformat(),
                "source": (
                    "Datos Abiertos Colombia; datos suministrados "
                    "por la Superintendencia Financiera de Colombia"
                ),
            }

        except Exception as exc:
            raise RuntimeError(
                f"No fue posible consultar la TRM oficial: {exc}"
            ) from exc

    def fetch_yfinance_price(self, symbol):
        """
        Devuelve:
        (precio, fuente, fecha_del_cierre)
        """

        try:
            import yfinance as yf

            ticker_symbol = str(symbol).strip().upper()

            if not ticker_symbol:
                raise ValueError(
                    "Debes indicar un símbolo bursátil."
                )

            ticker = yf.Ticker(ticker_symbol)

            history = ticker.history(
                period="10d",
                interval="1d",
                auto_adjust=False,
                actions=False,
            )

            if history is None or history.empty:
                raise ValueError(
                    "Yahoo Finance no devolvió cotizaciones "
                    "para ese símbolo."
                )

            close_values = history["Close"].dropna()

            if close_values.empty:
                raise ValueError(
                    "No hay precios de cierre disponibles."
                )

            price = float(close_values.iloc[-1])

            if price <= 0:
                raise ValueError(
                    "La fuente devolvió un precio no válido."
                )

            quote_date = (
                close_values.index[-1].date().isoformat()
            )

            source = (
                "Yahoo Finance (yfinance), último cierre "
                f"disponible del {quote_date}; "
                "no es una cotización en tiempo real"
            )

            return price, source, quote_date

        except Exception as exc:
            raise RuntimeError(
                f"No fue posible consultar {symbol} "
                f"en Yahoo Finance: {exc}"
            ) from exc

    @staticmethod
    def today():
        return date.today().isoformat()
'''

# ---------------------------------------------------------
# 4. RESPALDO Y GUARDADO
# ---------------------------------------------------------

app_backup = ROOT / "app_antes_paso2.py"
market_backup = ROOT / "market_data_antes_paso2.py"

if not app_backup.exists():
    app_backup.write_text(
        original_app,
        encoding="utf-8"
    )

if original_market is not None and not market_backup.exists():
    market_backup.write_text(
        original_market,
        encoding="utf-8"
    )

# Comprobar sintaxis antes de escribir.
temporary_app = ROOT / "_app_validacion.py"
temporary_market = ROOT / "_market_validacion.py"

try:
    temporary_app.write_text(app, encoding="utf-8")
    temporary_market.write_text(
        market_code,
        encoding="utf-8"
    )

    py_compile.compile(
        str(temporary_app),
        doraise=True
    )

    py_compile.compile(
        str(temporary_market),
        doraise=True
    )

finally:
    temporary_app.unlink(missing_ok=True)
    temporary_market.unlink(missing_ok=True)

MARKET.write_text(market_code, encoding="utf-8")
APP.write_text(app, encoding="utf-8")

print("ACTUALIZACIÓN TERMINADA")
print("1. Contraste de textos corregido.")
print("2. Consulta de TRM oficial incorporada.")
print("3. Consulta del último cierre de Yahoo incorporada.")
print("4. Fecha real de cotización guardada.")
print("5. Copias de seguridad creadas.")
print("6. Base de datos e historial conservados.")
