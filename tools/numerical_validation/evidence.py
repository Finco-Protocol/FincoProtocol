"""F3.9 read-only evidence bundle for one committed FINCO Run.

``build_bundle`` turns the payloads a Run already persisted (runtime summary, financial statements, tax / debt /
distribution / sponsor schedules, Run Integrity evidence) into one normalised, identity-bound document.  It performs
NO calculation: it renames, aligns and serialises what is there.

* every value is a decimal STRING (never a float), and a value that is absent stays ``null`` - never zero;
* every series states its axis, unit, basis (full precision or persisted at 2 decimals) and the payload path it came from;
* period axes are keyed by date (ISO) and phase; an index that cannot be tied to a date, or a date that appears twice,
  is recorded in ``axis_errors`` and the affected series is withheld rather than repaired;
* nothing here imports a production financial module or runs a model.

The bundle is the ONLY input of the identity checks, so a report can always be reproduced from it.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from .reconcile import ReconciliationInputError, canonical_bytes

SCHEMA = "FINCO_NUMERICAL_EVIDENCE_V1"
UNIT = "kEUR"
CURRENCY = "EUR"
REQUIRED_IDENTITY = ("project_key", "scenario_key", "run_key", "snapshot_id", "composite_hash", "engine_version")

#: Conventions the checks rely on.  They are DECLARED here and hashed into the identity; none is inferred.
CONVENTIONS = {
    "currency": CURRENCY,
    "unit": UNIT,
    "statement_basis": "persisted at 2 decimal places (representation allowance applies only to these series)",
    "integrity_basis": "full precision as recorded at commit time",
    "period_key": "ISO date of the period row; construction and operation phases are kept apart",
    "revenue_period_label": r"Y<yyyy>-H<1|2>, valid only when it agrees with the row's date (half = month <= 6)",
    "xirr_day_count": "ACT/365 from the first flow date (the documented Excel-compatible basis)",
    "signs": "sources, revenue and distributions positive; uses, costs and contributions as recorded by the payload",
}

UNSUPPORTED = (
    ("facility_tax_attribution", "Facility-level deductible interest and tax allocation are not persisted (F3.8)."),
    ("investor_specific_returns", "Investor-specific allocation is F4 scope and is not evidenced here."),
    ("npv", "Project and equity NPV are not published by the persisted Run (no persisted discount basis)."),
    ("independent_project_irr", "The unlevered project cash-flow vector is not persisted, so Project IRR cannot be "
                                "recomputed independently."),
    ("generation_times_price", "Generation is persisted only as display text and the price path is not persisted."),
    ("external_workbook_parity", "No authorised independent workbook reference is part of this repository."),
)

_LABEL = re.compile(r"^Y(\d{4})-H([12])$")


def dec(value: Any) -> str | None:
    """Decimal text for a finite number; ``None`` for anything absent, boolean, non-finite or non-numeric."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(Decimal(repr(value)), "f") if math.isfinite(value) else None
    return None


def _rows(payload: Any, *path: str) -> list[Mapping] | None:
    node = payload
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, list) and all(isinstance(r, Mapping) for r in node) else None


def _num_map(payload: Any, *path: str) -> Mapping | None:
    node = payload
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, Mapping) else None


