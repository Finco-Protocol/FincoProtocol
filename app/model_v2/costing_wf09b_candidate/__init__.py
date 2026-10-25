"""WF-09B canonical cost receipts & LCOE/LCOS reconciliation — RELEASE-CLOSED CANDIDATE.

Read-only layer that atomises explicitly supplied, canonical-shaped evidence
(Run identity, period axis, cost lines, delivered energy, discount factors) into
the already implemented WF-09A arithmetic and reconciles the result. It adds no
formula, route, Run output, persistence, flag or UI and is imported by nothing.
See ``docs/model_v2/WF09B_COST_RECEIPT_DESIGN.md`` and
``docs/model_v2/WF09B_FINANCIAL_OWNER_DECISIONS.md``. Canonical analytics keeps
reporting LCOE as AUTHORITY_MISSING.
"""
from app.model_v2.costing_wf09b_candidate.contracts import (  # noqa: F401
    ACTIVATION_ENABLED, CANDIDATE, NON_AUTHORITATIVE, REFERENCE_PARITY, UNAVAILABLE,
    WF09B_CANDIDATE_AUTHORITY, AugmentationEvidence, ChargingEvidence, Component, Decision,
    EnergyBoundary, Freshness, LineKind, Metric, Phase, PriceBasis, Treatment, Vertical,
    Wf09bError, canonical_json, identity,
)
from app.model_v2.costing_wf09b_candidate.receipts import (  # noqa: F401
    CostLine, CostReceipts, DiscountReceipt, EnergyLine, EnergyReceipts, PeriodAxis, PeriodSpec,
    RunIdRef, RunReceipt,
)
from app.model_v2.costing_wf09b_candidate.engine import (  # noqa: F401
    CostingRequest, CostingResult, Reconciliation, evaluate,
)
