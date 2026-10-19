"""Lightweight SQLite persistence for runs, scenarios, and exports.

`app.persistence` is the single active persistence backend for the pilot
product workflow. It stores snapshots and workflow metadata only.
Runtime calculations remain authoritative in the model layer.
"""

import os
import threading
from contextlib import contextmanager

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.getenv("FINCO_DB_PATH", os.path.join(DATA_DIR, "finco_runs.db"))

os.makedirs(DATA_DIR, exist_ok=True)


# V8-A: schema checks are bypassed ONLY after this process has completed
# the migrations on this same database file and observed its SQLite DDL version.
# Bump this constant when changing _init_schema without changing its DDL.
_SCHEMA_CONTRACT_VERSION = 1
_SCHEMA_GUARD_LOCK = threading.RLock()
_SCHEMA_GUARD_SEEN = {}


def _database_file_identity():
    """Use file identity, never pathname alone; fail closed when uncertain.

    The optional birthtime distinguishes recycled inodes on filesystems which
    expose it. SQLite's on-disk schema generation independently detects a new
    empty database, a restored older database, and external DDL.
    """
    if not DB_PATH or DB_PATH == ":memory:" or str(DB_PATH).startswith("file:"):
        return None
    try:
        stat = os.stat(DB_PATH)
        return (
            os.getpid(), os.path.realpath(DB_PATH), stat.st_dev, stat.st_ino,
            getattr(stat, "st_birthtime_ns", None),
        )
    except (OSError, TypeError, ValueError):
        return None


def _schema_generation(conn):
    """SQLite's durable schema cookie; changes on DDL in another process."""
    return int(conn.execute("PRAGMA schema_version").fetchone()[0])


def _schema_signature(conn):
    """Current SQLite DDL inventory catches backup restore even if cookies match.

    A read-only, single-catalog query replaces dozens of per-connection DDL
    statements and table_info probes. Unlike mtime/ctime it is insensitive to
    ordinary Run or Working Copy data writes.
    """
    return tuple(
        (row[0], row[1], row[2])
        for row in conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE type IN ('table', 'index') ORDER BY type, name"
        )
    )


def _ensure_schema_ready(conn):
    """Process-local schema check, with cross-process transactional DDL.

    Each process performs the full migration at least once per file identity;
    the local cache holds only a successfully committed schema generation.
    After an external schema change, the generation differs and the full
    migration is repeated. Uncertain identities always migrate. No table,
    tenant metadata, user_version, or backup format is added or modified.
    """
    identity = _database_file_identity()
    with _SCHEMA_GUARD_LOCK:
        generation = _schema_generation(conn)
        # Inode reuse, in-place backup restoration and a copied database can
        # preserve a schema cookie. Check the actual SQLite catalog as well.
        signature = _schema_signature(conn)
        if (identity is not None
                and _SCHEMA_GUARD_SEEN.get(identity)
                == (_SCHEMA_CONTRACT_VERSION, generation, signature)):
            return
        try:
            # BEGIN IMMEDIATE serialises first-boot DDL across processes.
            # _init_schema never commits inside this transaction.
            conn.execute("BEGIN IMMEDIATE")
            _init_schema(conn, commit=False)
            conn.commit()
        except BaseException:
            conn.rollback()
            if identity is not None:
                _SCHEMA_GUARD_SEEN.pop(identity, None)
            raise

        current_identity = _database_file_identity()
        if identity is not None and identity == current_identity:
            current_generation = _schema_generation(conn)
            if len(_SCHEMA_GUARD_SEEN) >= 128:
                _SCHEMA_GUARD_SEEN.clear()
            _SCHEMA_GUARD_SEEN[identity] = (
                _SCHEMA_CONTRACT_VERSION, current_generation, _schema_signature(conn)
            )


# Bounded, deadline-driven handling of the journal-mode switch (see _ensure_wal).
_WAL_SWITCH_DEADLINE_S = 30.0
_WAL_SWITCH_BACKOFF_S = (0.005, 0.01, 0.02, 0.04, 0.08, 0.16, 0.25)


