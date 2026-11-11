"""Formato de cifras para toda la aplicación (convención colombiana).

* Punto para los miles y coma para los decimales.
* COP sin decimales:        $ 1.234.567
* USD con dos decimales:    US$ 1.234,56
* Cantidades de acciones:   enteras cuando lo son; si no, hasta 6 decimales sin ceros sobrantes.
* Valor faltante:           "Pendiente" (nunca se muestra como cero).
"""
import math

PENDING = "Pendiente"


def _is_missing(value):
    if value is None:
        return True
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return True


def fmt_number(value, decimals=0):
    """Número con puntos de miles y coma decimal."""
    text = f"{abs(float(value)):,.{decimals}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_money(value, currency="COP", missing=PENDING):
    """Valor monetario. COP sin decimales; USD con dos."""
    if _is_missing(value):
        return missing
    value = float(value)
    decimals = 0 if currency == "COP" else 2
    rounded = round(value, decimals)
    negative = rounded < 0
    body = fmt_number(rounded, decimals)
    symbol = "$" if currency == "COP" else "US$"
    return f"-{symbol} {body}" if negative else f"{symbol} {body}"


def fmt_cop(value, missing=PENDING):
    return fmt_money(value, "COP", missing)


def fmt_usd(value, missing=PENDING):
    return fmt_money(value, "USD", missing)


def fmt_qty(value, missing="—"):
    """Cantidad de acciones: entera si corresponde, si no hasta 6 decimales."""
    if _is_missing(value):
        return missing
    value = float(value)
    if abs(value - round(value)) < 1e-9:
        return fmt_number(round(value), 0)
    text = fmt_number(value, 6).rstrip("0").rstrip(",")
    return text


def fmt_pct(value, missing="N/D", signed=False):
    if _is_missing(value):
        return missing
    value = float(value)
    sign = "+" if signed and value > 0 else ("-" if value < 0 and round(value, 2) != 0 else "")
    return f"{sign}{fmt_number(abs(value), 2)} %"
