"""Presentation helpers for ordinary (non-governed) screens: readable evidence values and plain-language reasons.

Nothing here changes data: complex stored values stay available verbatim (as JSON) in a technical-details expander, and every mapped reason keeps its
original typed code visible next to the sentence.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

# Typed reason / status codes -> one plain sentence. Unknown codes fall back to the readable form of the code itself.
REASON_SENTENCES = {
    "LLCR_NOT_PERSISTED": "Loan life cover ratio (LLCR) is not stored with this Run, so it is not shown.",
    "LLCR_REQUIREMENT_NOT_SUPPLIED": "No LLCR requirement has been entered, so there is nothing to compare the LLCR with.",
    "DSRA_TARGET_AUTHORITY_MISSING": "The debt service reserve (DSRA) target is not defined in the inputs, so it cannot be checked.",
    "COVENANT_THRESHOLDS_NOT_SUPPLIED": "Covenant thresholds have not been entered, so covenant headroom cannot be assessed.",
    "MIN_DSCR_COVENANT_NOT_SUPPLIED": "No minimum DSCR covenant has been entered.",
    "LOCKUP_DSCR_NOT_SUPPLIED": "No lock-up DSCR has been entered.",
    "CONTINGENCY_POLICY_NOT_SUPPLIED": "No contingency policy has been entered.",
    "ACTIVE_SCENARIO_NOT_SUPPLIED": "The active scenario was not supplied to this check.",
    "FRESHNESS_NOT_DETERMINED": "Whether these results are current could not be determined.",
    "EVIDENCE_MISSING": "The evidence for this check is not available.",
}


def readable_code(code: Any) -> str:
    text = str(code or "").replace("_", " ").strip().lower()
    return text[:1].upper() + text[1:] if text else ""


def reason_sentence(code: Any) -> str:
    """Plain sentence for a typed reason code; the code itself is shown separately by the caller."""
    key = str(code or "").strip()
    return REASON_SENTENCES.get(key) or readable_code(key)


def is_complex(value: Any) -> bool:
    return isinstance(value, Mapping) or (isinstance(value, (list, tuple)) and not isinstance(value, str))


def evidence_json(value: Any) -> str:
    """The exact stored value as JSON (unserialisable members are shown as text, never dropped)."""
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def evidence_summary(value: Any) -> str:
    if isinstance(value, Mapping):
        return f"{len(value)} recorded item{'s' if len(value) != 1 else ''}"
    if isinstance(value, (list, tuple)):
        return f"{len(value)} recorded row{'s' if len(value) != 1 else ''}"
    return str(value)
