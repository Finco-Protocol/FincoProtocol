"""Exact M6 economic parity: validate individual binding THEN remove identity only."""
from __future__ import annotations
from copy import deepcopy

from app.model_v2.acquisition.evidence import KEY, validate

def independent_economic_view(summary, *, owner_id, project_id, snapshot_id,
                              composite_hash, scenario_id):
    if KEY not in summary:
        raise AssertionError("M6 canonical source evidence absent")
    original = summary[KEY]
    validated = validate(original, owner_id=owner_id, project_id=project_id,
                         snapshot_id=snapshot_id, composite_hash=composite_hash,
                         scenario_id=scenario_id)
    economic = deepcopy(summary)
    # Only two M6 *provenance* fields are excluded from parity comparison.
    # All full-precision dates, receipts, contributions, SHL and C1 rows remain.
    economic[KEY] = {k: deepcopy(v) for k, v in validated.items()
                     if k not in ("binding", "digest")}
    return economic
