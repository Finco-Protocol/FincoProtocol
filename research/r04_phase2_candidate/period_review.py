"""Exact declared-period cap review; no annual prorating, pricing or persistence.

The canonical generator supplies actual selected-case full-period production.
Callers separately declare every delivery. This checks ONLY those period rows;
it never asserts that they fulfil the parsed annual obligation. That policy and
all production admission remain closed.
"""
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
from fractions import Fraction
import hashlib
import json
import math
import re
from decimal import Decimal, InvalidOperation

from .contracts import AnnualBook, CandidateError, _text, parse_annual_document


def _default(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal) and value.is_finite():
        return str(value)
    raise TypeError()


def _hash(value):
    return hashlib.sha256(json.dumps(value, default=_default, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def exact(value):
    """Lossless JSON amount; presentation precision is not a business policy."""
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


@dataclass(frozen=True)
class GenerationPeriod:
    index: int
    start: date
    end: date
    mwh: Fraction
    # Raw engine row labels are not universally half-open calendar dates.
    days_in_period: int | None = None
    day_fraction: str | None = None


@dataclass(frozen=True)
class TechnicalSource:
    technology: str
    case: str
    input_sha256: str
    context_sha256: str
    periods: tuple[GenerationPeriod, ...]
    axis_scope: str = "EXPLICIT_DECLARED_PERIOD_ROWS"

    @property
    def identity_sha256(self):
        return _hash({"inputs": self.input_sha256, "context": self.context_sha256,
                      "technology": self.technology, "case": self.case, "axis_scope": self.axis_scope,
                      "periods": [(p.index, p.start, p.end, exact(p.mwh), p.days_in_period, p.day_fraction)
                                  for p in self.periods]})


def source_from_inputs(inputs, *, technology, project_id, scenario_id, input_revision):
    """Bind typed effective input facts; identity is content, not authorization.

    Does not load a project, infer user ownership or resolve a scenario. A future
    admitted writer must obtain these inputs and context inside its transaction.
    """
    try:
        from finco_core.inputs._models import ProjectInputs
        from financial_engine.adapters.project_inputs import from_project_inputs
        from financial_engine.orchestrator import _build_period_engine
        from finco_core.revenue.generation import full_generation_schedule
        if type(inputs) is not ProjectInputs or technology not in ("solar", "wind"):
            raise CandidateError("R04_P2_TECHNOLOGY")
        for value in (project_id, scenario_id, input_revision):
            _text(value)
        # Keep the adapter's exact admitted cases. Core generation by itself has
        # a P50 fallback which must not accept unknown or unsupported case names.
        case = inputs.technical.yield_scenario
        if case not in ("P_50", "P90-10y"):
            raise CandidateError("R04_P2_SELECTED_CASE_UNSUPPORTED")
        if inputs.technical.bess_enabled or getattr(inputs.technical, "bess_native_config_json", ""):
            raise CandidateError("R04_P2_TECHNOLOGY")
        numeric = (inputs.technical.capacity_mw, inputs.technical.operating_hours_p50,
                   inputs.technical.operating_hours_p90_10y, inputs.technical.plant_availability,
                   inputs.technical.grid_availability, inputs.technical.pv_degradation)
        # Match the existing engine's TECH001/2/3/4/6/7 domains before
        # multiplication: invalid negative factors can otherwise cancel, and
        # a finite nonnegative output would falsely look like usable source.
        # Degradation [0,1] is already the core input-validator contract.
        if (any(isinstance(v, bool) or not math.isfinite(v) for v in numeric)
                or any(v < 0 for v in numeric[:3])
                or not 0 <= inputs.technical.plant_availability <= 1
                or not 0 <= inputs.technical.grid_availability <= 1
                or not 0 <= inputs.technical.pv_degradation <= 1
                or (case == "P90-10y" and inputs.technical.operating_hours_p90_10y <= 0)):
            raise CandidateError("R04_P2_GENERATION_INVALID")
        typed_hash = _hash(asdict(inputs))
        engine = _build_period_engine(from_project_inputs(inputs))
        schedule = full_generation_schedule(inputs, engine)
        rows = []
        for p in engine.periods():
            if not p.is_operation:
                continue
            value = schedule[p.index]
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise CandidateError("R04_P2_GENERATION_INVALID")
            rows.append(GenerationPeriod(p.index, p.start_date, p.end_date, Fraction(str(value)),
                                         p.days_in_period, str(p.day_fraction)))
        periods = tuple(rows)
        _validate_periods(periods)
        context_hash = _hash({"project": project_id, "scenario": scenario_id, "revision": input_revision})
        return TechnicalSource(technology, case, typed_hash, context_hash, periods,
                               "CANONICAL_PERIOD_ENGINE_ROW_LABELS")
    except CandidateError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, UnicodeError, OverflowError, RecursionError):
        raise CandidateError("R04_P2_EFFECTIVE_INPUTS_UNSUPPORTED") from None


def _validate_periods(periods):
    if type(periods) is not tuple or not periods or len(periods) > 1000:
        raise CandidateError("R04_P2_PERIOD_AXIS")
    previous = None
    for p in periods:
        if (type(p) is not GenerationPeriod or type(p.index) is not int or type(p.start) is not date or type(p.end) is not date
                or p.index < 0 or p.end <= p.start or type(p.mwh) is not Fraction or p.mwh < 0
                or (previous is not None and (p.index <= previous.index or p.start != previous.end))):
            raise CandidateError("R04_P2_PERIOD_AXIS")
        if p.days_in_period is not None or p.day_fraction is not None:
            if (type(p.days_in_period) is not int or p.days_in_period <= 0
                    or not isinstance(p.day_fraction, str) or len(p.day_fraction) > 128):
                raise CandidateError("R04_P2_PERIOD_AXIS")
            try:
                fraction = Decimal(p.day_fraction)
                if not fraction.is_finite() or fraction <= 0:
                    raise CandidateError("R04_P2_PERIOD_AXIS")
            except InvalidOperation:
                raise CandidateError("R04_P2_PERIOD_AXIS") from None
        previous = p


@dataclass(frozen=True)
class DeclaredDelivery:
    contract_id: str
    period_index: int
    mwh: Fraction


class PeriodCapExceeded(CandidateError):
    def __init__(self, report):
        super().__init__("GLOBAL_PPA_CAP_EXCEEDED")
        self.report = report


def review_declared_deliveries(book: AnnualBook, source: TechnicalSource, deliveries,
                               *, expected_source_sha256, requested_contract_id=None):
    """Check explicit aligned period quantities, never validate an annual deal.

    No absent delivery becomes zero. No daily/seasonal or anniversary curve is
    inferred. Matching engine boundary labels is not calendar-window validation. A WITHIN_LIMIT result remains closed to production Save and Run.
    """
    if type(book) is not AnnualBook or type(source) is not TechnicalSource:
        raise CandidateError("R04_P2_TYPED_CANDIDATE_REQUIRED")
    if parse_annual_document(book.canonical_json) != book:
        raise CandidateError("R04_P2_DOCUMENT_IDENTITY")
    _validate_periods(source.periods)
    if any(not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None
           for v in (source.input_sha256, source.context_sha256)):
        raise CandidateError("R04_P2_SOURCE_IDENTITY")
    if source.identity_sha256 != expected_source_sha256 or book.technology != source.technology:
        raise CandidateError("R04_P2_SOURCE_IDENTITY")
    if source.axis_scope not in ("EXPLICIT_DECLARED_PERIOD_ROWS", "CANONICAL_PERIOD_ENGINE_ROW_LABELS"):
        raise CandidateError("R04_P2_PERIOD_AXIS")
    if (source.axis_scope == "CANONICAL_PERIOD_ENGINE_ROW_LABELS"
            and any(p.days_in_period is None or p.day_fraction is None for p in source.periods)):
        raise CandidateError("R04_P2_PERIOD_AXIS")
    if source.case not in ("P_50", "P90-10y"):
        raise CandidateError("R04_P2_SELECTED_CASE_UNSUPPORTED")
    _validate_periods(source.periods)
    contracts = {c.contract_id: c for c in book.contracts}
    if not contracts or len(contracts) != len(book.contracts):
        raise CandidateError("R04_P2_DUPLICATE_CONTRACT")
    if requested_contract_id is not None:
        _text(requested_contract_id)
        if requested_contract_id not in contracts:
            raise CandidateError("R04_P2_REQUESTED_CONTRACT")
    starts = {p.start for p in source.periods}
    ends = {p.end for p in source.periods}
    for c in book.contracts:
        if c.start not in starts or c.end not in ends:
            raise CandidateError("R04_P2_PARTIAL_PERIOD_POLICY_REQUIRED")
    expected = {(c.contract_id, p.index) for c in book.contracts for p in source.periods
                if c.start <= p.start and p.end <= c.end}
    if type(deliveries) not in (list, tuple) or len(deliveries) > 24000:
        raise CandidateError("R04_P2_DECLARED_DELIVERY")
    supplied = {}
    for d in deliveries:
        if type(d) is not DeclaredDelivery or not isinstance(d.contract_id, str):
            raise CandidateError("R04_P2_DECLARED_DELIVERY")
        pair = (d.contract_id, d.period_index)
        if (type(d.period_index) is not int or type(d.mwh) is not Fraction or d.mwh < 0
                or pair not in expected or pair in supplied):
            raise CandidateError("R04_P2_DECLARED_DELIVERY")
        supplied[pair] = d.mwh
    if set(supplied) != expected:
        raise CandidateError("R04_P2_DECLARED_DELIVERY_COVERAGE")
    rows, violations = [], []
    for p in source.periods:
        per_contract = {cid: value for (cid, idx), value in supplied.items() if idx == p.index}
        committed = sum(per_contract.values(), Fraction(0))
        requested = per_contract.get(requested_contract_id, Fraction(0))
        existing = committed - requested
        row = {"period_index": p.index, "start_boundary_label": p.start.isoformat(), "end_boundary_label": p.end.isoformat(),
               "days_in_period": p.days_in_period, "day_fraction": p.day_fraction,
               "available_mwh": exact(p.mwh), "committed_mwh": exact(committed),
               "uncontracted_mwh": exact(p.mwh - committed),
               "per_contract_mwh": {cid: exact(v) for cid, v in sorted(per_contract.items())}}
        rows.append(row)
        if committed > p.mwh:
            violations.append({"case": source.case, "start_boundary_label": row["start_boundary_label"], "end_boundary_label": row["end_boundary_label"],
                               **{key + "_gwh": exact(v / 1000) for key, v in {
                                   "available": p.mwh, "existing": existing, "requested": requested,
                                   "remaining": p.mwh - existing, "excess": committed - p.mwh,
                                   "maximum_additional": max(Fraction(0), p.mwh - existing)}.items()}})
    report = {"scope": "DECLARED_PERIOD_DELIVERY_CAP_ONLY", "source_identity_sha256": source.identity_sha256,
              "identity_scope": "CONTENT_ONLY_NOT_AUTHORIZATION_OR_COMMITTED_RUN", "case": source.case,
              "status": "EXCEEDED" if violations else "WITHIN_LIMIT_NOT_ANNUAL_CONTRACT_ACCEPTANCE",
              "axis_scope": source.axis_scope, "calendar_delivery_interval_verified": False,
              "annual_semantics_verified": False, "pricing_verified": False,
              "production_supported": False, "persisted": False, "run_executed": False,
              "periods": rows, "violations": violations}
    if violations:
        raise PeriodCapExceeded(report)
    return report
