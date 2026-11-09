from datetime import date
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import json

import yfinance as yf


class MarketDataProvider:
    """Consulta TRM oficial y precios de acciones disponibles."""

    def fetch_trm(self):
        """
        Consulta la TRM publicada por la Superintendencia Financiera
        en el conjunto oficial de Datos Abiertos Colombia.
        """
        base_url = "https://www.datos.gov.co/resource/32sa-8pi3.json"

        params = urlencode({
            "$select": "valor,vigenciadesde",
            "$order": "vigenciadesde DESC",
            "$limit": "1"
        })

        url = f"{base_url}?{params}"

        try:
            request = Request(
                url,
                headers={"User-Agent": "PortfolioInversion/1.0"}
            )

            with urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))

            if not data:
                raise ValueError("La fuente no devolvió datos de TRM.")

            value = float(data[0]["valor"])
            effective_date = str(data[0]["vigenciadesde"])[:10]

            if value <= 0:
                raise ValueError("La TRM recibida no es válida.")

            return (
                value,
                effective_date,
                "Superintendencia Financiera - Datos Abiertos Colombia"
            )

        except Exception as exc:
            raise RuntimeError(
                f"No fue posible consultar la TRM oficial: {exc}"
            ) from exc

    def fetch_yfinance_price(self, symbol):
        """Consulta el último precio de cierre disponible en Yahoo Finance."""
        symbol = str(symbol).strip().upper()

        if not symbol:
            raise ValueError("Debes indicar el símbolo de la acción.")

        try:
            ticker = yf.Ticker(symbol)

            history = ticker.history(
                period="5d",
                interval="1d",
                auto_adjust=False
            )

            if history.empty or "Close" not in history:
                raise ValueError(
                    "Yahoo Finance no devolvió cotizaciones para este símbolo."
                )

            close_prices = history["Close"].dropna()

            if close_prices.empty:
                raise ValueError("No hay precios de cierre disponibles.")

            price = float(close_prices.iloc[-1])
            quote_date = close_prices.index[-1].date().isoformat()

            if price <= 0:
                raise ValueError("El precio recibido no es válido.")

            return (
                price,
                "Yahoo Finance - último cierre disponible",
                quote_date
            )

        except Exception as exc:
            raise RuntimeError(
                f"No se pudo consultar {symbol} en Yahoo Finance: {exc}"
            ) from exc

    @staticmethod
    def today():
        return date.today().isoformat()