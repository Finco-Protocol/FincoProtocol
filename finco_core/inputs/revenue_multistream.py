"""Explicit opt-in revenue authority; the legacy dataclass shape stays unchanged."""
from dataclasses import dataclass

from finco_core.inputs._models import RevenueParams


@dataclass(frozen=True)
class MultiStreamRevenueParams(RevenueParams):
    multistream_config_json: str = ""

    def __post_init__(self):
        from domain.revenue.multistream_runtime import parse_config
        if parse_config(self.multistream_config_json) is None:
            raise ValueError("REVENUE_V2_AUTHORITY: explicit contracts required")
