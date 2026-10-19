"""Typed operating/debt calendar policy for the matched 3/3 candidate (RC-7B v1, RC-7C v2).

Every convention is an explicit, versioned enum value. Constructing a policy is
NOT owner approval and does NOT admit quarterly Runs: product admission is a
separate, closed gate owned by the application workspace. Legacy absence of a
policy resolves ONLY to the released six-month contract; nothing in this module
defaults an unknown or partial policy to semiannual.

Decision references (all OPEN, see docs/model_v2/RC7B_QUARTERLY_DECISION_MATRIX.md):
D-01 stub, D-02 fractions, D-03 horizon, D-04 annual clock, D-10 maturity.
D-06 (3/6) and D-07 (6/3) are refused here by construction.

Two versioned candidate policies exist; neither is owner-approved and neither admits a product Run:

* ``rc7b-quarterly-candidate-v1`` (historical): exactly four operating rows per horizon year, stub included. When COD falls in the
  second quarter of a half-year the stub row is one quarter, so v1 ends one quarter AFTER the equivalent six-month project and shifts
  every model-year boundary (degradation, indexation, depreciation, OPEX steps) and the Senior maturity by a quarter (D-03/D-04/D-10).
* ``rc7c-quarterly-candidate-v2`` (current candidate): the economic calendar is DATE-authoritative. The horizon end, the model-year
  boundaries and the Senior maturity are the dates the equivalent six-month project has; the frequency only subdivides the same
  calendar into quarterly rows. The two rule sets can never be mixed.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

QUARTERLY_CANDIDATE_POLICY_VERSION = "rc7b-quarterly-candidate-v1"
QUARTERLY_CANDIDATE_POLICY_VERSION_V2 = "rc7c-quarterly-candidate-v2"
SUPPORTED_POLICY_VERSIONS = (QUARTERLY_CANDIDATE_POLICY_VERSION, QUARTERLY_CANDIDATE_POLICY_VERSION_V2)


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
    """D-04: how an operating row is assigned to a model year (degradation, indexation, depreciation, OPEX)."""
    FOUR_OPERATING_PERIODS_INCLUDING_STUB = "FOUR_OPERATING_PERIODS_INCLUDING_STUB"          # v1: every four rows, stub counted as a row
    SEMIANNUAL_MODEL_YEAR_ALIGNED = "SEMIANNUAL_MODEL_YEAR_ALIGNED"                           # v2: the model year of the containing six-month row


class HorizonRule(str, Enum):
    """D-03: where the economic horizon ends."""
    FIXED_FOUR_PERIODS_PER_HORIZON_YEAR = "FIXED_FOUR_PERIODS_PER_HORIZON_YEAR"              # v1: exactly four rows per horizon year
    SEMIANNUAL_ECONOMIC_END_DATE_PRESERVED = "SEMIANNUAL_ECONOMIC_END_DATE_PRESERVED"       # v2: the end date of the equivalent six-month horizon


class ConstructionReportingRule(str, Enum):
    """Construction model columns are the released six-month segments ending at actual COD.

    Monthly construction financing keeps its own dated axis; this rule only fixes
    the reporting columns, and it is enforced to be identical to the released
    6/6 columns for the same project (see QUARTERLY_COD_ROLL_WINDOW_PENDING_D01).
    """
    RELEASED_SIX_MONTH_SEGMENTS_TO_ACTUAL_COD = "RELEASED_SIX_MONTH_SEGMENTS_TO_ACTUAL_COD"


class MaturityRule(str, Enum):
    """D-10: where Senior debt matures."""
    ROW_COUNT_SERVICE_ENDPOINT = "ROW_COUNT_SERVICE_ENDPOINT"                                # v1: the end date of operating row tenor_years * 4
    SEMIANNUAL_MATURITY_DATE_PRESERVED = "SEMIANNUAL_MATURITY_DATE_PRESERVED"               # v2: the end date of six-month row tenor_years * 2


# The three date-sensitive rules travel together: a policy is either the historical fixed-row set or the date-authoritative set.
_RULESETS = {
    QUARTERLY_CANDIDATE_POLICY_VERSION: {
        "horizon": HorizonRule.FIXED_FOUR_PERIODS_PER_HORIZON_YEAR,
        "model_year": YearRule.FOUR_OPERATING_PERIODS_INCLUDING_STUB,
        "maturity": MaturityRule.ROW_COUNT_SERVICE_ENDPOINT,
    },
    QUARTERLY_CANDIDATE_POLICY_VERSION_V2: {
        "horizon": HorizonRule.SEMIANNUAL_ECONOMIC_END_DATE_PRESERVED,
        "model_year": YearRule.SEMIANNUAL_MODEL_YEAR_ALIGNED,
        "maturity": MaturityRule.SEMIANNUAL_MATURITY_DATE_PRESERVED,
    },
}

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
        if type(self.version) is not str or self.version not in SUPPORTED_POLICY_VERSIONS:
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
        for name, required in _RULESETS[self.version].items():
            if getattr(self, name) is not required:
                raise ValueError(
                    f"QUARTERLY_POLICY_RULESET_MISMATCH: {self.version} requires {name}={required.value}, got {getattr(self, name).value}")

    @property
    def periods_per_year(self) -> int:
        return 12 // self.operating_months

    @property
    def date_authoritative(self) -> bool:
        """True for the v2 rule set: horizon, model years and maturity are dates, not row counts."""
        return self.version == QUARTERLY_CANDIDATE_POLICY_VERSION_V2

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


def quarterly_candidate_policy_v1() -> OperatingCalendarPolicy:
    """Historical RC-7B candidate (fixed four rows per year). Kept decodable and testable; superseded by v2. Not approval."""
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


def quarterly_candidate_policy_v2() -> OperatingCalendarPolicy:
    """RC-7C date-authoritative candidate: same economic calendar as 6/6, subdivided into quarters. Construction is explicit; not approval."""
    return OperatingCalendarPolicy(
        version=QUARTERLY_CANDIDATE_POLICY_VERSION_V2,
        operating_months=3,
        debt_service_months=3,
        stub=StubRule.KEEP_ACTUAL_COD,
        day_rule=DayRule.HALF_OPEN,
        fraction=FractionRule.ACTUAL_END_YEAR,
        model_year=YearRule.SEMIANNUAL_MODEL_YEAR_ALIGNED,
        horizon=HorizonRule.SEMIANNUAL_ECONOMIC_END_DATE_PRESERVED,
        construction_reporting=ConstructionReportingRule.RELEASED_SIX_MONTH_SEGMENTS_TO_ACTUAL_COD,
        maturity=MaturityRule.SEMIANNUAL_MATURITY_DATE_PRESERVED,
    )


def quarterly_candidate_policy() -> OperatingCalendarPolicy:
    """The current (v2) candidate. Construction is explicit; it is not approval."""
    return quarterly_candidate_policy_v2()
