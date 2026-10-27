"""financial_engine.dsra.reserve_authority — explicit typed reserve policy selection (FIN-V2-R1).

One place that states, for a ``ProjectInputs`` financing block or a Bankability editor reserve
selection, WHICH reserve policy is in force, under WHICH calculation version, and whether it is ACTIVE
or GATED. It reads typed fields only; it never calculates a reserve and never changes an input.

Why it exists (R0). The editor used to map ``automatic_peak`` to
``dsra_support_mode=NONE, dsra_target_policy=None, dsra_months=N``. That is the *input signature the
H-1 generic financing policy recognises as "derive an automatic Cash DSRA"* — but the same
fields also read as "no reserve" (NONE) and, for ``dsra_target_policy=None``, as FIXED_AMOUNT in the
adapter. Nothing distinguished the three, so a run under any other financing policy silently carried no
reserve. ``classify_financing`` makes the distinction explicit and ``assert_selection_realised`` refuses
a selection whose resulting inputs would not carry the selected policy.

Kinds and versions are orthogonal:

* ``ReservePolicyKind``: NONE, FIXED_AMOUNT, FORWARD, PEAK_FORWARD.
* ``ReservePolicyVersion``: STATIC_V0 (historical static scalar), SHORTCUT_V0 (historical
  ``next_period_service * months * periods_per_year / 12`` target, still the only version the engine
  executes) and CALENDAR_V1 (``financial_engine.dsra.forward_coverage``; requirement and read-only
  projection implemented, engine funding activation GATED — see ``CALENDAR_V1_GATE``).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from finco_core.inputs import DebtServiceReserveSupportMode
from financial_engine.dsra.target import DsraTargetPolicy


class ReservePolicyKind(Enum):
    NONE = "none"
    FIXED_AMOUNT = "fixed_amount"
    FORWARD = "forward"
    PEAK_FORWARD = "peak_forward"


class ReservePolicyVersion(Enum):
    NOT_APPLICABLE = "not_applicable"
    STATIC_V0 = "static_v0"
    SHORTCUT_V0 = "forward_shortcut_v0"
    CALENDAR_V1 = "forward_calendar_coverage_v1"


class ReserveActivation(Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"            # NONE: no reserve is selected
    ACTIVE_STATIC = "ACTIVE_STATIC"              # explicit CASH_DSRA with a funded scalar
    ACTIVE_EXPLICIT_POLICY = "ACTIVE_EXPLICIT_POLICY"  # CASH_DSRA + explicit forward policy + funded scalar
    ACTIVE_VIA_GENERIC_POLICY_H1 = "ACTIVE_VIA_GENERIC_POLICY_H1"  # automatic; funded by the H-1 fixed point
    GATED = "GATED"                              # selected but not executable: typed refusal reason


# Stable typed refusal codes.
CODE_UNRECOGNISED = "RESERVE_POLICY_UNRECOGNISED"
CODE_AUTOMATIC_NOT_REALISED = "RESERVE_AUTOMATIC_SELECTION_NOT_REALISED"
CODE_CALENDAR_FUNDING_GATED = "RESERVE_CALENDAR_V1_FUNDING_UNRESOLVED"
CODE_GATED_MODE = "RESERVE_MODE_GATED"
CODE_MISMATCH = "RESERVE_SELECTION_MISMATCH"

CALENDAR_V1_GATE = (
    "Calendar coverage V1 is a tested requirement and read-only projection only. Automatic initial Cash "
    "DSRA funding under V1 needs a new versioned fixed-point contract (reserve requirement -> Project "
    "Uses -> gearing capacity -> Senior sizing -> final Senior debt service -> V1 requirement) and an "
    "engine hook that builds the V1 schedule; neither exists, so V1 cannot be activated. The historical "
    "SHORTCUT_V0 fixed point owned by the H-1 generic financing policy is unchanged."
)

# Editor modes that are recognised but deliberately not executable in this release.
GATED_EDITOR_MODES = {
    "automatic_forward": "FORWARD",
    "automatic_peak_forward_calendar": "PEAK_FORWARD",
    "automatic_forward_calendar": "FORWARD",
}


class ReserveAuthorityError(ValueError):
    """Typed fail-closed refusal. ``code`` is stable and machine-readable."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ReserveSelection:
    kind: ReservePolicyKind
    version: ReservePolicyVersion
    activation: ReserveActivation
    instrument: str                      # "NONE" | "CASH_DSRA" | "DSRF"
    coverage_months: Optional[int]
    initial_funding_keur: Optional[float]  # explicit scalar funding; None when derived by H-1 or not applicable
    reason_code: Optional[str] = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value, "version": self.version.value, "activation": self.activation.value,
            "instrument": self.instrument, "coverage_months": self.coverage_months,
            "initial_funding_keur": self.initial_funding_keur, "reason_code": self.reason_code,
            "detail": self.detail,
        }


