from dataclasses import dataclass

@dataclass
class FixedIncomeTerms:
    asset_id: int
    annual_rate_pct: float
    rate_type: str
    issue_date: str
    maturity_date: str
    payment_frequency: str
    nominal_value: float
    notes: str = ""
