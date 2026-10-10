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


__all__ = ["HISTORY_UNAVAILABLE", "INSIGHT_SCENARIO_LIMIT", "InsightScenarioSet", "list_insight_scenarios",
           "newest_committed_runs"]
