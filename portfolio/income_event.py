from dataclasses import dataclass

@dataclass
class IncomeEvent:
    id: int
    asset_id: int
    event_type: str
    date: str
    amount: float
    description: str = ""
