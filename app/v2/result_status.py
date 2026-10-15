"""ResultStatus - ONE read-only projection of "which committed Run am I looking at, and in what state".

It only arranges values that the existing authorities already produced (``resolve_runtime_freshness`` for CURRENT / STALE / NOT RUN, the
persisted workspace for the Run time and scenario, ``trust_pack.integrity`` for the integrity verdict). It performs no arithmetic, reads no
financial value and creates no new authority. Freshness and integrity are separate fields on purpose: a STALE model can still have a PASS
integrity verdict for its Last Run, and a CURRENT model can have a FAIL verdict.

Consumers: the persistent strip (``partials/_hybrid_status.html``) on page load and on every state-changing response, and the Trust sheet
refresh. The toolbar chip and the header are rendered from the same freshness authority and the same workspace read.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

_FRESHNESS_LABELS = {"CURRENT": "CURRENT", "STALE": "STALE", "NOT_RUN": "NOT RUN"}
_INTEGRITY_VERDICTS = frozenset({"PASS", "FAIL", "WARNING", "UNAVAILABLE"})


@dataclass(frozen=True)
class ResultStatus:
    freshness: str            # CURRENT | STALE | NOT_RUN
    freshness_label: str      # CURRENT | STALE | NOT RUN
    integrity: str            # PASS | FAIL | UNAVAILABLE (independent of freshness)
    scenario_name: str        # display name of the active scenario ("Base" when none)
    run_at_display: str       # time of the Last Run, "" when there is none
    has_run: bool


def unavailable_trust_pack(project_code: str) -> dict:
    """The explicit fail-closed Trust pack: every evidence section UNAVAILABLE. An evidence surface must never 500 or show a stale Run."""
    from app.api.v1_1.institutional import STATE_UNAVAILABLE as unavailable
    return {
        "overall_state": unavailable,
        "last_run": {"state": unavailable, "working_copy_changed_since_run": False},
        "kpis": {"state": unavailable, "rows": [], "lineage": {}},
        "validation": {"state": "DEFERRED", "load_url": f"/v2/workbook/trust/validation?project={project_code}",
                       "gaps": [], "gap_count": 0},
        "verify": {"state": unavailable, "verify_url": f"/verify/run/{project_code}"},
        "export": {"state": unavailable},
        "methodology": {"state": unavailable, "rows": [], "page_url": "/model/methodology"},
    }


def _integrity(trust_pack: Optional[Mapping[str, Any]]) -> str:
    block = (trust_pack or {}).get("integrity") if isinstance(trust_pack, Mapping) else None
    if not isinstance(block, Mapping) or str(block.get("state") or "").upper() != "AVAILABLE":
        return "UNAVAILABLE"
    overall = str(block.get("overall") or "").upper()
    return overall if overall in _INTEGRITY_VERDICTS else "UNAVAILABLE"


def build_result_status(*, runtime_state: str, has_runtime: bool, last_runtime_at_display: str,
                        active_scenario_name: Optional[str], trust_pack: Optional[Mapping[str, Any]]) -> ResultStatus:
    state = str(runtime_state or "").upper()
    label = _FRESHNESS_LABELS.get(state)
    if label is None:                       # an unknown state is never promoted to CURRENT
        state, label = "NOT_RUN", "NOT RUN"
    has_run = bool(has_runtime) and state != "NOT_RUN"
    return ResultStatus(
        freshness=state, freshness_label=label, integrity=_integrity(trust_pack),
        scenario_name=(active_scenario_name or "").strip() or "Base",
        run_at_display=(last_runtime_at_display or "") if has_run else "", has_run=has_run)


def with_current_scenario_label(ws, workspace_owner: str):
    """Return ``ws`` with ``active_scenario_name`` read from the scenario record (UX-020).

    The workspace row keeps a copied label that goes stale on rename; the scenario record is the authority.
    Read-only; any failure keeps the copied label.
    """
    import dataclasses

    sid = getattr(ws, "active_scenario_id", None)
    if not sid or not dataclasses.is_dataclass(ws):
        return ws
    try:
        from app.persistence.scenarios_repository import get_scenario

        sc = get_scenario(scenario_id=sid, user_id=workspace_owner)
    except Exception:
        return ws
    name = getattr(sc, "scenario_name", None) if sc is not None else None
    if not name or name == getattr(ws, "active_scenario_name", None):
        return ws
    return dataclasses.replace(ws, active_scenario_name=name)