class _Builder:
    def __init__(self, identity: Mapping[str, Any]):
        self.identity = dict(identity)
        self.axes: dict[str, list[dict[str, Any]]] = {}
        self.axis_errors: list[dict[str, str]] = []
        self.series: dict[str, dict[str, Any]] = {}
        self.scalars: dict[str, dict[str, Any]] = {}
        self.facts: dict[str, Any] = {}
        self.index_to_key: dict[int, str] = {}

    def error(self, axis: str, reason: str, detail: str = "") -> None:
        self.axis_errors.append({"axis": axis, "reason": reason, "detail": detail})

    def add_series(self, sid: str, axis: str, basis: str, source: str, values: dict[str, str | None]) -> None:
        self.series[sid] = {"axis": axis, "unit": UNIT, "basis": basis, "source": source, "values": values}

    def add_unit_series(self, sid: str, axis: str, unit: str, basis: str, source: str,
                        values: dict[str, str | None]) -> None:
        self.series[sid] = {"axis": axis, "unit": unit, "basis": basis, "source": source, "values": values}

    def add_ratio(self, sid: str, axis: str, source: str, values: dict[str, str | None]) -> None:
        self.series[sid] = {"axis": axis, "unit": "ratio", "basis": "FULL_PRECISION", "source": source,
                            "values": values}

    def add_scalar(self, sid: str, value: Any, source: str, *, unit: str = UNIT, basis: str = "FULL_PRECISION") -> None:
        self.scalars[sid] = {"unit": unit, "basis": basis, "source": source, "value": dec(value)}

    # ── axes ──────────────────────────────────────────────────────────────────────────────────────
    def statements_axis(self, financial_statements: Any, tax_schedule: Any) -> None:
        rows = _rows(financial_statements, "pnl", "periods")
        if not rows:
            self.error("statements", "STATEMENT_AXIS_MISSING", "financial_statements.pnl.periods")
            return
        phase = {}
        for row in _rows(tax_schedule, "periods") or []:
            if isinstance(row.get("period"), int) and isinstance(row.get("is_operation"), bool):
                phase[row["period"]] = "operation" if row["is_operation"] else "construction"
        axis, seen = [], set()
        for row in rows:
            index, date = row.get("period"), row.get("date")
            if type(index) is not int or not isinstance(date, str):
                self.error("statements", "STATEMENT_ROW_WITHOUT_INDEX_OR_DATE", repr(row.get("period")))
                continue
            if date in seen or index in self.index_to_key:
                self.error("statements", "DUPLICATE_PERIOD", f"index {index} / {date}")
                continue
            seen.add(date)
            self.index_to_key[index] = date
            axis.append({"key": date, "index": index, "phase": phase.get(index, "unknown")})
        self.axes["statements"] = axis

    def dated_series(self, name: str, sid_prefix: str, rows: list[Mapping] | None, index_field: str,
                     fields: Mapping[str, str], basis: str, source: str) -> None:
        """Series keyed by the statement date of each row's index; a row whose date disagrees is a conflict."""
        if rows is None:
            return
        values: dict[str, dict[str, str | None]] = {out: {} for out in fields.values()}
        for row in rows:
            index = row.get(index_field)
            key = self.index_to_key.get(index) if type(index) is int else None
            if key is None:
                self.error(name, "INDEX_NOT_ON_STATEMENT_AXIS", repr(index))
                continue
            date = row.get("date")
            if isinstance(date, str) and date != key:
                self.error(name, "DATE_DISAGREES_WITH_STATEMENT_AXIS", f"index {index}: {date} != {key}")
                continue
            for src, out in fields.items():
                values[out][key] = dec(row.get(src))
        for out, vals in values.items():
            self.add_series(f"{sid_prefix}.{out}", "statements", basis, f"{source}.{out}", vals)


def _sponsor(builder: _Builder, evidence: Any) -> None:
    rows = _rows(evidence, "sponsor", "periods")
    if rows is None:
        return
    axis, seen = [], set()
    fields = ("share_capital", "share_premium", "other_committed_equity", "additional_equity", "shl_contribution",
              "shl_cash_interest", "shl_principal", "legal_equity_distribution", "pure_equity_net", "total_sponsor_net")
    values: dict[str, dict[str, str | None]] = {f: {} for f in fields}
    for row in rows:
        date = row.get("date")
        phase = "construction" if row.get("is_construction") is True else "operation" if row.get(
            "is_construction") is False else "unknown"
        if not isinstance(date, str) or date in seen:
            builder.error("sponsor", "DUPLICATE_OR_MISSING_DATE", f"period {row.get('period')!r} / {date!r}")
            continue
        seen.add(date)
        axis.append({"key": date, "index": row.get("period"), "phase": phase})
        for f in fields:
            values[f][date] = dec(row.get(f))
    builder.axes["sponsor"] = axis
    for f, vals in values.items():
        builder.add_series(f"ev.sponsor.{f}", "sponsor", "FULL_PRECISION", f"integrity_evidence.sponsor.periods.{f}", vals)


