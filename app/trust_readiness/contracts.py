"""Typed contracts for the FINCO Model trust and release-readiness foundation (WF-10A).

This package states what the product does and does not do about security, privacy,
retention and release readiness, and ties every statement to evidence in the repository.
It never touches the financial engine, financial inputs, workspace writers, Radar or any
runtime path: it is read-only documentation-as-code.

Four statuses, deliberately separated so that a reader can never mistake an intention for
a control:

* ``IMPLEMENTED_VERIFIED``         - exists in code today AND an automated check proves it.
* ``PROPOSED``                     - engineering direction that is not built.
* ``REQUIRES_LEGAL_APPROVAL``      - cannot be stated or published until counsel approves it.
* ``REQUIRES_OPERATIONAL_CONTROLS``- depends on deployment, hosting or process controls that
                                     the repository cannot prove.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReadinessStatus(str, Enum):
    IMPLEMENTED_VERIFIED = "IMPLEMENTED_VERIFIED"
    PROPOSED = "PROPOSED"
    REQUIRES_LEGAL_APPROVAL = "REQUIRES_LEGAL_APPROVAL"
    REQUIRES_OPERATIONAL_CONTROLS = "REQUIRES_OPERATIONAL_CONTROLS"


STATUS_LABEL = {
    ReadinessStatus.IMPLEMENTED_VERIFIED: "Implemented and verified",
    ReadinessStatus.PROPOSED: "Proposed",
    ReadinessStatus.REQUIRES_LEGAL_APPROVAL: "Requires legal approval",
    ReadinessStatus.REQUIRES_OPERATIONAL_CONTROLS: "Requires operational controls",
}

STATUS_MEANING = {
    ReadinessStatus.IMPLEMENTED_VERIFIED:
        "Present in the code today, and an automated test or CI gate in this repository proves it.",
    ReadinessStatus.PROPOSED:
        "A direction under consideration. It is not built and must not be relied on.",
    ReadinessStatus.REQUIRES_LEGAL_APPROVAL:
        "Cannot be stated or published as a commitment until it has been approved by counsel.",
    ReadinessStatus.REQUIRES_OPERATIONAL_CONTROLS:
        "Depends on hosting, deployment or process controls that the repository cannot prove.",
}


class EvidenceKind(str, Enum):
    CODE = "CODE"   # a source file that implements the behaviour
    TEST = "TEST"   # an automated test that proves it
    CI = "CI"       # a CI workflow gate (counts as both implementation and verification)
    DOC = "DOC"     # a design or policy document


@dataclass(frozen=True)
class EvidenceRef:
    """A pointer into the repository. ``anchor`` is text that must appear in the file."""

    kind: EvidenceKind
    path: str
    anchor: str


@dataclass(frozen=True)
class ReadinessItem:
    key: str
    area: str
    title: str
    status: ReadinessStatus
    statement: str
    evidence: tuple[EvidenceRef, ...] = ()
    limitation: str = ""


class GapSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class KnownGap:
    """A verified deviation from what a reader would reasonably expect.

    Every gap is pinned by a test, so closing it forces this record to be updated.
    """

    key: str
    title: str
    severity: GapSeverity
    statement: str
    recommended_action: str
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class DataStoreEntry:
    """One category of data the product stores or handles."""

    key: str
    data_category: str
    store: str
    tenant_key: str
    contents: str
    may_contain_user_text: bool
    retention_rule: str
    deletion_path: str
    automatic_deletion: bool
    status: ReadinessStatus
    evidence: tuple[EvidenceRef, ...] = ()
    limitation: str = ""
    tables: tuple[str, ...] = ()


@dataclass(frozen=True)
class NotClaimed:
    label: str
    statement: str


@dataclass(frozen=True)
class LegalDocument:
    key: str
    title: str
    publication_state: str
    approval_required: str
    note: str
