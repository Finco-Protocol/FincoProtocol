"""
Workbook V2 — WorkbookService: pure domain service layer.

Architecture position:

  WorkspaceStateRecord  (persistence)
          │
          ▼
  WorkbookService                       ← this module
          │
          ├── build_input_set()  ──▶ ProjectInputSet  (PR 2)
          │       └── to_projectinputs()  ──▶ ProjectInputs (existing engine)
          │
          ├── build_draft_input_set_from_workspace()   ──▶ ProjectInputSet
          ├── build_saved_input_set_from_workspace()   ──▶ ProjectInputSet
          │
          ├── get_runtime_result() ──▶ RuntimeResult  (PR 3)
          │       └── to_sessionstorage_script() ──▶ <script>…</script>
          │
          └── runtime_hydration_script()  (convenience wrapper)

Design invariants:
- All methods are pure functions (no DB calls, no HTTP, no I/O, no side effects).
- WorkbookService never imports from app.persistence directly.
- It delegates to ProjectInputSet and RuntimeResult; it does not duplicate logic.
- template_source is NEVER derived from project_code or any other identity field.
  It must come only from the snapshot itself, a dedicated persisted field, or an
  explicit caller-supplied argument.
- Draft vs saved snapshot boundaries are explicit: callers must choose
  build_draft_input_set_from_workspace() or build_saved_input_set_from_workspace().
- It is the single controlled entry point for converting persistence types
  into Workbook V2 domain types, so future callers (app/v2/ shell, PR 5;
  sheet migration, PR 6) import from here rather than from input_set.py or
  runtime_result.py directly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from app.workbook.input_set import ProjectInputSet
from app.workbook.runtime_result import RuntimeResult

if TYPE_CHECKING:
    from app.persistence.records import WorkspaceStateRecord
    from app.domain.project_inputs import ProjectInputs  # engine domain object


class WorkbookService:
    """Pure domain service coordinating Workbook V2 types.

    All methods are static — there is no instance state.  Import and call
    directly::

        from app.workbook.service import WorkbookService

        pis = WorkbookService.build_input_set(snapshot)
        rr  = WorkbookService.get_runtime_result(ws)
    """

    # ------------------------------------------------------------------ #
    # Input set construction                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def build_input_set(
        snapshot: dict[str, Any],
        *,
        strict: bool = False,
    ) -> ProjectInputSet:
        """Build a ProjectInputSet from a flat snapshot dict.

        Parameters
        ----------
        snapshot : dict
            Flat key→value snapshot (e.g. ``workspace_state.draft_snapshot``).
            May include ``template_source`` and ``project_origin`` keys, which
            ProjectInputSet.from_snapshot() extracts as provenance metadata.
            template_source is taken only from the snapshot; it is never
            invented or derived from identity fields.
        strict : bool
            Forwarded to ProjectInputSet.from_snapshot().  When True, raises
            ProjectInputSetError on unknown keys or coercion errors.

        Returns
        -------
        ProjectInputSet
            Immutable, hash-stable input aggregate.
        """
        return ProjectInputSet.from_snapshot(snapshot=snapshot, strict=strict)

    @staticmethod
    def build_draft_input_set_from_workspace(
        ws: "WorkspaceStateRecord",
        *,
        strict: bool = False,
    ) -> ProjectInputSet:
        """Build a ProjectInputSet from a WorkspaceStateRecord's *draft* snapshot.

        Uses ``ws.draft_snapshot`` — the current in-progress editable state.
        This is the appropriate source for UI display and mid-session validation.
        It must NOT be used as the input for a persisted model run; use
        ``build_saved_input_set_from_workspace`` for that boundary.

        template_source is taken only from the snapshot itself.  It is never
        copied from ``ws.project_code`` or any other identity field.

        Parameters
        ----------
        ws : WorkspaceStateRecord
        strict : bool
            Forwarded to ProjectInputSet.from_snapshot().

        Returns
        -------
        ProjectInputSet
        """
        return ProjectInputSet.from_snapshot(
            snapshot=ws.draft_snapshot, strict=strict
        )

    @staticmethod
    def build_saved_input_set_from_workspace(
        ws: "WorkspaceStateRecord",
        *,
        strict: bool = False,
    ) -> ProjectInputSet:
        """Build a ProjectInputSet from a WorkspaceStateRecord's *saved* snapshot.

        Uses ``ws.saved_snapshot`` — the immutable runtime boundary, written at
        the moment a model run is committed.  This is the appropriate source for
        re-running the engine or auditing a past result.  It must NOT silently
        fall back to draft values.

        template_source is taken only from the snapshot itself.  It is never
        copied from ``ws.project_code`` or any other identity field.

        Parameters
        ----------
        ws : WorkspaceStateRecord
        strict : bool
            Forwarded to ProjectInputSet.from_snapshot().

        Returns
        -------
        ProjectInputSet
        """
        return ProjectInputSet.from_snapshot(
            snapshot=ws.saved_snapshot, strict=strict
        )

    # ------------------------------------------------------------------ #
    # Engine bridge                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def to_projectinputs(pis: ProjectInputSet) -> "ProjectInputs":
        """Convert a ProjectInputSet to the engine's ProjectInputs domain object.

        This is the bridge between Workbook V2's canonical input model and the
        existing WaterfallRunner input type.  No formula or engine logic lives
        here — the conversion is fully delegated to ProjectInputSet.to_projectinputs().

        Parameters
        ----------
        pis : ProjectInputSet
            Validated, immutable input aggregate.

        Returns
        -------
        ProjectInputs
            The engine's frozen domain object.
        """
        return pis.to_projectinputs()

    # ------------------------------------------------------------------ #
    # RuntimeResult                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_runtime_result(ws: "WorkspaceStateRecord") -> Optional[RuntimeResult]:
        """Reconstruct a RuntimeResult from a persisted WorkspaceStateRecord.

        Returns None when no run has been persisted yet (last_runtime_snapshot_id
        is absent or last_runtime_summary is empty).

        Parameters
        ----------
        ws : WorkspaceStateRecord

        Returns
        -------
        RuntimeResult | None
        """
        return RuntimeResult.from_workspace_state(ws)

    @staticmethod
    def runtime_hydration_script(ws: "WorkspaceStateRecord") -> str:
        """Return the sessionStorage hydration <script> block for this workspace.

        Convenience wrapper: reconstructs RuntimeResult and calls
        to_sessionstorage_script().  Returns an empty string when no
        RuntimeResult is persisted (so callers can safely concatenate without
        an extra None check).

        Parameters
        ----------
        ws : WorkspaceStateRecord

        Returns
        -------
        str
            A ``<script>…</script>`` block, or empty string if no runtime.
        """
        rr = RuntimeResult.from_workspace_state(ws)
        if rr is None:
            return ""
        return rr.to_sessionstorage_script()
