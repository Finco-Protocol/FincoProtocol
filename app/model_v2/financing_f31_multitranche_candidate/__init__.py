"""F3.1 multi-tranche candidate — NOT runtime-activated, non-authoritative.

Candidate-only pre-integration slice (WF-05A): typed N-tranche validation,
N-tranche facility schedules and multi-instrument source/use reconciliation
for 3+ pari-passu senior tranches, extending the released two-Senior F3.2-4
authority (`F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1`) toward institutional
multi-tranche structures.

This package is deliberately NON_AUTHORITATIVE:

  - it is never imported by production code (AST-pinned by its test);
  - it has no route, no persistence surface and no activation path;
  - its authority string is distinct from the released two-Senior authority;
  - its schedule math is proven equal to the released engine at N=2 by a
    property test, so the future Gate-R integration can swap it in without
    changing released two-Senior results.

It imports ONLY the canonical F3.1 proposal schema plus the standard
library. All financial behaviour remains OFF and unavailable to product
users until explicit Financial Owner policy decisions, independent final
review and later product acceptance.
"""
from app.model_v2.financing_f31_multitranche_candidate.reconciliation import (
    MultitrancheReconciliation,
    reconcile_multitranche_sources_uses,
)
from app.model_v2.financing_f31_multitranche_candidate.schedules import (
    CandidateFacilitySchedule,
    CandidatePeriod,
    build_candidate_aggregate,
    build_candidate_facility_schedules,
)
from app.model_v2.financing_f31_multitranche_candidate.validation import (
    F31_MULTITRANCHE_CANDIDATE_AUTHORITY,
    validate_multitranche_collection,
)

NON_AUTHORITATIVE = True

__all__ = [
    "NON_AUTHORITATIVE",
    "F31_MULTITRANCHE_CANDIDATE_AUTHORITY",
    "CandidateFacilitySchedule",
    "CandidatePeriod",
    "MultitrancheReconciliation",
    "build_candidate_aggregate",
    "build_candidate_facility_schedules",
    "reconcile_multitranche_sources_uses",
    "validate_multitranche_collection",
]
