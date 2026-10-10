"""Clean opt-in contract, without changing any inactive RevenueInput payload."""
from dataclasses import dataclass

from financial_engine.inputs import RevenueInput


@dataclass(frozen=True)
class MultiStreamRevenueInput(RevenueInput):
    multistream_config_json: str = ""

    def __post_init__(self):
        from domain.revenue.multistream_runtime import parse_config
        if parse_config(self.multistream_config_json) is None:
            raise ValueError("REVENUE_V2_AUTHORITY: explicit contracts required")
