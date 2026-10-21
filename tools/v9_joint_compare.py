"""Exact complete-evidence comparison and OD-1 differences; no acceptance tolerance."""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, localcontext
import json
import math
from pathlib import Path
import struct


def decoded(value):
    if value and value[0] == "float64":
        return struct.unpack(">d", bytes.fromhex(value[1]))[0]
    return value


def decimal_audit(evidence):
    with localcontext() as context:
        context.prec = 80
        return _decimal_audit(evidence)


def _decimal_audit(evidence):
    def number(path):
        value = evidence.get(path)
        if not value or value[0] != "float64":
            return None
        raw = decoded(value)
        return Decimal.from_float(raw) if math.isfinite(raw) else None

    f = ".g2c_result.financing_result"
    sources = number(f + ".construction_funding.total_audit_sources_keur")
    uses = number(f + ".project_uses.total_project_uses_keur")
    bs = ".financial_statements_result.balance_sheet_periods"
    errors, unavailable = [], 0
    for index in range(evidence.get(bs, ["tuple", 0])[1]):
        prefix = bs + f"[{index}]."
        fields = ("gross_fixed_assets_keur", "accumulated_book_depreciation_keur",
                  "unrestricted_cash_keur", "dsra_balance_keur", "distribution_account_balance_keur",
                  "senior_debt_balance_keur", "shl_balance_keur", "share_capital_keur",
                  "share_premium_keur", "additional_equity_keur", "legal_reserve_keur",
                  "retained_earnings_keur", "net_cit_payable_keur")
        values = [number(prefix + name) for name in fields]
        if any(v is None for v in values):
            unavailable += 1
            continue
        assets = values[0] - values[1] + sum(values[2:5])
        errors.append(abs(assets - sum(values[5:])))
    debt = f + ".project_model_result.senior_debt."
    count = evidence.get(debt + "period_indices", ["tuple", 0])[1]
    roll = []
    for index in range(count):
        values = [number(debt + name + f"[{index}]") for name in
                  ("senior_debt_opening_keur", "senior_principal_keur", "senior_debt_closing_keur")]
        if all(v is not None for v in values):
            roll.append(abs(values[0] - values[1] - values[2]))
    terminal = ".g2c_result.return_summary.terminal."
    margins = {}
    for facility in ("senior", "shareholder_loan"):
        balance = number(terminal + facility + ".balance_at_contractual_maturity_keur")
        margins[facility] = {"balance_keur": str(balance) if balance is not None else None,
                             "margin_to_existing_1e_7_keur": str(Decimal("1e-7") - balance) if balance is not None else None,
                             "status": evidence.get(terminal + facility + ".status")}
    return {"method": "independent Decimal.from_float arithmetic on complete stored IEEE evidence; no plugs or coercion of missing values",
            "sources_minus_uses_keur": str(sources - uses) if sources is not None and uses is not None else None,
            "max_bs_identity_keur": str(max(errors)) if errors else None,
            "bs_rows_recomputed": len(errors), "bs_rows_unavailable": unavailable,
            "max_senior_rollforward_keur": str(max(roll)) if roll else None,
            "terminal": margins}


def compare(left, right):
    with localcontext() as context:
        context.prec = 80
        return _compare(left, right)


def _compare(left, right):
    reports = {}
    for name in sorted(set(left["results"]) | set(right["results"])):
        if name not in left["results"] or name not in right["results"]:
            reports[name] = {"outcome": "MISSING_CASE"}
            continue
        a, b = left["results"][name], right["results"][name]
        if a["status"] != b["status"]:
            outcome = "OUTCOME_FLIP"
        elif a["status"] == "REJECTED":
            outcome = "REJECTION_IDENTICAL" if a["evidence"] == b["evidence"] else "REJECTION_DIFFERENT"
        else:
            outcome = "BIT_IDENTICAL" if a["digest"] == b["digest"] else "NUMERICALLY_OR_EVIDENTIALLY_DIFFERENT"
        changes = []
        maximum = Decimal(0)
        financial_categories = []
        provenance_changes = []
        for path in sorted(set(a["evidence"]) | set(b["evidence"])):
            av, bv = a["evidence"].get(path), b["evidence"].get(path)
            if av == bv:
                continue
            change = {"path": path, "baseline": av, "candidate": bv}
            if isinstance(av, list) and isinstance(bv, list) and av[0] == bv[0] == "float64":
                x, y = decoded(av), decoded(bv)
                if math.isfinite(x) and math.isfinite(y):
                    delta = abs(Decimal.from_float(y) - Decimal.from_float(x))
                    change.update(abs_difference=str(delta), relative_difference=(
                        str(delta / abs(Decimal.from_float(x))) if x else None),
                        unit="kEUR" if "_keur" in path else "native field unit")
                    if "_keur" in path:
                        maximum = max(maximum, delta)
                else:
                    change["nonfinite_difference"] = True
            elif path == ".integrity['evidence_digest']" or path.startswith(".authority_metadata"):
                provenance_changes.append(change)
            elif any(token in path for token in (".terminal.", ".binding_senior_constraint", ".integrity")):
                financial_categories.append(change)
            changes.append(change)
        reports[name] = {"outcome": outcome, "changed_leaves": len(changes),
                         "max_keur_difference": str(maximum),
                         "financial_categorical_changes": financial_categories,
                         "provenance_changes": provenance_changes,
                         "changes": changes,
                         "baseline_decimal_audit": decimal_audit(a["evidence"]) if a["status"] == "FEASIBLE" else None,
                         "candidate_decimal_audit": decimal_audit(b["evidence"]) if b["status"] == "FEASIBLE" else None,
                         "candidate_execution": b.get("candidate_evidence", {})}
    return {"baseline_source": left["source_head"], "candidate_source": right["source_head"],
            "mode": right["mode"], "counts": dict(Counter(row["outcome"] for row in reports.values())),
            "acceptance": "NO_NEW_PRECISION_AUTHORITY_CREATED", "cases": reports}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--require-identical", action="store_true")
    args = p.parse_args()
    report = compare(json.loads(args.baseline.read_text()), json.loads(args.candidate.read_text()))
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(report["counts"])
    if args.require_identical:
        allowed = {"BIT_IDENTICAL", "REJECTION_IDENTICAL"}
        raise SystemExit(int(any(key not in allowed for key in report["counts"])))


if __name__ == "__main__":
    main()
