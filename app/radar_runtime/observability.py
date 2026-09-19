"""Structured runtime observability for the acquisition runtime (P13).

Every acquisition is traced by a ``correlation_id`` and emits structured
records with a FIXED field whitelist:

    correlation_id, request_fingerprint, snapshot_id, provider,
    result_state, elapsed_ms, cache (HIT/MISS), single_flight
    (new/reused), error_class, event

Secrets, API keys, auth headers and provider payloads are NEVER part of
the whitelist, so they can never reach the log stream.  These records are
runtime diagnostics only — they are not authority evidence and are never
consumed by R0-R12 verification.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger("radar_runtime")

# The ONLY fields ever serialized into structured runtime records (P13).
_EVENT_FIELDS = (
    "event", "correlation_id", "request_fingerprint", "snapshot_id",
    "provider", "result_state", "elapsed_ms", "cache", "single_flight",
    "error_class",
)


@dataclass(frozen=True)
class AcquisitionEvent:
    """One structured runtime diagnostic record."""

    event: str
    correlation_id: "str | None" = None
    request_fingerprint: "str | None" = None
    snapshot_id: "str | None" = None
    provider: "str | None" = None
    result_state: "str | None" = None
    elapsed_ms: "float | None" = None
    cache: "str | None" = None          # "HIT" | "MISS" | None
    single_flight: "str | None" = None  # "new" | "reused" | None
    error_class: "str | None" = None

    def to_dict(self) -> dict[str, Any]:
        """Whitelist-only serialization — non-whitelisted attributes are
        structurally impossible to leak into the record."""
        record: dict[str, Any] = {}
        for name in _EVENT_FIELDS:
            value = getattr(self, name)
            if value is not None:
                record[name] = value
        return record


class RuntimeEventLogger:
    """Collects structured events in a bounded in-memory ring and emits
    them through the ``radar_runtime`` logger as JSON records."""

    def __init__(self, ring_size: int = 1000,
                 logger: "Any" = _LOGGER) -> None:
        self._records: deque = deque(maxlen=ring_size)
        self._logger = logger

    def record(self, event: AcquisitionEvent) -> AcquisitionEvent:
        record = event.to_dict()
        self._records.append(record)
        self._logger.info(json.dumps(record, sort_keys=True))
        return event

    @property
    def records(self) -> "list[dict[str, Any]]":
        return list(self._records)
