"""Canonical current-state recognition of the release-closed quarterly candidate for the current-authority guards.

One import point instead of per-guard wiring. It answers: "is the tree under test exactly one of the recognised release-closed quarterly candidates?"

* ``rc7b_postmerge_successor`` - the twelve RC-7B blobs as merged by PR #320 (recognised only while NOTHING in the twelve changes; unchanged contract), or
  (pre-merge, never active in this repository) a complete authentic Gate R;
* ``rc7c_candidate_successor`` - eight unchanged RC-7B blobs + the four explicitly pinned RC-7C blobs (candidate policy ``rc7c-quarterly-candidate-v2``);
* ``v9p2a_odr_successor`` - RC-7C at its immutable checkpoints, then exactly six OD-R paths (Financial Owner exact-content decision on the four new
  blobs; two carried blobs), every other RC-7C path unchanged. ``CANDIDATE_PATHS`` stays the twelve; the OD-R state adds its two new paths.
* ``v10_native_shadow_successor`` - OD-R at its immutable checkpoint (main ``0b57031a``), then exactly the V10 dormant native-shadow paths
  (Financial Owner exact-content decision for PR #347); every other path unchanged. Content recognition only: no release, no activation.
* ``v11_stage3_successor`` - V10 at its immutable checkpoint (main ``9e712e21``), then exactly the V11 Stage 3 native senior-debt
  candidate paths (one Financial Owner exact-content decision for Stage 3a + 3b); every other path, incl. every approved V10 native
  source and manifest, unchanged. Content recognition only: no release, no activation, no V10 reseal.

Recognition grants bytes on a branch/main ONLY. It is not Financial Owner approval, not D-01..D-12 approval, not Gate P, not product admission, not
activation and not a financial release; ``approved_frozen_path`` and ``released_engine_authority_matches`` never consult it. The historical pin maps
(M7 / PPA-01 / WF-04 / WF-07 / F3) are never rewritten: a recognised path is judged against ``candidate_blobs()``, every other path against its pin.
"""
from __future__ import annotations

try:
    import rc7b_postmerge_successor as rc7b
    import rc7c_candidate_successor as rc7c
    import rc7b_quarterly_candidate_authority as authority
    import v9p2a_odr_successor as odr
except ModuleNotFoundError:          # imported as ``tests.quarterly_candidate_recognition``
    from tests import rc7b_postmerge_successor as rc7b
    from tests import rc7c_candidate_successor as rc7c
    from tests import rc7b_quarterly_candidate_authority as authority
    from tests import v9p2a_odr_successor as odr
try:
    import v10_native_shadow_successor as v10
except ModuleNotFoundError:
    from tests import v10_native_shadow_successor as v10
try:
    import v11_stage3_successor as v11
except ModuleNotFoundError:
    from tests import v11_stage3_successor as v11

CANDIDATE_PATHS = tuple(authority.RC7B_CANDIDATE_AUTHORITIES)           # the same twelve protected paths in every recognised state


def recognized_state(*, repo=None, ref: str = "HEAD", fetcher=None) -> str | None:
    """``"RC7B"`` (twelve RC-7B blobs), ``"RC7C"`` (eight RC-7B + four RC-7C blobs), ``"ODR"`` (RC-7C + the six exact OD-R blobs),
    ``"V10"`` (OD-R + the exact V10 dormant native-shadow blobs), ``"V11S3"`` (V10 + the exact V11 Stage 3 blobs) or None. The states
    are mutually exclusive by blob identity."""
    if rc7b.candidate_recognized(repo=repo, ref=ref, fetcher=fetcher):
        return "RC7B"
    if rc7c.rc7c_recognized(repo=repo, ref=ref):
        return "RC7C"
    if odr.odr_recognized(repo=repo, ref=ref):
        return "ODR"
    if v10.v10_recognized(repo=repo, ref=ref):
        return "V10"
    if v11.v11_recognized(repo=repo, ref=ref):
        return "V11S3"
    return None


def candidate_recognized(*, repo=None, ref: str = "HEAD", fetcher=None) -> bool:
    return recognized_state(repo=repo, ref=ref, fetcher=fetcher) is not None


def candidate_blobs(*, repo=None, ref: str = "HEAD", fetcher=None) -> dict:
    """Pinned blobs of the recognised state ({} when nothing is recognised)."""
    state = recognized_state(repo=repo, ref=ref, fetcher=fetcher)
    if state == "RC7B":
        return dict(authority.RC7B_CANDIDATE_AUTHORITIES)
    if state == "RC7C":
        return dict(rc7c.RC7C_CANDIDATE_AUTHORITIES)
    if state == "ODR":
        return odr.odr_candidate_authorities()
    if state == "V10":
        return v10.v10_candidate_authorities()
    if state == "V11S3":
        from tests.fin_v2_cohorts import protected_blobs
        return {**v11.v11_candidate_authorities(), **protected_blobs(repo, ref)}
    return {}


def scope_exempt(path: str, *, repo=None, ref: str = "HEAD", fetcher=None) -> bool:
    """One of the exact paths of the recognised candidate while the whole candidate is present. Never consulted by ``approved_frozen_path``."""
    return path in candidate_blobs(repo=repo, ref=ref, fetcher=fetcher)


superseded = scope_exempt            # same predicate; the guards that compare against historical pins read better with this name


def current_expected_blob(path: str, historical_pin, *, repo=None, ref: str = "HEAD", fetcher=None):
    """The recognised candidate blob for a recognised path, otherwise the historical pin (which is never rewritten)."""
    blobs = candidate_blobs(repo=repo, ref=ref, fetcher=fetcher)
    return blobs[path] if path in blobs else historical_pin


def without_superseded(paths, *, repo=None, ref: str = "HEAD", fetcher=None) -> list[str]:
    from tests.fin_v2_cohorts import matches
    return [p for p in paths if not superseded(p, repo=repo, ref=ref, fetcher=fetcher)
            and not matches(p, repo=repo)]
