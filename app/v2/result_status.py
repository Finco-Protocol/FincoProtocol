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
    integrity_note: str = ""  # why the integrity verdict is UNAVAILABLE when the Last Run is not the active scenario's


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


def last_run_matches_active_scenario(ws: Any, owner: str) -> Optional[bool]:
    """True when the committed Last Run belongs to the ACTIVE scenario, False when it belongs to another one, None when unproven.

    The workspace keeps one Last Run.  After a scenario switch it can still be another scenario's Run; its Integrity verdict must
    not be shown as the active scenario's.  Base Case is the scenario with ``scenario_id`` None (pre-scenario Runs) or a Base record.
    Read-only; any unreadable scenario record is "unproven", never "matches".
    """
    if not getattr(ws, "last_runtime_snapshot_id", None):
        return None
    active, last = getattr(ws, "active_scenario_id", None), getattr(ws, "last_runtime_scenario_id", None)
    if active == last:
        return True
    try:
        from app.persistence.scenarios_repository import get_scenario

        def is_base(scenario_id):
            if scenario_id is None:
                return True
            rec = get_scenario(scenario_id=scenario_id, user_id=owner)
            return None if rec is None else bool(rec.is_base_case)

        a, b = is_base(active), is_base(last)
    except Exception:  # noqa: BLE001
        return None
    if a is None or b is None:
        return None
    return bool(a and b)


_NO_SCENARIO_RUN_NOTE = ("This scenario has no committed Run of its own; the project's other Run integrity verdict is not shown here."
                         " Run the scenario to establish its integrity evidence.")
_UNPROVEN_NOTE = "Which scenario the Last Run belongs to could not be proven, so its integrity verdict is not shown here."
_OTHER_SCENARIO_NOTE = "The Last Run belongs to a different scenario; this scenario has no committed Run of its own."


def scope_trust_pack_to_active_scenario(pack: Optional[Mapping[str, Any]], ws: Any, owner: str) -> Optional[Mapping[str, Any]]:
    """Return the pack with its Run Integrity section withheld when the Last Run is not proven to be the ACTIVE scenario's.

    The Trust pack reads the project's latest committed Run; after a scenario switch that Run may belong to another scenario (or
    the active one has none).  Presenting its PASS under the active scenario would be a false integrity claim.  Pure projection:
    the committed evidence and every other section are untouched.
    """
    if not isinstance(pack, Mapping) or not isinstance(pack.get("integrity"), Mapping):
        return pack
    if last_run_matches_active_scenario(ws, owner) is True:
        return pack
    if str(pack["integrity"].get("state") or "").upper() != "AVAILABLE":
        return pack
    from app.api.v1_1.institutional import STATE_UNAVAILABLE as unavailable
    scoped = dict(pack)
    scoped["integrity"] = {
        "state": unavailable, "overall": None, "counts": {}, "checks": [], "authority": "RUN_INTEGRITY_CHECKS",
        "scope": "Not available for the active scenario: it has no committed Run of its own.", "reason": "NO_ACTIVE_SCENARIO_RUN"}
    return scoped


def build_result_status(*, runtime_state: str, has_runtime: bool, last_runtime_at_display: str,
                        active_scenario_name: Optional[str], trust_pack: Optional[Mapping[str, Any]],
                        last_run_matches_scenario: Optional[bool] = True) -> ResultStatus:
    """``last_run_matches_scenario`` False/None => the integrity verdict belongs to a Run the active scenario did not produce."""
    state = str(runtime_state or "").upper()
    label = _FRESHNESS_LABELS.get(state)
    if label is None:                       # an unknown state is never promoted to CURRENT
        state, label = "NOT_RUN", "NOT RUN"
    has_run = bool(has_runtime) and state != "NOT_RUN"
    integrity, note = _integrity(trust_pack), ""
    block = (trust_pack or {}).get("integrity") if isinstance(trust_pack, Mapping) else None
    withheld = isinstance(block, Mapping) and block.get("reason") == "NO_ACTIVE_SCENARIO_RUN"
    if (integrity != "UNAVAILABLE" or withheld) and last_run_matches_scenario is not True:
        integrity = "UNAVAILABLE"
        note = (_UNPROVEN_NOTE if last_run_matches_scenario is None and has_runtime else
                _OTHER_SCENARIO_NOTE if has_runtime else _NO_SCENARIO_RUN_NOTE)
    return ResultStatus(
        freshness=state, freshness_label=label, integrity=integrity,
        scenario_name=(active_scenario_name or "").strip() or "Base",
        run_at_display=(last_runtime_at_display or "") if has_run else "", has_run=has_run, integrity_note=note)


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
