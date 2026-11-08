from dataclasses import dataclass

@dataclass
class Transaction:
    id: int
    asset_id: int
    operation: str
    date: str
    quantity: float
    price: float
    commission: float
