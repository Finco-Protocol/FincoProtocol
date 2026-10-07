"""Performance V4 canonical runtime parity matrix.

The same script is executed against canonical base and candidate HEAD. Numeric
leaves use float.hex(), so +0.0/-0.0 and exact IEEE values are distinguished.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import decimal
import enum
import hashlib
import json
import os
import sys
from dataclasses import replace
from datetime import timedelta
from typing import Any

ROOT = os.path.abspath(os.environ.get("FINCO_RUNTIME_REPO_ROOT", os.path.dirname(os.path.dirname(__file__))))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from app.services.production_financial_authority import run_clean_production  # noqa: E402
from finco_core.inputs import (  # noqa: E402
    DeveloperFeeMode,
    DevelopmentEconomicsInput,
    DevelopmentSpendEntry,
    SponsorFundingMode,
)
from tools import model_runtime_parity as v2  # noqa: E402


def _one_opex(pi):
    return replace(
        pi,
        opex=tuple(
            replace(o, y1_amount_keur=o.y1_amount_keur * 1.10) if i == 0 else o
            for i, o in enumerate(pi.opex)
        ),
    )


def _atad_binding(pi):
    return replace(
        pi,
        tax=replace(
            pi.tax,
            atad_enabled=True,
            atad_ebitda_limit=0.01,
            atad_min_interest_keur=0.0,
        ),
    )


def _atad_nonbinding(pi):
    return replace(
        pi,
        tax=replace(
            pi.tax,
            atad_enabled=True,
            atad_ebitda_limit=1.0,
            atad_min_interest_keur=1_000_000_000.0,
        ),
    )


def _dev_spend(pi):
    fc = pi.info.financial_close
    return (
        DevelopmentSpendEntry(fc - timedelta(days=365), 1250.0),
        DevelopmentSpendEntry(fc - timedelta(days=180), 750.0),
    )


def _dev_disabled(pi):
    return replace(pi, development_economics=DevelopmentEconomicsInput())


def _dev_reimbursement(pi):
    return replace(
        pi,
        development_economics=DevelopmentEconomicsInput(
            enabled=True,
            spend_schedule=_dev_spend(pi),
            reimbursed_development_cost_keur=1500.0,
        ),
    )


def _dev_fixed_fee(pi):
    return replace(
        pi,
        development_economics=DevelopmentEconomicsInput(
            enabled=True,
            developer_fee_value=400.0,
        ),
    )


def _dev_percentage_fee(pi):
    return replace(
        pi,
        development_economics=DevelopmentEconomicsInput(
            enabled=True,
            developer_fee_mode=DeveloperFeeMode.PCT_OF_HARD_CAPEX,
            developer_fee_value=0.02,
        ),
    )


def _zero_interest(pi):
    cfg = pi.financing.senior_debt_interest_config
    zero_schedule = replace(
        cfg.rate_schedule,
        explicit_all_in_rates=tuple(0.0 for _ in cfg.rate_schedule.explicit_all_in_rates),
    )
    return replace(
        pi,
        financing=replace(
            pi.financing,
            sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY,
            shl_amount_keur=0.0,
            clean_shl_principal_keur=0.0,
            senior_debt_interest_config=replace(cfg, rate_schedule=zero_schedule),
        ),
    )


def _negative_taxable(pi):
    return replace(pi, tax=replace(pi.tax, tax_deductible_book_dep_pct=5.0))


# 16 established Runtime scenarios (V2 matrix excluding its generic atad_on),
# plus 9 V4 additions = 25 required scenarios.
SCENARIOS = {
    "solar": (v2._solar, lambda pi: pi, "solar"),
    "wind": (v2._wind, lambda pi: pi, "wind"),
    "solar_opex_all": (v2._solar, v2._opex_edit, "solar"),
    "wind_opex_all": (v2._wind, v2._opex_edit, "wind"),
    "solar_reference": (v2._solar_ref, lambda pi: pi, "solar"),
    "wind_reference": (v2._wind_ref, lambda pi: pi, "wind"),
    "data_center": (v2._dc, lambda pi: pi, "data"),
    "ev_charging": (v2._ev, lambda pi: pi, "ev"),
    "shl_deductible": (v2._wind, v2._shl_deductible, "wind"),
    "shl_non_deductible": (v2._wind, v2._shl_non_deductible, "wind"),
    "opening_tax_losses": (v2._solar, v2._loss_carryforward, "solar"),
    "alternative_tax_rate": (v2._solar, v2._alt_tax_rate, "solar"),
    "low_gearing": (v2._wind, v2._gearing_low, "wind"),
    "high_gearing": (v2._wind, v2._gearing_high, "wind"),
    "distribution_lockup": (v2._solar, v2._lockup, "solar"),
    "infeasible_debt": (v2._solar, v2._infeasible, "solar"),
    "solar_opex_one": (v2._solar, _one_opex, "solar"),
    "atad_binding": (v2._solar, _atad_binding, "solar"),
    "atad_nonbinding": (v2._solar, _atad_nonbinding, "solar"),
    "developer_disabled": (v2._solar_ref, _dev_disabled, "solar"),
    "developer_reimbursement": (v2._solar_ref, _dev_reimbursement, "solar"),
    "developer_fixed_fee": (v2._solar_ref, _dev_fixed_fee, "solar"),
    "developer_percentage_fee": (v2._solar_ref, _dev_percentage_fee, "solar"),
    "zero_interest": (v2._solar_ref, _zero_interest, "solar"),
    "negative_taxable_income": (v2._solar_ref, _negative_taxable, "solar"),
}


def _model(run):
    return run.g2c_result.financing_result.project_model_result


def _semantic_guard(name, run):
    model = _model(run)
    if name == "atad_binding":
        if not any(ar.disallowed_interest_keur > 0.0 for ar in model.tax_and_cfads.annual_results):
            raise AssertionError("V4_MATRIX_ATAD_BINDING_NOT_EXERCISED")
    elif name == "atad_nonbinding":
        if any(ar.disallowed_interest_keur != 0.0 for ar in model.tax_and_cfads.annual_results):
            raise AssertionError("V4_MATRIX_ATAD_NONBINDING_BOUND")
    elif name == "zero_interest":
        if any(v != 0.0 for v in model.senior_debt.senior_interest_keur):
            raise AssertionError("V4_MATRIX_ZERO_SENIOR_INTEREST_NOT_EXERCISED")
        if model.shareholder_loan is not None and any(
            v != 0.0 for v in model.shareholder_loan.shl_gross_interest_keur
        ):
            raise AssertionError("V4_MATRIX_ZERO_SHL_INTEREST_NOT_EXERCISED")
    elif name == "negative_taxable_income":
        if not any(v < 0.0 for v in model.tax_and_cfads.taxable_income_before_losses_audit_keur):
            raise AssertionError("V4_MATRIX_NEGATIVE_TAXABLE_NOT_EXERCISED")


def _walk(obj: Any, path: str, out: list[str], seen: set[int]) -> None:
    if obj is None or isinstance(obj, (bool, int, str)):
        out.append(f"{path}={obj!r}")
        return
    if isinstance(obj, float):
        out.append(f"{path}=float:{obj.hex()}")
        return
    if isinstance(obj, enum.Enum):
        out.append(f"{path}=enum:{type(obj).__module__}.{type(obj).__qualname__}:{obj.value!r}")
        return
    if isinstance(obj, (datetime.date, datetime.datetime)):
        out.append(f"{path}=date:{obj.isoformat()}")
        return
    if isinstance(obj, decimal.Decimal):
        out.append(f"{path}=decimal:{obj}")
        return

    oid = id(obj)
    if oid in seen:
        out.append(f"{path}=<cycle:{type(obj).__module__}.{type(obj).__qualname__}>")
        return
    seen.add(oid)
    try:
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            out.append(f"{path}=<dataclass:{type(obj).__module__}.{type(obj).__qualname__}>")
            for field in dataclasses.fields(obj):
                _walk(getattr(obj, field.name), f"{path}.{field.name}", out, seen)
        elif isinstance(obj, dict):
            out.append(f"{path}=<dict:{len(obj)}>")
            for key in sorted(obj, key=lambda k: repr(k)):
                _walk(obj[key], f"{path}[{key!r}]", out, seen)
        elif isinstance(obj, (tuple, list)):
            out.append(f"{path}=<{type(obj).__name__}:{len(obj)}>")
            for i, value in enumerate(obj):
                _walk(value, f"{path}[{i}]", out, seen)
        elif isinstance(obj, (set, frozenset)):
            out.append(f"{path}=<{type(obj).__name__}:{sorted(repr(v) for v in obj)!r}>")
        else:
            out.append(f"{path}=<opaque:{type(obj).__module__}.{type(obj).__qualname__}>")
    finally:
        seen.discard(oid)


def _fingerprint(run):
    payload = {
        "g2c": run.g2c_result,
        "statements": run.financial_statements_result,
        "developer": getattr(run, "developer_economics_result", None),
    }
    lines: list[str] = []
    _walk(payload, "root", lines, set())
    return hashlib.sha256("\n".join(lines).encode()).hexdigest(), len(lines)


def _run(name):
    build, mutate, project_type = SCENARIOS[name]
    try:
        run = run_clean_production(mutate(build()), "Base", project_type=project_type)
        _semantic_guard(name, run)
        digest, leaves = _fingerprint(run)
        model = _model(run)
        return {
            "kind": "digest",
            "sha256": digest,
            "leaves": leaves,
            "solver_iterations": None if model.senior_debt is None else model.senior_debt.diagnostics.get("iteration_count"),
            "solver_termination": None if model.senior_debt is None else model.senior_debt.diagnostics.get("termination_reason"),
            "shl_iterations": None if model.shareholder_loan is None else model.shareholder_loan.diagnostics.iteration_count,
            "shl_termination": None if model.shareholder_loan is None else model.shareholder_loan.diagnostics.termination_reason,
        }
    except Exception as exc:
        return {
            "kind": "fail_closed",
            "error_type": type(exc).__name__,
            "reason": str(getattr(exc, "reason_code", None) or exc),
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record")
    parser.add_argument("--compare")
    parser.add_argument("--only")
    args = parser.parse_args()
    names = sorted(SCENARIOS) if not args.only else args.only.split(",")
    results = {}
    for name in names:
        results[name] = _run(name)
        marker = results[name].get("sha256", results[name].get("reason", ""))[:18]
        print(f"{name:30s} {results[name]['kind']:12s} {marker}", flush=True)
    if args.record:
        with open(args.record, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2, sort_keys=True)
        print(f"V4_RECORDED {len(results)}")
    if args.compare:
        with open(args.compare, encoding="utf-8") as fh:
            expected = json.load(fh)
        failures = [(n, expected.get(n), results.get(n)) for n in names if expected.get(n) != results.get(n)]
        if failures:
            for name, want, got in failures:
                print("V4_MISMATCH", name)
                print("BASE", json.dumps(want, sort_keys=True)[:900])
                print("HEAD", json.dumps(got, sort_keys=True)[:900])
            print(f"V4_PARITY_FAILED {len(failures)}/{len(names)}")
            raise SystemExit(1)
        print(f"V4_PARITY_OK {len(names)}/{len(names)}")


if __name__ == "__main__":
    main()
