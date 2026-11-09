from datetime import date
import requests


class MarketDataProvider:
    """
    Fuentes de consulta:
    - Yahoo Finance: último cierre disponible para símbolos compatibles.
    - Datos Abiertos Colombia: TRM publicada por la Superintendencia Financiera.

    Los precios pueden tener retraso. No son precios de ejecución de Trii.
    """

    TRM_URL = "https://www.datos.gov.co/resource/32sa-8pi3.json"

    def __init__(self, timeout=15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "PortfolioPersonal/1.0"
        })

    @staticmethod
    def today():
        return date.today().isoformat()

    def fetch_yfinance_price(self, symbol):
        try:
            import yfinance as yf

            ticker = yf.Ticker(str(symbol).strip().upper())
            history = ticker.history(
                period="5d",
                interval="1d",
                auto_adjust=False
            )

            if history.empty or "Close" not in history:
                raise ValueError("Yahoo Finance no devolvió precios.")

            closes = history["Close"].dropna()

            if closes.empty:
                raise ValueError("No hay cierres disponibles.")

            price = float(closes.iloc[-1])
            quote_date = closes.index[-1].date().isoformat()

            if price <= 0:
                raise ValueError("El precio recibido no es válido.")

            source = (
                f"Yahoo Finance - último cierre disponible "
                f"({quote_date}); puede tener retraso"
            )

            return price, source

        except Exception as exc:
            raise RuntimeError(
                f"No fue posible consultar {symbol} en Yahoo Finance: {exc}"
            ) from exc

    def fetch_trm(self):
        """
        Consulta la TRM más reciente publicada en el conjunto oficial
        de datos abiertos de Colombia.
        """
        try:
            params = {
                "$select": "valor,vigenciadesde",
                "$order": "vigenciadesde DESC",
                "$limit": "1"
            }

            response = self.session.get(
                self.TRM_URL,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()

            rows = response.json()

            if not rows:
                raise ValueError("La fuente oficial no devolvió registros.")

            row = rows[0]
            value = float(str(row["valor"]).replace(",", "."))
            valid_from = str(row["vigenciadesde"])[:10]

            if value <= 0:
                raise ValueError("La TRM recibida no es válida.")

            return {
                "value": value,
                "date": valid_from,
                "source": "Datos Abiertos Colombia - Superintendencia Financiera"
            }

        except Exception as exc:
            raise RuntimeError(
                f"No fue posible consultar la TRM oficial: {exc}"
            ) from exc
