"""Per-user alert persistence and watchlist binding for Yield Alerts V1.

Durable JSONL stores (same conventions as the Yield history store):

- ``WatchlistStore``   — per-user watched canonical opportunity UIDs.
- ``PerUserAlertStore``— per-user typed alert records with deterministic
  dedupe, read/unread transitions and unread counts.

Deterministic alert uniqueness is based on equivalent canonical fields:
(user_id, opportunity_uid, alert_type, previous observation identity,
current observation identity).  The same transition can therefore never
create duplicate alerts.

Removing a watchlist entry stops future alerts; historical alert evidence
is retained (unwatching never destroys stored alerts).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .alerts_types import AlertEvent


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


# ── Watchlist ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WatchlistEntry:
    user_id: str
    opportunity_uid: str  # exact yld_* canonical UID
    created_at: str       # ISO-8601 UTC


class WatchlistStore:
    """Per-user watched canonical opportunities (append/remove, history kept)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _entries(self) -> list[WatchlistEntry]:
        out = []
        for row in _load_jsonl(self.path):
            out.append(WatchlistEntry(
                user_id=row["user_id"],
                opportunity_uid=row["opportunity_uid"],
                created_at=row.get("created_at", ""),
            ))
        return out

    def watch(self, user_id: str, opportunity_uid: str) -> bool:
        """Watch one canonical opportunity.  Returns True when newly added."""
        for entry in self._entries():
            if (entry.user_id == user_id
                    and entry.opportunity_uid == opportunity_uid):
                return False  # already watched — idempotent
        _append_jsonl(self.path, {
            "user_id": user_id,
            "opportunity_uid": opportunity_uid,
            "created_at": _now_iso(),
        })
        return True

    def unwatch(self, user_id: str, opportunity_uid: str) -> bool:
        """Remove a watchlist entry.  Returns True when it existed.

        Historical alerts for that opportunity are retained; only future
        alerts stop.
        """
        entries = self._entries()
        kept, removed = [], False
        for entry in entries:
            if (entry.user_id == user_id
                    and entry.opportunity_uid == opportunity_uid):
                removed = True
                continue
            kept.append(entry)
        if removed:
            self._rewrite(kept)
        return removed

    def watched_uids(self, user_id: str) -> frozenset[str]:
        """Canonical opportunity UIDs currently watched by the user."""
        return frozenset(
            entry.opportunity_uid for entry in self._entries()
            if entry.user_id == user_id
        )

    def is_watched(self, user_id: str, opportunity_uid: str) -> bool:
        return opportunity_uid in self.watched_uids(user_id)

    def _rewrite(self, entries: list[WatchlistEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(asdict(entry), sort_keys=True) + "\n")


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ── Per-user alerts ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AlertRecord:
    user_id: str
    opportunity_uid: str
    alert_type: str
    field: str | None
    previous: Any
    current: Any
    previous_observation_hash: str
    current_observation_hash: str
    detected_at: str        # ISO-8601 UTC
    read: bool = False

    @property
    def dedupe_key(self) -> str:
        """Deterministic uniqueness from equivalent canonical fields."""
        import hashlib

        payload = json.dumps({
            "user_id": self.user_id,
            "opportunity_uid": self.opportunity_uid,
            "alert_type": self.alert_type,
            "previous_observation_hash": self.previous_observation_hash,
            "current_observation_hash": self.current_observation_hash,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PerUserAlertStore:
    """Per-user typed alert records with dedupe and read-state transitions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _records(self) -> list[dict[str, Any]]:
        return _load_jsonl(self.path)

    def _dedupe_index(self, records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        index: dict[str, list[dict[str, Any]]] = {}
        for row in records:
            key = AlertRecord(
                user_id=row["user_id"],
                opportunity_uid=row["opportunity_uid"],
                alert_type=row["alert_type"],
                field=row.get("field"),
                previous=row.get("previous"),
                current=row.get("current"),
                previous_observation_hash=row["previous_observation_hash"],
                current_observation_hash=row["current_observation_hash"],
                detected_at=row.get("detected_at", ""),
            ).dedupe_key
            index.setdefault(key, []).append(row)
        return index

    def create_from_events(self, user_id: str, events, *,
                           dedupe: bool = True) -> list[dict[str, Any]]:
        """Persist typed alert events for one user.  Returns created records.

        Deterministic dedupe: the same (user, opportunity, alert_type,
        previous observation identity, current observation identity)
        transition never creates a second alert.
        """
        existing = self._records()
        existing_keys = set()
        if dedupe:
            index = self._dedupe_index(existing)
            for rows in index.values():
                for row in rows:
                    if row["user_id"] == user_id:
                        existing_keys.add(_event_key(
                            user_id, row["opportunity_uid"], row["alert_type"],
                            row["previous_observation_hash"],
                            row["current_observation_hash"]))
        created: list[dict[str, Any]] = []
        for event in events:
            key = _event_key(
                user_id, event.opportunity_uid, event.alert_type.value,
                event.previous_observation_hash, event.current_observation_hash)
            if dedupe and key in existing_keys:
                continue
            record = {
                "user_id": user_id,
                "opportunity_uid": event.opportunity_uid,
                "alert_type": event.alert_type.value,
                "label": event.label,
                "field": event.field,
                "previous": event.previous,
                "current": event.current,
                "previous_observation_hash": event.previous_observation_hash,
                "current_observation_hash": event.current_observation_hash,
                "detected_at": event.detected_at.isoformat(),
                "read": False,
            }
            _append_jsonl(self.path, record)
            existing_keys.add(key)
            created.append(record)
        return created

    def list_alerts(self, user_id: str, *,
                    unread_only: bool = False) -> list[dict[str, Any]]:
        out = []
        for row in self._records():
            if row["user_id"] != user_id:
                continue
            if unread_only and row.get("read"):
                continue
            out.append(row)
        return out

    def mark_read(self, user_id: str, opportunity_uid: str,
                  alert_type: str) -> int:
        """Mark matching unread alerts read.  Returns marked count."""
        records = self._records()
        marked = 0
        for row in records:
            if (row["user_id"] == user_id
                    and row["opportunity_uid"] == opportunity_uid
                    and row["alert_type"] == alert_type
                    and not row.get("read")):
                row["read"] = True
                marked += 1
        if marked:
            self._rewrite(records)
        return marked

    def mark_all_read(self, user_id: str) -> int:
        records = self._records()
        marked = 0
        for row in records:
            if row["user_id"] == user_id and not row.get("read"):
                row["read"] = True
                marked += 1
        if marked:
            self._rewrite(records)
        return marked

    def unread_count(self, user_id: str) -> int:
        return sum(
            1 for row in self._records()
            if row["user_id"] == user_id and not row.get("read")
        )

    def _rewrite(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for row in records:
                handle.write(json.dumps(row, sort_keys=True) + "\n")


def _event_key(user_id: str, opportunity_uid: str, alert_type: str,
               previous_hash: str, current_hash: str) -> str:
    import hashlib
    import json

    payload = json.dumps({
        "user_id": user_id,
        "opportunity_uid": opportunity_uid,
        "alert_type": alert_type,
        "previous_observation_hash": previous_hash,
        "current_observation_hash": current_hash,
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
