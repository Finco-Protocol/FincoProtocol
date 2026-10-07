"""Model Runtime V2 — canonical result-tree parity recorder.

Fingerprints the COMPLETE financial result tree of ``run_clean_production``
for a deterministic scenario matrix, so any performance refactor can be
proven bit-exact against the pristine base:

    python tools/model_runtime_parity.py --record base_digests.json
    python tools/model_runtime_parity.py --compare base_digests.json

The fingerprint covers the G2C waterfall result (schedules, per-period
waterfall rows, return summaries, diagnostics) and the decision-complete
financial statements — every numeric leaf, full float precision (repr),
sorted keys.  Non-financial volatile fields (timings, request ids) are
excluded.  Fail-closed scenarios record the typed failure reason instead of
a digest, preserving failure parity.

Interpreter note: float summation order is interpreter-stable (same
implementation), but record and compare on the SAME interpreter anyway
(local 3.12.10 == CI 3.12).
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import decimal
import hashlib
import json
import os
import sys
from dataclasses import dataclass, replace
from typing import Any, Callable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import project_factories as F  # noqa: E402
from app.services.production_financial_authority import (  # noqa: E402
    run_clean_production,
)


# ---------------------------------------------------------------------------
# Scenario matrix (§10)
# ---------------------------------------------------------------------------

def _solar(): return F.create_default_solar_project(capacity_mw=64.0)
def _wind(): return F.create_default_wind_project(capacity_mw=48.0)
def _solar_ref(): return F.create_generic_solar_reference()
def _wind_ref(): return F.create_generic_wind_reference()
def _dc(): return F.create_generic_data_center_reference()
def _ev(): return F.create_generic_ev_charging_reference()


def _opex_edit(pi):
    """Typical interactive edit: every OPEX line +10 % (bench opex_one uses one line; +10 % all lines for stronger coverage)."""
    return replace(
        pi,
        opex=tuple(replace(o, y1_amount_keur=o.y1_amount_keur * 1.10) for o in pi.opex),
    )


def _atad_on(pi):
    tax = pi.tax
    for field in ("atad_interest_limit_ratio", "atad_enabled", "thin_cap_enabled"):
        if hasattr(tax, field):
            try:
                tax = replace(tax, **{field: True})
            except TypeError:
                pass
    return replace(pi, tax=tax)


def _shl_mode(pi):
    """Toggle the SHL interest tax mode between the typed contracts."""
    from finco_core.inputs._models import ShlInterestDeductibilityMode
    tax = pi.tax
    current = getattr(tax, "shl_interest_deductibility", None)
    if current is None:
        return pi
    target = (ShlInterestDeductibilityMode.FULLY_DEDUCTIBLE
              if current != ShlInterestDeductibilityMode.FULLY_DEDUCTIBLE
              else ShlInterestDeductibilityMode.FULLY_NON_DEDUCTIBLE)
    return replace(pi, tax=replace(tax, shl_interest_deductibility=target))


def _shl_deductible(pi):
    from finco_core.inputs._models import ShlInterestDeductibilityMode
    tax = pi.tax
    if hasattr(tax, "shl_interest_deductibility"):
        return replace(pi, tax=replace(
            tax, shl_interest_deductibility=ShlInterestDeductibilityMode.FULLY_DEDUCTIBLE))
    return pi


def _shl_non_deductible(pi):
    from finco_core.inputs._models import ShlInterestDeductibilityMode
    tax = pi.tax
    if hasattr(tax, "shl_interest_deductibility"):
        return replace(pi, tax=replace(
            tax, shl_interest_deductibility=ShlInterestDeductibilityMode.FULLY_NON_DEDUCTIBLE))
    return pi


def _loss_carryforward(pi):
    """Opening tax-loss vintages + explicit gate (typed loss authority)."""
    from finco_core.inputs._models import OpeningTaxLossVintageParams
    tax = pi.tax
    year0 = pi.info.cod_date.year if getattr(pi.info, "cod_date", None) else 2031
    vintages = (
        OpeningTaxLossVintageParams(origin_tax_year=year0 - 2,
                                    opening_amount_keur=4000.0,
                                    source_label="parity-prior-year"),
        OpeningTaxLossVintageParams(origin_tax_year=year0 - 1,
                                    opening_amount_keur=2500.0,
                                    source_label="parity-prior-year"),
    )
    return replace(pi, tax=replace(
        tax, opening_tax_loss_vintages=vintages))


def _alt_tax_rate(pi):
    """Alternative corporate rate via the country-policy override authority."""
    return replace(pi, tax=replace(
        pi.tax,
        country_tax_policy_id="parity-alt-policy",
        corporate_rate_override=0.19,
    ))


def _gearing_low(pi):
    return replace(pi, financing=replace(pi.financing, gearing_ratio=0.55))


def _gearing_high(pi):
    return replace(pi, financing=replace(pi.financing, gearing_ratio=0.85))


def _lockup(pi):
    fin = pi.financing
    if hasattr(fin, "lockup_dscr"):
        return replace(pi, financing=replace(fin, lockup_dscr=1.45))
    return pi


def _infeasible(pi):
    """DSCR target no CFADS can service → solver must fail closed."""
    return replace(pi, financing=replace(pi.financing, target_dscr=25.0))


SCENARIOS: dict[str, tuple[Callable[[], Any], Callable[[Any], Any]]] = {
    "solar": (_solar, lambda pi: pi),
    "wind": (_wind, lambda pi: pi),
    "solar_opex_edit": (_solar, _opex_edit),
    "wind_opex_edit": (_wind, _opex_edit),
    "solar_ref": (_solar_ref, lambda pi: pi),
    "wind_ref": (_wind_ref, lambda pi: pi),
    "data_center": (_dc, lambda pi: pi),
    "ev_charging": (_ev, lambda pi: pi),
    "atad_on": (_solar, _atad_on),
    "shl_deductible": (_wind, _shl_deductible),
    "shl_non_deductible": (_wind, _shl_non_deductible),
    "loss_carryforward": (_solar, _loss_carryforward),
    "alt_tax_rate": (_solar, _alt_tax_rate),
    "gearing_low": (_wind, _gearing_low),
    "gearing_high": (_wind, _gearing_high),
    "lockup": (_solar, _lockup),
    "infeasible_debt": (_solar, _infeasible),
}


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

_VOLATILE_KEYS = {
    "duration_s", "elapsed_s", "timestamp", "generated_at", "created_at",
    "ran_at", "request_id", "reference", "wall_time_s", "computed_at",
}


def _walk(obj: Any, path: str, out: list[str]) -> None:
    """Depth-first emission of canonical scalar lines (sorted dict keys)."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out.append(f"{path}=<dataclass {type(obj).__name__}>")
        fields = {fld.name: getattr(obj, fld.name)
                  for fld in dataclasses.fields(obj)}
        for f in sorted(fields):
            _walk(fields[f], f"{path}.{f}", out)
        return
    if isinstance(obj, dict):
        for k in sorted(obj.keys(), key=lambda k: str(k)):
            _walk(obj[k], f"{path}[{k!r}]", out)
        return
    if isinstance(obj, (list, tuple)):
        out.append(f"{path}=<len {len(obj)}>")
        for i, item in enumerate(obj):
            _walk(item, f"{path}[{i}]", out)
        return
    if isinstance(obj, bool) or obj is None:
        out.append(f"{path}={obj!r}")
        return
    if isinstance(obj, float):
        if obj != obj:
            out.append(f"{path}=NaN")
        elif obj == float("inf"):
            out.append(f"{path}=Infinity")
        elif obj == float("-inf"):
            out.append(f"{path}=-Infinity")
        else:
            out.append(f"{path}={obj!r}")
        return
    if isinstance(obj, (int, str)):
        out.append(f"{path}={obj!r}")
        return
    if isinstance(obj, (datetime.date, datetime.datetime)):
        out.append(f"{path}={obj.isoformat()}")
        return
    if isinstance(obj, decimal.Decimal):
        out.append(f"{path}={str(obj)}")
        return
    # anything else (enums, classes): stable repr
    out.append(f"{path}={obj!r}")


