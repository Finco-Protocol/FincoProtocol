"""Demo environment reset — P6.4.

Wipes demo session data and re-seeds canonical reference models.
Safe to run repeatedly (idempotent).

Usage:
    python tools/demo_reset.py [--cleanup-only | --full-bootstrap] [--yes]

Options:
    --cleanup-only     Delete expired demo data only (TTL-scoped, demo rows only)
    --full-bootstrap   Full disposable-staging reset: wipe ALL non-reference
                       project/user state (including admin-owned), then seed
                       the three canonical references.  Post-condition:
                       exactly 3 reference rows, zero non-reference project rows.
    (default)          Delete ALL demo data and re-seed reference models
                       (demo rows only, same as Correction B behaviour)

Safety gates (fail-closed — all modes):
    - FINCO_ENV must be explicitly set to one of: staging, demo, test
      (absent/empty/production/development all refused)
    - FINCO_DB_PATH must be explicitly set (refuses to operate on the
      default/fallback database path)
    - FINCO_DEMO_RESET_ALLOWED=true must be set as a second explicit
      opt-in (prevents accidental invocation in scripts that happen to
      have the right FINCO_ENV but have not consciously enabled reset)
    - Never deletes the database file itself

--cleanup-only:
    Only removes expired demo data (TTL-scoped).
    Never touches admin (user_id='1') or reference (user_id='__reference__') rows.

--full-bootstrap:
    Wipes ALL non-reference state, including admin rows.
    Only use on a disposable staging database.
    Seeds Solar XA / Wind XB / Storage XC and verifies post-condition.
"""

import os
import sys

# ── Safety gate: refuse production and missing env ────────────────────────────

# Positive allowlist — ONLY these three explicit values are accepted.
# Empty string, "production", "development", and any unrecognised value are
# refused. The empty-string case is critical: an absent FINCO_ENV variable
# must not silently pass the gate.
_ALLOWED_ENVS = frozenset({"staging", "demo", "test"})
_ENV = os.getenv("FINCO_ENV", "").strip().lower()
if _ENV not in _ALLOWED_ENVS:
    print(f"ERROR: demo_reset refused. FINCO_ENV={_ENV!r} is not in the allowed set.")
    print(f"  Allowed: {sorted(_ALLOWED_ENVS)}")
    print("  FINCO_ENV must be explicitly set to staging, demo, or test.")
    print("  Absent, empty, 'production', or 'development' values are all refused.")
    sys.exit(2)

# ── Safety gate: require explicit FINCO_DB_PATH ───────────────────────────────

_DB_PATH = os.getenv("FINCO_DB_PATH", "").strip()
if not _DB_PATH:
    print("ERROR: demo_reset refused. FINCO_DB_PATH is not set.")
    print("  You must explicitly set FINCO_DB_PATH to the staging database path.")
    print("  Refusing to operate on the default/fallback database path.")
    sys.exit(2)

_DEFAULT_DB_FRAGMENTS = ("finco_runs.db", "app/data/")
if any(fragment in _DB_PATH for fragment in _DEFAULT_DB_FRAGMENTS):
    print(f"ERROR: demo_reset refused. FINCO_DB_PATH={_DB_PATH!r} looks like the default DB path.")
    print("  Set FINCO_DB_PATH to the staging-specific database path.")
    sys.exit(2)

# ── Safety gate: require FINCO_DEMO_RESET_ALLOWED=true ───────────────────────

_RESET_ALLOWED = os.getenv("FINCO_DEMO_RESET_ALLOWED", "").strip().lower()
if _RESET_ALLOWED != "true":
    print("ERROR: demo_reset refused. FINCO_DEMO_RESET_ALLOWED is not set to 'true'.")
    print("  Set FINCO_DEMO_RESET_ALLOWED=true to explicitly opt in to demo reset.")
    print("  This prevents accidental invocation in scripts without conscious opt-in.")
    sys.exit(2)

_APP_MODE = os.getenv("FINCO_APP_MODE", "development").strip().lower()

# ── Argument parsing ──────────────────────────────────────────────────────────

_cleanup_only = "--cleanup-only" in sys.argv
_full_bootstrap = "--full-bootstrap" in sys.argv
_yes = "--yes" in sys.argv or "-y" in sys.argv

if _cleanup_only and _full_bootstrap:
    print("ERROR: --cleanup-only and --full-bootstrap are mutually exclusive.")
    sys.exit(2)

# ── Confirmation ──────────────────────────────────────────────────────────────

if not _yes:
    if _cleanup_only:
        msg = "This will DELETE all expired demo session data. Continue? [y/N] "
    elif _full_bootstrap:
        msg = (
            "WARNING: --full-bootstrap will DELETE ALL non-reference project/user state\n"
            f"  including admin rows, from FINCO_DB_PATH={_DB_PATH!r}.\n"
            "  Post-condition: exactly 3 canonical reference rows remain.\n"
            "  Only use on a disposable staging database. Continue? [y/N] "
        )
    else:
        msg = "This will DELETE ALL demo session data and re-seed reference models. Continue? [y/N] "
    answer = input(msg).strip().lower()
    if answer not in ("y", "yes"):
        print("Aborted.")
        sys.exit(0)

# ── Bootstrap path ────────────────────────────────────────────────────────────
# Ensure repo root is on sys.path so app.* imports resolve.

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("demo_reset")

# ── Execute ───────────────────────────────────────────────────────────────────

if _cleanup_only:
    logger.info("Running expired demo data cleanup only...")
    from app.demo_cleanup import cleanup_expired_demo_data
    result = cleanup_expired_demo_data()
    if result:
        for table, count in result.items():
            logger.info("  %s: %d rows deleted", table, count)
    else:
        logger.info("  No expired demo data found.")

elif _full_bootstrap:
    logger.info("Running full disposable-staging bootstrap (DB: %s)...", _DB_PATH)
    from app.persistence.db import get_connection
    from app.demo_cleanup import bootstrap_staging_db
    try:
        conn = get_connection()
        result = bootstrap_staging_db(conn)
        conn.close()
        deleted = result.get("deleted", {})
        if deleted:
            for table, count in deleted.items():
                logger.info("  deleted %d rows from %s", count, table)
        logger.info("  seeded %d canonical reference rows", result.get("seeded", 0))
        logger.info("  post-condition: %s", result.get("post_condition", "unknown"))
    except Exception as exc:
        logger.error("  Full bootstrap failed: %s", exc)
        sys.exit(1)

else:
    logger.info("Running full demo data wipe...")
    from app.demo_cleanup import cleanup_all_demo_data
    result = cleanup_all_demo_data()
    if result:
        for table, count in result.items():
            logger.info("  %s: %d rows deleted", table, count)
    else:
        logger.info("  No demo data found.")

    logger.info("Re-seeding canonical reference models...")
    try:
        from app.services.project_library_service import ensure_reference_models
        ensure_reference_models()
        logger.info("  Reference models seeded OK.")
    except Exception as exc:
        logger.error("  Failed to seed reference models: %s", exc)
        sys.exit(1)

logger.info("Done.")
sys.exit(0)
