"""Request-local, owner-scoped SQLite snapshot; canonical decoders/identity only."""
from dataclasses import replace

from app.v2.portfolio_projection import ProjectEvidence


class PortfolioReadError(RuntimeError):
    pass


def _projects(connection, user_id):
    from app.persistence.records import ProjectRecord
    return {row["project_id"]: ProjectRecord.from_row(row) for row in connection.execute(
        "SELECT * FROM projects WHERE user_id=? AND archived=0 ORDER BY project_id", (user_id,))}


def _version(connection):
    return connection.execute("PRAGMA data_version").fetchone()[0]


def _capture(connection, user_id):
    from app.persistence.records import WorkspaceStateRecord
    from app.persistence.run_history_repository import _decode_entry, RunHistoryError
    from app.workbook.registry import WORKBOOK
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.workbook_identity import assemble_transactional

    connection.execute("BEGIN DEFERRED")
    try:
        records = _projects(connection, user_id)
        entries, errors, history_ids = {}, {}, {}
        # Same ordering and fail-closed decoder as get_latest_history_entry;
        # partition only after BOTH project and history ownership are proved.
        for raw in connection.execute("""
            SELECT * FROM (
                SELECT h.*, ROW_NUMBER() OVER (
                    PARTITION BY h.project_id ORDER BY h.ran_at DESC, h.history_id DESC
                ) AS portfolio_rank
                FROM model_run_history h JOIN projects p ON p.project_id=h.project_id
                WHERE h.user_id=? AND p.user_id=? AND p.archived=0
            ) WHERE portfolio_rank=1
        """, (user_id, user_id)):
            history_ids[raw["project_id"]] = raw["history_id"]
            try:
                entries[raw["project_id"]] = _decode_entry(raw)
            except RunHistoryError:
                errors[raw["project_id"]] = "Run History unreadable; no older Run substituted"
        result, proofs = {}, {}
        for project_id, record in records.items():
            entry, state, issue = entries.get(project_id), "UNKNOWN", errors.get(project_id, "")
            raw = connection.execute(
                "SELECT * FROM workspace_states WHERE user_id=? AND project_id=?", (user_id, project_id)).fetchone()
            current_hash = None
            try:
                ws = WorkspaceStateRecord.from_row(raw) if raw is not None else None
                if entry is None:
                    state = "UNKNOWN" if issue else "NOT_RUN"
                    if ws and ws.last_runtime_snapshot_id and not issue:
                        issue = "Last Run has no immutable history evidence"
                elif ws and ws.last_runtime_snapshot_id == entry.runtime_snapshot_id:
                    if ws.active_scenario_id and not connection.execute(
                        "SELECT 1 FROM scenarios WHERE scenario_id=? AND user_id=? AND project_id=? AND archived=0",
                            (ws.active_scenario_id, user_id, project_id)).fetchone():
                        raise ValueError("Scenario does not belong to this project")
                    identity = assemble_transactional(
                        draft_snapshot_json=raw["draft_snapshot_json"], project_id=project_id, user_id=user_id,
                        active_scenario_id=ws.active_scenario_id, active_scenario_name=ws.active_scenario_name,
                        cursor=connection.cursor(), workbook_version=WORKBOOK.version)
                    current_hash = identity.composite_hash
                    state = resolve_runtime_freshness(ws, current_composite_hash=current_hash).state.value
                else:
                    state = "HISTORICAL"
            except Exception:
                state = "UNKNOWN"
                issue = issue or "Evidence or input freshness could not be verified"
            result[project_id] = ProjectEvidence(record, entry, state, issue)
            # Not a financial identity: only a comparison of captured raw state.
            fields = ("workspace_id", "user_id", "project_id", "project_code", "active_scenario_id",
                      "active_scenario_name", "draft_snapshot_json", "saved_snapshot_json", "dirty", "updated_at",
                      "last_runtime_snapshot_id", "last_runtime_scenario_id", "last_runtime_composite_hash",
                      "last_runtime_identity_json", "any_run_committed")
            proofs[project_id] = (history_ids.get(project_id), current_hash,
                                 tuple(raw[key] for key in fields) if raw is not None else None)
        connection.execute("COMMIT")
        return result, proofs
    except Exception:
        connection.rollback()
        raise


def load_portfolio(user_id):
    from app.persistence.db import get_connection
    try:
        connection = get_connection()
    except Exception as error:
        raise PortfolioReadError("Portfolio evidence temporarily unavailable; refresh required") from error
    try:
        connection.execute("PRAGMA query_only=ON")
        before = _version(connection)
        result, proofs = _capture(connection, user_id)
        after = _version(connection)
        changed, unsettled = set(), False
        if after != before:
            # A bounded second snapshot is needed ONLY when some writer committed.
            # Unrelated tenant activity can still be proved irrelevant; no cache.
            _, second = _capture(connection, user_id)
            changed = {key for key in proofs if proofs[key] != second.get(key)}
            final = _version(connection)
            unsettled = final != after or proofs.keys() != second.keys()
            after = final
        current = _projects(connection, user_id)  # fresh authorization/archival check
        unsettled = unsettled or _version(connection) != after
        if not result and current:
            raise PortfolioReadError("Portfolio changed during review")
        return [replace(item, record=current[key],
                        freshness="UNKNOWN" if unsettled or key in changed else item.freshness,
                        issue="Portfolio changed during review; refresh required" if unsettled or key in changed else item.issue)
                for key, item in result.items() if key in current]
    except Exception as error:
        raise PortfolioReadError("Portfolio evidence temporarily unavailable; refresh required") from error
    finally:
        connection.close()