def _clean_result(run) -> dict[str, Any]:
    """Extract the deterministic financial payload of one CleanProductionRun."""
    return {
        "g2c": {
            "waterfall_periods": run.g2c_result.waterfall_periods,
            "return_summary": run.g2c_result.return_summary,
            "valuation_summary": getattr(run.g2c_result, "valuation_summary", None),
            "totals": {
                k: getattr(run.g2c_result, k)
                for k in (
                    "pure_equity_xirr", "pure_equity_moic", "total_sponsor_xirr",
                    "total_sponsor_moic", "total_sponsor_contributed_keur",
                    "total_legal_equity_contributed_keur",
                    "total_shl_cash_contributed_keur",
                    "total_sponsor_receipts_keur", "distribution_lockup_dscr",
                    "periods_locked_by_dscr", "total_distribution_account_locked_keur",
                    "total_covenant_locked_keur", "pure_equity_xirr_status",
                    "pure_equity_moic_status", "total_sponsor_xirr_status",
                    "total_sponsor_moic_status",
                )
            },
        },
        "financial_statements": {
            "income_statement_periods": run.financial_statements_result.income_statement_periods,
            "balance_sheet_periods": run.financial_statements_result.balance_sheet_periods,
            "pf_cash_waterfall_periods": run.financial_statements_result.pf_cash_waterfall_periods,
            "fixed_asset_periods": run.financial_statements_result.fixed_asset_periods,
            "tax_bridge_periods": run.financial_statements_result.tax_bridge_periods,
            "retained_earnings_periods": run.financial_statements_result.retained_earnings_periods,
            "funding_audit": run.financial_statements_result.funding_audit,
            "status": str(run.financial_statements_result.status),
        },
    }


