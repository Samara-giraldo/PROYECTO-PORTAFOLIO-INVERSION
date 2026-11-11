"""Cálculo transparente de comisiones.

IMPORTANTE: lo que calcula este módulo es una ESTIMACIÓN. La comisión real es la
que aparece en el comprobante de la operación; la aplicación permite corregirla.

Tarifas de referencia (revisadas el 9-nov-2026, pueden cambiar):
* Bolsa de Colombia, usuario estándar: $14.875 (= $12.500 + IVA) por operación hasta
  $5.000.000 y 0,25 % + IVA por encima. VERIFICADO en https://trii.co/faq.
* Bolsa de EE. UU.: 0,2 % estándar y gratis con triipro. VERIFICADO en
  https://trii.co/acciones-estados-unidos (la página no dice si suma IVA: configurable).
* Dividendos: trii cobra el 1 % del dividendo recibido (o $200 si el 1 % es menor), más la
  retención en la fuente cuando aplique. VERIFICADO en https://trii.co/faq. No se sabe si
  ese cobro lleva IVA; por eso es una estimación configurable.
* Trii Pro, Bolsa de Colombia: 0,125 % con mínimo $6.250 + IVA. NO VERIFICADO: trii.co no
  publica la tarifa Pro de acciones colombianas; es una estimación basada en un descuento
  del 50 % que menciona la prensa. Corrígela con tu comprobante.
"""
from dataclasses import dataclass, asdict, fields
from decimal import Decimal, ROUND_HALF_UP

from portfolio.formatting import fmt_number

PLAN_STANDARD = "ESTANDAR"
PLAN_PRO = "PRO"
PLAN_CUSTOM = "PERSONALIZADA"
PLANS = (PLAN_STANDARD, PLAN_PRO, PLAN_CUSTOM)
PLAN_LABELS = {
    PLAN_STANDARD: "Trii estándar",
    PLAN_PRO: "Trii Pro",
    PLAN_CUSTOM: "Personalizada (otro intermediario)",
}

SETTINGS_KEY = "fee_config"
TARIFFS_VERIFIED_ON = "2026-11-09"
TARIFFS_NOTE = (
    "Tarifas revisadas el 9 de noviembre de 2026 en trii.co. Verificado: Colombia estándar "
    "($12.500 + IVA hasta $5.000.000; 0,25 % + IVA por encima), EE. UU. (0,2 % estándar, "
    "gratis con Pro) y dividendos (1 %, mínimo $200). NO verificado: la tarifa Pro de "
    "acciones colombianas. Todo es estimación: la comisión real es la del comprobante."
)


@dataclass
class FeeConfig:
    plan: str = PLAN_STANDARD
    vat_pct: float = 19.0
    # Bolsa de Colombia (activos en COP)
    co_std_pct: float = 0.25
    co_std_min: float = 12500.0
    co_pro_pct: float = 0.125
    co_pro_min: float = 6250.0
    # Bolsa de EE. UU. (activos en USD)
    us_std_pct: float = 0.20
    us_pro_pct: float = 0.0
    us_add_vat: bool = False
    # Costo de Trii por dividendos (solo activos en COP): % del dividendo recibido y mínimo
    div_fee_pct: float = 1.0
    div_fee_min: float = 200.0
    div_fee_add_vat: bool = False
    # Plan personalizado
    custom_pct: float = 0.50
    custom_min: float = 0.0
    custom_add_vat: bool = False

    @classmethod
    def from_dict(cls, data):
        allowed = {f.name for f in fields(cls)}
        clean = {k: v for k, v in (data or {}).items() if k in allowed}
        config = cls(**clean)
        if config.plan not in PLANS:
            config.plan = PLAN_STANDARD
        return config

    def to_dict(self):
        return asdict(self)


@dataclass
class FeeResult:
    base: float
    vat: float
    total: float
    description: str
    is_estimate: bool = True


def _pct(value):
    """Porcentaje legible: 0,25 / 0,125 / 1 (sin ceros sobrantes)."""
    text = fmt_number(value, 3)
    return text.rstrip("0").rstrip(",") if "," in text else text


