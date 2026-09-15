"""
app.workbook.runtime_projection — unified persisted runtime projection layer.

Pure module: no FastAPI, no Jinja2, no database calls.
Accepts a RuntimeResult (or None) and workspace dirty flag; returns typed
projection bundles consumed by router adapters and OOB view helpers.

State machine (per sheet payload):
    NOT_RUN     — no RuntimeResult exists
    UNAVAILABLE — rr exists but this sheet's payload is absent  (beats STALE)
    STALE       — rr + payload + workspace dirty
    CLEAN       — rr + payload + workspace clean

Structural availability contract for debt/tax schedules:
    payload is None                       → UNAVAILABLE, periods=None
    payload is {}                         → UNAVAILABLE, periods=None
    payload exists but "periods" key absent → UNAVAILABLE, periods=None
    payload["periods"] is None            → UNAVAILABLE, periods=None
    payload["periods"] == []              → CLEAN or STALE, periods=[]
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, List, Optional


# ── State enum ──────────────────────────────────────────────────────────── #

class RuntimeProjectionState(str, Enum):
    NOT_RUN     = "NOT_RUN"
    CLEAN       = "CLEAN"
    STALE       = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


# ── Shared utilities ─────────────────────────────────────────────────────── #

def thaw_runtime_payload(obj: Any) -> Any:
    """Recursively convert MappingProxyType → plain dict for template rendering."""
    if isinstance(obj, MappingProxyType):
        return {k: thaw_runtime_payload(v) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {k: thaw_runtime_payload(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [thaw_runtime_payload(i) for i in obj]
    return obj


def _schedule_has_valid_periods(schedule: Optional[Dict]) -> bool:
    """True iff schedule is a non-empty dict with a non-None 'periods' key."""
    if not schedule:
        return False
    if "periods" not in schedule:
        return False
    return schedule["periods"] is not None


def classify_runtime_state(
    rr: Any,
    payload: Any,
    is_dirty: bool,
) -> RuntimeProjectionState:
    """Classify state for FS-style payloads (top-level dict presence only).

    UNAVAILABLE takes precedence over STALE: if the run completed but the
    payload was not persisted, the bar must say "unavailable", not "stale".
    """
    if rr is None:
        return RuntimeProjectionState.NOT_RUN
    if not payload:
        return RuntimeProjectionState.UNAVAILABLE
    if is_dirty:
        return RuntimeProjectionState.STALE
    return RuntimeProjectionState.CLEAN


def classify_schedule_state(
    rr: Any,
    schedule: Optional[Dict],
    is_dirty: bool,
) -> RuntimeProjectionState:
    """Classify state for debt/tax schedule payloads with explicit periods-key check.

    All four structural-unavailability conditions map to UNAVAILABLE:
      - schedule is None
      - schedule is {} (empty, no "periods" key)
      - schedule has keys but "periods" is absent
      - schedule["periods"] is None

    Only schedule["periods"] == [] (present, non-None, but empty) is CLEAN/STALE.
    """
    if rr is None:
        return RuntimeProjectionState.NOT_RUN
    if not _schedule_has_valid_periods(schedule):
        return RuntimeProjectionState.UNAVAILABLE
    if is_dirty:
        return RuntimeProjectionState.STALE
    return RuntimeProjectionState.CLEAN


def extract_periods(
    schedule: Optional[Dict],
    operational_only: bool = False,
) -> Optional[List[Dict]]:
    """Return the periods list from a thawed schedule dict.

    Returns None for all structural-unavailability conditions:
      schedule is None, {}, missing 'periods' key, or periods is None.
    Returns [] when periods list is explicitly empty.
    When operational_only=True, filters to is_operation=True entries.
    """
    if not _schedule_has_valid_periods(schedule):
        return None
    raw: List[Dict] = schedule["periods"]  # type: ignore[index]
    if operational_only:
        return [p for p in raw if p.get("is_operation")]
    return raw


def project_period_labels(periods: Optional[List[Dict]]) -> List[str]:
    """Extract YYYY-MM display labels from period date fields."""
    if not periods:
        return []
    return [
        p.get("date", "")[:7] if p.get("date") else "—"
        for p in periods
    ]


def project_rows(
    row_defs: List[tuple],
    periods: Optional[List[Dict]],
) -> Optional[List[Dict]]:
    """Build presentation rows from payload periods.

    Returns None when periods is None (no runtime / statement unavailable).
    Returns [] when periods is [] (run produced zero periods).
    Values are preserved verbatim: None stays None, 0 stays 0.
    No arithmetic is performed.
    """
    if periods is None:
        return None
    return [
        {
            "key": key,
            "label": label,
            "is_total": is_total,
            "is_stock": is_stock,
            "values": [p.get(key) for p in periods],
        }
        for key, label, is_total, is_stock in row_defs
    ]


def annotate_balance_check_row(rows: Optional[List[Dict]]) -> Optional[List[Dict]]:
    """Classify the balance_check_keur row server-side.

    Adds 'balance_check_ok' (bool), 'css_class' (str), and 'status_title' (str)
    to the balance_check_keur row so Jinja performs no numeric comparison.
    The threshold is ±1 kEUR.  All other rows are returned unchanged.
    Values of None are treated as 0 for threshold purposes only.
    """
    if rows is None:
        return None
    result = []
    for row in rows:
        if row.get("key") != "balance_check_keur":
            result.append(row)
            continue
        values = row.get("values", [])
        warn = any(
            abs(v) > 1.0
            for v in values
            if v is not None
        )
        result.append({
            **row,
            "balance_check_ok": not warn,
            "css_class": "v2-bs-balance-check-ok" if not warn else "v2-bs-balance-check-warn",
            "status_title": "Balanced within ±1 kEUR" if not warn else "Balance sheet does not balance",
        })
    return result


# ── Financial Statements row definitions ─────────────────────────────────── #
# (key, display_label, is_total, is_stock)
# is_stock=True  → Annual value = year-end period value  (balance sheet items)
# is_stock=False → Annual value = sum of all model periods in the year (flow items)

FS_PNL_ROW_DEFS: List[tuple] = [
    ("revenues_keur",                "Revenues",             False, False),
    ("operating_expenses_keur",      "Operating Expenses",   False, False),
    ("depreciation_keur",            "Depreciation",         False, False),
    ("ebit_keur",                    "EBIT",                 True,  False),
    ("senior_interest_expense_keur", "Senior Interest",      False, False),
    ("shl_interest_expense_keur",    "SHL Interest",         False, False),
    ("earnings_before_tax_keur",     "Earnings Before Tax",  True,  False),
    ("cit_accrual_keur",             "CIT Accrual",          False, False),
    ("net_income_keur",              "Net Income",           True,  False),
    ("retained_earnings_keur",       "Retained Earnings",    False, True),
    ("net_dividends_keur",           "Net Dividends",        False, False),
]

FS_PF_CF_ROW_DEFS: List[tuple] = [
    ("revenue_cash_keur",          "Revenue Cash",         False, False),
    ("opex_cash_keur",             "OPEX Cash",            False, False),
    ("ebitda_cash_keur",           "EBITDA Cash",          True,  False),
    ("cash_tax_keur",              "Cash Tax",             False, False),
    ("fcf_banks_keur",             "FCF to Banks",         True,  False),
    ("senior_total_ds_keur",       "Senior Total DS",      False, False),
    ("dsra_funding_keur",          "DSRA Funding",         False, False),
    ("dsra_release_keur",          "DSRA Release",         False, False),
    ("fcf_junior_keur",            "FCF Junior",           False, False),
    ("fcf_for_distribution_keur",  "FCF for Distribution", True,  False),
    ("net_dividends_keur",         "Net Dividends",        False, False),
]

FS_BS_ROW_DEFS: List[tuple] = [
    ("net_fixed_assets_keur",          "Net Fixed Assets",           False, True),
    ("dsra_balance_keur",              "DSRA Balance",               False, True),
    ("cash_keur",                      "Cash",                       False, True),
    ("total_assets_keur",              "Total Assets",               True,  True),
    ("share_capital_keur",             "Share Capital ★",            False, True),
    ("retained_earnings_keur",         "Retained Earnings",          False, True),
    ("shl_balance_keur",               "SHL Balance",                False, True),
    ("senior_balance_keur",            "Senior Balance",             False, True),
    ("total_liabilities_equity_keur",  "Total Liabilities + Equity", True,  True),
    ("balance_check_keur",             "Balance Check",              False, True),
]


def _year_from_label(label: str) -> Optional[str]:
    """Return the 4-digit year string from a YYYY-MM label, or None."""
    if label and len(label) >= 4:
        return label[:4]
    return None


def aggregate_to_annual(
    rows: Optional[List[Dict]],
    period_labels: List[str],
) -> tuple:
    """Aggregate model-period rows to annual rows and annual labels.

    Flow items (is_stock=False): annual value = sum of all model periods in year.
    Stock items (is_stock=True):  annual value = last model period in year.
    None values are treated as 0 for flow summation; last-value for stock.

    Returns (annual_rows, annual_labels) where annual_labels are the year strings
    in ascending order.  Returns (None, []) when rows is None.
    """
    if rows is None:
        return None, []
    if not rows or not period_labels:
        return [], []

    # Group period indices by year.
    years_ordered: List[str] = []
    year_to_indices: Dict[str, List[int]] = {}
    for i, lbl in enumerate(period_labels):
        yr = _year_from_label(lbl)
        if yr is None:
            continue
        if yr not in year_to_indices:
            years_ordered.append(yr)
            year_to_indices[yr] = []
        year_to_indices[yr].append(i)

    if not years_ordered:
        return [], []

    annual_rows: List[Dict] = []
    for row in rows:
        is_stock = row.get("is_stock", False)
        vals = row.get("values", [])
        annual_vals: List[Any] = []
        for yr in years_ordered:
            indices = year_to_indices[yr]
            period_vals = [vals[i] for i in indices if i < len(vals)]
            if is_stock:
                # year-end: last non-None value; None if all None
                val = None
                for v in period_vals:
                    if v is not None:
                        val = v
                annual_vals.append(val)
            else:
                # flow: sum; None if all None
                non_none = [v for v in period_vals if v is not None]
                annual_vals.append(sum(non_none) if non_none else None)
        annual_rows.append({
            "key": row["key"],
            "label": row["label"],
            "is_total": row.get("is_total", False),
            "is_stock": is_stock,
            "values": annual_vals,
        })

    return annual_rows, years_ordered


def fs_classify_statement(rr: Any, fs: Optional[Dict], statement_key: str) -> str:
    """Per-statement classification: NOT_RUN / PARTIAL / UNAVAILABLE."""
    if rr is None:
        return "NOT_RUN"
    if fs is None:
        return "UNAVAILABLE"
    if statement_key not in fs:
        return "UNAVAILABLE"
    if fs[statement_key].get("periods") is None:
        return "UNAVAILABLE"
    return "PARTIAL"


# ── Typed projection structs ──────────────────────────────────────────────── #

@dataclass(frozen=True)
class RuntimeProjectionMeta:
    """Identity and state metadata shared from the single RuntimeResult.

    snapshot_id, ran_at, and origin come from the persisted RuntimeResult and
    are identical across all three sheet projections built from the same rr.
    Only state and has_payload differ per sheet.
    """
    state: RuntimeProjectionState
    has_runtime: bool
    has_payload: bool
    is_dirty: bool
    snapshot_id: Optional[str]
    ran_at: Optional[str]
    origin: Optional[str]


@dataclass(frozen=True)
class DebtRuntimeProjection:
    meta: RuntimeProjectionMeta
    # Canonical field names
    source: Optional[Dict]          # thawed authoritative schedule payload
    periods: Optional[List[Dict]]   # all source periods in original order
    operational_periods: Optional[List[Dict]]
    summary: Optional[Dict]
    # Backward-compat aliases (same objects, no copy)
    state: RuntimeProjectionState
    schedule: Optional[Dict]        # alias for source
    runtime_summary: Optional[Dict] # alias for summary


@dataclass(frozen=True)
class TaxRuntimeProjection:
    meta: RuntimeProjectionMeta
    # Canonical field names
    source: Optional[Dict]
    periods: Optional[List[Dict]]
    operational_periods: Optional[List[Dict]]
    summary: Optional[Dict]
    # Backward-compat aliases
    state: RuntimeProjectionState
    schedule: Optional[Dict]
    runtime_summary: Optional[Dict]


@dataclass(frozen=True)
class FinancialStatementsProjection:
    meta: RuntimeProjectionMeta
    state: RuntimeProjectionState
    fs_available: bool
    pnl_rows: Optional[List[Dict]]
    bs_rows: Optional[List[Dict]]
    pf_cf_rows: Optional[List[Dict]]
    pnl_period_labels: List[str]
    bs_period_labels: List[str]
    pf_cf_period_labels: List[str]
    pnl_classification: str
    bs_classification: str
    pf_cf_classification: str
    runtime_summary: Optional[Dict]
    # Annual aggregated rows and labels (server-side; None when no data)
    pnl_annual_rows: Optional[List[Dict]]
    bs_annual_rows: Optional[List[Dict]]
    pf_cf_annual_rows: Optional[List[Dict]]
    pnl_annual_labels: List[str]
    bs_annual_labels: List[str]
    pf_cf_annual_labels: List[str]


@dataclass(frozen=True)
class WorkbookRuntimeProjection:
    debt: DebtRuntimeProjection
    tax: TaxRuntimeProjection
    fs: FinancialStatementsProjection


# ── Factory ───────────────────────────────────────────────────────────────── #

def build_runtime_projection_bundle(
    rr: Any,
    is_dirty: bool,
) -> WorkbookRuntimeProjection:
    """Build all three sheet projections from one RuntimeResult.

    Accepts rr=None (no runtime persisted yet) — all three sheets will be
    in NOT_RUN state.  All payload extraction and state classification is
    done here; router adapters and view helpers only read the bundle.

    No financial arithmetic is performed.  Period dicts are passed verbatim.
    """
    # ── Thaw payloads once ───────────────────────────────────────────────── #
    # Use getattr so the factory is robust to partial mocks in tests that only
    # set financial_statements on a MagicMock(spec=RuntimeResult).
    _debt_raw    = getattr(rr, "debt_schedule", None)    if rr else None
    _tax_raw     = getattr(rr, "tax_schedule", None)     if rr else None
    _fs_raw      = getattr(rr, "financial_statements", None) if rr else None
    _summary_raw = getattr(rr, "runtime_summary", None)  if rr else None

    debt_schedule   = thaw_runtime_payload(_debt_raw)    if _debt_raw    else None
    tax_schedule    = thaw_runtime_payload(_tax_raw)     if _tax_raw     else None
    fs_payload      = thaw_runtime_payload(_fs_raw)      if _fs_raw      else None
    runtime_summary = thaw_runtime_payload(_summary_raw) if _summary_raw else None

    # ── Shared rr identity (same across all three sheets) ────────────────── #
    _has_runtime = rr is not None
    def _identity(attr: str) -> Optional[str]:
        v = getattr(rr, attr, None) if _has_runtime else None
        return str(v) if v is not None else None

    _snapshot_id = _identity("snapshot_id")
    _ran_at      = _identity("ran_at")
    _origin      = _identity("origin")

    # ── Debt projection ──────────────────────────────────────────────────── #
    debt_state = classify_schedule_state(rr, debt_schedule, is_dirty)
    debt_periods    = extract_periods(debt_schedule, operational_only=False)
    debt_op_periods = extract_periods(debt_schedule, operational_only=True)
    debt_meta = RuntimeProjectionMeta(
        state=debt_state,
        has_runtime=_has_runtime,
        has_payload=_schedule_has_valid_periods(debt_schedule),
        is_dirty=is_dirty,
        snapshot_id=_snapshot_id,
        ran_at=_ran_at,
        origin=_origin,
    )
    debt = DebtRuntimeProjection(
        meta=debt_meta,
        source=debt_schedule,
        periods=debt_periods,
        operational_periods=debt_op_periods,
        summary=runtime_summary,
        state=debt_state,
        schedule=debt_schedule,
        runtime_summary=runtime_summary,
    )

    # ── Tax projection ───────────────────────────────────────────────────── #
    tax_state = classify_schedule_state(rr, tax_schedule, is_dirty)
    tax_periods    = extract_periods(tax_schedule, operational_only=False)
    tax_op_periods = extract_periods(tax_schedule, operational_only=True)
    tax_meta = RuntimeProjectionMeta(
        state=tax_state,
        has_runtime=_has_runtime,
        has_payload=_schedule_has_valid_periods(tax_schedule),
        is_dirty=is_dirty,
        snapshot_id=_snapshot_id,
        ran_at=_ran_at,
        origin=_origin,
    )
    tax = TaxRuntimeProjection(
        meta=tax_meta,
        source=tax_schedule,
        periods=tax_periods,
        operational_periods=tax_op_periods,
        summary=runtime_summary,
        state=tax_state,
        schedule=tax_schedule,
        runtime_summary=runtime_summary,
    )

    # ── Financial Statements projection ──────────────────────────────────── #
    fs_state = classify_runtime_state(rr, fs_payload, is_dirty)
    pnl_periods    = fs_payload.get("pnl", {}).get("periods") if fs_payload else None
    bs_periods     = fs_payload.get("balance_sheet", {}).get("periods") if fs_payload else None
    pf_cf_periods  = fs_payload.get("pf_cash_waterfall", {}).get("periods") if fs_payload else None
    fs_meta = RuntimeProjectionMeta(
        state=fs_state,
        has_runtime=_has_runtime,
        has_payload=fs_payload is not None,
        is_dirty=is_dirty,
        snapshot_id=_snapshot_id,
        ran_at=_ran_at,
        origin=_origin,
    )
    _pnl_rows    = project_rows(FS_PNL_ROW_DEFS, pnl_periods)
    _bs_rows     = project_rows(FS_BS_ROW_DEFS, bs_periods)
    _pf_cf_rows  = project_rows(FS_PF_CF_ROW_DEFS, pf_cf_periods)
    _pnl_labels    = project_period_labels(pnl_periods)
    _bs_labels     = project_period_labels(bs_periods)
    _pf_cf_labels  = project_period_labels(pf_cf_periods)
    _bs_rows_annotated        = annotate_balance_check_row(_bs_rows)
    _bs_annual_rows, _bs_annual_labels       = aggregate_to_annual(_bs_rows, _bs_labels)
    _bs_annual_rows_annotated = annotate_balance_check_row(_bs_annual_rows)
    _pnl_annual_rows, _pnl_annual_labels     = aggregate_to_annual(_pnl_rows, _pnl_labels)
    _pf_cf_annual_rows, _pf_cf_annual_labels = aggregate_to_annual(_pf_cf_rows, _pf_cf_labels)
    fs = FinancialStatementsProjection(
        meta=fs_meta,
        state=fs_state,
        fs_available=fs_payload is not None,
        pnl_rows=_pnl_rows,
        bs_rows=_bs_rows_annotated,
        pf_cf_rows=_pf_cf_rows,
        pnl_period_labels=_pnl_labels,
        bs_period_labels=_bs_labels,
        pf_cf_period_labels=_pf_cf_labels,
        pnl_classification=fs_classify_statement(rr, fs_payload, "pnl"),
        bs_classification=fs_classify_statement(rr, fs_payload, "balance_sheet"),
        pf_cf_classification=fs_classify_statement(rr, fs_payload, "pf_cash_waterfall"),
        runtime_summary=runtime_summary,
        pnl_annual_rows=_pnl_annual_rows,
        bs_annual_rows=_bs_annual_rows_annotated,
        pf_cf_annual_rows=_pf_cf_annual_rows,
        pnl_annual_labels=_pnl_annual_labels,
        bs_annual_labels=_bs_annual_labels,
        pf_cf_annual_labels=_pf_cf_annual_labels,
    )

    return WorkbookRuntimeProjection(debt=debt, tax=tax, fs=fs)