def classify_financing(financing, capex=None) -> ReserveSelection:
    """Classify the reserve policy a ``FinancingParams`` (and optional ``CapexStructure``) carries."""
    mode = financing.dsra_support_mode
    raw_policy = getattr(financing, "dsra_target_policy", None)
    months = getattr(financing, "dsra_months", None)
    requirement = float(getattr(financing, "debt_service_reserve_requirement_keur", 0.0) or 0.0)
    legacy = float(getattr(capex, "reserve_accounts_keur", 0.0) or 0.0) if capex is not None else 0.0
    valid = {p.value: p for p in DsraTargetPolicy}
    if raw_policy is not None and raw_policy not in valid:
        raise ReserveAuthorityError(CODE_UNRECOGNISED, f"dsra_target_policy={raw_policy!r} is not a DsraTargetPolicy value.")

    if mode == DebtServiceReserveSupportMode.NONE:
        # The H-1 handshake signature: NONE + positive months + no policy + no funded scalar anywhere.
        if raw_policy is None and (months or 0) > 0 and requirement == 0.0 and legacy == 0.0:
            return ReserveSelection(
                ReservePolicyKind.PEAK_FORWARD, ReservePolicyVersion.SHORTCUT_V0,
                ReserveActivation.ACTIVE_VIA_GENERIC_POLICY_H1, "CASH_DSRA", int(months), None,
                detail="Implicit automatic reserve: realised only by the H-1 generic financing policy; "
                       "a run under a disabled policy carries no reserve.")
        return ReserveSelection(ReservePolicyKind.NONE, ReservePolicyVersion.NOT_APPLICABLE,
                                ReserveActivation.NOT_APPLICABLE, "NONE", None, 0.0)
    if mode == DebtServiceReserveSupportMode.DSRF:
        return ReserveSelection(ReservePolicyKind.NONE, ReservePolicyVersion.NOT_APPLICABLE,
                                ReserveActivation.NOT_APPLICABLE, "DSRF", None, 0.0,
                                detail="DSRF is a facility, not a Cash DSRA policy; out of scope for FIN-V2-R1.")
    # CASH_DSRA
    funding = requirement if requirement > 0.0 else legacy
    if raw_policy in (None, DsraTargetPolicy.FIXED_AMOUNT.value):
        return ReserveSelection(ReservePolicyKind.FIXED_AMOUNT, ReservePolicyVersion.STATIC_V0,
                                ReserveActivation.ACTIVE_STATIC, "CASH_DSRA", None, funding)
    kind = (ReservePolicyKind.FORWARD if raw_policy == DsraTargetPolicy.FORWARD_DEBT_SERVICE_MONTHS.value
            else ReservePolicyKind.PEAK_FORWARD)
    return ReserveSelection(kind, ReservePolicyVersion.SHORTCUT_V0, ReserveActivation.ACTIVE_EXPLICIT_POLICY,
                            "CASH_DSRA", int(months or 0), funding)


def selection_from_editor(reserve: dict) -> ReserveSelection:
    """The selection a Bankability editor ``reserve`` block REQUESTS (before any input is mutated)."""
    mode = reserve["mode"]
    if mode in GATED_EDITOR_MODES:
        raise ReserveAuthorityError(
            CODE_CALENDAR_FUNDING_GATED if "calendar" in mode else CODE_GATED_MODE,
            f"reserve mode {mode!r} is not executable: {CALENDAR_V1_GATE}")
    if mode == "none":
        return ReserveSelection(ReservePolicyKind.NONE, ReservePolicyVersion.NOT_APPLICABLE,
                                ReserveActivation.NOT_APPLICABLE, "NONE", None, 0.0)
    if mode == "automatic_peak":
        return ReserveSelection(ReservePolicyKind.PEAK_FORWARD, ReservePolicyVersion.SHORTCUT_V0,
                                ReserveActivation.ACTIVE_VIA_GENERIC_POLICY_H1, "CASH_DSRA",
                                int(reserve["months"]), None)
    if mode == "cash_fixed":
        return ReserveSelection(ReservePolicyKind.FIXED_AMOUNT, ReservePolicyVersion.STATIC_V0,
                                ReserveActivation.ACTIVE_STATIC, "CASH_DSRA", None, float(reserve["requirement_keur"]))
    if mode == "dsrf":
        return ReserveSelection(ReservePolicyKind.NONE, ReservePolicyVersion.NOT_APPLICABLE,
                                ReserveActivation.NOT_APPLICABLE, "DSRF", None, 0.0)
    raise ReserveAuthorityError(CODE_UNRECOGNISED, f"reserve mode {mode!r} is not supported.")


def assert_selection_realised(requested: ReserveSelection, effective_financing, effective_capex=None) -> ReserveSelection:
    """Refuse a selection whose resulting inputs do not carry the same policy kind, instrument and months.

    This is the guard against an automatic selection that silently collapses to NONE (or a static
    FIXED_AMOUNT). Returns the classification of the effective inputs when they match.
    """
    actual = classify_financing(effective_financing, effective_capex)
    same = (actual.kind == requested.kind and actual.instrument == requested.instrument
            and actual.coverage_months == requested.coverage_months)
    if not same:
        code = CODE_AUTOMATIC_NOT_REALISED if requested.activation is ReserveActivation.ACTIVE_VIA_GENERIC_POLICY_H1 else CODE_MISMATCH
        raise ReserveAuthorityError(
            code, f"selected {requested.kind.value}/{requested.instrument}/months={requested.coverage_months} "
                  f"but the resulting inputs carry {actual.kind.value}/{actual.instrument}/months={actual.coverage_months}.")
    return actual
