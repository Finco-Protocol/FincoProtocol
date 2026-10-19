"""Immutable HISTORICAL stream-scope proofs (not an approval, not an exemption, not a current-HEAD check).

Dozens of historical tests were written as "this stream changed no frozen financial path" but evaluate ``HEAD`` against ``origin/main``, so they
silently turned into a global freeze check duplicated per stream. Two different questions are kept apart:

* HISTORICAL SOURCE PROOF (this module): the original, immutable source range of ONE accepted stream (its merge base .. its source head, taken
  from the merge that landed it on main) changed no path in the guarded namespaces. This is a fact about that stream and never changes.
* CURRENT INTEGRATION AUTHORITY: whether the protected paths changed by the tree under test are authorized. That is answered ONLY by the
  central current gates (``test_ci_acceptance::test_frozen_financial_namespaces_unmodified``, ``finance_integrity_governance`` and the
  exact-content authority tests). Those gates are untouched and remain mandatory: a stream test that uses this module still does not
  authorize anything about HEAD.

Every range is a literal with its landing merge. ``protected_delta`` verifies the provenance on every call and FAILS CLOSED: if any commit is
missing, the head is not an ancestor of ``origin/main``, the base is not the merge base of the merge's parents, or git cannot answer, it returns a
``PROVENANCE_UNVERIFIED`` marker that is never an empty list, so the calling guard fails instead of passing.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[1]


class StreamRange(NamedTuple):
    base: str      # merge base of the landing merge's two parents
    head: str      # second parent of the landing merge = the stream's source head
    merge: str     # the merge commit on main that landed the stream


# key = the test module that owns the historical claim.
STREAM_RANGES: dict[str, StreamRange] = {
    "test_crypto_p0_product_reality_reset": StreamRange("d2597f2cb31d7b92eb1a65f05c6cb8f8432faac8", "fe88ada8d43ceab503ebde98dcdc4077b54a9a01", "542b1d245c00e5f66de91118e59cccf0bd4e3293"),
    "test_crypto_roadmap_q4_q1": StreamRange("347812cca574a73c64bc71e29296204b3e144cfc", "b7919375a67d08620d0040ff5a65519169e41e96", "6760fb58331df54a2df44da3ea948fbdd15b8120"),
    "test_data_center_a3_1": StreamRange("9136350d26897caccea57f8cf407df8ea7a4401c", "430ef3bfe12a53f9577f3ab89cda02382e3eb272", "2f13a4469bf58342a42825ae5e7e3f89d2cef473"),
    "test_model_market_bridge": StreamRange("a03104300df00f6c4e3b9c46cbdc00ac73c54e71", "ab4e87e79106d5e07368377375570992f3fa7ef4", "b933ebbe67098532d47bb27ce86195dd0862ec86"),
    "test_multi_source_evidence_v2": StreamRange("846f9dfebd2bdab60b6c1a62df8b49b422423e5b", "154bef6e6b5340cf7a0a73a7f312ab62cb29be70", "a269c946ddb35fc4c7e176a9450ea121d8c57438"),
    "test_opus_c1_product_truth": StreamRange("1ac9e03f7386fa5b028cd4231cb6bdb79889bd41", "4ae43134c9bcf082c14c40f7917ed2f99ff66424", "f373c817268b180141574022ca9828b4e5daa794"),
    "test_p0a_model_execution": StreamRange("b933ebbe67098532d47bb27ce86195dd0862ec86", "9a3d99e4cc7bd2491d5d9cf9057c89893e61d84b", "98f64061872b2c4774e6a87bfd4f95ddf7c37673"),
    "test_p1_2_xlsx_export_reconciliation": StreamRange("ef1be8cd4120c4bdc0169239a16e7b76ffc6fda2", "dad078eb703f33699374f40ad705a339ce521947", "29bfbbd3360e5f5d9a4f6832a5bbd8e21ae812b5"),
    "test_p1_3_institutional_validation": StreamRange("dfb86571e18c426d3fc6b87ad8a67a5aa63128e1", "394182eb447a667dff71ce287714122b88a812d4", "412324caf4cd0db79a96c002caae666aafc9950d"),
    "test_p3_run_certificate_v1": StreamRange("c5188af1e1fd22239f77d48d58e23c872b45cd1d", "286f25a2d3c10bf0f91ef804a37037f2104e5b3e", "9f67d91d19905aec74459f0af711a22f427c1dda"),
    "test_public_product_truth_sync": StreamRange("0ea50a3322647252d1e648ef9ba804032e771094", "a87dd70d48ede996d106138c5c069f92b7858c24", "5aa267f56be9671a968df1052b8cdb0fc4ee9f16"),
    "test_radar_crypto_surface_coherence": StreamRange("2f963a77bbad7bda23ca5bac5d6efbe9a11d2b0b", "bc3a018bdfb90a9f802693e986e3685e0ea4daf7", "846f9dfebd2bdab60b6c1a62df8b49b422423e5b"),
    "test_rwa_integrity": StreamRange("6c7f529c98e8c9cf22b4496368740d3bfafb464c", "8186082ebeff29b17cfba3940b385bd442647e36", "d2597f2cb31d7b92eb1a65f05c6cb8f8432faac8"),
    "test_staging_product_truth": StreamRange("77f29ae8fb5db736b998f5ade27cff74e9ab7b5a", "cf5cefd80383e363a53a1a139af29add7428ea77", "7c4655b155d2bdca469501765719c88e050458f9"),
    "test_stock_token_oracle_rejection": StreamRange("aa053c3c3850aa6f600f082eda1046e8cdaef30a", "8f354a846788571a583af7cf4127475f8caa3bdc", "0bb257076158153aa373979ceff33e727e37416c"),
    "test_tokenized_access_wiring": StreamRange("abb39ebfe19a25501280a35023b1e6c583ea15ce", "79758348efe8ae82edaadee7bbb3013d81a59c14", "e6db40d95afb77787df511b3e7f45eb6262cce8f"),
    "test_tokenized_markets_composition": StreamRange("4c0cb488642ff06319db9c99d63b4f4f100f2a23", "a6785ff34c0ef28e95b7d5ea7237a29a8cb1801d", "efa76c682455b6321346d52749e4a45a5159ed6e"),
    "test_yield_alerts_core": StreamRange("347812cca574a73c64bc71e29296204b3e144cfc", "b7919375a67d08620d0040ff5a65519169e41e96", "6760fb58331df54a2df44da3ea948fbdd15b8120"),
    # Streams that landed on main only inside a larger integration merge: the range is the stream's OWN landing merge (second parent = its
    # source head) inside that integration branch, found by descending from the main merge to the first commit that contains the stream's test.
    "test_m3_two_driver_sensitivity": StreamRange("5058c6b4935168241d6923676cb32955cb903185", "0fa0ac5e268a37decbae6bc252487aba3e6e31c9", "2cd6e1545bb4fa90b130d5487bf931f2ad45e877"),
    "test_model_v2_assumption_trace_references": StreamRange("3d2ab9c58838512f3ebc89e3f0369b289a214973", "ceb2046a5d755c067c90a4c2e95d3e475c4d8585", "fbef2191348aa137bcf1c56bb30a6c172f84180e"),
    "test_model_v2_cost_templates": StreamRange("f6e9c5081a1eb1bc2c3d61b58e7ba524f142ca6d", "ff3aa0ec6078cbbef6050c3a333eb923e5b3a5d7", "3d2ab9c58838512f3ebc89e3f0369b289a214973"),
    "test_model_v2_cost_templates_cd": StreamRange("f6e9c5081a1eb1bc2c3d61b58e7ba524f142ca6d", "ff3aa0ec6078cbbef6050c3a333eb923e5b3a5d7", "3d2ab9c58838512f3ebc89e3f0369b289a214973"),
    "test_model_v2_revenue_runtime_parity": StreamRange("c0e254349f62fe6d5aeb5891766ffa8f920065e2", "f1a6df8600b8782d983db4fd237ff2c033062245", "e25c574f7db0fb281babe6804183de5e448ad21b"),
    "test_parallel_stream_frozen_diff": StreamRange("f6e9c5081a1eb1bc2c3d61b58e7ba524f142ca6d", "ff3aa0ec6078cbbef6050c3a333eb923e5b3a5d7", "3d2ab9c58838512f3ebc89e3f0369b289a214973"),
    "test_radar_r3_deepstate_composition": StreamRange("5058c6b4935168241d6923676cb32955cb903185", "6c704f4e799a9dc1a10eb4f10d4e6b9a14f0ea2f", "896b48eab6cd5df760a08d515a3f9ec5bb33561c"),
    "test_radar_r4_tokenized_monitor_v2": StreamRange("6fc77de98bc0562fb51efdbf96e1803a29b5b148", "8378e5df30ec10b4de2b2f5330491837a7cd1ffb", "e2a6efff440c6bc6333caf89501f9a09af6e378a"),
    "test_radar_tokenized_signal_lifecycle": StreamRange("6fc77de98bc0562fb51efdbf96e1803a29b5b148", "9f93dc843eed8f2f2cf7f11cf409fffd003ce70f", "d0e4408beaac21a1d9571026892c00d719668011"),
    "test_tokenized_live_intelligence_v1": StreamRange("f026890448e13af9ef940f41a929d38329738ae5", "26176f47f260ed91dcdf36a56bbe2ff34adce526", "abb39ebfe19a25501280a35023b1e6c583ea15ce"),
}

UNVERIFIED = "PROVENANCE_UNVERIFIED"


def _git(repo, *args: str):
    proc = subprocess.run(["git", *args], cwd=str(repo or REPO), capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def provenance_violations(key: str, *, repo=None, main_ref: str = "origin/main") -> list[str]:
    """[] only when the literal range is exactly the landed stream. Any gap is a violation (fail closed)."""
    rng = STREAM_RANGES.get(key)
    if rng is None:
        return [f"{UNVERIFIED}: no immutable stream range is registered for {key}"]
    bad = []
    for label, sha in (("base", rng.base), ("head", rng.head), ("merge", rng.merge)):
        if _git(repo, "cat-file", "-t", sha) != "commit":
            bad.append(f"{UNVERIFIED}: {label} {sha[:12]} is not an available commit (full history required)")
    if bad:
        return bad
    parents = (_git(repo, "rev-list", "--parents", "-n", "1", rng.merge) or "").split()[1:]
    if len(parents) != 2 or parents[1] != rng.head:
        bad.append(f"{UNVERIFIED}: {rng.head[:12]} is not the second parent of the landing merge {rng.merge[:12]}")
    elif _git(repo, "merge-base", parents[0], parents[1]) != rng.base:
        bad.append(f"{UNVERIFIED}: {rng.base[:12]} is not the merge base of the landing merge's parents")
    if subprocess.run(["git", "merge-base", "--is-ancestor", rng.merge, main_ref], cwd=str(repo or REPO), capture_output=True).returncode != 0:
        bad.append(f"{UNVERIFIED}: the landing merge is not an ancestor of {main_ref}")
    return bad


def protected_delta(key: str, *pathspec: str, repo=None, main_ref: str = "origin/main", diff_filter: str | None = None) -> list[str]:
    """Paths under ``pathspec`` changed by the stream's immutable source range. ``[UNVERIFIED]`` (never ``[]``) if provenance is not proven."""
    bad = provenance_violations(key, repo=repo, main_ref=main_ref)
    if bad:
        return bad
    rng = STREAM_RANGES[key]
    flags = [f"--diff-filter={diff_filter}"] if diff_filter else []
    out = _git(repo, "diff", "--name-only", *flags, rng.base, rng.head, "--", *pathspec)
    if out is None:
        return [f"{UNVERIFIED}: git diff failed for {key}"]
    return sorted(line for line in out.splitlines() if line.strip())


def verified_delta(key: str, *pathspec: str, repo=None, main_ref: str = "origin/main", diff_filter: str | None = None) -> list[str]:
    """``protected_delta`` for guards whose own filters could silently drop a marker string: unproven provenance RAISES instead of returning."""
    bad = provenance_violations(key, repo=repo, main_ref=main_ref)
    if bad:
        raise AssertionError("; ".join(bad))
    return protected_delta(key, *pathspec, repo=repo, main_ref=main_ref, diff_filter=diff_filter)
