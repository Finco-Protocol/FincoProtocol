"""RC-7B typed operating/debt calendar policy for the matched 3/3 candidate.

Every convention is an explicit, versioned enum value. Constructing a policy is
NOT owner approval and does NOT admit quarterly Runs: product admission is a
separate, closed gate owned by the application workspace. Legacy absence of a
policy resolves ONLY to the released six-month contract; nothing in this module
defaults an unknown or partial policy to semiannual.

Decision references (all OPEN, see docs/model_v2/RC7B_QUARTERLY_DECISION_MATRIX.md):
D-01 stub, D-02 fractions, D-03 horizon, D-04 annual clock, D-10 maturity.
D-06 (3/6) and D-07 (6/3) are refused here by construction.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

QUARTERLY_CANDIDATE_POLICY_VERSION = "rc7b-quarterly-candidate-v1"


class StubRule(str, Enum):
    """D-01: actual COD retained; first quarter ends at the next calendar-quarter end."""
    KEEP_ACTUAL_COD = "KEEP_ACTUAL_COD"


class DayRule(str, Enum):
    """D-02: half-open operating intervals; no COD first-day inclusion."""
    HALF_OPEN = "HALF_OPEN"


class FractionRule(str, Enum):
    """D-02: operating fraction = actual days / period-end year's 365 or 366."""
    ACTUAL_END_YEAR = "ACTUAL_END_YEAR"


class YearRule(str, Enum):
    """D-04: four sequential operating rows (stub included) form one model year."""
    FOUR_OPERATING_PERIODS_INCLUDING_STUB = "FOUR_OPERATING_PERIODS_INCLUDING_STUB"


class HorizonRule(str, Enum):
    """D-03: exactly four operating rows per horizon year, stub included."""
    FIXED_FOUR_PERIODS_PER_HORIZON_YEAR = "FIXED_FOUR_PERIODS_PER_HORIZON_YEAR"


class ConstructionReportingRule(str, Enum):
    """Construction model columns are the released six-month segments ending at actual COD.

    Monthly construction financing keeps its own dated axis; this rule only fixes
    the reporting columns, and it is enforced to be identical to the released
    6/6 columns for the same project (see QUARTERLY_COD_ROLL_WINDOW_PENDING_D01).
    """
    RELEASED_SIX_MONTH_SEGMENTS_TO_ACTUAL_COD = "RELEASED_SIX_MONTH_SEGMENTS_TO_ACTUAL_COD"


class MaturityRule(str, Enum):
    """D-10: Senior maturity is the end date of operating row ``tenor_years * 4``."""
    ROW_COUNT_SERVICE_ENDPOINT = "ROW_COUNT_SERVICE_ENDPOINT"


_POLICY_ENUMS = {
    "stub": StubRule,
    "day_rule": DayRule,
    "fraction": FractionRule,
    "model_year": YearRule,
    "horizon": HorizonRule,
    "construction_reporting": ConstructionReportingRule,
    "maturity": MaturityRule,
}


@dataclass(frozen=True)
class OperatingCalendarPolicy:
    """Explicit matched operating/debt calendar. Only matched 3/3 is defined."""

    version: str
    operating_months: int
    debt_service_months: int
    stub: StubRule
    day_rule: DayRule
    fraction: FractionRule
    model_year: YearRule
    horizon: HorizonRule
    construction_reporting: ConstructionReportingRule
    maturity: MaturityRule

    def __post_init__(self) -> None:
        if type(self.version) is not str or self.version != QUARTERLY_CANDIDATE_POLICY_VERSION:
            raise ValueError(f"QUARTERLY_POLICY_VERSION_UNSUPPORTED: {self.version!r}")
        for name in ("operating_months", "debt_service_months"):
            value = getattr(self, name)
            if type(value) is not int:
                raise ValueError(f"QUARTERLY_POLICY_INTEGER_MONTHS_REQUIRED: {name}={value!r}")
        if (self.operating_months, self.debt_service_months) != (3, 3):
            # D-06 (3/6) and D-07 (6/3) are deferred; 6/6 has no policy object.
            raise ValueError(
                "QUARTERLY_MATCHED_3_3_REQUIRED: "
                f"operating={self.operating_months} debt_service={self.debt_service_months}"
            )
        for name, enum in _POLICY_ENUMS.items():
            if type(getattr(self, name)) is not enum:
                raise ValueError(f"QUARTERLY_EXPLICIT_POLICY_REQUIRED: {name}")

    @property
    def periods_per_year(self) -> int:
        return 12 // self.operating_months

    def to_dict(self) -> dict:
        return {
            f.name: (getattr(self, f.name).value if f.name in _POLICY_ENUMS else getattr(self, f.name))
            for f in fields(self)
        }

    @classmethod
    def from_dict(cls, raw: object) -> "OperatingCalendarPolicy":
        """Strict decode: every field present, nothing extra, no defaulting."""
        expected = {f.name for f in fields(cls)}
        if type(raw) is not dict or set(raw) != expected:
            raise ValueError("QUARTERLY_COMPLETE_VERSIONED_POLICY_REQUIRED")
        values = dict(raw)
        for name, enum in _POLICY_ENUMS.items():
            try:
                values[name] = enum(values[name])
            except ValueError as exc:
                raise ValueError(f"QUARTERLY_POLICY_VALUE_UNSUPPORTED: {name}={values[name]!r}") from exc
        return cls(**values)

    def cache_key(self) -> tuple:
        return tuple(sorted(self.to_dict().items()))


def quarterly_candidate_policy() -> OperatingCalendarPolicy:
    """The single defined candidate. Construction is explicit; it is not approval."""
    return OperatingCalendarPolicy(
        version=QUARTERLY_CANDIDATE_POLICY_VERSION,
        operating_months=3,
        debt_service_months=3,
        stub=StubRule.KEEP_ACTUAL_COD,
        day_rule=DayRule.HALF_OPEN,
        fraction=FractionRule.ACTUAL_END_YEAR,
        model_year=YearRule.FOUR_OPERATING_PERIODS_INCLUDING_STUB,
        horizon=HorizonRule.FIXED_FOUR_PERIODS_PER_HORIZON_YEAR,
        construction_reporting=ConstructionReportingRule.RELEASED_SIX_MONTH_SEGMENTS_TO_ACTUAL_COD,
        maturity=MaturityRule.ROW_COUNT_SERVICE_ENDPOINT,
    )
