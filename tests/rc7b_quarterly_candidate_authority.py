"""RC-7B matched 3/3 successor governance contract - exact-content RECOGNITION only. Not an approval, not a release.

The RC-7B integration legitimately changes twelve protected financial paths (financial_engine / finco_core). Following the
RC-3 C2 PPA-01 precedent, this module keeps the questions apart and never collapses them into one boolean:

``research_isolated``                    the PR #313 research package under ``tools/quarterly_research/`` is byte-identical to the
                                        predecessor (research stays an independent validation reference, never production).
``candidate_content_matches_exactly``   the tree carries EXACTLY the twelve reviewed RC-7B blobs, no other protected path differs from the
                                        immutable predecessor (main ``5be8c4b1``), the reviewed source head is an ancestor, the historical
                                        authority maps are byte-identical and ``quarterly_frequency_config.ACTIVATION_ENABLED`` is a literal
                                        ``False``. This is a statement about bytes; it lets the frozen-scope gates tell "the candidate" from "an
                                        unauthorized change".
``candidate_is_financially_approved``   a SEPARATE committed record ``docs/model_v2/RC7B_QUARTERLY_FINANCIAL_ACCEPTANCE.json`` names a human
                                        independent reviewer AND the financial owner, the reviewed source head, the exact blobs and the owner
                                        decisions D-01..D-12. It does not exist: the answer is False.
``candidate_is_product_admitted``       approval AND the activation flag opened by a separate change. Unavailable while closed.
``candidate_is_released``               admission AND an explicit release authorization in the record. Unavailable.

The historical pin maps in ``tests/model_v2_governance.py`` (Developer Economics, F3, WF04, WF07, Revenue V2/V3, F3.5-A), the M7 eleven-blob
and PPA-01 three-blob candidates are not touched, extended or reinterpreted: each is judged at its own checkpoint. A changed byte in any of the
twelve blobs, a missing or substituted path, any other protected change, an opened flag or a forged record exempts NOTHING.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Immutable predecessor (main after PR #313) and the reviewed RC-7B source head carrying the final protected content.
RC7B_PREDECESSOR = "5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d"
RC7B_REVIEWED_SOURCE_HEAD = "4b086b83e207249c807cc0521a14f78812ac8be3"
PROTECTED_PREFIXES = ("financial_engine/", "finco_core/", "domain/")

# Predecessor blobs (``None`` = new file) and the exact RC-7B candidate blobs: the approved changed-file inventory.
RC7B_PREDECESSOR_BLOBS = {
    "financial_engine/adapters/project_inputs.py": "14bd759a9958515a7796626f93c1bd2233d69150",
    "financial_engine/adapters/tax_inputs.py": "0150eb1cdb9e7c0968e1f8dcbf754266d0158f8a",
    "financial_engine/financing/generic_product_policy.py": "2894334e7241c4ac9f8967d4ce4ca6ce77a32fa0",
    "financial_engine/financing/project.py": "30536cec8779fdb6a490d82fd80bfce2c09e16fe",
    "financial_engine/financing/quarterly_scope.py": None,
    "financial_engine/inputs.py": "8ba4cd3e7de248e163ba727a59e3faa6757edd03",
    "financial_engine/orchestrator.py": "be7ac31c6c4fed43b5fd7ca49fe53bfd1cc54c03",
    "financial_engine/senior_debt/project_adapter.py": "a73611a117f0c04ecc7bd7350eac64456520f265",
    "finco_core/engine/calendar_policy.py": None,
    "finco_core/engine/period_engine.py": "7a44c10b003aee9e8d41de33490db1bb0bdcfd71",
    "finco_core/inputs/_models.py": "b896d3c071ee22c1c82c48f23d4c169e058c7a7b",
    "finco_core/inputs/serialization.py": "31f70570376b2f5b50ece583c54c1d9811e90a3c",
}
RC7B_CANDIDATE_AUTHORITIES = {
    "financial_engine/adapters/project_inputs.py": "d97ae939559cbd6e031414192fa23fc40be1110f",
    "financial_engine/adapters/tax_inputs.py": "9e271f696b4dfa8dcfef44387b2b4b3c1842c63e",
    "financial_engine/financing/generic_product_policy.py": "59a2c1f868b4c12718a22919c3114f3af5af5120",
    "financial_engine/financing/project.py": "2e18a6e7c8ddfd85929d9b1906f91dd8858d0044",
    "financial_engine/financing/quarterly_scope.py": "0bcf6605c84d8716dc07a111cdf911eb0a6bac60",
    "financial_engine/inputs.py": "6fb5913a6cedec3b526b26fc4b55340a8a682361",
    "financial_engine/orchestrator.py": "07aa1e18cc72a1422fcf7fc779dd72ee835c8096",
    "financial_engine/senior_debt/project_adapter.py": "b2302be9d9760ab7a663ff873e95415a4bf18842",
    "finco_core/engine/calendar_policy.py": "91f55f9b8356ae0b8b1ca635b28d008949a8146f",
    "finco_core/engine/period_engine.py": "465c172d5d7176f294872fd2e9542315e3027db2",
    "finco_core/inputs/_models.py": "a48139b9e2aed875d6f3a8358f2c53e9489983c7",
    "finco_core/inputs/serialization.py": "7e678450304467fce435d6052e78af76171b03f7",
}
RESEARCH_PATHS = ("tools/quarterly_research/__init__.py", "tools/quarterly_research/calculation.py",
                  "tools/quarterly_research/calendar.py", "tools/quarterly_research/runtime.py")
HISTORICAL_AUTHORITY_FILES = ("tests/model_v2_governance.py", "tests/m7_rc3_candidate_successor.py",
                              "tests/radar_authority_governance.py")
RELEASE_FLAG = ("app/workbook/quarterly_frequency_config.py", "ACTIVATION_ENABLED")
ACCEPTANCE_RECORD = "docs/model_v2/RC7B_QUARTERLY_FINANCIAL_ACCEPTANCE.json"
REQUIRED_DECISIONS = tuple(f"D-{n:02d}" for n in range(1, 13))
# Reviewer identities that can never count as an independent reviewer or the financial owner.
NOT_INDEPENDENT = re.compile(r"claude|anthropic|assistant|agent|bot|\bai\b|gpt|author|self", re.I)


def _git(root, *args: str):
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def blob(path: str, *, repo=None, ref: str = "HEAD"):
    return _git(repo or ROOT, "rev-parse", f"{ref}:{path}")


def candidate_blobs_match(*, repo=None, ref: str = "HEAD") -> bool:
    """Blob identity of ALL twelve paths (a partial slice is not the candidate)."""
    return all(blob(p, repo=repo, ref=ref) == b for p, b in RC7B_CANDIDATE_AUTHORITIES.items())


def collect(*, repo=None, ref: str = "HEAD") -> dict:
    root = repo or ROOT
    from tests.test_rc2_integration_manifest import activation_state
    predecessor_ok = _git(root, "rev-parse", f"{RC7B_PREDECESSOR}^{{commit}}") == RC7B_PREDECESSOR and subprocess.run(
        ["git", "merge-base", "--is-ancestor", RC7B_PREDECESSOR, ref], cwd=str(root), capture_output=True).returncode == 0
    changed = (_git(root, "diff", "--name-only", "--no-renames", RC7B_PREDECESSOR, ref, "--", *PROTECTED_PREFIXES)
               if predecessor_ok else None)
    flag_source = _git(root, "show", f"{ref}:{RELEASE_FLAG[0]}")
    record_text = _git(root, "show", f"{ref}:{ACCEPTANCE_RECORD}")
    try:
        record = json.loads(record_text) if record_text is not None else None
    except ValueError:
        record = "malformed"
    return {
        "blobs": {p: blob(p, repo=root, ref=ref) for p in RC7B_CANDIDATE_AUTHORITIES},
        "source_blobs": {p: blob(p, repo=root, ref=RC7B_REVIEWED_SOURCE_HEAD) for p in RC7B_CANDIDATE_AUTHORITIES},
        "predecessor_blobs": {p: blob(p, repo=root, ref=RC7B_PREDECESSOR) for p in RC7B_CANDIDATE_AUTHORITIES},
        "source_head_ancestor": subprocess.run(["git", "merge-base", "--is-ancestor", RC7B_REVIEWED_SOURCE_HEAD, ref],
                                               cwd=str(root), capture_output=True).returncode == 0,
        "predecessor_valid": predecessor_ok,
        "protected_changes": sorted(changed.splitlines()) if changed is not None else None,
        "historical_authorities_unchanged": all(
            blob(p, repo=root, ref=ref) is not None and blob(p, repo=root, ref=ref) == blob(p, repo=root, ref=RC7B_PREDECESSOR)
            for p in HISTORICAL_AUTHORITY_FILES),
        "research_unchanged": all(
            blob(p, repo=root, ref=ref) is not None and blob(p, repo=root, ref=ref) == blob(p, repo=root, ref=RC7B_PREDECESSOR)
            for p in RESEARCH_PATHS),
        "activation": activation_state(flag_source + "\n", RELEASE_FLAG[1]) if flag_source is not None else "MISSING",
        "record": record,
    }


def content_violations(facts) -> list[str]:
    """Exact-content check ONLY. [] means the bytes are the reviewed release-closed candidate (not that they are accepted)."""
    try:
        bad = []
        if facts["predecessor_valid"] is not True:
            bad.append("the immutable predecessor main is unavailable or not an ancestor")
        if facts["source_head_ancestor"] is not True:
            bad.append("the reviewed RC-7B source head is not an ancestor")
        if facts["historical_authorities_unchanged"] is not True:
            bad.append("historical financial authority maps changed or are unavailable")
        if facts["research_unchanged"] is not True:
            bad.append("the isolated research reference under tools/quarterly_research changed")
        if facts["activation"] != "CLOSED":
            bad.append(f"quarterly activation is not a literal release-closed False ({facts['activation']})")
        for path, pin in RC7B_CANDIDATE_AUTHORITIES.items():
            if facts["blobs"].get(path) != pin:
                bad.append(f"{path}: not the exact reviewed candidate blob")
            if facts["source_blobs"].get(path) != pin:
                bad.append(f"{path}: the reviewed source head does not carry this blob")
            if facts["predecessor_blobs"].get(path) != RC7B_PREDECESSOR_BLOBS[path]:
                bad.append(f"{path}: predecessor identity differs from the recorded original authority")
        extra = set(facts["blobs"]) - set(RC7B_CANDIDATE_AUTHORITIES)
        if extra:
            bad.append(f"substituted or extra protected files: {sorted(extra)}")
        changes = facts["protected_changes"]
        if changes is None:
            bad.append("the protected-path diff against the immutable predecessor is unavailable")
        else:
            unlisted = [p for p in changes if p not in RC7B_CANDIDATE_AUTHORITIES]
            if unlisted:
                bad.append(f"unlisted financial/core/domain changes: {unlisted}")
            missing = [p for p in RC7B_CANDIDATE_AUTHORITIES if p not in changes]
            if missing:
                bad.append(f"partial slice: reviewed protected files are not part of the change: {missing}")
        return bad
    except (KeyError, TypeError, AttributeError) as exc:
        return [f"facts incomplete or malformed: {exc!r}"]


def acceptance_violations(facts) -> list[str]:
    """The financial approval gate: empty ONLY with a valid, separate, independent acceptance record."""
    problems = content_violations(facts)
    try:
        record = facts["record"]
        if record is None:
            return problems + ["FINANCIAL_OWNER_APPROVAL_REQUIRED: no independent RC-7B acceptance record exists"]
        if not isinstance(record, dict):
            return problems + ["acceptance record is malformed"]
        for label in ("independent_reviewer", "financial_owner"):
            who = record.get(label)
            if not isinstance(who, str) or not who.strip() or NOT_INDEPENDENT.search(who):
                problems.append(f"acceptance record does not identify a human {label.replace('_', ' ')}")
        if record.get("reviewed_source_head") != RC7B_REVIEWED_SOURCE_HEAD:
            problems.append("acceptance record names a different source head than the reviewed one")
        if record.get("accepted_blobs") != RC7B_CANDIDATE_AUTHORITIES:
            problems.append("acceptance record does not repeat the exact twelve blobs")
        decisions = record.get("owner_decisions")
        if not isinstance(decisions, dict) or set(decisions) != set(REQUIRED_DECISIONS) or any(
                not isinstance(v, str) or not v.strip() for v in decisions.values()):
            problems.append("acceptance record does not record owner decisions D-01..D-12")
        if record.get("scope") != "CANDIDATE_CONTENT_ONLY":
            problems.append("acceptance must be candidate-content only; admission and release stay separate decisions")
        if not isinstance(record.get("decision_reference"), str) or not record["decision_reference"].strip():
            problems.append("acceptance record carries no decision reference")
        return problems
    except (KeyError, TypeError, AttributeError) as exc:
        return problems + [f"acceptance facts incomplete or malformed: {exc!r}"]


def admission_violations(facts) -> list[str]:
    """Product admission needs approval AND a separately reviewed change opening the flag; content recognition requires it closed."""
    problems = acceptance_violations(facts)
    problems.append("PRODUCT_ADMISSION_NOT_GRANTED: quarterly activation is release-closed")
    return problems


def release_violations(facts) -> list[str]:
    problems = admission_violations(facts)
    record = facts.get("record") if isinstance(facts, dict) else None
    if not (isinstance(record, dict) and record.get("release_authorized") is True):
        problems.append("RELEASE_NOT_AUTHORIZED: acceptance of candidate content is not a release")
    return problems


def states(*, repo=None, ref: str = "HEAD") -> dict:
    """The separate research / content / acceptance / admission / release states (never one boolean)."""
    facts = collect(repo=repo, ref=ref)
    return {
        "research_isolated": facts["research_unchanged"] is True,
        "candidate_content_matches_exactly": content_violations(facts) == [],
        "candidate_is_financially_approved": acceptance_violations(facts) == [],
        "candidate_is_product_admitted": admission_violations(facts) == [],
        "candidate_is_released": release_violations(facts) == [],
    }


def candidate_content_matches_exactly(*, repo=None, ref: str = "HEAD") -> bool:
    return content_violations(collect(repo=repo, ref=ref)) == []


def frozen_scope_exempt(path: str, *, repo=None, ref: str = "HEAD") -> bool:
    """Frozen-namespace recognition for the current-integration guards: one of the twelve exact paths, and only while the WHOLE candidate
    content matches exactly (a modified, partial, substituted or activated candidate exempts nothing). NOT a release and not an approval."""
    return path in RC7B_CANDIDATE_AUTHORITIES and candidate_blobs_match(repo=repo, ref=ref) and candidate_content_matches_exactly(
        repo=repo, ref=ref)


# ═══════════════════════════ Gate R: candidate-boundary authorization ═══════════════════════════
#
# Gate R is NOT a financial approval. It authorizes exactly one thing: carrying the twelve reviewed blobs above as a RELEASE-CLOSED integration
# candidate. It never approves D-01..D-12, Gate P, activation of the quarterly Run, a financial-policy change, product admission, release or merge.
#
# It is INERT unless ALL of the following are verified, and every uncertainty (missing, unsigned, unverifiable, stale, expired, revoked) means REJECT:
#   1. the exact-content facts above hold (twelve blobs, ancestry, change scope, literal ``ACTIVATION_ENABLED = False``, historical files unchanged);
#   2. a committed record ``GATE_R_RECORD`` repeats the exact blobs, the M7 supersession, DEFERRED D-06/D-07 and grants that are all ``False`` except
#      the release-closed boundary itself, and carries an OWNER ATTESTATION: an OpenSSH ``ssh-ed25519`` signature, in the namespace
#      ``GATE_R_OWNER_NAMESPACE``, over the canonical payload of the WHOLE record plus the blobs of every Gate R mechanism file. Text in the record
#      (a "SIGNED" status, a login, a commit author) is never authority; only a valid signature by a key that is BOTH pinned for that login in the
#      reviewed registry ``GATE_R_REGISTRY`` AND currently listed among the owner's GitHub SSH signing keys (removing the key revokes) is. The
#      implementation agent holds no such private key and therefore cannot produce this attestation;
#   3. an authentic GitHub review (fetched live from GitHub, never read from the repository, complete history) exists: state APPROVED, by the named
#      reviewer, who is neither the PR author nor the Financial Owner nor a bot, with a repository-collaborator association, on a commit whose twelve
#      blobs and mechanism-file blobs equal the evaluated ones (a review of other or older content is stale), with no later decisive review by that
#      reviewer and no unresolved CHANGES_REQUESTED from any authorized reviewer.
# The owner attestation is deliberately separate from the independent review, from financial-policy approval (D-01..D-12), from product admission and
# from merge authorization. There is no process-lifetime result cache: immutable Git facts are memoised per commit; live GitHub evidence is cached for
# at most ``GATE_R_EVIDENCE_TTL_SECONDS`` and can be bypassed with ``fresh=True`` at an approval or merge decision boundary.
GATE_R_RECORD = "docs/model_v2/RC7B_GATE_R_AUTHORIZATION.json"
GATE_R_REGISTRY = "docs/model_v2/RC7B_GATE_R_AUTHORITY_REGISTRY.json"
GATE_R_REGISTRY_SCHEMA = "finco.rc7b.gate-r-authority-registry.v1"
GATE_R_SCHEMA = "finco.rc7b.gate-r-candidate-boundary-authorization.v2"
GATE_R_RECORD_TYPE = "GATE_R_CANDIDATE_BOUNDARY_AUTHORIZATION"
GATE_R_SCOPE = "CANDIDATE_BOUNDARY_ONLY"
GATE_R_REPOSITORY = "Finco-Protocol/FincoProtocol"
GATE_R_PULL_NUMBER = 320
GATE_R_ACCEPTED_RESULT = "ACCEPTED_CANDIDATE_CONTENT"
GATE_R_OWNER_NAMESPACE = "finco-rc7b-gate-r-owner-v1"
GATE_R_MAX_VALIDITY_DAYS = 90
GATE_R_CLOCK_SKEW_SECONDS = 300
GATE_R_EVIDENCE_TTL_SECONDS = 20
GATE_R_PAGE_SIZE = 100
GATE_R_MAX_REVIEW_PAGES = 30
GATE_R_DECISIVE_STATES = ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")
GATE_R_GRANTS = {
    "release_closed_integration_of_listed_blobs": True,
    "financial_approval_of_d01_d12": False,
    "gate_p": False,
    "user_activation_of_quarterly_run": False,
    "financial_policy_change": False,
    "product_admission": False,
    "release": False,
    "merge_to_main": False,
}
GATE_R_ALLOWED_DECISION_VALUES = ("NOT_DECIDED_BY_THIS_RECORD", "DEFERRED")
GATE_R_DEFERRED = ("D-06", "D-07")
GATE_R_M7_SUPERSEDED = {
    "financial_engine/orchestrator.py": "be7ac31c6c4fed43b5fd7ca49fe53bfd1cc54c03",
    "financial_engine/adapters/project_inputs.py": "14bd759a9958515a7796626f93c1bd2233d69150",
}
GATE_R_REVIEWER_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")
# The Gate R mechanism. An independent review AND the owner attestation cover THESE bytes together with the twelve blobs; a later change to any of
# them makes the review stale and the attestation invalid. Included: the validator and the owner-signature verifier, the guard wiring, the historical
# stream-provenance mechanism, the Gate R tests, and the registry that pins who may act as Financial Owner.
GATE_R_GOVERNANCE_FILES = (
    "tests/rc7b_quarterly_candidate_authority.py",
    "tests/rc7b_owner_attestation.py",
    "tests/finance_integrity_governance.py",
    "tests/rc3_authority_states.py",
    "tests/stream_scope_proof.py",
    "tests/test_rc7b_gate_r_authorization.py",
    GATE_R_REGISTRY,
    # Workflow permissions and the job that runs the guards: a change here can alter what token the validator sees or whether the guards run.
    ".github/workflows/ci_public_job.yml",
    ".github/workflows/public_safety_and_smoke.yml",
)
_GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_ATTESTATION_ID = re.compile(r"^[0-9a-f]{32,64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class GateRFetchError(Exception):
    """GitHub evidence could not be obtained. ``kind`` distinguishes rate limiting from missing authorization from malformed data; every kind rejects."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind


