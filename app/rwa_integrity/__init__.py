"""RWA Integrity & Trust Intelligence V1.

Read-intelligence over existing canonical authorities: answers, with
explicit typed evidence, what FINCO knows about one tokenized
representation — identity completeness, market/reference/attestation
evidence state, and observable structural dependency risks.

This vertical is NOT a market-data provider, trading feature, custody
feature, valuation model, or opaque rating engine.  V1 exposes an
evidence matrix with deterministic states; no composite trust score
exists in V1.  No external attestation evidence is invented: where no
approved source exists, state is UNAVAILABLE and that truth is preserved.
"""
from app.rwa_integrity.contracts import (
    AttestationEvaluation,
    BackingAttestationEvidence,
    EvidenceState,
    IdentityFlag,
    evaluate_attestations,
)
from app.rwa_integrity.read_model import (
    RepresentationIntegrityProfile,
    UnderlyingIntegrityView,
    build_representation_integrity,
    build_underlying_integrity,
    list_integrity_profiles,
)

__all__ = [
    "AttestationEvaluation",
    "BackingAttestationEvidence",
    "EvidenceState",
    "IdentityFlag",
    "RepresentationIntegrityProfile",
    "UnderlyingIntegrityView",
    "build_representation_integrity",
    "build_underlying_integrity",
    "evaluate_attestations",
    "list_integrity_profiles",
]
