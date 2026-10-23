# PR #346 exact-content Financial Owner decision

Reference: `conversation:2026-10-22:PR346:Correction-D:section-1`.

Basis: explicit user-provided Financial Owner statement in this conversation on
2026-10-22, Correction D section 1. This is not a signed GitHub review or a
cryptographic owner attestation. Existing Radar content governance requires
reviewed code-level content pins; it does not require a signed GitHub attestation.
The statement authorizes this exact content recognition and CI closure only.

Source request SHA256: `e49043bc8e976becc2bbdae2291a1e33f35189f25b596bed3aa013a2aaefd0a4`.

## Verbatim decision section

The Financial Owner explicitly approved the following exact Git blob contents in the current conversation on 2026-10-22:

**Approved protected source 1**

Path: `app/radar_rwa/r_live_snapshot_store.py`

Git blob SHA-1: `4179c296c803f42040b2811dc70ef55a1cdfa1d0`

**Approved protected source 2**

Path: `app/radar_rwa/r_live_warming.py`

Git blob SHA-1: `563c1a256886f7b26af21ac63e121216f908c840`

**Approval scope:** Exact-content governance successor and CI closure for PR #346 only.

**Not authorized:** Production activation, deployment, hosted shadow execution, Phase 4 activation or automatic merge.

The previously proposed warming blob `9635b99e1d06f91b701dc8c4b2ffda97be839fea` is superseded and MUST NOT be recognized by the new successor.

Do not interpret this owner statement as a cryptographically signed GitHub attestation. Preserve the actual approval reference accurately. If an independently authenticated attestation is mandatory under the existing governance contract, report that specific unmet requirement rather than fabricating one.

## Non-circular source chain

Original reviewed PR source: `a0d243c7d9c88d16990da9115e00ed00e3ad8160` / tree `864382c8ac955c72ee6ccad15ee86be373de8edd`.

Corrected protected-source commit: `a385e67fb71acebe00b2fe6f2f23c3f248614a86` / tree `82f7f27d70285afcdab598c4e72f2770d808c2ec`.
This earlier commit contains both approved source blobs and the CLI tests. It
contains no successor approval record. The later governance commit records and
pins this predecessor; its own commit hash is not used to authorize itself.
Final governance HEAD/tree and exact-head CI are reported independently in the
handoff after commit and execution. The original reviewed PR HEAD does not
contain the newly approved CLI blob and is never represented as doing so.

No merge, deployment, image publication, hosted shadow or Phase 4 activation is
approved by this decision. Other pilot policy and spending decisions remain separate.