def _facility(builder: _Builder, fid: str, raw: Any, source: str) -> None:
    if not isinstance(raw, Mapping):
        return
    indices = raw.get("period_indices")
    if not isinstance(indices, list) or any(type(i) is not int for i in indices):
        builder.error(f"facility.{fid}", "FACILITY_AXIS_MISSING", source)
        return
    for field in ("opening_keur", "interest_keur", "principal_keur", "debt_service_keur", "closing_keur"):
        vector = raw.get(field)
        if not isinstance(vector, list) or len(vector) != len(indices):
            builder.error(f"facility.{fid}", "FACILITY_VECTOR_LENGTH", f"{field}")
            continue
        values: dict[str, str | None] = {}
        for index, value in zip(indices, vector):
            key = builder.index_to_key.get(index)
            if key is None:
                builder.error(f"facility.{fid}", "INDEX_NOT_ON_STATEMENT_AXIS", repr(index))
                continue
            values[key] = dec(value)
        builder.add_series(f"fac.{fid}.{field.removesuffix('_keur')}", "statements", "FULL_PRECISION",
                           f"{source}.{field}", values)
    for field, name in (("construction_draws_keur", "construction_draws_total"),
                        ("construction_idc_keur", "construction_idc_total"),
                        ("construction_commitment_fees_keur", "commitment_fees_total"),
                        ("upfront_fees_keur", "upfront_fees_total")):
        vector = raw.get(field)
        # The total exists only when EVERY recorded construction value is a finite number: nothing is defaulted.
        total = (math.fsum(vector) if isinstance(vector, list) and vector
                 and all(dec(x) is not None for x in vector) else None)
        builder.add_scalar(f"fac.{fid}.{name}", total, f"{source}.{field} (sum of the recorded vector)")
    builder.add_scalar(f"fac.{fid}.commitment", raw.get("commitment_keur"), f"{source}.commitment_keur")
    builder.facts[f"fac.{fid}.maturity_period_index"] = raw.get("maturity_period_index")


def _contract_revenue(b: _Builder, audit: list[Mapping]) -> None:
    """Revenue V2 explicit-contract evidence, keyed by statement date (never by label or guessed order)."""
    types: dict[str, str] = {}
    period: dict[str, dict[str, str | None]] = {k: {} for k in ("net_revenue", "settlement", "balancing",
                                                                   "certificate", "unallocated")}
    streams: dict[str, dict[str, dict[str, str | None]]] = {}
    for row in audit:
        index = row.get("period_index")
        key = b.index_to_key.get(index) if type(index) is int else None
        if key is None:
            b.error("revenue_contracts", "INDEX_NOT_ON_STATEMENT_AXIS", repr(index))
            continue
        for name, src in (("net_revenue", "net_revenue_keur"), ("settlement", "settlement_keur"),
                          ("balancing", "balancing_cost_keur"), ("certificate", "legacy_certificate_revenue_keur"),
                          ("unallocated", "unallocated_generation_mwh")):
            period[name][key] = dec(row.get(src))
        for stream in row.get("streams") or []:
            sid = stream.get("id") if isinstance(stream, Mapping) else None
            if not isinstance(sid, str):
                b.error("revenue_contracts", "STREAM_WITHOUT_ID", key)
                continue
            if types.setdefault(sid, str(stream.get("type"))) != str(stream.get("type")):
                b.error("revenue_contracts", "STREAM_TYPE_CHANGES", sid)
            for name, src in (("quantity", "quantity_mwh"), ("price", "price_eur_mwh"), ("revenue", "revenue_keur"),
                              ("settlement", "settlement_keur"), ("capture", "capture_rate")):
                streams.setdefault(sid, {}).setdefault(name, {})[key] = dec(stream.get(src))
    src = "runtime_summary.revenue_multistream_audit"
    for name, unit in (("net_revenue", UNIT), ("settlement", UNIT), ("balancing", UNIT), ("certificate", UNIT),
                       ("unallocated", "MWh")):
        b.add_unit_series(f"rv2.{name}", "statements", unit, "FULL_PRECISION", f"{src}.{name}", period[name])
    units = {"quantity": "MWh", "price": "EUR/MWh", "revenue": UNIT, "settlement": UNIT, "capture": "ratio"}
    for sid, fields in streams.items():
        for name, values in fields.items():
            b.add_unit_series(f"rv2.stream.{sid}.{name}", "statements", units[name], "FULL_PRECISION",
                              f"{src}.streams.{name}", values)
    b.facts["rv2.streams"] = types