def _ensure_wal(conn):
    """Put the database into WAL mode without failing a concurrent first boot.

    WAL is a persistent property of the database file, so only the FIRST connection ever needs to
    switch it; every later connection merely reads it. ``PRAGMA journal_mode=WAL`` takes an
    exclusive lock for the switch and SQLite can return SQLITE_BUSY at once, without consulting
    the busy handler, when other connections of a simultaneous first boot hold locks. So:

    1. read the mode (no write, no exclusive lock) and return when it is already WAL;
    2. otherwise attempt the switch; on a genuinely transient ``database is locked`` re-read the mode
       (another booting connection may have won the switch - then we are done) and retry with a short,
       bounded backoff until a fixed deadline;
    3. any other error, or the deadline, is re-raised unchanged. Nothing is swallowed and WAL stays
       mandatory: the function only returns once the database reports ``wal``.
    """
    import sqlite3
    import time

    def mode():
        row = conn.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]).lower() if row else ""

    deadline = time.monotonic() + _WAL_SWITCH_DEADLINE_S
    attempt = 0
    while True:
        if mode() == "wal":
            return
        try:
            row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
            if row and str(row[0]).lower() == "wal":
                return
            raise sqlite3.OperationalError(f"journal_mode switch to WAL refused (reported {row[0] if row else None!r})")
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            if time.monotonic() >= deadline:
                raise
            time.sleep(_WAL_SWITCH_BACKOFF_S[min(attempt, len(_WAL_SWITCH_BACKOFF_S) - 1)])
            attempt += 1


def get_connection():
    """Return a fresh SQLite connection with schema ensured."""
    import sqlite3

    conn = sqlite3.connect(DB_PATH, timeout=30.0, isolation_level=None)
    try:
        # Connection-local settings remain mandatory on EVERY new connection. The busy timeout is set first so that
        # every following statement - including the journal-mode read - already honours it.
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        _ensure_wal(conn)
        conn.execute("PRAGMA foreign_keys=ON")
        _ensure_schema_ready(conn)
        return conn
    except BaseException:
        conn.close()
        raise