def round_money(value, currency):
    """COP sin decimales; USD con dos decimales. Redondeo comercial (0,5 sube)."""
    exp = Decimal("1") if currency == "COP" else Decimal("0.01")
    return float(Decimal(str(value)).quantize(exp, rounding=ROUND_HALF_UP))


def load_fee_config(database):
    return FeeConfig.from_dict(database.get_json_setting(SETTINGS_KEY, {}))


def save_fee_config(database, config):
    database.set_json_setting(SETTINGS_KEY, config.to_dict())


def compute_commission(gross, currency, config=None, asset_override_pct=None):
    """Estima la comisión de una operación de valor bruto ``gross``.

    ``asset_override_pct``: porcentaje personalizado de la empresa (ya incluye todo);
    si existe, reemplaza al plan.
    """
    config = config or FeeConfig()
    gross = float(gross or 0)
    if gross <= 0:
        return FeeResult(0.0, 0.0, 0.0, "Sin valor de operación")

    if asset_override_pct is not None:
        base = round_money(gross * float(asset_override_pct) / 100, currency)
        return FeeResult(base, 0.0, base,
                         f"Porcentaje personalizado de la empresa: {fmt_number(asset_override_pct, 2)} %")

    vat_rate = config.vat_pct / 100
    add_vat = True

    if config.plan == PLAN_CUSTOM:
        base = max(gross * config.custom_pct / 100, config.custom_min)
        add_vat = config.custom_add_vat
        description = f"Plan personalizado: {fmt_number(config.custom_pct, 2)} %"
        if config.custom_min:
            description += f" (mínimo {fmt_number(config.custom_min, 0)})"
    elif currency == "COP":
        if config.plan == PLAN_PRO:
            base = max(gross * config.co_pro_pct / 100, config.co_pro_min)
            description = f"Trii Pro, Bolsa de Colombia: {_pct(config.co_pro_pct)} % (mínimo {fmt_number(config.co_pro_min, 0)}) + IVA"
        else:
            base = max(gross * config.co_std_pct / 100, config.co_std_min)
            description = f"Trii estándar, Bolsa de Colombia: {_pct(config.co_std_pct)} % (mínimo {fmt_number(config.co_std_min, 0)}) + IVA"
    elif currency == "USD":
        pct = config.us_pro_pct if config.plan == PLAN_PRO else config.us_std_pct
        base = gross * pct / 100
        add_vat = config.us_add_vat
        description = f"Bolsa de EE. UU.: {fmt_number(pct, 2)} %" + (" + IVA" if add_vat else " (IVA no incluido)")
    else:
        return FeeResult(0.0, 0.0, 0.0,
                         f"No hay tarifa configurada para {currency}; ingresa la comisión real.")

    base = round_money(base, currency)
    vat = round_money(base * vat_rate, currency) if add_vat else 0.0
    return FeeResult(base, vat, round_money(base + vat, currency), description)


def compute_dividend_fee(gross, withholding, currency, config=None):
    """Estima el costo de Trii por recibir un dividendo (activos en COP).

    Regla publicada en trii.co/faq: 1 % del dividendo recibido, o $200 si el 1 % es menor.
    Se calcula sobre el valor bruto menos la retención (lo que realmente llega). La página no
    aclara si lleva IVA ni sobre qué base exacta: es una ESTIMACIÓN; corrígela con tu comprobante.
    No incluye la retención en la fuente, que se registra aparte.
    """
    config = config or FeeConfig()
    if currency != "COP":
        return FeeResult(0.0, 0.0, 0.0,
                         "No hay tarifa de dividendos configurada para esta moneda; "
                         "ingresa el costo real del comprobante.")
    received = float(gross or 0) - float(withholding or 0)
    if received <= 0:
        return FeeResult(0.0, 0.0, 0.0, "Sin valor recibido")
    base = round_money(max(received * config.div_fee_pct / 100, config.div_fee_min), currency)
    vat = round_money(base * config.vat_pct / 100, currency) if config.div_fee_add_vat else 0.0
    return FeeResult(base, vat, round_money(base + vat, currency),
                     f"Trii, dividendos: {_pct(config.div_fee_pct)} % del dividendo recibido "
                     f"(mínimo {fmt_number(config.div_fee_min, 0)})" + (" + IVA" if config.div_fee_add_vat else ""))
