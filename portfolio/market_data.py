
from datetime import date


class MarketDataProvider:
    """Consulta cotizaciones de acciones mediante yfinance."""

    SUPPORTED_SYMBOLS = {"AMZN", "KO", "NKE"}

    def fetch_yfinance_price(self, symbol):
        symbol = str(symbol).strip().upper()

        if symbol not in self.SUPPORTED_SYMBOLS:
            raise RuntimeError(
                f"El símbolo {symbol} no está habilitado "
                "para consulta automática."
            )

        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            history = ticker.history(
                period="5d",
                auto_adjust=False
            )

            if history.empty:
                raise ValueError(
                    "La fuente no devolvió cotizaciones."
                )

            close_prices = history["Close"].dropna()

            if close_prices.empty:
                raise ValueError(
                    "No hay precios de cierre disponibles."
                )

            price = float(close_prices.iloc[-1])

            if price <= 0:
                raise ValueError(
                    "La fuente devolvió un precio no válido."
                )

            last_date = close_prices.index[-1].date().isoformat()

            source = (
                f"Yahoo Finance / yfinance. "
                f"Último cierre disponible: {last_date}"
            )

            return price, source

        except Exception as exc:
            raise RuntimeError(
                f"No fue posible consultar {symbol}: {exc}"
            ) from exc

    @staticmethod
    def today():
        return date.today().isoformat()
