#!/usr/bin/env bash
# backup.sh — FINCO Model SQLite database backup
#
# Backs up the SQLite DB at FINCO_DB_PATH to /opt/finco_protocol/backups/
# Naming: finco_runs_YYYYMMDD_HHMMSS.db.xz
# WAL file backed up alongside if present.
#
# Retention: removes backups older than 30 days.
#
# Usage: ./backup.sh
# Requirements: sqlite3 CLI on PATH, xz for compression, FINCO_DB_PATH env var

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-/opt/finco_protocol/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Load FINCO_DB_PATH from .env if present
ENV_FILE="/opt/finco_protocol/.env"
if [[ -f "$ENV_FILE" ]]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

DB_PATH="${FINCO_DB_PATH:-/opt/finco_protocol/app/data/finco_runs.db}"
WAL_PATH="${DB_PATH}-wal"

# ── Pre-flight checks ────────────────────────────────────────────────────────
if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: SQLite DB not found at $DB_PATH" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

# ── WAL checkpoint (flush WAL to DB before backup) ──────────────────────────
if [[ -f "$WAL_PATH" ]]; then
    sqlite3 "$DB_PATH" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true
fi

# ── Backup ───────────────────────────────────────────────────────────────────
BACKUP_FILE="${BACKUP_DIR}/finco_runs_${TIMESTAMP}.db"
WAL_BACKUP_FILE="${BACKUP_DIR}/finco_runs_${TIMESTAMP}.db-wal"

# Prefer SQLite .backup command (consistent, crash-safe)
if command -v sqlite3 > /dev/null 2>&1; then
    sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"
else
    # Fallback: copy DB only after WAL checkpoint — warn that this is less safe
    echo "WARNING: sqlite3 not available — using cp fallback (unsafe for live DB)" >&2
    cp "$DB_PATH" "$BACKUP_FILE"
fi

# Copy WAL if present
if [[ -f "$WAL_PATH" ]]; then
    cp "$WAL_PATH" "$WAL_BACKUP_FILE"
fi

# Compress
xz -9 "$BACKUP_FILE"
if [[ -f "${BACKUP_FILE}.xz" ]]; then
    rm -f "$BACKUP_FILE"
    BACKUP_FILE="${BACKUP_FILE}.xz"
fi

# Compress WAL backup too
if [[ -f "$WAL_BACKUP_FILE" ]]; then
    xz -9 "$WAL_BACKUP_FILE" 2>/dev/null || rm -f "$WAL_BACKUP_FILE"
fi

echo "Backup created: $BACKUP_FILE"

# ── Cleanup old backups ───────────────────────────────────────────────────────
find "$BACKUP_DIR" -name "finco_runs_*.db*" -mtime "+${RETENTION_DAYS}" -delete
echo "Backups older than $RETENTION_DAYS days purged."

# List current backups
echo ""
echo "Current backups:"
ls -lh "$BACKUP_DIR"/finco_runs_*.db* 2>/dev/null || echo "(none)"