def _init_schema(conn, *, commit=True):
    """Run schema creation on an open connection (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id       TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL,
            project_type TEXT NOT NULL,
            scenario     TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            inputs_json  TEXT NOT NULL,
            kpis_json    TEXT NOT NULL,
            excel_path   TEXT,
            notes        TEXT,
            replay_metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_user ON runs(user_id, created_at DESC)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id               TEXT PRIMARY KEY,
            user_id                  TEXT NOT NULL,
            project_code             TEXT NOT NULL,
            project_name             TEXT NOT NULL,
            project_type             TEXT,
            project_origin           TEXT NOT NULL DEFAULT 'factory_template',
            source_project_template  TEXT NOT NULL,
            template_source          TEXT,
            baseline_snapshot_json   TEXT NOT NULL DEFAULT '{}',
            archived                 INTEGER NOT NULL DEFAULT 0,
            governance_state_json    TEXT NOT NULL,
            last_run_summary_json    TEXT NOT NULL,
            replay_metadata_json     TEXT NOT NULL DEFAULT '{}',
            created_at               TEXT NOT NULL,
            updated_at               TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_user_code ON projects(user_id, project_code)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scenarios (
            scenario_id               TEXT PRIMARY KEY,
            project_id                TEXT NOT NULL,
            user_id                   TEXT NOT NULL,
            scenario_name             TEXT NOT NULL,
            project_code              TEXT NOT NULL,
            source_project_template   TEXT NOT NULL,
            copied_from_scenario_id   TEXT,
            archived                  INTEGER NOT NULL DEFAULT 0,
            is_base_case              INTEGER NOT NULL DEFAULT 0,
            parent_scenario_id        TEXT,
            base_input_set_json       TEXT NOT NULL DEFAULT '{}',
            overrides_json            TEXT NOT NULL DEFAULT '{}',
            schema_version            TEXT NOT NULL DEFAULT '1.0',
            snapshot_json             TEXT NOT NULL,
            governance_state_json     TEXT NOT NULL,
            last_run_summary_json     TEXT NOT NULL,
            replay_metadata_json      TEXT NOT NULL DEFAULT '{}',
            created_at                TEXT NOT NULL,
            updated_at                TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(project_id)
        )
        """
    )
    _ensure_column(conn, "scenarios", "is_base_case", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "scenarios", "parent_scenario_id", "TEXT")
    _ensure_column(conn, "scenarios", "base_input_set_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "scenarios", "overrides_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "scenarios", "schema_version", "TEXT NOT NULL DEFAULT '1.0'")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenarios_user_project ON scenarios(user_id, project_id, archived, updated_at DESC)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scenario_exports (
            export_id                 TEXT PRIMARY KEY,
            scenario_id               TEXT,
            project_id                TEXT,
            user_id                   TEXT NOT NULL,
            export_type               TEXT NOT NULL,
            artifact_name             TEXT NOT NULL,
            artifact_path             TEXT,
            project_code              TEXT NOT NULL,
            governance_state_json     TEXT NOT NULL,
            runtime_snapshot_id       TEXT,
            replay_metadata_json      TEXT NOT NULL DEFAULT '{}',
            created_at                TEXT NOT NULL,
            FOREIGN KEY(scenario_id) REFERENCES scenarios(scenario_id),
            FOREIGN KEY(project_id) REFERENCES projects(project_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_exports_user_project ON scenario_exports(user_id, project_id, created_at DESC)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_states (
            workspace_id               TEXT PRIMARY KEY,
            project_id                 TEXT NOT NULL,
            user_id                    TEXT NOT NULL,
            project_code               TEXT NOT NULL,
            active_scenario_id         TEXT,
            active_scenario_name       TEXT,
            draft_snapshot_json        TEXT NOT NULL,
            saved_snapshot_json        TEXT NOT NULL,
            last_runtime_snapshot_json TEXT NOT NULL,
            last_runtime_summary_json  TEXT NOT NULL,
            last_runtime_snapshot_id   TEXT,
            last_runtime_origin        TEXT,
            last_runtime_scenario_id   TEXT,
            dirty                      INTEGER NOT NULL DEFAULT 0,
            governance_state_json      TEXT NOT NULL,
            replay_metadata_json       TEXT NOT NULL DEFAULT '{}',
            created_at                 TEXT NOT NULL,
            updated_at                 TEXT NOT NULL,
            last_runtime_at            TEXT,
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            FOREIGN KEY(last_runtime_scenario_id) REFERENCES scenarios(scenario_id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_states_user_project ON workspace_states(user_id, project_id)"
    )

    # Phase 57A-9B: CAPEX user-added sub-lines table.
    # See docs/phase57a9a_capex_add_line_persistence_design_gate.md
    # and docs/phase57a9b_capex_sub_lines_schema.md.
    # Existence of user-added sub-lines lives here; per-scenario
    # amount overrides live in the scenario overrides_json blob
    # (landed in 57A-9C, NOT in this PR).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS capex_sub_lines (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            sub_line_id           TEXT    NOT NULL UNIQUE,
            project_id            TEXT    NOT NULL,
            parent_category_code  TEXT    NOT NULL,
            business_code         TEXT    NOT NULL,
            display_order         INTEGER NOT NULL,
            label                 TEXT    NOT NULL,
            amount_keur           REAL    NOT NULL DEFAULT 0.0,
            comments              TEXT    NOT NULL DEFAULT '',
            schedule_json         TEXT    NOT NULL DEFAULT '{}',
            source                TEXT    NOT NULL DEFAULT 'user',
            is_active             INTEGER NOT NULL DEFAULT 1,
            governance_state_json TEXT    NOT NULL DEFAULT '{}',
            replay_metadata_json  TEXT    NOT NULL DEFAULT '{}',
            created_at            TEXT    NOT NULL,
            updated_at            TEXT    NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            UNIQUE(project_id, business_code)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_capex_sub_lines_project"
        " ON capex_sub_lines(project_id, is_active, parent_category_code, display_order)"
    )
    # Workbook V2 PR 11: OPEX custom-row sub-lines table.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS opex_sub_lines (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            sub_line_id       TEXT    NOT NULL UNIQUE,
            project_id        TEXT    NOT NULL,
            parent_group_code TEXT    NOT NULL,
            business_code     TEXT    NOT NULL,
            display_order     INTEGER NOT NULL,
            label             TEXT    NOT NULL,
            amount_keur       REAL    NOT NULL DEFAULT 0.0,
            inflation_pct     REAL    NOT NULL DEFAULT 0.0,
            comments          TEXT    NOT NULL DEFAULT '',
            source            TEXT    NOT NULL DEFAULT 'user',
            replay_metadata_json TEXT NOT NULL DEFAULT '{}',
            is_active         INTEGER NOT NULL DEFAULT 1,
            created_at        TEXT    NOT NULL,
            updated_at        TEXT    NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            UNIQUE(project_id, business_code)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_opex_sub_lines_project"
        " ON opex_sub_lines(project_id, is_active, parent_group_code, display_order)"
    )
    _ensure_column(conn, "opex_sub_lines", "replay_metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "runs", "replay_metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "projects", "project_type", "TEXT")
    _ensure_column(conn, "projects", "project_origin", "TEXT NOT NULL DEFAULT 'factory_template'")
    _ensure_column(conn, "projects", "replay_metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "projects", "template_source", "TEXT")
    _ensure_column(conn, "projects", "baseline_snapshot_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "projects", "archived", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "projects", "is_readonly", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "projects", "full_inputs_json", "TEXT")
    # Project Library (PR: project-library-reference-working-copies)
    _ensure_column(conn, "projects", "project_role", "TEXT NOT NULL DEFAULT 'user_project'")
    _ensure_column(conn, "projects", "is_protected", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "projects", "source_project_id", "TEXT")
    # Model V2 foundation: non-economic project metadata. Nullable — existing
    # rows keep NULL ("not set"); no stage/perspective value is ever inferred
    # for legacy projects. Stored values are validated at the app boundary
    # (app.model_v2.project_metadata), never inside the financial engine.
    _ensure_column(conn, "projects", "project_stage", "TEXT")
    _ensure_column(conn, "projects", "model_perspective", "TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_projects_role"
        " ON projects(user_id, project_role, archived, updated_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_projects_template_role"
        " ON projects(template_source, project_role, archived)"
    )
    # Unique constraint: exactly one canonical system reference per
    # template_source. The OLD index
    #   ux_projects_system_reference_source
    # used the partial WHERE
    #   user_id='__reference__' AND project_role='reference' AND archived=0
    # which was broader than the canonical-reference contract
    #   user_id='__reference__' AND project_role='reference'
    #   AND is_protected=1 AND archived=0
    #   AND template_source IN ('generic_wind_reference','generic_solar_reference','generic_storage_reference')
    # The new index carries the same name on existing databases that
    # have already been initialised — we therefore drop the old
    # versioned name first and recreate it under the corrected
    # versioned name ux_projects_canonical_reference_source. This
    # migration is idempotent: on a fresh DB the DROP is a no-op.
    conn.execute("DROP INDEX IF EXISTS ux_projects_system_reference_source")
    # Drop the previous version of the canonical-reference index so the
    # recreated version picks up the current canonical template list
    # (adding the Generic Data Center reference).  Idempotent: on a fresh
    # DB the DROP is a no-op.
    conn.execute("DROP INDEX IF EXISTS ux_projects_canonical_reference_source")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_projects_canonical_reference_source
        ON projects(template_source)
        WHERE user_id='__reference__'
          AND project_role='reference'
          AND is_protected=1
          AND archived=0
          AND template_source IN ('generic_wind_reference','generic_solar_reference','generic_storage_reference','generic_data_center_reference')
        """
    )
    # Backfill: only rows already owned by the system reference user get
    # promoted to role='reference'. User-owned factory_template rows are
    # intentionally left untouched — they must not become globally visible.
    conn.execute(
        """
        UPDATE projects
        SET project_role='reference', is_protected=1
        WHERE user_id='__reference__'
          AND template_source IN ('generic_wind_reference','generic_solar_reference','generic_storage_reference','generic_data_center_reference')
          AND project_role='user_project'
        """
    )
    _ensure_column(conn, "scenarios", "replay_metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "scenarios", "full_inputs_json", "TEXT")  # V3-8
    _ensure_column(conn, "scenario_exports", "replay_metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "workspace_states", "replay_metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    # Workbook V2 PR 3: persist full schedule payloads so DB is authoritative.
    _ensure_column(conn, "workspace_states", "last_financial_statements_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "workspace_states", "last_debt_schedule_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "workspace_states", "last_tax_schedule_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "workspace_states", "last_distribution_schedule_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "workspace_states", "last_sponsor_schedule_json", "TEXT NOT NULL DEFAULT '{}'")
    # H-4b: full-precision Run Integrity evidence recorded with the committed Last Run.
    _ensure_column(conn, "workspace_states", "last_integrity_evidence_json", "TEXT NOT NULL DEFAULT '{}'")
    # Workbook V2 PR 7: SHA-256 of draft ProjectInputSet for atomic CAS edits.
    _ensure_column(conn, "workspace_states", "draft_content_hash", "TEXT")
    # R9/N03-CorrA: distinguish "never run" (0) from "Base run" (1, last_runtime_scenario_id=NULL)
    _ensure_column(conn, "workspace_states", "any_run_committed", "INTEGER NOT NULL DEFAULT 0")
    # F07-B Correction B: run-bound composite identity for canonical export authority.
    # last_runtime_composite_hash: SHA-256 of the full composite workbook identity at run time.
    # last_runtime_identity_json: serialised capex_rows, opex_rows, scenario_overrides, and
    #   scenario_name captured at run commit — used for run-bound canonical export without
    #   re-reading mutable live tables.
    _ensure_column(conn, "workspace_states", "last_runtime_composite_hash", "TEXT")
    _ensure_column(conn, "workspace_states", "last_runtime_identity_json", "TEXT")
    # Workflow 07: Model V2 Working Copy selections — versioned typed payload
    # (app.model_v2.persistence). '' (empty) means NO Model V2 state: the exact
    # legacy absence. Rows are never defaulted with invented V2 economics.
    _ensure_column(conn, "workspace_states", "model_v2_working_state_json", "TEXT NOT NULL DEFAULT ''")
    # Run History V1: append-only canonical ledger of successful runs.
    # One immutable row per successful canonical run, appended INSIDE the
    # same transaction that promotes the Last Run (never a second commit
    # path). History starts prospectively: existing workspaces are never
    # back-filled and no row is synthesized from the current Last Run.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_run_history (
            history_id                  TEXT PRIMARY KEY,
            user_id                     TEXT NOT NULL,
            project_id                  TEXT NOT NULL,
            project_code                TEXT NOT NULL,
            runtime_snapshot_id         TEXT NOT NULL,
            runtime_origin              TEXT,
            ran_at                      TEXT NOT NULL,
            engine_version              TEXT,
            workbook_version            TEXT,
            active_scenario_id          TEXT,
            active_scenario_name        TEXT,
            last_runtime_scenario_id    TEXT,
            composite_hash              TEXT,
            last_runtime_identity_json  TEXT,
            runtime_summary_json        TEXT NOT NULL,
            financial_statements_json   TEXT NOT NULL,
            debt_schedule_json          TEXT NOT NULL,
            tax_schedule_json           TEXT NOT NULL,
            distribution_schedule_json  TEXT NOT NULL,
            sponsor_schedule_json       TEXT NOT NULL,
            integrity_evidence_json     TEXT NOT NULL DEFAULT '{}',
            replay_metadata_json        TEXT NOT NULL DEFAULT '{}',
            created_at                  TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(project_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_model_run_history_project"
        " ON model_run_history(user_id, project_id, ran_at DESC, history_id DESC)"
    )
    if commit:
        conn.commit()


def _ensure_column(conn, table_name: str, column_name: str, column_sql: str) -> None:
    import sqlite3 as _sqlite3
    columns = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        try:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
        except _sqlite3.OperationalError as exc:
            # Concurrent initialisation: another connection may have added the
            # column between our PRAGMA check and our ALTER TABLE.  Treat
            # "duplicate column name" as success; re-raise everything else.
            if "duplicate column name" not in str(exc):
                raise


@contextmanager
def get_cursor():
    """Open a connection, yield a cursor, and close it automatically."""
    import sqlite3 as _sqlite3
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except _sqlite3.OperationalError as exc:
        conn.rollback()
        _msg = str(exc).lower()
        if "locked" in _msg or "busy" in _msg:
            try:
                from app.observability import log_sqlite_lock
                log_sqlite_lock()
            except Exception:
                pass
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def init_db():
    """Explicitly initialize the DB schema."""
    conn = get_connection()
    conn.close()
