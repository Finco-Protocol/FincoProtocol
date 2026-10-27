"""Python mirror of the React Run-identity presentation contract (frontend/src/app/runIdentity.tsx).

A committed Run's canonical snapshot id is its UTC commit instant without separators
(``20261027T004939.123456+0000``).  The UI shows the human-readable time to the second plus the
canonical sub-second part as the distinguishing suffix; the full identifier is one disclosure away.
The first 12 characters of the snapshot id (``20261027T004``) are NOT an identity: every Run committed
within ten minutes shares them.
"""
from __future__ import annotations

import re
from datetime import datetime

_SHAPE = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{4})?$")
# protected reference Runs: canonical_last_run__<template>__<UTC time with microseconds, no separators>Z
_REFERENCE = re.compile(r"^canonical_last_run__[A-Za-z0-9_]+__(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(\d{1,9})?Z$")


def parse(snapshot_id):
    raw = (snapshot_id or "").strip()
    reference = _REFERENCE.match(raw)
    match = reference or _SHAPE.match(raw)
    if not match:
        return None
    groups = match.groups()
    y, mo, d, h, mi, s, fraction = groups[:7]
    zone = "Z" if reference else (groups[7] or "")
    try:
        datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))      # an impossible instant is not canonical
    except ValueError:
        return None
    zone_text = "UTC" if zone in ("", "Z", "+0000", "-0000") else f"UTC{zone[:3]}:{zone[3:]}"
    return {"label": f"{y}-{mo}-{d} {h}:{mi}:{s} {zone_text}", "suffix": fraction or ""}


def text(snapshot_id):
    """What the UI prints for this Run (identical to runIdentityText in the frontend)."""
    parsed = parse(snapshot_id)
    if not (snapshot_id or "").strip():
        return "No persisted Run"
    if parsed is None:
        return snapshot_id.strip()
    return parsed["label"] + (f" · {parsed['suffix']}" if parsed["suffix"] else "")