def build_bundle(payloads: Mapping[str, Any], identity: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise the persisted payloads of ONE Run into an identity-bound evidence bundle (no calculation)."""
    missing = [k for k in REQUIRED_IDENTITY if not identity.get(k)]
    if missing:
        raise ReconciliationInputError("bundle identity incomplete: " + ", ".join(missing))
    summary = payloads.get("runtime_summary") or {}
    statements = payloads.get("financial_statements")
    tax = payloads.get("tax_schedule")
    debt = payloads.get("debt_schedule")
    dist = payloads.get("distribution_schedule")
    sponsor = payloads.get("sponsor_schedule")
    evidence = payloads.get("integrity_evidence")
    b = _Builder(identity)
    b.statements_axis(statements, tax)

    # Persisted statements (2 decimals).
    b.dated_series("pnl", "stmt.pnl", _rows(statements, "pnl", "periods"), "period",
                   {"revenues_keur": "revenues", "operating_expenses_keur": "operating_expenses",
                    "depreciation_keur": "depreciation", "ebit_keur": "ebit",
                    "senior_interest_expense_keur": "senior_interest_expense", "cit_accrual_keur": "cit_accrual",
                    "net_income_keur": "net_income"}, "PERSISTED_2DP", "financial_statements.pnl.periods")
    b.dated_series("pf", "stmt.pf", _rows(statements, "pf_cash_waterfall", "periods"), "period_index",
                   {"revenue_cash_keur": "revenue_cash", "opex_cash_keur": "opex_cash", "ebitda_cash_keur": "ebitda_cash",
                    "cash_tax_keur": "cash_tax", "senior_total_ds_keur": "senior_total_ds",
                    "fcf_banks_keur": "fcf_banks", "fcf_for_distribution_keur": "fcf_for_distribution",
                    "net_dividends_keur": "net_dividends"}, "PERSISTED_2DP",
                   "financial_statements.pf_cash_waterfall.periods")
    b.dated_series("debt", "debt", _rows(debt, "periods"), "period",
                   {"senior_ds_keur": "senior_ds", "senior_interest_keur": "senior_interest",
                    "senior_principal_keur": "senior_principal", "senior_balance_keur": "senior_balance"},
                   "PERSISTED_2DP", "debt_schedule.periods")
    b.dated_series("tax", "tax", _rows(tax, "periods"), "period",
                   {"corporate_tax_cash_keur": "corporate_tax_cash", "tax_keur": "tax"},
                   "PERSISTED_2DP", "tax_schedule.periods")
    b.dated_series("tax_audit", "tax_audit", _rows(tax, "periods"), "period",
                   {"taxable_income_before_losses_audit_keur": "taxable_income_before_losses",
                    "tax_loss_used_audit_keur": "tax_loss_used",
                    "taxable_profit_after_losses_audit_keur": "taxable_profit_after_losses",
                    "tax_loss_opening_audit_keur": "tax_loss_opening", "tax_loss_closing_audit_keur": "tax_loss_closing",
                    "cit_accrual_audit_keur": "cit_accrual", "cash_tax_current_period_audit_keur": "cash_tax_current"},
                   "PERSISTED_2DP", "tax_schedule.periods")

    # Full-precision Run Integrity evidence.
    if isinstance(evidence, Mapping):
        b.dated_series("ev.senior", "ev.senior", _rows(evidence, "senior_debt", "periods"), "period_index",
                       {"opening": "opening", "interest": "interest", "principal": "principal", "closing": "closing",
                        "debt_service": "debt_service", "annual_rate": "annual_rate", "day_fraction": "day_fraction",
                        "base_cfads": "base_cfads", "bank_cfads": "bank_cfads", "reported_dscr": "reported_dscr",
                        "target_dscr": "target_dscr", "availability": "availability"},
                       "FULL_PRECISION", "integrity_evidence.senior_debt.periods")
        b.dated_series("ev.cash", "ev.cash", _rows(evidence, "cash"), "period_index",
                       {"cash_after_senior_before_reserves": "after_senior"}, "FULL_PRECISION",
                       "integrity_evidence.cash")
        bs_fields = ("gross_fixed_assets", "accumulated_depreciation", "unrestricted_cash", "dsra_balance",
                     "distribution_account", "senior_debt", "shl", "share_capital", "share_premium", "legal_reserve",
                     "retained_earnings", "net_cit_payable", "additional_equity", "junior_debt", "reported_balance_check")
        b.dated_series("ev.bs", "ev.bs", _rows(evidence, "balance_sheet"), "period_index",
                       {f: f for f in bs_fields}, "FULL_PRECISION", "integrity_evidence.balance_sheet")
        junior = _rows(evidence, "junior_debt", "periods")
        b.dated_series("ev.junior", "ev.junior", junior, "period_index",
                       {"opening": "opening", "interest": "interest", "principal": "principal", "closing": "closing",
                        "debt_service": "debt_service", "annual_rate": "annual_rate", "day_fraction": "day_fraction",
                        "post_senior_cash": "post_senior_cash", "post_junior_cash": "post_junior_cash"},
                       "FULL_PRECISION", "integrity_evidence.junior_debt.periods")
        _sponsor(b, evidence)
        # Sources & Uses
        su = _num_map(evidence, "sources_uses", "summary") or {}
        for k in sorted(su):
            b.add_scalar(f"su.{k}", su[k], f"integrity_evidence.sources_uses.summary.{k}")
        construction = _rows(evidence, "sources_uses", "construction_periods")
        if construction is not None:
            axis, uses, sources = [], {}, {}
            for row in construction:
                key = f"C{row.get('period')}"
                if key in uses:
                    b.error("construction", "DUPLICATE_PERIOD", key)
                    continue
                axis.append({"key": key, "index": row.get("period"), "phase": "construction"})
                uses[key], sources[key] = dec(row.get("uses")), dec(row.get("sources"))
            b.axes["construction"] = axis
            b.series["su.construction.uses"] = {"axis": "construction", "unit": UNIT, "basis": "FULL_PRECISION",
                                                  "source": "integrity_evidence.sources_uses.construction_periods.uses",
                                                  "values": uses}
            b.series["su.construction.sources"] = {"axis": "construction", "unit": UNIT, "basis": "FULL_PRECISION",
                                                     "source": "integrity_evidence.sources_uses.construction_periods.sources",
                                                     "values": sources}
        nc = _num_map(summary, "financing_evidence", "construction_funding", "non_construction_fc_use") or {}
        for k, name in (("uses_keur", "uses"), ("total_sources_keur", "sources")):
            b.add_scalar(f"su.nonconstruction.{name}", nc.get(k),
                         f"runtime_summary.financing_evidence.construction_funding.non_construction_fc_use.{k}")
        audit = _num_map(evidence, "sources_uses", "audit") or {}
        for k in ("uses", "sources", "residual"):
            b.add_scalar(f"su.audit.{k}", audit.get(k), f"integrity_evidence.sources_uses.audit.{k}")
        sd = _num_map(evidence, "senior_debt") or {}
        b.facts["day_count"] = sd.get("day_count")
        b.facts["senior_converged"] = (_num_map(evidence, "senior_debt", "diagnostics") or {}).get("converged")
        b.facts["financing_authority"] = evidence.get("financing_authority")
        b.add_scalar("junior.commitment", (_num_map(evidence, "junior_debt") or {}).get("commitment"),
                     "integrity_evidence.junior_debt.commitment")
        b.facts["integrity_digest"] = evidence.get("digest")
        b.facts["integrity_schema"] = evidence.get("schema")
        rep = _num_map(evidence, "sponsor", "reported") or {}
        for k in ("pure_equity_xirr", "total_sponsor_xirr"):
            b.add_scalar(f"ret.{k}", rep.get(k), f"integrity_evidence.sponsor.reported.{k}", unit="ratio")
            b.facts[f"ret.{k}_status"] = rep.get(k + "_status")

    # Revenue periods (axis by label, validated against the statement dates later by the identities).
    rev = _rows(summary, "revenue_derivation", "revenue_periods")
    if rev is not None:
        axis, raw = [], {}
        for position, row in enumerate(rev):
            label = row.get("period_label")
            if not isinstance(label, str) or not _LABEL.match(label) or label in raw:
                b.error("revenue", "REVENUE_LABEL_INVALID_OR_DUPLICATE", repr(label))
                continue
            axis.append({"key": label, "index": position, "phase": "operation"})
            raw[label] = dec(row.get("revenue_keur_raw"))
        b.axes["revenue"] = axis
        b.series["rev.period_revenue"] = {"axis": "revenue", "unit": UNIT, "basis": "FULL_PRECISION",
                                           "source": "runtime_summary.revenue_derivation.revenue_periods.revenue_keur_raw",
                                           "values": raw}
        generation = {}
        for row in rev:
            label, text = row.get("period_label"), row.get("generation_mwh")
            match = re.fullmatch(r"\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*MWh\s*", text) if isinstance(text, str) else None
            if label in raw:
                generation[label] = match.group(1).replace(",", "") if match else None
        b.add_unit_series("rev.generation_display", "revenue", "MWh", "PERSISTED_DISPLAY_ROUNDED_1MWH",
                          "runtime_summary.revenue_derivation.revenue_periods.generation_mwh (display text)", generation)

    # Scalars from the runtime summary.
    for k in ("total_revenue_keur", "total_opex_keur", "total_ebitda_keur", "total_senior_ds_keur",
              "total_distributions_keur", "total_tax_keur", "total_capex_keur", "total_project_uses_keur",
              "senior_debt_keur", "total_shl_service_keur", "derived_shl_cash_keur"):
        b.add_scalar(f"summary.{k}", summary.get(k), f"runtime_summary.{k}")
    for k in ("project_irr", "equity_irr", "sponsor_irr", "total_sponsor_xirr", "min_dscr", "avg_dscr"):
        b.add_scalar(f"summary.{k}", summary.get(k), f"runtime_summary.{k}", unit="ratio")
    for k in ("project_npv_keur", "equity_npv_keur"):
        b.add_scalar(f"summary.{k}", summary.get(k), f"runtime_summary.{k}")
    ssum = _num_map(sponsor, "summary") or {}
    b.add_scalar("sponsor.project_xirr", ssum.get("project_xirr"), "sponsor_schedule.summary.project_xirr", unit="ratio")
    b.add_scalar("sponsor.total_legal_equity_distributions", ssum.get("total_legal_equity_distributions_keur"),
                 "sponsor_schedule.summary.total_legal_equity_distributions_keur")
    b.add_scalar("tax.total_tax", (_num_map(tax, "summary") or {}).get("total_tax_keur"),
                 "tax_schedule.summary.total_tax_keur", basis="PERSISTED_2DP")
    b.add_scalar("dist.total_distribution", (_num_map(dist, "summary") or {}).get("total_distribution_keur"),
                 "distribution_schedule.summary.total_distribution_keur", basis="PERSISTED_2DP")

    # Facility schedules (two Senior, or Senior + Junior through the controlled test-only path).
    fe = summary.get("financing_evidence") if isinstance(summary, Mapping) else None
    fe = fe if isinstance(fe, Mapping) else {}
    b.facts["financing_evidence_authority"] = fe.get("authority")
    b.facts["facility_authority"] = fe.get("facility_authority")
    facilities = fe.get("facility_schedules")
    if isinstance(facilities, list):
        for raw in facilities:
            fid = raw.get("instrument_id") if isinstance(raw, Mapping) else None
            if isinstance(fid, str):
                _facility(b, fid, raw, "runtime_summary.financing_evidence.facility_schedules")
    for name in ("senior_facility", "junior_facility"):
        raw = fe.get(name)
        if isinstance(raw, Mapping):
            _facility(b, name, raw, f"runtime_summary.financing_evidence.{name}")
    junior_idc = fe.get("junior_cash_idc")
    vector = junior_idc.get("capitalized_cash_by_period_keur") if isinstance(junior_idc, Mapping) else None
    b.add_scalar("junior.cash_idc_total",
                 math.fsum(vector) if isinstance(vector, list) and vector and all(dec(x) is not None for x in vector)
                 else None, "runtime_summary.financing_evidence.junior_cash_idc.capitalized_cash_by_period_keur (sum)")
    b.facts["facilities"] = sorted({k.split(".")[1] for k in b.series if k.startswith("fac.")})

    # Contracted-revenue streams (Revenue V2), when the Run used an explicit contract book.
    audit = summary.get("revenue_multistream_audit") if isinstance(summary, Mapping) else None
    if isinstance(audit, list) and audit:
        _contract_revenue(b, [row for row in audit if isinstance(row, Mapping)])

    for sid, item in b.series.items():          # rates and day fractions are ratios, never kEUR
        if sid.endswith((".day_fraction", ".annual_rate")):
            item["unit"] = "ratio"
    conventions_sha = hashlib.sha256(canonical_bytes(CONVENTIONS)).hexdigest()
    source = {k: v for k, v in payloads.items() if v is not None}
    ident = dict(identity)
    ident.setdefault("currency", CURRENCY)
    ident["conventions_sha256"] = conventions_sha
    ident["source_sha256"] = hashlib.sha256(canonical_bytes(source)).hexdigest()
    ident["financing_authority"] = b.facts.get("financing_authority") or fe.get("authority") or "UNAVAILABLE"
    bundle = {
        "schema": SCHEMA, "identity": ident, "conventions": CONVENTIONS, "axes": b.axes,
        "axis_errors": b.axis_errors, "series": b.series, "scalars": b.scalars, "facts": b.facts,
        "unsupported": [{"capability": k, "reason": v} for k, v in UNSUPPORTED],
        "payloads_present": sorted(k for k, v in payloads.items() if v is not None),
    }
    json.dumps(bundle, allow_nan=False)  # fails loudly if a non-JSON value slipped in
    return bundle