def _http_get_json(path: str, *, timeout: int = 10):
    """Read-only GitHub REST GET. Uses ``GITHUB_TOKEN``/``GH_TOKEN`` when present (never logged, never written). Raises GateRFetchError."""
    import os
    import urllib.error
    import urllib.request

    request = urllib.request.Request(f"https://api.github.com/{path}", headers={
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "finco-gate-r-validator"})
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:      # noqa: S310 - fixed https GitHub API host
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers is not None else None
        if exc.code == 429 or (exc.code == 403 and remaining == "0"):
            raise GateRFetchError("RATE_LIMITED", f"HTTP {exc.code}") from None
        kinds = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND"}
        raise GateRFetchError(kinds.get(exc.code, "HTTP_ERROR"), f"HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise GateRFetchError("NETWORK", type(exc).__name__) from None
    except ValueError:
        raise GateRFetchError("MALFORMED", "response is not JSON") from None


def github_review_fetcher(pull_number: int = GATE_R_PULL_NUMBER, owner_login=None, *, http=None):
    """Live, COMPLETE evidence: the pull request, every page of its reviews, and (if ``owner_login``) the owner's registered SSH signing keys.

    Raises GateRFetchError on any problem, including an incomplete history (more pages than ``GATE_R_MAX_REVIEW_PAGES`` or an owner with a full
    page of keys). A partial history is never returned, because a missing page could hide a later CHANGES_REQUESTED or DISMISSED review."""
    get = http or _http_get_json
    pull = get(f"repos/{GATE_R_REPOSITORY}/pulls/{pull_number}")
    if not isinstance(pull, dict):
        raise GateRFetchError("MALFORMED", "pull request")
    reviews: list = []
    for page in range(1, GATE_R_MAX_REVIEW_PAGES + 1):
        batch = get(f"repos/{GATE_R_REPOSITORY}/pulls/{pull_number}/reviews?per_page={GATE_R_PAGE_SIZE}&page={page}")
        if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
            raise GateRFetchError("MALFORMED", f"reviews page {page}")
        reviews.extend(batch)
        if len(batch) < GATE_R_PAGE_SIZE:
            break
    else:
        raise GateRFetchError("INCOMPLETE_PAGINATION", f"more than {GATE_R_MAX_REVIEW_PAGES} pages of reviews")
    keys = None
    if owner_login is not None:
        if not isinstance(owner_login, str) or not _GITHUB_LOGIN.match(owner_login):
            raise GateRFetchError("MALFORMED", "owner login")
        listing = get(f"users/{owner_login}/ssh_signing_keys?per_page={GATE_R_PAGE_SIZE}")
        if not isinstance(listing, list) or any(not isinstance(item, dict) for item in listing):
            raise GateRFetchError("MALFORMED", "signing keys")
        if len(listing) >= GATE_R_PAGE_SIZE:
            raise GateRFetchError("INCOMPLETE_PAGINATION", "signing keys")
        keys = [item["key"] for item in listing if isinstance(item.get("key"), str)]
    return {"pull": pull, "reviews": reviews, "owner_signing_keys": keys}


def _is_human_login(value) -> bool:
    return (isinstance(value, str) and bool(_GITHUB_LOGIN.match(value)) and not NOT_INDEPENDENT.search(value)
            and not value.lower().endswith("[bot]"))


def _utc(value):
    from datetime import datetime, timezone
    if not isinstance(value, str) or not _UTC.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def owner_payload(record, mechanism_blobs) -> bytes:
    """The exact bytes the Financial Owner signs: the WHOLE record (so any edit of any field breaks the signature) except the signature itself,
    bound to the repository, pull request, namespace and the blob of every Gate R mechanism file (so changing the mechanism breaks it too)."""
    import copy
    unsigned = copy.deepcopy(record)
    attestation = unsigned.get("owner_attestation") if isinstance(unsigned, dict) else None
    if isinstance(attestation, dict):
        attestation.pop("signature", None)
    body = {"repository": GATE_R_REPOSITORY, "pull_number": GATE_R_PULL_NUMBER, "namespace": GATE_R_OWNER_NAMESPACE,
            "mechanism_blobs": dict(mechanism_blobs), "record": unsigned}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


_SIGNATURE_MEMO: dict = {}


def _signature_problems(armoured, payload: bytes, key) -> list[str]:
    """Pure function of its (immutable) inputs, so memoising it is safe and keeps the guards fast."""
    import hashlib
    try:
        import rc7b_owner_attestation as attestation
    except ImportError:                                           # imported as ``tests.rc7b_...``
        from tests import rc7b_owner_attestation as attestation
    memo_key = (hashlib.sha256(str(armoured).encode()).hexdigest(), hashlib.sha256(payload).hexdigest(), str(key))
    if memo_key not in _SIGNATURE_MEMO:
        _SIGNATURE_MEMO[memo_key] = attestation.verification_problems(armoured, payload, GATE_R_OWNER_NAMESPACE, key)
    return list(_SIGNATURE_MEMO[memo_key])


def _attestation():
    try:
        import rc7b_owner_attestation as module
    except ImportError:
        from tests import rc7b_owner_attestation as module
    return module


def gate_r_record_violations(record, *, registry=None, mechanism_blobs=None, now=None) -> list[str]:
    """Structure, content and OWNER ATTESTATION of the record (no network). ``registry`` and ``mechanism_blobs`` come from the evaluated commit;
    without them the attestation cannot be verified and the record is rejected."""
    if record is None:
        return ["GATE_R_APPROVAL_REQUIRED: no signed Gate R authorization record exists"]
    if not isinstance(record, dict):
        return ["Gate R record is malformed"]
    bad = []
    if record.get("schema") != GATE_R_SCHEMA or record.get("record_type") != GATE_R_RECORD_TYPE:
        bad.append("Gate R record has the wrong schema or record type")
    if record.get("status") != "SIGNED":
        bad.append("Gate R record is not SIGNED (an unsigned template authorizes nothing)")
    if record.get("scope") != GATE_R_SCOPE:
        bad.append("Gate R scope must be CANDIDATE_BOUNDARY_ONLY")
    if record.get("predecessor_main") != RC7B_PREDECESSOR:
        bad.append("Gate R record names a different predecessor main")
    if record.get("reviewed_source_head") != RC7B_REVIEWED_SOURCE_HEAD:
        bad.append("Gate R record names a different reviewed source head")
    if record.get("accepted_blobs") != RC7B_CANDIDATE_AUTHORITIES:
        bad.append("Gate R record does not repeat the exact twelve candidate blobs")
    if record.get("predecessor_blobs") != RC7B_PREDECESSOR_BLOBS:
        bad.append("Gate R record does not repeat the exact predecessor blobs")
    supersession = record.get("supersedes_candidate_blobs")
    if (not isinstance(supersession, dict)
            or {k: v for k, v in supersession.items() if k in GATE_R_M7_SUPERSEDED} != GATE_R_M7_SUPERSEDED
            or supersession.get("m7_supersession_acknowledged_by_reviewer") is not True):
        bad.append("Gate R record does not explicitly acknowledge the supersession of the two shared M7 candidate blobs")
    people = {}
    for label, review_key in (("financial_owner", None), ("independent_reviewer", "review_result")):
        who = record.get(label)
        if not isinstance(who, dict):
            bad.append(f"Gate R record has no {label}")
            continue
        login = who.get("identity_reference")
        people[label] = login
        if not (isinstance(who.get("name"), str) and who["name"].strip() and not NOT_INDEPENDENT.search(who["name"])):
            bad.append(f"Gate R {label} is not a named human")
        if not _is_human_login(login):
            bad.append(f"Gate R {label}.identity_reference must be a human GitHub login")
        stamp = who.get("confirmed_at_utc" if label == "financial_owner" else "reviewed_at_utc")
        if not (isinstance(stamp, str) and stamp.strip()):
            bad.append(f"Gate R {label} carries no confirmation timestamp")
        if review_key and who.get(review_key) != GATE_R_ACCEPTED_RESULT:
            bad.append("Gate R independent review result is not ACCEPTED_CANDIDATE_CONTENT")
    if (isinstance(people.get("financial_owner"), str) and isinstance(people.get("independent_reviewer"), str)
            and people["financial_owner"].lower() == people["independent_reviewer"].lower()):
        bad.append("the independent reviewer must not be the Financial Owner")
    if record.get("grants") != GATE_R_GRANTS:
        bad.append("Gate R grants must be exactly: release-closed integration true, every other grant false")
    decisions = record.get("owner_decisions")
    if not isinstance(decisions, dict):
        bad.append("Gate R record has no owner_decisions block")
    else:
        body = {k: v for k, v in decisions.items() if not k.startswith("_")}
        if set(body) != set(REQUIRED_DECISIONS) or any(v not in GATE_R_ALLOWED_DECISION_VALUES for v in body.values()):
            bad.append("Gate R decides no owner decision: every D-01..D-12 must be NOT_DECIDED_BY_THIS_RECORD or DEFERRED")
        if any(body.get(d) != "DEFERRED" for d in GATE_R_DEFERRED):
            bad.append("D-06 and D-07 must remain DEFERRED")
    if not (isinstance(record.get("decision_reference"), str) and record["decision_reference"].strip()):
        bad.append("Gate R record carries no decision reference")
    review = record.get("github_review")
    if not (isinstance(review, dict) and review.get("pull_number") == GATE_R_PULL_NUMBER
            and isinstance(review.get("review_id"), int) and not isinstance(review.get("review_id"), bool)
            and _is_human_login(review.get("reviewer_login"))):
        bad.append("Gate R record does not reference one GitHub review (pull_number, review_id, reviewer_login)")
    return bad + _owner_attestation_problems(record, registry, mechanism_blobs, now)


def _owner_attestation_problems(record, registry, mechanism_blobs, now) -> list[str]:
    """The Financial Owner's authorization. Everything here must hold; nothing is inferred from text the implementation agent could write."""
    from datetime import datetime, timedelta, timezone
    owner = record.get("financial_owner") if isinstance(record, dict) else None
    attestation = record.get("owner_attestation") if isinstance(record, dict) else None
    if not isinstance(owner, dict) or not isinstance(attestation, dict):
        return ["OWNER_ATTESTATION_REQUIRED: the record carries no owner attestation (a SIGNED status is text, not a signature)"]
    ssh = _attestation()
    bad = []
    key, login = owner.get("signing_key"), owner.get("identity_reference")
    fingerprint = ssh.fingerprint(key)
    if fingerprint is None:
        bad.append("OWNER_KEY_INVALID: financial_owner.signing_key is not a strict ssh-ed25519 public key")
    elif owner.get("signing_key_fingerprint") != fingerprint:
        bad.append("OWNER_KEY_INVALID: the recorded fingerprint is not the fingerprint of the recorded key")
    # who may act as Financial Owner is pinned in the reviewed registry, never by the record itself
    owners = registry.get("financial_owners") if isinstance(registry, dict) and registry.get("schema") == GATE_R_REGISTRY_SCHEMA else None
    if not isinstance(owners, list):
        bad.append("OWNER_REGISTRY_UNAVAILABLE: no valid Financial Owner registry at the evaluated commit")
    else:
        entry = next((e for e in owners if isinstance(e, dict) and isinstance(e.get("login"), str) and isinstance(login, str)
                      and e["login"].lower() == login.lower()), None)
        if entry is None:
            bad.append("OWNER_NOT_REGISTERED: the named Financial Owner is not in the reviewed Financial Owner registry")
        elif fingerprint is None or fingerprint not in (entry.get("ssh_signing_key_fingerprints") or []):
            bad.append("OWNER_KEY_NOT_REGISTERED: the signing key is not pinned for this Financial Owner in the reviewed registry")
    if attestation.get("namespace") != GATE_R_OWNER_NAMESPACE:
        bad.append("OWNER_ATTESTATION_INVALID: wrong namespace")
    if not (isinstance(attestation.get("attestation_id"), str) and _ATTESTATION_ID.match(attestation["attestation_id"])):
        bad.append("OWNER_ATTESTATION_INVALID: attestation_id must be a random 128-bit-or-longer lowercase hex string")
    signed, expires = _utc(attestation.get("signed_at_utc")), _utc(attestation.get("expires_at_utc"))
    current = now or datetime.now(timezone.utc)
    if signed is None or expires is None:
        bad.append("OWNER_ATTESTATION_INVALID: signed_at_utc and expires_at_utc must be UTC timestamps")
    else:
        if signed > current + timedelta(seconds=GATE_R_CLOCK_SKEW_SECONDS):
            bad.append("OWNER_ATTESTATION_INVALID: signed in the future")
        if expires <= signed or expires - signed > timedelta(days=GATE_R_MAX_VALIDITY_DAYS):
            bad.append(f"OWNER_ATTESTATION_INVALID: validity must be positive and at most {GATE_R_MAX_VALIDITY_DAYS} days")
        if current >= expires:
            bad.append("OWNER_ATTESTATION_EXPIRED: the Financial Owner authorization has expired")
    if not isinstance(mechanism_blobs, dict) or set(mechanism_blobs) != set(GATE_R_GOVERNANCE_FILES) or any(
            not isinstance(v, str) for v in mechanism_blobs.values()):
        bad.append("OWNER_ATTESTATION_UNVERIFIABLE: a Gate R mechanism file is missing at the evaluated commit")
    elif fingerprint is not None:
        bad += _signature_problems(attestation.get("signature"), owner_payload(record, mechanism_blobs), key)
    return bad


def _review_integrity_problems(reviews) -> list[str]:
    """Review ordering must be establishable: unique integer ids, and submission times (if present) consistent with the id order."""
    ids = [r.get("id") for r in reviews]
    if any(not isinstance(i, int) or isinstance(i, bool) for i in ids) or len(set(ids)) != len(ids):
        return ["REVIEW_ORDER_UNVERIFIABLE: review ids are missing, malformed or duplicated"]
    stamps = [r.get("submitted_at") for r in sorted(reviews, key=lambda r: r["id"]) if r.get("submitted_at") is not None]
    if any(not isinstance(s, str) for s in stamps) or stamps != sorted(stamps):
        return ["REVIEW_ORDER_UNVERIFIABLE: review submission times are inconsistent with review ids"]
    return []


_BINDING_MEMO: dict = {}


def _commit_binding_problems(root, head: str, commit: str) -> list[str]:
    """Is the reviewed commit an ancestor of the evaluated one, with the twelve blobs and every mechanism file byte-identical? Immutable per SHA pair."""
    key = (str(root), head, commit)
    if key not in _BINDING_MEMO:
        bad = []
        if subprocess.run(["git", "merge-base", "--is-ancestor", commit, head], cwd=str(root), capture_output=True).returncode != 0:
            bad.append("STALE_REVIEW: the reviewed commit is not an ancestor of the evaluated ref")
        for path, pin in RC7B_CANDIDATE_AUTHORITIES.items():
            if blob(path, repo=root, ref=commit) != pin:
                bad.append(f"STALE_REVIEW: {path} at the reviewed commit is not the accepted blob")
        # The review also covers the Gate R mechanism itself: validator, verifier, wiring, provenance proof, registry and tests must be
        # byte-identical to what the reviewer saw.
        for path in GATE_R_GOVERNANCE_FILES:
            at_review, now = blob(path, repo=root, ref=commit), blob(path, repo=root, ref=head)
            if at_review is None or at_review != now:
                bad.append(f"STALE_REVIEW: governance file {path} differs from (or is absent at) the reviewed commit")
        _BINDING_MEMO[key] = bad
    return list(_BINDING_MEMO[key])


def gate_r_review_violations(record, evidence, *, repo=None, ref: str = "HEAD", fetch_error=None) -> list[str]:
    """Authenticity of the independent review and live owner-key evidence against COMPLETE GitHub data. Missing/partial/malformed => rejected."""
    root = repo or ROOT
    if not isinstance(record, dict) or not isinstance(record.get("github_review"), dict):
        return ["no GitHub review is referenced"]
    if (not isinstance(evidence, dict) or not isinstance(evidence.get("reviews"), list) or not isinstance(evidence.get("pull"), dict)
            or any(not isinstance(r, dict) for r in evidence["reviews"])):
        return [f"REVIEW_EVIDENCE_UNVERIFIABLE[{fetch_error or 'UNVERIFIABLE'}]: the GitHub review history could not be fetched completely or is malformed"]
    head = _git(root, "rev-parse", ref) or ref
    ref_review = record["github_review"]
    bad = _review_integrity_problems(evidence["reviews"])
    if bad:
        return bad
    matches = [r for r in evidence["reviews"] if r.get("id") == ref_review.get("review_id")]
    if len(matches) != 1:
        return ["REVIEW_EVIDENCE_UNVERIFIABLE[NOT_FOUND]: the referenced GitHub review was not found in the complete review history"]
    review, pull = matches[0], evidence["pull"]
    login = (review.get("user") or {}).get("login") if isinstance(review.get("user"), dict) else None
    reviewer = record["independent_reviewer"]["identity_reference"]
    owner = record["financial_owner"]["identity_reference"]
    author = (pull.get("user") or {}).get("login") if isinstance(pull.get("user"), dict) else None
    if review.get("state") != "APPROVED":
        bad.append("the GitHub review is not an APPROVED review")
    # A later decisive review by the same reviewer (CHANGES_REQUESTED, DISMISSED or a newer APPROVED on other content) supersedes this one.
    later = [r for r in evidence["reviews"] if isinstance(r.get("user"), dict) and isinstance(login, str)
             and str(r["user"].get("login", "")).lower() == login.lower() and r.get("state") in GATE_R_DECISIVE_STATES and r["id"] > review["id"]]
    if later:
        bad.append("SUPERSEDED_REVIEW: the reviewer submitted a later decisive review")
    # Any authorized reviewer's latest decisive review being CHANGES_REQUESTED blocks Gate R (fail closed). GitHub branch protection is separate
    # and is neither read nor changed here.
    latest: dict = {}
    for r in sorted(evidence["reviews"], key=lambda r: r["id"]):
        who = (r.get("user") or {}).get("login") if isinstance(r.get("user"), dict) else None
        if isinstance(who, str) and r.get("state") in GATE_R_DECISIVE_STATES:
            latest[who.lower()] = r
    for who, r in latest.items():
        if r.get("state") == "CHANGES_REQUESTED" and r.get("author_association") in GATE_R_REVIEWER_ASSOCIATIONS:
            bad.append(f"UNRESOLVED_CHANGES_REQUESTED: {who} has an unresolved change request")
    if not isinstance(login, str) or login.lower() != reviewer.lower() or login.lower() != str(ref_review.get("reviewer_login")).lower():
        bad.append("the GitHub review was not written by the named independent reviewer")
    if not isinstance(author, str) or not author or login is None or login.lower() == author.lower():
        bad.append("the independent reviewer is the PR author or the author is unknown")
    if isinstance(login, str) and login.lower() == str(owner).lower():
        bad.append("the independent reviewer is the Financial Owner")
    if review.get("author_association") not in GATE_R_REVIEWER_ASSOCIATIONS:
        bad.append("the reviewer has no OWNER/MEMBER/COLLABORATOR association with the repository")
    if pull.get("number") != GATE_R_PULL_NUMBER:
        bad.append("the evidence is not about the integration PR")
    # The owner's signing key must STILL be registered on the owner's GitHub account: removing the key revokes the authorization.
    keys = evidence.get("owner_signing_keys")
    pub = _attestation().public_key_from_line(record["financial_owner"].get("signing_key"))
    if not isinstance(keys, list) or pub is None or not any(_attestation().public_key_from_line(k) == pub for k in keys):
        bad.append("OWNER_KEY_REVOKED_OR_UNVERIFIABLE: the owner's signing key is not currently registered on the owner's GitHub account")
    commit = review.get("commit_id")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        return bad + ["the GitHub review names no commit"]
    return bad + _commit_binding_problems(root, head, commit)


_STATIC_MEMO: dict = {}


def _static_facts(root, head: str) -> dict:
    """Everything derived from immutable Git objects of ONE commit. Content-addressed, so memoising per (repository, SHA) cannot go stale."""
    key = (str(root), head)
    if key not in _STATIC_MEMO:
        record_text = _git(root, "show", f"{head}:{GATE_R_RECORD}")
        try:
            record = json.loads(record_text) if record_text is not None else None
        except ValueError:
            record = "malformed"
        registry_text = _git(root, "show", f"{head}:{GATE_R_REGISTRY}")
        try:
            registry = json.loads(registry_text) if registry_text is not None else None
        except ValueError:
            registry = None
        _STATIC_MEMO[key] = {"content": content_violations(collect(repo=root, ref=head)), "record": record, "registry": registry,
                             "mechanism_blobs": {p: blob(p, repo=root, ref=head) for p in GATE_R_GOVERNANCE_FILES}}
    return _STATIC_MEMO[key]


_EVIDENCE_CACHE: dict = {}


def _clock() -> float:
    import time
    return time.monotonic()


def _fetch_evidence(fetcher, record, fresh: bool):
    """(evidence, error_kind). Only a successful default-fetcher result is cached, and only for ``GATE_R_EVIDENCE_TTL_SECONDS``; failures never are."""
    pull_number = record["github_review"]["pull_number"]
    owner = record["financial_owner"]["identity_reference"]
    use_cache = fetcher is None and not fresh
    key = (pull_number, str(owner).lower())
    if use_cache:
        hit = _EVIDENCE_CACHE.get(key)
        if hit is not None and 0 <= _clock() - hit[0] < GATE_R_EVIDENCE_TTL_SECONDS:
            return hit[1], None
    try:
        evidence = (fetcher or github_review_fetcher)(pull_number, owner)
    except GateRFetchError as exc:
        return None, exc.kind
    except Exception:                                                        # noqa: BLE001 - unverifiable evidence must never raise into approval
        return None, "UNVERIFIABLE"
    if evidence is None:
        return None, "UNVERIFIABLE"
    if use_cache:
        _EVIDENCE_CACHE[key] = (_clock(), evidence)
    else:
        _EVIDENCE_CACHE.pop(key, None)
    return evidence, None


def invalidate_gate_r_evidence() -> None:
    _EVIDENCE_CACHE.clear()


def gate_r_violations(*, repo=None, ref: str = "HEAD", fetcher=None, fresh: bool = False, now=None) -> list[str]:
    """Everything that must hold for Gate R. [] means the release-closed candidate boundary is authorized (nothing more).

    ``fresh=True`` bypasses the evidence cache and must be used at every approval or merge decision boundary."""
    root = repo or ROOT
    head = _git(root, "rev-parse", ref)
    if head is None:
        return ["GATE_R_REF_UNRESOLVABLE: the evaluated ref does not resolve"]
    facts = _static_facts(root, head)
    bad = list(facts["content"])
    bad += gate_r_record_violations(facts["record"], registry=facts["registry"], mechanism_blobs=facts["mechanism_blobs"], now=now)
    if bad:
        return bad                                   # never touch the network for a record that is already invalid
    evidence, kind = _fetch_evidence(fetcher, facts["record"], fresh)
    return gate_r_review_violations(facts["record"], evidence, repo=root, ref=head, fetch_error=kind)


def gate_r_scope_exempt(path: str, *, repo=None, ref: str = "HEAD", fetcher=None) -> bool:
    """Frozen-scope recognition for the CURRENT-authority guards: one of the twelve exact paths, and only under an active Gate R (which itself
    requires the whole exact candidate, an authentic owner attestation and an authentic independent review). NOT an approval, NOT a release, NOT a pin:
    it is never consulted by ``approved_frozen_path`` or ``released_engine_authority_matches``."""
    return path in RC7B_CANDIDATE_AUTHORITIES and gate_r_active(repo=repo, ref=ref, fetcher=fetcher)


def gate_r_active(*, repo=None, ref: str = "HEAD", fetcher=None, fresh: bool = False) -> bool:
    """True only when :func:`gate_r_violations` is empty. Fails closed on any error. Cheap when no record is committed (no network)."""
    try:
        root = repo or ROOT
        head = _git(root, "rev-parse", ref)
        if head is None or _git(root, "cat-file", "-e", f"{head}:{GATE_R_RECORD}") is None:
            return False                                # no committed record: reject without any network access
        return gate_r_violations(repo=repo, ref=head, fetcher=fetcher, fresh=fresh) == []
    except Exception:                                    # noqa: BLE001 - fail closed
        return False


def _main(argv) -> int:
    """``python tests/rc7b_quarterly_candidate_authority.py owner-payload <record.json> [ref]`` writes the exact bytes the Financial Owner must sign
    (``ssh-keygen -Y sign -n finco-rc7b-gate-r-owner-v1 -f <owner key> payload.bin``). It signs nothing and decides nothing."""
    import sys
    if len(argv) < 2 or argv[0] != "owner-payload":
        sys.stderr.write("usage: owner-payload <record.json> [ref]\n")
        return 2
    record = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    ref = argv[2] if len(argv) > 2 else "HEAD"
    mechanism = {p: blob(p, ref=ref) for p in GATE_R_GOVERNANCE_FILES}
    if any(v is None for v in mechanism.values()):
        sys.stderr.write("a Gate R mechanism file is missing at the given ref\n")
        return 1
    sys.stdout.buffer.write(owner_payload(record, mechanism))
    return 0


def superseded_by_gate_r(path: str, *, repo=None, ref: str = "HEAD", fetcher=None) -> bool:
    """True only for one of the twelve paths while a complete, authentic Gate R is active.

    Historical exact-content guards (F3 / WF04 / WF07 / M7 / PPA-01 / RC-3 inventory) keep asserting the original pin for every other path and for
    every tree without an active Gate R. For a superseded path they instead assert the Gate R candidate blob AND that the path is only a
    release-closed candidate (never released, never ``approved_frozen_path``). This is recognition of bytes, not financial approval."""
    return path in RC7B_CANDIDATE_AUTHORITIES and gate_r_active(repo=repo, ref=ref, fetcher=fetcher)


def current_expected_blob(path: str, historical_pin, *, repo=None, ref: str = "HEAD", fetcher=None):
    """The blob a current-authority guard must see at ``path``: the Gate R candidate blob for a superseded path, otherwise the historical pin."""
    return RC7B_CANDIDATE_AUTHORITIES[path] if superseded_by_gate_r(path, repo=repo, ref=ref, fetcher=fetcher) else historical_pin


def without_gate_r_superseded(paths, *, repo=None, ref: str = "HEAD", fetcher=None) -> list[str]:
    """``paths`` minus those superseded by an ACTIVE Gate R (identity when Gate R is inactive). Used by the current-authority guards on the OUTPUT of
    ``unapproved_engine_changes`` so that function itself stays byte-identical to its historical checkpoint."""
    return [p for p in paths if not superseded_by_gate_r(p, repo=repo, ref=ref, fetcher=fetcher)]


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
