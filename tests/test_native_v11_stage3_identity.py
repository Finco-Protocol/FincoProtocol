"""Full production-Run identity: OFF vs V10 Stage 1+2 vs V11 Stage 3 vs Stage 3 on top of Stage 1+2.

For Solar, Wind, W25, S16, Data Center and the P8 SHL cases, under both the canonical and the OD-R SHL
maturity authority: identical verdict, identical exception text, identical digests of every financial leaf,
of the complete result, of Integrity and of the final checks. A case the canonical engine rejects stays
rejected with the identical error. Native execution is proven by the Run's own counters; every decline is
one of the documented admission reasons (the canonical evaluation then ran)."""
from __future__ import annotations

import pytest

from tests.native_v11_support import outcome_key, run_case

pytestmark = pytest.mark.usefixtures("stage3_artifacts")

FEASIBLE = ("reference-solar", "reference-wind", "W25", "S16", "DC", "P8-W25-bullet", "P8-S16-bullet", "P8-W25-IL")
# dynamic SHL interest limitation (capitalisation gate) is outside the Stage 3 admission: every senior-debt
# evaluation of these cases declines and runs canonically (still part of the identity check)
CANONICAL_ONLY = ("P8-W25-IL",)
REJECTED = ("W25-tenor18",)          # canonical: explicit_all_in_rates length mismatch (fail closed)
# admission declines that keep the canonical evaluation (never a mismatch, never an error of Stage 3)
ALLOWED_DECLINES = ("DYNAMIC_INTEREST_LIMITATION", "SENIOR_INVALID_INPUT", "SHL_MATURITY_CONTEXT_WITHOUT_SHL")


@pytest.fixture(scope="module")
def catalogue():
    from tests.native_v10_support import entries
    return entries()


def _declines_allowed(stats: dict) -> bool:
    for reason in stats["declines"]:
        if reason.startswith(ALLOWED_DECLINES):
            continue
        # the canonical fail-closed raise of a schedule Stage 3 evaluated with the canonical function
        if reason.startswith("ADMISSION_EXCEPTION:ValueError:SHL_MATURITY_RESIDUAL_FAILS_CLOSED"):
            continue
        return False
    return True


@pytest.mark.parametrize("authority", ["canonical", "odr"])
@pytest.mark.parametrize("name", FEASIBLE + REJECTED)
def test_off_v10_stage3_identity(catalogue, name, authority):
    runs = {arm: run_case(name, authority, arm, catalogue) for arm in ("off", "v10_s12", "s3", "s12_s3")}
    off = runs["off"]
    assert off["verdict"] == ("REJECTED" if name in REJECTED else "FEASIBLE"), off["error"]
    for arm in ("v10_s12", "s3", "s12_s3"):
        assert outcome_key(runs[arm]) == outcome_key(off), arm
    assert off["s3"]["native_models"] == 0 and off["v10"]["native_solves"] == 0
    assert runs["v10_s12"]["s3"]["native_models"] == 0
    for arm in ("s3", "s12_s3"):
        stats = runs[arm]["s3"]
        assert _declines_allowed(stats), stats["declines"]
        if name in CANONICAL_ONLY:
            assert stats["native_models"] == 0 and set(stats["declines"]) == {"DYNAMIC_INTEREST_LIMITATION"}, stats
        elif name in FEASIBLE:
            assert stats["native_models"] > 0, stats
            assert stats["native_full_tax"] >= stats["native_models"], stats
            assert stats["build_id"] is not None
    if name in FEASIBLE:
        assert off["digests"]["integrity"] == "PASS"
        # Stage 3 alone runs no V10 kernel; on top of Stage 1+2 the declined evaluations may use them
        assert runs["s3"]["v10"]["native_solves"] == 0
