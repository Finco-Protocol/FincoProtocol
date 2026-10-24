"""Augmentation commercial policy inputs (WF-08A, release-closed).

Typed commercial inputs only: an SOH-based threshold, a planned event, a warranty trigger and a replacement
CAPEX PROPOSAL. Funding, residual-value, construction-vs-operating CAPEX classification and the warranty
remedy are OPEN Financial Owner decisions. The native post-COD augmentation financial posting stays
release-closed (``financial_engine/bess.py`` raises ``BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED``); this module
cannot turn it on and invents no depreciation, financing, tax or cash-flow value. Trigger detection only READS
the native hourly state of health; it never recalculates degradation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from app.bess_commercial_candidate.contracts import (
    exact_arithmetic,
    CANDIDATE, UNAVAILABLE, AugmentationTrigger, BessCommercialError, Decision, dec, enum_member, ident,
    open_decision, opt_dec, opt_ident, reconciles, require_release, tuple_of, utc_hour,
)

POSTING = "RELEASE_CLOSED"


@dataclass(frozen=True)
class AugmentationCommercialPolicy:
    policy_id: str
    trigger: AugmentationTrigger
    soh_threshold: Optional[Decimal] = None
    planned_at: Optional[datetime] = None
    warranty_ref: Optional[str] = None
    warranty_soh_floor: Optional[Decimal] = None
    replacement_capex_proposal_keur: Optional[Decimal] = None   # None = MISSING proposal
    proposal_ref: Optional[str] = None
    funding_treatment: Decision = Decision.OPEN
    residual_value_treatment: Decision = Decision.OPEN
    capex_classification: Decision = Decision.OPEN             # construction vs operating CAPEX
    warranty_remedy: Decision = Decision.OPEN
    financial_posting: str = POSTING

    def __post_init__(self):
        ident(self.policy_id, "policy_id")
        enum_member(self.trigger, AugmentationTrigger, "augmentation trigger")
        opt_dec(self.soh_threshold, "soh_threshold", positive=True, maximum=Decimal(1))
        opt_dec(self.warranty_soh_floor, "warranty_soh_floor", positive=True, maximum=Decimal(1))
        opt_dec(self.replacement_capex_proposal_keur, "replacement_capex_proposal_keur", nonnegative=True)
        opt_ident(self.warranty_ref, "warranty_ref")
        opt_ident(self.proposal_ref, "proposal_ref")
        if self.planned_at is not None:
            utc_hour(self.planned_at, "planned_at")
        needed = {AugmentationTrigger.SOH_THRESHOLD: {"soh_threshold": self.soh_threshold},
                  AugmentationTrigger.PLANNED_EVENT: {"planned_at": self.planned_at},
                  AugmentationTrigger.WARRANTY_TRIGGERED: {"warranty_ref": self.warranty_ref,
                                                           "warranty_soh_floor": self.warranty_soh_floor}}
        every = {"soh_threshold": self.soh_threshold, "planned_at": self.planned_at,
                 "warranty_ref": self.warranty_ref, "warranty_soh_floor": self.warranty_soh_floor}
        for name, value in every.items():
            if name in needed[self.trigger] and value is None:
                raise BessCommercialError(f"BESS_COMMERCIAL_SCHEMA: {self.trigger.value} requires {name}")
            if name not in needed[self.trigger] and value is not None:
                raise BessCommercialError(f"BESS_COMMERCIAL_SCHEMA: {self.trigger.value} must not carry {name}")
        if (self.replacement_capex_proposal_keur is None) != (self.proposal_ref is None):
            raise BessCommercialError(
                "BESS_COMMERCIAL_SCHEMA: a replacement CAPEX proposal and its proposal_ref come together")
        for name in ("funding_treatment", "residual_value_treatment", "capex_classification", "warranty_remedy"):
            open_decision(getattr(self, name), name)
        if self.financial_posting != POSTING:
            raise BessCommercialError(
                "BESS_COMMERCIAL_AUGMENTATION_POSTING_RELEASE_CLOSED: financial posting cannot be enabled here")


@dataclass(frozen=True)
class TriggerEvidence:
    status: str
    reason: str
    policy_id: str
    trigger: AugmentationTrigger
    triggered: Optional[bool]
    at: Optional[datetime]
    observed_soh: Optional[Decimal]
    minimum_observed_soh: Optional[Decimal]
    proposal_status: str
    replacement_capex_proposal_keur: Optional[Decimal]


def _proposal(policy):
    return (CANDIDATE if policy.replacement_capex_proposal_keur is not None else UNAVAILABLE,
            policy.replacement_capex_proposal_keur)


@exact_arithmetic
def evaluate_trigger(policy: AugmentationCommercialPolicy, native_hours, minimum_soh: Decimal) -> TriggerEvidence:
    """Read native hourly state of health against the declared trigger. No degradation is recomputed.

    A threshold at or below the native hard minimum SoH can never be reached (the native engine fails
    first), so it is rejected rather than silently never triggering.
    """
    require_release()
    hours = tuple_of(native_hours, "native_hours")
    if not hours:
        raise BessCommercialError("BESS_COMMERCIAL_ALLOCATION: native hourly evidence required")
    floor = dec(minimum_soh, "minimum_soh", positive=True, maximum=Decimal(1))
    proposal_status, proposal = _proposal(policy)
    lowest = min(h.soh_closing for h in hours)
    base = (policy.policy_id, policy.trigger)
    if policy.trigger is AugmentationTrigger.PLANNED_EVENT:
        first, last = hours[0].start, hours[-1].end
        if not first <= policy.planned_at < last:
            return TriggerEvidence(UNAVAILABLE, "planned event lies outside the native evidence horizon", *base,
                                   None, None, None, lowest, proposal_status, proposal)
        return TriggerEvidence(CANDIDATE, "planned event inside the native horizon", *base, True,
                               policy.planned_at, None, lowest, proposal_status, proposal)
    level = policy.soh_threshold if policy.trigger is AugmentationTrigger.SOH_THRESHOLD else policy.warranty_soh_floor
    if level <= floor:
        raise BessCommercialError(
            "BESS_COMMERCIAL_AUGMENTATION: the SoH level is at or below the native minimum SoH, so the native "
            "engine would fail before it could be reached")
    for hour in hours:
        if hour.soh_closing <= level:
            reason = ("SoH threshold reached" if policy.trigger is AugmentationTrigger.SOH_THRESHOLD
                      else "warranty SoH floor reached; remedy is an OPEN Financial Owner decision")
            return TriggerEvidence(CANDIDATE, reason, *base, True, hour.end, hour.soh_closing, lowest,
                                   proposal_status, proposal)
    return TriggerEvidence(CANDIDATE, "level not reached in the native evidence", *base, False, None, None,
                           lowest, proposal_status, proposal)


@dataclass(frozen=True)
class EventAlignment:
    aligned: bool
    mismatches: tuple


@exact_arithmetic
def native_event_alignment(policy: AugmentationCommercialPolicy, native_events) -> EventAlignment:
    """Compare a PLANNED_EVENT policy with the native configuration events (read-only)."""
    require_release()
    if policy.trigger is not AugmentationTrigger.PLANNED_EVENT:
        raise BessCommercialError("BESS_COMMERCIAL_AUGMENTATION: only a PLANNED_EVENT aligns with a native event")
    matches = [e for e in tuple_of(native_events, "native_events") if e.at == policy.planned_at]
    if not matches:
        return EventAlignment(False, ("no native event at the planned time",))
    event = matches[0]
    problems = []
    if policy.replacement_capex_proposal_keur is None:
        problems.append("replacement CAPEX proposal missing")
    elif not reconciles(policy.replacement_capex_proposal_keur, event.cost_keur):
        problems.append("proposal differs from the native event cost")
    return EventAlignment(not problems, tuple(problems))


def augmentation_financial_posting(*_args, **_kwargs):
    """Unconditionally closed: the candidate never posts augmentation to any cash flow."""
    raise BessCommercialError(
        "BESS_COMMERCIAL_AUGMENTATION_POSTING_RELEASE_CLOSED: no depreciation, financing, tax or cash-flow "
        "posting is available; native BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED stays in force")
