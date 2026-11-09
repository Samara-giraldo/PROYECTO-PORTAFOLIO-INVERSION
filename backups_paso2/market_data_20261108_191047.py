
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
