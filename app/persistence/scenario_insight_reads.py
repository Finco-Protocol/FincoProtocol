"""Read-only, bounded scenario reads for FINCO Insight (Q3 scenario intelligence).

Two narrowly scoped queries; nothing here writes, orders other features' lists, or loads unbounded history:

* ``list_insight_scenarios`` — the scenarios to DISPLAY for one owner + project.  Deterministic, documented
  ordering: (1) the ACTIVE scenario, (2) the Base Case, (3) the remaining scenarios by most recent
  ``updated_at`` then ``scenario_id``.  The active scenario and the Base Case are therefore always inside
  the display window, whatever the global ``updated_at`` ordering of ``list_scenarios`` is.  The total number
  of candidates is returned so omitted scenarios are disclosed, never silently dropped.
* ``newest_committed_runs`` — the newest immutable committed Run per displayed scenario, using the same
  canonical rule as the scenario workspace (``ran_at DESC, history_id DESC``; a pre-scenario Run with no
  scenario id belongs to the Base Case).  One bounded ``LIMIT 1`` lookup per scenario; only the winning
  history row is decoded.  Result per scenario is the entry, ``None`` (the query succeeded and PROVED there is
  no committed Run) or ``HISTORY_UNAVAILABLE`` (retrieval or decoding failed: absence is NOT established, and
  an older row is never substituted for a malformed newest one).

Owner and project isolation is part of every WHERE clause.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

HISTORY_UNAVAILABLE = "HISTORY_UNAVAILABLE"
INSIGHT_SCENARIO_LIMIT = 8
BASE_CASE_LABEL = "Base Case"


@dataclass(frozen=True)
class InsightScenarioSet:
    records: tuple[Any, ...]
    candidates: int            # scenarios eligible for display (before the window)
    complete: bool             # False when the read itself failed

    @property
    def omitted(self) -> int:
        return max(0, self.candidates - len(self.records))


def list_insight_scenarios(user_id: str, project_id: str, active_scenario_id: Optional[str],
                           limit: int = INSIGHT_SCENARIO_LIMIT) -> InsightScenarioSet:
    from app.persistence.db import get_cursor
    from app.persistence.records import ScenarioRecord

    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 2:
        raise ValueError("INSIGHT_SCENARIO_LIMIT_INVALID")
    where = "user_id=? AND project_id=? AND (archived=0 OR scenario_id=?)"
    base = (user_id, project_id, active_scenario_id)
    try:
        with get_cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM scenarios WHERE {where}", base)
            candidates = int(cur.fetchone()[0])
            cur.execute(
                f"SELECT * FROM scenarios WHERE {where} "
                "ORDER BY (scenario_id=?) DESC, is_base_case DESC, updated_at DESC, scenario_id ASC LIMIT ?",
                base + (active_scenario_id, limit))
            records = tuple(ScenarioRecord.from_row(row) for row in cur.fetchall())
    except Exception:  # noqa: BLE001 - a failed read is reported, never turned into an empty list
        return InsightScenarioSet(records=(), candidates=0, complete=False)
    return InsightScenarioSet(records=records, candidates=candidates, complete=True)


@dataclass(frozen=True)
class LastRunScenario:
    """The scenario a COMMITTED Last Run belongs to (never the currently selected Working Copy scenario)."""

    scenario_id: Optional[str]
    label: Optional[str]        # display label; None = the scenario could not be proven
    is_base_case: bool
    proven: bool


def resolve_last_run_scenario(user_id: str, project_id: str,
                              last_runtime_scenario_id: Optional[str]) -> LastRunScenario:
    """Resolve the scenario identity of the committed Last Run from ``last_runtime_scenario_id``.

    * ``None`` is the canonical Base Case relationship (a Run committed before any scenario row existed records
      no scenario id).  The label is ``Base Case`` and, when the project's Base Case record is readable, its name
      is appended so the two identities stay visible (``Base Case (<record name>)``).
    * An explicit id is resolved ONLY through this owner's and project's own scenario records (an archived
      scenario is still the scenario that produced the Run).  A Base Case record keeps the ``Base Case`` label.
    * An id that cannot be resolved is NOT proven: ``label`` is ``None`` (shown as UNAVAILABLE).  It is never
      replaced by the Base Case, by the active Working Copy scenario, or by an invented name.
    """
    from app.persistence.db import get_cursor

    try:
        with get_cursor() as cur:
            if last_runtime_scenario_id is None:
                cur.execute("SELECT scenario_name FROM scenarios WHERE user_id=? AND project_id=? AND is_base_case=1 "
                            "ORDER BY archived ASC, updated_at DESC LIMIT 1", (user_id, project_id))
                row = cur.fetchone()
                record_name = str(row[0]).strip() if row and row[0] else ""
                label = f"{BASE_CASE_LABEL} ({record_name})" if record_name and record_name != BASE_CASE_LABEL \
                    else BASE_CASE_LABEL
                return LastRunScenario(None, label, True, True)
            cur.execute("SELECT scenario_name, is_base_case FROM scenarios WHERE user_id=? AND project_id=? "
                        "AND scenario_id=? LIMIT 1", (user_id, project_id, last_runtime_scenario_id))
            row = cur.fetchone()
    except Exception:  # noqa: BLE001 - an unreadable record is not a proof
        return LastRunScenario(last_runtime_scenario_id, None, False, False)
    if row is None or not str(row[0] or "").strip():
        return LastRunScenario(last_runtime_scenario_id, None, False, False)
    is_base = bool(row[1])
    name = str(row[0]).strip()
    label = (f"{BASE_CASE_LABEL} ({name})" if name != BASE_CASE_LABEL else BASE_CASE_LABEL) if is_base else name
    return LastRunScenario(last_runtime_scenario_id, label, is_base, True)


def newest_committed_runs(user_id: str, project_id: str, scenarios: Sequence[Any]) -> dict[str, Any]:
    from app.persistence.db import get_cursor
    from app.persistence.run_history_repository import get_run_history_entry

    out: dict[str, Any] = {}
    for sc in scenarios:
        sid = sc.scenario_id
        scope = ("(last_runtime_scenario_id=? OR last_runtime_scenario_id IS NULL)"
                 if getattr(sc, "is_base_case", False) else "last_runtime_scenario_id=?")
        try:
            with get_cursor() as cur:
                cur.execute(
                    "SELECT history_id FROM model_run_history WHERE user_id=? AND project_id=? "
                    f"AND {scope} ORDER BY ran_at DESC, history_id DESC LIMIT 1",
                    (user_id, project_id, sid))
                row = cur.fetchone()
            if row is None:
                out[sid] = None                      # proven: the lookup succeeded and found nothing
                continue
            entry = get_run_history_entry(user_id, project_id, row[0])
            out[sid] = entry if entry is not None else HISTORY_UNAVAILABLE
        except Exception:  # noqa: BLE001 - malformed newest row / read failure: absence is NOT established
            out[sid] = HISTORY_UNAVAILABLE
    return out


__all__ = ["BASE_CASE_LABEL", "HISTORY_UNAVAILABLE", "INSIGHT_SCENARIO_LIMIT", "InsightScenarioSet",
           "LastRunScenario", "list_insight_scenarios", "newest_committed_runs", "resolve_last_run_scenario"]
