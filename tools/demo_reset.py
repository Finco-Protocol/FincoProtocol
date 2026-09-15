"""Demo environment reset — P6.4.

Wipes all demo session data and re-seeds canonical reference models.
Safe to run repeatedly (idempotent).

Usage:
    python tools/demo_reset.py [--cleanup-only] [--yes]

Options:
    --cleanup-only   Delete expired demo data only (no full wipe)
    --yes            Skip the confirmation prompt

Safety gates:
    - Refuses to run if FINCO_ENV=production
    - Refuses to run if FINCO_APP_MODE=pilot and --yes is not passed
    - Never touches admin or reference user data
    - Never deletes the database file itself
"""

import os
import sys

# ── Safety gate: refuse production ───────────────────────────────────────────

_ENV = os.getenv("FINCO_ENV", "").strip().lower()
if _ENV == "production":
    print("ERROR: demo_reset refused. FINCO_ENV=production.")
    print("  This script must never run against production.")
    sys.exit(2)

_APP_MODE = os.getenv("FINCO_APP_MODE", "development").strip().lower()

# ── Argument parsing ──────────────────────────────────────────────────────────

_cleanup_only = "--cleanup-only" in sys.argv
_yes = "--yes" in sys.argv or "-y" in sys.argv

# ── Confirmation ──────────────────────────────────────────────────────────────

if not _yes:
    if _cleanup_only:
        msg = "This will DELETE all expired demo session data. Continue? [y/N] "
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
else:
    logger.info("Running full demo data wipe...")
    from app.demo_cleanup import cleanup_all_demo_data
    result = cleanup_all_demo_data()

if result:
    for table, count in result.items():
        logger.info("  %s: %d rows deleted", table, count)
else:
    logger.info("  No demo data found.")

if not _cleanup_only:
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
