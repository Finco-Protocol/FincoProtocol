"""RC-7 - versioned persisted monthly CAPEX profile document (strict, fail-closed, no I/O).

The document is stored as ONE canonical JSON string under the draft-snapshot key ``capex_monthly_profiles_json``.  Because it lives in the
Working Copy snapshot it is part of the composite workbook identity (scalar axis), is covered by the existing CAS/dirty/STALE protocol,
is copied into every Run's runtime snapshot (historical Runs are immutable) and is inherited by scenarios (scenario-specific profiles
are not supported in this version and are refused at Save).

Only the user's AUTHORING input is stored (shape plus its parameters); the exact monthly weights are derived deterministically at
bind time with ``contract.build_weights`` (Fraction arithmetic), so no float weights are ever persisted.

  {"version": 1, "profiles": [{"item_key": "base:production_units" | "C.01.01", "shape": "UNIFORM|FRONT_LOADED|BACK_LOADED|EXPLICIT|MILESTONE",
                               "explicit_percent": ["10", "20", ...], "milestone_month": 3}]}

``item_key`` names a LEAF row: ``base:<CapexStructure field>`` for a category without sub-lines, or the sub-line business code.
"""
from __future__ import annotations

import json
import re

from app.capex_profiles.contract import ProfileError, ProfileShape, ProfileSpec, reject_duplicates

SNAPSHOT_KEY = "capex_monthly_profiles_json"
VERSION = 1
MAX_BYTES = 64 * 1024
MAX_PROFILES = 200
_TOP_KEYS = frozenset({"version", "profiles"})
_ROW_KEYS = frozenset({"item_key", "shape", "explicit_percent", "milestone_month"})
_KEY = re.compile(r"^(base:[a-z][a-z_]{2,39}|C\.\d{2}\.\d{2,4})$")
SOURCE_PERSISTED = "PERSISTED_PROFILE"


def _reject_constant(token):
    raise ProfileError("CAPEX_PROFILE_DOCUMENT_NONFINITE", token)


def parse(raw) -> tuple[ProfileSpec, ...]:
    """Typed specs, or ``()`` when ``raw`` is absent/empty.  Raises ``ProfileError`` on anything malformed."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ()
    if isinstance(raw, dict):
        document = raw
    else:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
            raise ProfileError("CAPEX_PROFILE_DOCUMENT_INVALID", "payload must be a bounded JSON object")
        try:
            document = json.loads(raw, parse_constant=_reject_constant)
        except json.JSONDecodeError as exc:
            raise ProfileError("CAPEX_PROFILE_DOCUMENT_INVALID", "not valid JSON") from exc
    if not isinstance(document, dict) or set(document) != _TOP_KEYS:
        raise ProfileError("CAPEX_PROFILE_DOCUMENT_INVALID", "keys are not exactly the profile schema")
    if document["version"] != VERSION or isinstance(document["version"], bool):
        raise ProfileError("CAPEX_PROFILE_DOCUMENT_VERSION", "unsupported version")
    rows = document["profiles"]
    if not isinstance(rows, list) or len(rows) > MAX_PROFILES:
        raise ProfileError("CAPEX_PROFILE_DOCUMENT_INVALID", "profiles must be a bounded list")
    specs: list[ProfileSpec] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            raise ProfileError("CAPEX_PROFILE_DOCUMENT_INVALID", "each profile needs exactly item_key, shape, explicit_percent, milestone_month")
        key, shape = row["item_key"], row["shape"]
        if not isinstance(key, str) or not _KEY.match(key):
            raise ProfileError("CAPEX_PROFILE_ITEM_KEY_INVALID", repr(key))
        try:
            shape_enum = ProfileShape(shape)
        except ValueError as exc:
            raise ProfileError("CAPEX_PROFILE_SHAPE_INVALID", repr(shape)) from exc
        percents = row["explicit_percent"]
        if not isinstance(percents, list) or len(percents) > 60 or not all(isinstance(p, str) for p in percents):
            raise ProfileError("CAPEX_PROFILE_DOCUMENT_INVALID", "explicit_percent must be a list of strings")
        milestone = row["milestone_month"]
        if milestone is not None and (isinstance(milestone, bool) or not isinstance(milestone, int)):
            raise ProfileError("CAPEX_PROFILE_MILESTONE_MONTH_INVALID", repr(milestone))
        if shape_enum is ProfileShape.EXPLICIT and not percents:
            raise ProfileError("CAPEX_PROFILE_PERIOD_COUNT_MISMATCH", "explicit profile has no weights")
        if shape_enum is not ProfileShape.EXPLICIT and percents:
            raise ProfileError("CAPEX_PROFILE_DOCUMENT_INVALID", f"{shape_enum.value} takes no explicit_percent")
        if shape_enum is ProfileShape.MILESTONE and milestone is None:
            raise ProfileError("CAPEX_PROFILE_MILESTONE_MONTH_INVALID", "missing")
        if shape_enum is not ProfileShape.MILESTONE and milestone is not None:
            raise ProfileError("CAPEX_PROFILE_DOCUMENT_INVALID", f"{shape_enum.value} takes no milestone_month")
        specs.append(ProfileSpec(key, shape_enum, tuple(percents), milestone, SOURCE_PERSISTED))
    reject_duplicates(specs)
    return tuple(specs)


def to_document(specs) -> dict:
    return {"version": VERSION, "profiles": [
        {"item_key": s.item_key, "shape": ProfileShape(s.shape).value, "explicit_percent": list(s.explicit_percent),
         "milestone_month": s.milestone_month} for s in sorted(specs, key=lambda s: s.item_key)]}


def canonical_json(raw) -> str:
    """Canonical stored text ('' when there is no profile).  Idempotent for stored values."""
    specs = parse(raw)
    if not specs:
        return ""
    return json.dumps(to_document(specs), sort_keys=True, separators=(",", ":"), allow_nan=False)
