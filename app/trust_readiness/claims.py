"""Claim-safety rules for trust and readiness surfaces (WF-10A).

A certification, attestation, compliance or quality-grade term may appear in text only in a
sentence that also carries a negation or conditionality cue ("does not claim", "none is
held", "requires legal approval"). Anything else is an unsupported claim.

Pure functions over strings and files: no I/O beyond reading the paths it is given.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# (label, pattern). Patterns are case-insensitive unless noted.
_DENY: tuple[tuple[str, str], ...] = (
    ("SOC 2", r"\bSOC[\s-]?2\b"),
    ("ISO 27001", r"\bISO(?:\s*/\s*IEC)?[\s-]*27001\b"),
    ("FAST Standard", r"(?-i:\bFAST\b)"),
    ("IFC", r"(?-i:\bIFC\b)"),
    ("certification", r"\bcertifi(?:ed|cation|cations)\b"),
    ("compliance", r"\bcompl(?:iant|iance)\b"),
    ("audited", r"\baudited\b"),
    ("penetration test", r"\bpen(?:etration)?[\s-]?test(?:ed|ing|s)?\b"),
    ("regulation", r"\b(?:GDPR|HIPAA|CCPA)\b"),
    ("quality grade", r"\b(?:institutional|bank|military|enterprise)[\s-]grade\b"),
    ("absolute security", r"\b(?:100\s*%\s*secure|unhackable|fully secure|guaranteed secure)\b"),
    ("lender approval", r"\blender[\s-](?:approved|accepted)\b"),
)
_DENY_RE = tuple((label, re.compile(p, re.IGNORECASE)) for label, p in _DENY)

_NEGATION = re.compile(
    r"\b(?:not|no|never|none|neither|nor|without|cannot|requires?|required|unless|until|"
    r"pending|proposed|open|unsupported)\b|n't",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>|\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class Violation:
    label: str
    sentence: str
    source: str = ""


def _plain(text: str) -> str:
    return _TAG.sub(" ", text).replace("&nbsp;", " ").replace("&amp;", "&")


def scan_text(text: str, source: str = "") -> list[Violation]:
    """Return every deny-listed term used outside a negated or conditional sentence."""
    out: list[Violation] = []
    for raw in _SENTENCE.split(_plain(text)):
        sentence = " ".join(raw.split())
        if not sentence:
            continue
        for label, rx in _DENY_RE:
            if rx.search(sentence) and not _NEGATION.search(sentence):
                out.append(Violation(label, sentence[:200], source))
    return out


def scan_file(path: Path, root: Path) -> list[Violation]:
    return scan_text(path.read_text(encoding="utf-8", errors="ignore"), str(path.relative_to(root)))


# Labels that are unambiguous enough to scan the whole repository's public documents and
# templates for. The wider deny-list is applied to the trust surfaces only, because ordinary
# prose elsewhere uses words such as "audited against" in a different sense.
REPO_WIDE_LABELS: frozenset[str] = frozenset({
    "SOC 2", "ISO 27001", "FAST Standard", "IFC", "quality grade", "absolute security",
    "lender approval", "regulation",
})

# Pre-existing unsupported phrases elsewhere in the repository. They are documented as known
# gaps (gap.pre_existing_grade_claim) and pinned by a test; this pack does not edit them.
PRE_EXISTING_BASELINE: frozenset[tuple[str, str]] = frozenset({
    ("docs/external_pilot_guide.md", "quality grade"),
})
