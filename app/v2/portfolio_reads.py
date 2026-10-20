"""Authorized repository reads only; never seed projects or execute a model."""
from app.v2.portfolio_projection import ProjectEvidence


def load_portfolio(user_id):
    from app.persistence.projects_repository import list_projects, get_project
    from app.persistence.run_history_repository import get_latest_history_entry, RunHistoryError
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.registry import WORKBOOK
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.workbook_identity import assemble_consistent_for_get

    result = []
    for record in list_projects(user_id):
        if record.user_id != user_id or record.archived:
            continue
        entry, state, issue = None, "UNKNOWN", ""
        try:
            entry = get_latest_history_entry(user_id, record.project_id)
            ws = get_workspace_state(user_id, record.project_id)
            if entry is None:
                state = "NOT_RUN"
                if ws and ws.last_runtime_snapshot_id:
                    issue = "Last Run has no immutable history evidence"
            elif ws and ws.last_runtime_snapshot_id == entry.runtime_snapshot_id:
                identity = assemble_consistent_for_get(user_id, record.project_id, WORKBOOK.version)
                state = resolve_runtime_freshness(ws, current_composite_hash=identity.composite_hash).state.value
                # Another request may switch scenarios or save while assembling.
                # Retain immutable figures but never assert currentness from mixed reads.
                if (ws != get_workspace_state(user_id, record.project_id)
                        or identity.composite_hash != assemble_consistent_for_get(
                            user_id, record.project_id, WORKBOOK.version).composite_hash):
                    state, issue = "UNKNOWN", "Project changed during review; refresh required"
            else:
                state = "HISTORICAL"
            latest = get_latest_history_entry(user_id, record.project_id)
            if (getattr(entry, "history_id", None) != getattr(latest, "history_id", None)):
                state, issue = "UNKNOWN", "A new Run was committed during review; refresh required"
        except RunHistoryError:
            entry, issue = None, "Run History unreadable; no older Run substituted"
        except Exception:
            state, issue = "UNKNOWN", "Evidence or input freshness could not be verified"
        # Recheck ownership/archival, not just the initial project-list snapshot.
        current = get_project(record.project_id, user_id)
        if current is not None and not current.archived and current.user_id == user_id:
            result.append(ProjectEvidence(current, entry, state, issue))
    return result
