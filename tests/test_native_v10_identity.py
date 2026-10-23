"""Full production-Run identity: OFF vs Stage 1 candidate vs Stage 1+2 candidate.

For Solar, Wind, W25, S16 and the P8 SHL cases, under both the canonical and the OD-R SHL maturity
authority: identical verdict, identical exception text, identical digests of every financial leaf, of
the complete result, of Integrity and of the final checks. A case the canonical engine rejects stays
rejected with the identical error. Native execution is proven by the Run's own counters."""
from __future__ import annotations

import pytest

from tests.native_v10_support import ARMS, entries, outcome_key, run_case

pytestmark = pytest.mark.usefixtures("native_artifacts")

FEASIBLE = ("reference-solar", "reference-wind", "W25", "S16", "P8-W25-bullet", "P8-S16-bullet", "P8-W25-IL")
REJECTED = ("W25-tenor18",)          # canonical: explicit_all_in_rates length mismatch (fail closed)


@pytest.fixture(scope="module")
def catalogue():
    return entries()


@pytest.mark.parametrize("authority", ["canonical", "odr"])
@pytest.mark.parametrize("name", FEASIBLE + REJECTED)
def test_off_stage1_stage2_identity(catalogue, name, authority):
    runs = {arm: run_case(name, authority, cfg, catalogue) for arm, cfg in ARMS.items()}
    off = runs["off"]
    assert off["verdict"] == ("REJECTED" if name in REJECTED else "FEASIBLE"), off["error"]
    for arm in ("stage1", "stage2"):
        assert outcome_key(runs[arm]) == outcome_key(off), arm
    assert off["native"]["native_solves"] == off["native"]["stage2_native_calls"] == 0
    if name in FEASIBLE:
        assert off["digests"]["integrity"] == "PASS"
        assert runs["stage1"]["native"]["native_solves"] > 0
        assert runs["stage1"]["native"]["stage2_native_calls"] == 0
        assert runs["stage2"]["native"]["stage2_native_calls"] > 0
        # Stage 2 declines are permitted only on the canonical-raise path of the kernel
        assert all(k == "STAGE2:KERNEL_STATUS_1" for k in runs["stage2"]["native"]["declines"]), runs["stage2"]["native"]
