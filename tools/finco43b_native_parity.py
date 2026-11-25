"""FINCO43B — exact native-arm parity matrix (opt-in, not CI).

Runs every scenario of ``tools/finco43_equivalence.py`` (17 parity + 8 dated OD-TIME-01/R04 + maturity rejection +
DSCR stress), the real U2 cash-reserve-interest + S2b configuration, and typed-admission negatives, under each native
arm, in ONE process on the SAME source tree:

    OFF         canonical Python only
    S1          V10 Stage 1 (senior solve / finalisation / tax)
    S1+2        V10 Stage 1 + experimental Stage 2 (SHL)
    S3          V11 Stage 3 alone
    S1+S3       V10 Stage 1 + V11 Stage 3
    S1+2+S3     V10 Stage 1+2 + V11 Stage 3 (what deploy/scripts/release_native.sh activates)

Every arm result is the COMPLETE ``CleanProductionRun`` digest (every leaf, ``float.hex``; see finco43_equivalence) or the
typed refusal (class + full message), compared with OFF. The arm's own ``NativeRunStats`` / ``Stage3Stats`` are recorded
for exactly that Run (served calls, declines by reason, build ID). The policy memo is cleared before every Run, so no
result is a cache hit. Kernels must be installed next to the package (``deploy/scripts/release_native.sh`` or the
repository build modules); an arm whose loader is unavailable is reported as such, never as native.

    python tools/finco43b_native_parity.py --out parity.json [--only <substring>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ARMS = {
    "OFF": (None, False, False),
    "S1": ("candidate", False, False),
    "S1+2": ("candidate", True, False),
    "S3": (None, False, True),
    "S1+S3": ("candidate", False, True),
    "S1+2+S3": ("candidate", True, True),
}


def _scenarios():
    from dataclasses import replace

    from tools.finco43_equivalence import _scenarios as base

    out = {name: (build, project_type) for name, (build, project_type) in base().items()}
    from tests.test_v9p2a_odr_finalization_contract import _cash_reserve_inputs

    out["u2s2b:wind_ref_cash_reserve_interest"] = (_cash_reserve_inputs, "Wind")
    dated_solar = out["dated:solar_r04"][0]
    # typed-admission negatives: the same dated Solar inputs under a renamed identity and a non-Solar/Wind/absent type
    out["admission:dated_renamed_type_dc"] = (
        lambda: (lambda p: replace(p, info=replace(p.info, name="Sunny Valley", code="SV-01")))(dated_solar()),
        "Generic Data Center Reference")
    out["admission:dated_untyped"] = (dated_solar, "")
    return out


def _digest(run) -> tuple[str, int]:
    from tools.finco43_equivalence import _emit

    lines: list[str] = []
    _emit(run, "run", lines, set())
    return hashlib.sha256("\n".join(lines).encode()).hexdigest(), len(lines)


def _run_arm(arm, build, project_type):
    from app.services import production_financial_authority as pfa
    from financial_engine.native_v10.config import NativeConfig, native_run
    from financial_engine.native_v11.config import Stage3Config, stage3_run

    v10_mode, stage2, s3 = ARMS[arm]
    v10 = NativeConfig(mode=v10_mode or "off", stage2_experimental=stage2) if v10_mode else NativeConfig(mode="off")
    v11 = Stage3Config(mode="candidate" if s3 else "off")
    pi = build()
    pfa._POLICY_RUN_CACHE.clear()
    started, cpu = time.perf_counter(), time.process_time()
    with native_run(v10) as st10, stage3_run(v11) as st11:
        try:
            run = pfa.run_clean_production(pi, project_type=project_type)
            sha, leaves = _digest(run)
            outcome = {"kind": "digest", "sha256": sha, "leaves": leaves}
        except Exception as exc:  # typed refusal: class + full message must match OFF
            outcome = {"kind": "rejected", "error_type": type(exc).__qualname__,
                       "reason_code": str(getattr(exc, "reason_code", "")), "message": str(exc)[:4000]}
    outcome.update(wall_s=round(time.perf_counter() - started, 4), cpu_s=round(time.process_time() - cpu, 4),
                   v10=st10.as_dict(), v11=st11.as_dict())
    pfa._POLICY_RUN_CACHE.clear()
    return outcome


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only")
    ap.add_argument("--arms", default=",".join(ARMS))
    args = ap.parse_args(argv)
    os.chdir(ROOT)
    from financial_engine.native_v10 import loader, stage2
    from financial_engine.native_v11 import stage3

    loaders = {"stage1": loader.get_native()[1], "stage2": stage2.get_stage2()[1]}
    getter = next((getattr(stage3, n) for n in ("get_stage3", "get_native", "load") if hasattr(stage3, n)), None)
    loaders["stage3"] = getter()[1] if getter else "UNKNOWN_LOADER_API"
    arms = args.arms.split(",")
    results: dict = {}
    for name, (build, project_type) in sorted(_scenarios().items()):
        if args.only and args.only not in name:
            continue
        row = {arm: _run_arm(arm, build, project_type) for arm in arms}
        ref = row["OFF"]
        key = ("sha256", "leaves") if ref["kind"] == "digest" else ("error_type", "reason_code", "message")
        for arm in arms:
            row[arm]["equal_to_off"] = all(row[arm].get(k) == ref.get(k) for k in key) and row[arm]["kind"] == ref["kind"]
        results[name] = row
        print(f"{name:42s} " + " ".join(
            f"{arm}={'=' if row[arm]['equal_to_off'] else 'DIFF'}"
            f"({row[arm]['wall_s']:.2f}s,n{row[arm]['v10']['native_solves'] + row[arm]['v10']['stage2_native_calls']}"
            f"/m{row[arm]['v11']['native_models']})" for arm in arms), flush=True)
    diffs = [(n, a) for n, row in results.items() for a in arms if not row[a]["equal_to_off"]]
    out = {"loaders": loaders, "python": sys.version.split()[0], "arms": arms, "results": results, "differences": diffs}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(f"{len(results)} scenarios x {len(arms)} arms; {len(diffs)} differences vs OFF; loaders={loaders}")
    return 1 if diffs else 0


if __name__ == "__main__":
    raise SystemExit(main())
