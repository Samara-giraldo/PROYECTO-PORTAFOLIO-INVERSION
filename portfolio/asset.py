from dataclasses import dataclass

@dataclass
class Asset:
    id: int
    name: str
    symbol: str
    asset_type: str
    currency: str
    market: str
    current_price: float
    source: str = "Manual"
