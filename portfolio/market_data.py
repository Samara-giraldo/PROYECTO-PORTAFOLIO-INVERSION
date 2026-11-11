from dataclasses import dataclass
from datetime import date, datetime


class QuoteError(RuntimeError):
    """No fue posible obtener una cotización confiable."""


@dataclass
class Quote:
    symbol: str
    price: float
    price_date: str      # fecha de la cotización (AAAA-MM-DD), no la de la consulta
    source: str          # texto que se guarda junto al precio
    currency: str = None  # moneda informada por la fuente, si la entregó
    realtime: bool = False


class MarketDataProvider:
    """Consulta precios con yfinance (Yahoo Finance).

    Lo que devuelve es el ÚLTIMO CIERRE DIARIO disponible, no un precio en tiempo real.
    Muchos símbolos colombianos no existen en Yahoo: en ese caso se lanza QuoteError
    y la app pide registrar el precio manualmente (por ejemplo, el visto en Trii).
    """

    SOURCE_TEXT = "Yahoo Finance (yfinance), último cierre diario; no es tiempo real"

    def _download(self, symbol):
        import yfinance as yf  # se importa aquí para que la app abra aunque falte la librería
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="10d", auto_adjust=False)
        currency = None
        try:
            currency = ticker.fast_info.get("currency")
        except Exception:
            currency = None
        return history, currency

    def fetch_quote(self, symbol, expected_currency=None):
        """Devuelve un Quote con precio, fecha de la cotización y fuente.

        Si la fuente informa una moneda distinta a ``expected_currency`` se rechaza,
        para no guardar, por ejemplo, un precio en USD en un activo en COP.
        """
        symbol = (symbol or "").strip()
        if not symbol:
            raise QuoteError("Falta el símbolo para consultar la cotización.")
        try:
            history, currency = self._download(symbol)
        except Exception as exc:
            raise QuoteError(f"No fue posible consultar {symbol}: {exc}") from exc

        if history is None or len(history) == 0:
            raise QuoteError(f"Yahoo Finance no devolvió datos para {symbol}. "
                             "Puede que el símbolo no exista allí; registra el precio manualmente.")
        close = history["Close"].dropna()
        if close.empty:
            raise QuoteError(f"No hay precio de cierre disponible para {symbol}.")
        price = float(close.iloc[-1])
        if not price > 0:
            raise QuoteError(f"La fuente devolvió un precio no válido para {symbol}.")
        last_index = close.index[-1]
        price_date = (last_index.date() if hasattr(last_index, "date") else last_index).isoformat()

        if expected_currency and currency and str(currency).upper() != expected_currency.upper():
            raise QuoteError(
                f"{symbol} cotiza en {currency}, pero el activo está en {expected_currency}. "
                "No se guardó el precio para evitar mezclar monedas.")
        return Quote(symbol=symbol, price=price, price_date=price_date,
                     source=self.SOURCE_TEXT, currency=currency)

    def fetch_usd_cop(self):
        """Tasa de mercado USD/COP de Yahoo Finance (símbolo COP=X).

        NO es la TRM oficial de la Superfinanciera/Banco de la República. Si necesitas la
        TRM oficial, ingrésala a mano con su fecha.
        """
        try:
            history, _ = self._download("COP=X")
        except Exception as exc:
            raise QuoteError(f"No fue posible consultar la tasa USD/COP: {exc}") from exc
        if history is None or len(history) == 0:
            raise QuoteError("Yahoo Finance no devolvió la tasa USD/COP.")
        close = history["Close"].dropna()
        if close.empty or not float(close.iloc[-1]) > 0:
            raise QuoteError("No hay una tasa USD/COP válida disponible.")
        last_index = close.index[-1]
        rate_date = (last_index.date() if hasattr(last_index, "date") else last_index).isoformat()
        return Quote(symbol="COP=X", price=float(close.iloc[-1]), price_date=rate_date,
                     source="Yahoo Finance (COP=X), tasa de mercado; no es la TRM oficial",
                     currency="COP")

    # Compatibilidad con el código anterior ---------------------------------
    def fetch_yfinance_price(self, symbol):
        quote = self.fetch_quote(symbol)
        return quote.price, quote.source

    @staticmethod
    def today():
        return date.today().isoformat()

    @staticmethod
    def now():
        return datetime.now().isoformat(timespec="seconds")