def _fingerprint(run) -> tuple[str, int]:
    lines: list[str] = []
    _walk(_clean_result(run), "root", lines)
    payload = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest(), len(lines)


def _run_scenario(name: str) -> dict:
    build, mutate = SCENARIOS[name]
    pi = mutate(build())
    try:
        run = run_clean_production(pi, "Base", project_type=name.split("_")[0])
        digest, lines = _fingerprint(run)
        return {"kind": "digest", "sha256": digest, "lines": lines}
    except Exception as exc:  # fail-closed scenarios carry the typed reason
        return {
            "kind": "fail_closed",
            "error_type": type(exc).__name__,
            "reason": str(getattr(exc, "reason_code", None) or exc)[:400],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", help="write digests to this JSON path")
    parser.add_argument("--compare", help="compare against a recorded JSON path")
    parser.add_argument("--only", help="comma-separated scenario subset")
    args = parser.parse_args()

    names = sorted(SCENARIOS) if not args.only else args.only.split(",")
    results: dict[str, dict] = {}
    for name in names:
        results[name] = _run_scenario(name)
        kind = results[name]["kind"]
        marker = results[name].get("sha256", results[name].get("reason", ""))[:16]
        print(f"{name:24s} {kind:12s} {marker}", flush=True)

    if args.record:
        with open(args.record, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1, sort_keys=True)
        print(f"recorded {len(results)} scenarios -> {args.record}")

    if args.compare:
        with open(args.compare, encoding="utf-8") as fh:
            expected = json.load(fh)
        failures = []
        for name in names:
            got, want = results.get(name), expected.get(name)
            if got != want:
                failures.append((name, want, got))
        if failures:
            for name, want, got in failures:
                print(f"MISMATCH {name}\n  base: {json.dumps(want, sort_keys=True)[:220]}"
                      f"\n  this: {json.dumps(got, sort_keys=True)[:220]}")
            print(f"PARITY FAILED: {len(failures)}/{len(names)} scenarios differ")
            sys.exit(1)
        print(f"PARITY OK: {len(names)}/{len(names)} scenarios bit-identical to base")


if __name__ == "__main__":
    main()
