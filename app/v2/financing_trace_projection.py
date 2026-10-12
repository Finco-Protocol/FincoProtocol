"""F3.8: read-only cross-references between evidence from one committed Run.

No input projection, solver, tax allocation or financial result is created here.
Statements are persisted at 2dp; their comparisons use the SAME serialization
rounding, not a relaxed financial tolerance. Audit identities use full precision.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from math import fsum, isfinite

from app.v2.financing_sources_uses_projection import (
    FINANCE_TOLERANCE_KEUR, FinancingEvidenceInvalid, amount,
    build_sources_uses_projection,
)
from app.workbook.runtime_projection import thaw_runtime_payload

FIN = "RuntimeResult.runtime_summary.financing_evidence"
FS = "RuntimeResult.financial_statements"
VECTORS = ("opening_keur", "interest_keur", "principal_keur", "debt_service_keur", "closing_keur")


def _num(v):
    return float(v) if not isinstance(v, bool) and isinstance(v, (int, float)) and isfinite(v) else None


def _object(value, source):
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise FinancingEvidenceInvalid(f'{source}: evidence must be an object')
    return value


def _indexed(rows, key, source):
    if not isinstance(rows, list):
        raise FinancingEvidenceInvalid(f"{source}: period evidence unavailable")
    result = {}
    for row in rows:
        index = row.get(key) if isinstance(row, Mapping) else None
        if type(index) is not int or index in result:
            raise FinancingEvidenceInvalid(f"{source}: invalid or duplicate period identity")
        result[index] = row
    return result


def _dated(rows, key, source):
    indexed = _indexed(rows, key, source)
    for row in indexed.values():
        try:
            date.fromisoformat(row["date"])
        except (KeyError, TypeError, ValueError):
            raise FinancingEvidenceInvalid(f"{source}: missing period date") from None
    return indexed


def _check(label, observed, canonical, source, *, display=False):
    a, b = _num(observed), _num(canonical)
    compared = round(a, 2) if display and a is not None else a
    delta = compared - b if compared is not None and b is not None else None
    status = ("UNAVAILABLE" if delta is None else "RECONCILED"
              if abs(delta) <= FINANCE_TOLERANCE_KEUR else "DIFFERS")
    return {"label": label, "observed": amount("Evidence", a, source),
            "canonical": amount("Canonical", b, source),
            "difference": amount("Difference", delta, source), "status": status,
            "basis": "Persisted statement 2dp" if display else "Full-precision audit", "source": source}


def _status(checks):
    return ("DIFFERS" if any(c["status"] == "DIFFERS" for c in checks) else
            "UNAVAILABLE" if not checks or any(c["status"] == "UNAVAILABLE" for c in checks) else "RECONCILED")


def _facility(raw, funding, dates):
    funding = {**funding, "id": funding["instrument_id"]}
    source = funding['commitment'].authority.removesuffix('.commitment_keur')
    indices = raw.get("period_indices")
    if not isinstance(indices, list) or not indices or any(type(i) is not int for i in indices):
        raise FinancingEvidenceInvalid("Facility operating period axis unavailable")
    if indices != sorted(set(indices)) or any(i not in dates for i in indices):
        raise FinancingEvidenceInvalid("Facility operating period axis inconsistent")
    for key in VECTORS:
        vector = raw.get(key)
        if not isinstance(vector, list) or len(vector) != len(indices) or any(_num(v) is None for v in vector):
            raise FinancingEvidenceInvalid(f"Facility {key}: incomplete or non-finite vector")
    maturity = raw.get("maturity_period_index")
    if type(maturity) is not int or maturity != indices[-1]:
        raise FinancingEvidenceInvalid("Facility maturity must match its final scheduled period")
    rows, checks = [], []
    for pos, index in enumerate(indices):
        values = {k: raw[k][pos] for k in VECTORS}
        checks += [_check(f"{funding['id']} P{index} opening minus principal", values["opening_keur"] - values["principal_keur"],
                          values["closing_keur"], FIN + ".facility operating roll-forward"),
                   _check(f"{funding['id']} P{index} interest plus principal", values["interest_keur"] + values["principal_keur"],
                          values["debt_service_keur"], FIN + ".facility debt service")]
        if pos:
            checks.append(_check(f"{funding['id']} P{index} continuity", values["opening_keur"],
                                 raw["closing_keur"][pos - 1], FIN + ".facility opening/closing"))
        rows.append({"index": index, "date": dates[index], "values": tuple(
            amount(k, values[k], source + "." + k) for k in VECTORS)})
    checks.append(_check(f"{funding['id']} funded opening", raw["opening_keur"][0], funding["drawn"].value,
                         FIN + ".construction_draws_keur -> opening_keur"))
    closing = raw["closing_keur"][-1]
    return {**funding, "rows": rows, "maturity": maturity, "maturity_date": dates[maturity],
            "unpaid": amount("Unpaid at maturity", closing, source + ".closing_keur"),
            "repayment": "REPAID" if closing == 0 else "OUTSTANDING" if closing > 0 else 'NEGATIVE_BALANCE', "checks": checks,
            "status": _status(checks), "raw": raw}


def build_financing_trace(*, runtime_result, freshness, snapshot_id, composite_hash, scenario_id,
                          integrity_evidence=None, historical=False):
    """Pure projection. Scope/identity authorization belongs to the request layer."""
    state = "HISTORICAL" if historical else freshness
    view = {"state": state, "snapshot_id": snapshot_id, "composite_hash": composite_hash,
            "status": "UNAVAILABLE", "funding": None, "facilities": [], "checks": [],
            "cash": [], "tax": [], "returns": [], "sponsor": [], "balance_audit": None, "reason": "No committed financing evidence.",
            "cash_headers": (), "tax_headers": (), "sponsor_headers": (),
            "limitations": [
                "Facility-level deductible interest and tax allocation: UNAVAILABLE; aggregate cash tax is not allocated to facilities.",
                "Historical interest-limitation policy and full-precision tax bridge: UNAVAILABLE in this persisted payload.",
                "IDC book basis: funded cost evidence only; asset-component depreciation attribution is not persisted here.",
                "Investor-specific returns remain F4 scope; aggregate Sponsor IRR is not investor IRR.",
            ]}
    if runtime_result is None:
        return view
    rs = _object(thaw_runtime_payload(runtime_result.runtime_summary), 'RuntimeResult.runtime_summary')
    fs = _object(thaw_runtime_payload(runtime_result.financial_statements), FS)
    su = build_sources_uses_projection(runtime_result=runtime_result, freshness=freshness,
        run_kind="HISTORICAL_RUN" if historical else "LAST_RUN", integrity_evidence=integrity_evidence,
        expected_snapshot_id=snapshot_id, expected_composite_hash=composite_hash, expected_scenario_id=scenario_id)
    funding = su.get("instrument_view")
    view["funding"] = funding
    pnl = _dated(_object(fs.get("pnl"), FS + '.pnl').get("periods", []), "period", FS + ".pnl")
    bs = _dated(_object(fs.get("balance_sheet"), FS + '.balance_sheet').get("periods", []), "period_index", FS + ".balance_sheet")
    pf = _dated(_object(fs.get("pf_cash_waterfall"), FS + '.pf_cash_waterfall').get("periods", []), "period_index", FS + ".pf_cash_waterfall")
    if set(pnl) != set(bs) or set(pnl) != set(pf) or any(pnl[i]["date"] != bs[i]["date"] or pnl[i]["date"] != pf[i]["date"] for i in pnl):
        raise FinancingEvidenceInvalid("Statement period identities disagree")
    if funding and funding["available"]:
        evidence = rs["financing_evidence"]
        raw = (evidence["facility_schedules"] if funding["mode"] == "TWO_SENIOR" else
               [evidence["senior_facility"], evidence["junior_facility"]])
        view["facilities"] = [_facility(r, f, {i: p["date"] for i, p in pnl.items()})
                              for r, f in zip(raw, funding["instruments"])]
        view["checks"] = [c for f in view["facilities"] for c in f["checks"]]
        for role, pnl_key, bs_key, pf_key in (
            ("Senior", "senior_interest_expense_keur", "senior_balance_keur", "senior_total_ds_keur"),
            ("Junior", "junior_interest_expense_keur", "junior_balance_keur", "junior_debt_service_keur"),
        ):
            selected = [f for f in view["facilities"] if f["role"] == role]
            if not selected:
                continue
            indexed = [{r["index"]: n for n, r in enumerate(f["rows"])} for f in selected]
            for i in pnl:
                # Zero AFTER an explicit facility maturity is supported by the
                # complete schedule; a missing in-tenor period is never zero.
                for f, axis in zip(selected, indexed):
                    if f["rows"][0]["index"] <= i <= f["maturity"] and i not in axis:
                        raise FinancingEvidenceInvalid("Missing in-tenor facility period")
                for vector, canonical, key in (("interest_keur", pnl[i], pnl_key),
                                                ("closing_keur", bs[i], bs_key), ("debt_service_keur", pf[i], pf_key)):
                    total = fsum(f["raw"][vector][axis[i]] for f, axis in zip(selected, indexed) if i in axis)
                    view["checks"].append(_check(f"P{i} {role} {vector}", total, canonical.get(key),
                        f"{FIN}.facility.{vector} -> {FS}.{key}", display=True))
        view["checks"] += [{**c, "observed": c["instruments"], "canonical": c["aggregate"],
                            "source": c["aggregate"].authority, "basis": "Full-precision funding audit"}
                           for c in funding["checks"]]
        view["reason"] = ""
    else:
        view["reason"] = "Per-instrument evidence is unavailable for this aggregate-only Run. No split is reconstructed."
    # These are canonical statement values, not a newly computed waterfall.
    cash_fields = (("Revenue", "revenue_cash_keur"), ("EBITDA", "ebitda_cash_keur"),
                   ("Cash tax", "cash_tax_keur"), ("CFADS to Senior", "fcf_banks_keur"),
                   ("Senior service", "senior_total_ds_keur"), ("Junior service", "junior_debt_service_keur"),
                   ("Post-Junior cash", "post_junior_cash_keur"), ("Distribution-account inflow", "fcf_for_distribution_keur"),
                   ("Legal equity distribution", "net_dividends_keur"))
    view["cash_headers"] = tuple(label for label, key in cash_fields)
    view["cash"] = [{"index": i, "date": row["date"], "values": tuple(
        amount(label, row.get(key), FS + ".pf_cash_waterfall." + key) for label, key in cash_fields)} for i, row in pf.items()]
    tax = _object(thaw_runtime_payload(getattr(runtime_result, "tax_schedule", None)), 'RuntimeResult.tax_schedule')
    tax_rows = _dated(tax.get("periods", []), "period", "RuntimeResult.tax_schedule")
    if any(i not in pnl or row["date"] != pnl[i]["date"] for i, row in tax_rows.items()):
        raise FinancingEvidenceInvalid("Tax period identities disagree with statements")
    tax_fields = (("Tax depreciation", "tax_depreciation_audit_keur"), ("Taxable profit", "taxable_profit_keur"),
                  ("CIT accrual", "cit_accrual_audit_keur"), ("Corporate cash tax", "corporate_tax_cash_keur"),
                  ("Income before losses", "taxable_income_before_losses_audit_keur"),
                  ("Loss opening", "tax_loss_opening_audit_keur"), ("Loss used", "tax_loss_used_audit_keur"),
                  ("Loss closing", "tax_loss_closing_audit_keur"),
                  ("Profit after losses", "taxable_profit_after_losses_audit_keur"),
                  ("Current-period cash tax", "cash_tax_current_period_audit_keur"))
    view["tax_headers"] = tuple(label for label, key in tax_fields)
    view["tax"] = [{"index": i, "date": row["date"], "values": tuple(
        amount(label, row.get(key), "RuntimeResult.tax_schedule." + key) for label, key in tax_fields)} for i, row in tax_rows.items()]
    audit = _object(thaw_runtime_payload(integrity_evidence), 'Last Run Integrity')
    if audit:
        from app.run_integrity import evidence_digest
        if audit.get('schema') != 'RUN_INTEGRITY_EVIDENCE_V1' or audit.get('digest') != evidence_digest(audit):
            raise FinancingEvidenceInvalid('Integrity evidence digest or schema is invalid')
        from app.run_integrity.checks import check_balance_sheet
        balance = check_balance_sheet(audit)
        view['balance_audit'] = balance.to_dict()
        senior = _indexed(_object(audit.get("senior_debt"), 'Integrity Senior').get("periods", []), "period_index", "Integrity Senior")
        cash = _indexed(audit.get("cash", []), "period_index", "Integrity cash")
        junior = _indexed(_object(audit.get("junior_debt"), 'Integrity Junior').get("periods", []), "period_index", "Integrity Junior")
        sponsor_fields = (("SHL funding", "shl_contribution"), ("SHL cash interest", "shl_cash_interest"),
                          ("SHL principal", "shl_principal"), ("Legal equity distribution", "legal_equity_distribution"),
                          ("Pure equity net cash", "pure_equity_net"), ("Total sponsor net cash", "total_sponsor_net"))
        view['sponsor_headers'] = tuple(label for label, key in sponsor_fields)
        # G2C construction cash events and operating periods have DIFFERENT
        # grains; construction events may repeat a model index. Preserve their
        # native order/date, never join or aggregate them onto the model axis.
        sponsor = _object(audit.get('sponsor'), 'Integrity sponsor').get('periods', [])
        if not isinstance(sponsor, list):
            raise FinancingEvidenceInvalid('Sponsor event evidence unavailable')
        for row in sponsor:
            if not isinstance(row, Mapping) or type(row.get('period')) is not int or type(row.get('is_construction')) is not bool:
                raise FinancingEvidenceInvalid('Sponsor event identity invalid')
            try:
                date.fromisoformat(row['date'])
            except (KeyError, TypeError, ValueError):
                raise FinancingEvidenceInvalid('Sponsor event date unavailable') from None
        view['sponsor'] = [{'index': ('Construction event ' if row['is_construction'] else 'Operating ') + str(row['period']),
            'date': row['date'], 'values': tuple(amount(label, row.get(key),
            'Last Run Integrity sponsor.periods.' + key) for label, key in sponsor_fields)} for row in sponsor]
        for i, row in senior.items():
            a, b = _num(row.get("base_cfads")), _num(row.get("debt_service"))
            view["checks"].append(_check(f"P{i} Base CFADS less Senior service", a - b if a is not None and b is not None else None,
                cash.get(i, {}).get("cash_after_senior_before_reserves"), "Last Run Integrity base_cfads/debt_service/cash"))
            view['checks'].append(_check(f'P{i} Base CFADS to statement', row.get('base_cfads'),
                pf.get(i, {}).get('fcf_banks_keur'), 'Last Run Integrity base_cfads -> PF fcf_banks_keur', display=True))
            for vector, field in (('interest_keur', 'interest'), ('principal_keur', 'principal'),
                                  ('debt_service_keur', 'debt_service'), ('closing_keur', 'closing')):
                parts = []
                for f in view['facilities']:
                    if f['role'] == 'Senior':
                        axis = f['raw']['period_indices']
                        parts.append(f['raw'][vector][axis.index(i)] if i in axis else 0.)
                if parts:
                    view['checks'].append(_check(f'P{i} Senior facility {field} to audit', fsum(parts),
                        row.get(field), 'Financing facility schedule -> Last Run Integrity senior_debt'))
        for i, row in junior.items():
            a, b = _num(row.get("post_senior_cash")), _num(row.get("debt_service"))
            view["checks"].append(_check(f"P{i} post-Senior less Junior service", a - b if a is not None and b is not None else None,
                row.get("post_junior_cash"), "Last Run Integrity junior_debt.periods"))
            for f in view['facilities']:
                if f['role'] != 'Junior':
                    continue
                axis = f['raw']['period_indices']
                if i not in axis:
                    raise FinancingEvidenceInvalid('Junior Integrity period missing from facility')
                for vector, field in (('opening_keur', 'opening'), ('interest_keur', 'interest'),
                                      ('principal_keur', 'principal'), ('debt_service_keur', 'debt_service'), ('closing_keur', 'closing')):
                    view['checks'].append(_check(f'P{i} Junior facility {field} to audit', f['raw'][vector][axis.index(i)],
                        row.get(field), 'Financing facility schedule -> Last Run Integrity junior_debt'))
    from app.v2.returns_projection import build_returns_projection
    view["returns"] = build_returns_projection(runtime_result, None, runtime_is_stale=state != "CURRENT").metrics
    view["status"] = _status(view["checks"]) if view["facilities"] else "UNAVAILABLE"
    if funding and funding['status'] == 'DIFFERS':
        view['status'] = 'DIFFERS'
    return view
