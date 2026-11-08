from datetime import date

class MarketDataProvider:
    """Consulta precios de tickers compatibles usando yfinance."""

    def fetch_yfinance_price(self, symbol):
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            history = ticker.history(period="5d", auto_adjust=False)
            if history.empty:
                raise ValueError("La fuente no devolvió cotizaciones.")
            close = history["Close"].dropna()
            if close.empty:
                raise ValueError("No hay precio de cierre disponible.")
            return float(close.iloc[-1]), f"Yahoo Finance/yfinance; último cierre disponible"
        except Exception as exc:
            raise RuntimeError(f"No fue posible consultar {symbol}: {exc}") from exc

    @staticmethod
    def today():
        return date.today().isoformat()
