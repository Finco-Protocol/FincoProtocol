"""
Workbook V2 — canonical field registry.

Builds the singleton `WORKBOOK` (WorkbookSpec) mapping every field visible in
the application to a stable semantic ID with a full canonical contract.

Semantic ID convention:  <sheet_id>.<section_id>.<name>
  e.g.  "project_setup.technical.capacity_mw"
        "capex.C.epc_contract"
        "opex.lines.technical_management"
        "revenue.ppa.base_tariff"
        "debt.senior.gearing_pct"

CAPEX editability rules (from capex_view_model.py / sheet_capex.html):
  - C.01–C.12, C.14–C.16 line amounts: editable for user projects (BOUND)
  - C.13 Contingencies: always derived (formula % × other CAPEX) — DISPLAY_ONLY
  - C.17 Financing Costs (IDC, bank_fees, commitment_fees, other_financial,
    vat_costs): always read-only — IDC is engine-computed (circular fixed point);
    bank_fees / commitment_fees / vat_costs are Excel/template anchors — TEMPLATE_LOCKED
  - C.18 Reserve Accounts: always read-only, engine-derived from DSRA — DISPLAY_ONLY
  - Hard CAPEX total, Grand Total: always derived — DISPLAY_ONLY

False-editable surface identified (fields that appear editable in the UI but
whose values are overridden / do not reach the engine as primary inputs):
  - total_capex_keur  (inputs_section): shown editable, but engine derives total
                      from per-line CapexItems — PARTIAL
  - opex_y1_keur      (inputs_section): shown editable, but engine derives OPEX Y1
                      from per-line OpexItems — PARTIAL
  - tariff_eur_mwh    (inputs_section): legacy key; newer projects use rev_ppa_base_tariff
                      as the authoritative revenue input — PARTIAL
  - ppa_term_years    (inputs_section): legacy key; superseded by rev_ppa_term_years — PARTIAL
  - capacity_factor   (inputs_section): shown as calculated/read-only but stored in
                      snapshot; derived from capacity_mw and p50_hours — DISPLAY_ONLY
  - gearing/dscr/rate/tenor in sheet_senior_debt: draft workspace controls
                      (data-grid-source), not the canonical form-submission path
                      (inputs_section IS the BOUND path for these fields) — PARTIAL

Import the singleton:
    from app.workbook.registry import WORKBOOK
"""
from __future__ import annotations

from typing import Literal

from app.workbook.specs import (
    BindingStatus,
    FieldKind,
    FieldSpec,
    FieldType,
    ScenarioPolicy,
    SectionSpec,
    SheetSpec,
    SourceOfTruth,
    WorkbookSpec,
)

# ---------------------------------------------------------------------------
# Constructor helpers
# ---------------------------------------------------------------------------

def _f(
    field_id: str,
    label: str,
    snapshot_key: str,
    field_type: FieldType,
    sheet_id: str,
    section_id: str,
    *,
    kind: FieldKind = FieldKind.INPUT,
    persisted: bool = True,
    runtime_only: bool = False,
    source_of_truth: SourceOfTruth = SourceOfTruth.INPUT_SET,
    engine_path: str | None = None,
    engine_path_conditional: str | None = None,
    scenario_policy: ScenarioPolicy = ScenarioPolicy.NOT_ALLOWED,
    binding_status: BindingStatus = BindingStatus.BOUND,
    excel_generic_wind_reference: str | None = None,
    excel_generic_solar_reference: str | None = None,
    excel_evidence: Literal["SOURCE_PROVEN", "NOT_APPLICABLE", "UNVERIFIED"] | None = None,
    export_mapping: str | None = None,
    dependencies: tuple[str, ...] = (),
    unit: str | None = None,
    description: str | None = None,
    editable: bool = True,
    required: bool = False,
    options: tuple[str, ...] = (),
    min_value: float | None = None,
    max_value: float | None = None,
    decimals: int | None = None,
    order: int = 0,
) -> FieldSpec:
    return FieldSpec(
        field_id=field_id, label=label, snapshot_key=snapshot_key,
        field_type=field_type, sheet_id=sheet_id, section_id=section_id,
        kind=kind, persisted=persisted, runtime_only=runtime_only,
        source_of_truth=source_of_truth, engine_path=engine_path,
        engine_path_conditional=engine_path_conditional,
        scenario_policy=scenario_policy, binding_status=binding_status,
        excel_generic_wind_reference=excel_generic_wind_reference, excel_generic_solar_reference=excel_generic_solar_reference,
        excel_evidence=excel_evidence,
        export_mapping=export_mapping, dependencies=dependencies,
        unit=unit, description=description, editable=editable,
        required=required, options=options,
        min_value=min_value, max_value=max_value,
        decimals=decimals, order=order,
    )


def _section(section_id: str, label: str, sheet_id: str, fields: list[FieldSpec], order: int = 0) -> SectionSpec:
    return SectionSpec(section_id=section_id, label=label, sheet_id=sheet_id, order=order, fields=tuple(fields))


def _sheet(sheet_id: str, label: str, sections: list[SectionSpec], icon: str | None = None, order: int = 0) -> SheetSpec:
    return SheetSpec(sheet_id=sheet_id, label=label, icon=icon, order=order, sections=tuple(sections))


# ---------------------------------------------------------------------------
# Sheet: project_setup
# ---------------------------------------------------------------------------

_PS = "project_setup"

_ps_identity = _section("identity", "Project Identity", _PS, order=0, fields=[
    _f(f"{_PS}.identity.project_name", "Project Name", "project_name", FieldType.TEXT, _PS, "identity",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="info.name",
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.BOUND,
       required=True, editable=True,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="Project Name", order=0),

    _f(f"{_PS}.identity.project_type", "Project Type", "project_type", FieldType.SELECT, _PS, "identity",
       kind=FieldKind.TEMPLATE_INPUT, persisted=True,
       source_of_truth=SourceOfTruth.TEMPLATE, engine_path=None,
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.TEMPLATE_LOCKED,
       editable=False,
       description="Set at project creation from template; cannot be changed afterwards.",
       options=("wind_onshore", "solar_pv", "bess", "hydro", "gas"), required=True,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=1),

    _f(f"{_PS}.identity.country_market", "Country / Market", "country_market", FieldType.TEXT, _PS, "identity",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="info.country_iso",
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.PARTIAL,
       editable=True,
       description="Free-text country label; mapped to country_iso enum internally (mapping not explicitly registered).",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=2),

    _f(f"{_PS}.identity.currency", "Currency", "currency", FieldType.SELECT, _PS, "identity",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path=None,
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.PARTIAL,
       editable=True,
       description="Display currency label; no direct field in ProjectInputs — engine uses EUR internally.",
       options=("EUR", "USD", "GBP", "HRK", "PLN", "RON"),
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=3),

    _f(f"{_PS}.identity.scenario", "Scenario", "scenario", FieldType.TEXT, _PS, "identity",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path=None,
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.PARTIAL,
       editable=True,
       description="Scenario label (e.g. 'Base', 'Upside'). Drives ScenarioRunner selection but not a ProjectInputs field directly.",
       order=4),
])

_ps_technical = _section("technical", "Technical Parameters", _PS, order=1, fields=[
    _f(f"{_PS}.technical.capacity_mw", "Installed Capacity", "capacity_mw", FieldType.MW, _PS, "technical",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="technical.capacity_mw",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       required=True, editable=True,
       unit="MW", min_value=0.1, decimals=2,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="Capacity (MW)", order=0),

    _f(f"{_PS}.technical.p50_hours", "P50 Operating Hours", "p50_hours", FieldType.MWH, _PS, "technical",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="technical.operating_hours_p50",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       required=True, editable=True,
       unit="h/yr", min_value=1, decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="P50 Hours", order=1),

    _f(f"{_PS}.technical.capacity_factor", "Capacity Factor (P50)", "capacity_factor", FieldType.FLOAT, _PS, "technical",
       kind=FieldKind.DERIVED_DISPLAY, persisted=True,
       source_of_truth=SourceOfTruth.DERIVED_UI, engine_path=None,
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.DISPLAY_ONLY,
       editable=False,
       unit="%", decimals=1, min_value=0, max_value=100,
       description="Computed: p50_hours / (8760 × capacity_mw). Stored in snapshot for display; engine recomputes from p50_hours.",
       dependencies=(f"{_PS}.technical.capacity_mw", f"{_PS}.technical.p50_hours"),
       order=2),

    _f(f"{_PS}.technical.cod_date", "Commercial Operation Date", "cod_date", FieldType.DATE, _PS, "technical",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="info.cod_date",
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.BOUND,
       required=True, editable=True,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=3),

    _f(f"{_PS}.technical.construction_months", "Construction Duration", "construction_months", FieldType.MONTHS, _PS, "technical",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="info.construction_months",
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.BOUND,
       required=True, editable=True,
       unit="months", min_value=1, max_value=120,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=4),

    _f(f"{_PS}.technical.horizon_years", "Project Horizon", "horizon_years", FieldType.YEARS, _PS, "technical",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="info.horizon_years",
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.BOUND,
       required=True, editable=True,
       unit="years", min_value=1, max_value=50,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="Horizon (years)", order=5),
])

_SHEET_PROJECT_SETUP = _sheet(_PS, "Project Setup", [_ps_identity, _ps_technical], icon="⚙️", order=0)


# ---------------------------------------------------------------------------
# Sheet: capex
#
# C.01–C.12, C.14–C.16: user-editable CapexItem amounts (BOUND for user projects)
# C.13 Contingencies: always derived (DISPLAY_ONLY)
# C.17 Financing Costs: always read-only — IDC engine-computed, others template-locked
# C.18 Reserve Accounts: always read-only — engine-derived from DSRA waterfall
# Subtotals / Grand Total: always derived (DISPLAY_ONLY)
# ---------------------------------------------------------------------------

_CX = "capex"

_cx_group_c = _section("C", "Construction & EPC (C.01–C.16)", _CX, order=0, fields=[
    _f(f"{_CX}.C.epc_contract", "EPC Contract", "capex_epc_contract_keur", FieldType.KEUR, _CX, "C",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.epc_contract.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="CAPEX EPC Contract (kEUR)", order=0),

    _f(f"{_CX}.C.production_units", "Production Units", "capex_production_units_keur", FieldType.KEUR, _CX, "C",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.production_units.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=1),

    _f(f"{_CX}.C.epc_other", "EPC Other", "capex_epc_other_keur", FieldType.KEUR, _CX, "C",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.epc_other.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=2),

    _f(f"{_CX}.C.grid_connection", "Grid Connection", "capex_grid_connection_keur", FieldType.KEUR, _CX, "C",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.grid_connection.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=3),

    _f(f"{_CX}.C.ops_preparation", "Operations Preparation", "capex_ops_prep_keur", FieldType.KEUR, _CX, "C",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.ops_prep.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=4),

    _f(f"{_CX}.C.insurances", "Insurances", "capex_insurances_keur", FieldType.KEUR, _CX, "C",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.insurances.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=5),

    _f(f"{_CX}.C.lease_tax", "Lease & Tax", "capex_lease_tax_keur", FieldType.KEUR, _CX, "C",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.lease_tax.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=6),

    _f(f"{_CX}.C.construction_mgmt_a", "Construction Management A", "capex_construction_mgmt_a_keur", FieldType.KEUR, _CX, "C",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.construction_mgmt_a.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=7),

    _f(f"{_CX}.C.commissioning", "Commissioning", "capex_commissioning_keur", FieldType.KEUR, _CX, "C",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.commissioning.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=8),

    _f(f"{_CX}.C.contingencies", "Contingencies (C.13)", "capex_contingencies_keur", FieldType.KEUR, _CX, "C",
       kind=FieldKind.DERIVED_DISPLAY, persisted=False,
       source_of_truth=SourceOfTruth.DERIVED_UI, engine_path="capex.contingencies.amount_keur",
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.DISPLAY_ONLY,
       editable=False, unit="kEUR", decimals=0,
       description="C.13 — always formula-derived (contingency % × non-contingency CAPEX). Never user-entered.",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       dependencies=(f"{_CX}.C.epc_contract", f"{_CX}.C.production_units", f"{_CX}.C.epc_other",
                     f"{_CX}.C.grid_connection", f"{_CX}.C.ops_preparation", f"{_CX}.C.insurances",
                     f"{_CX}.C.lease_tax", f"{_CX}.C.construction_mgmt_a", f"{_CX}.C.commissioning",
                     f"{_CX}.C.taxes"),
       order=9),

    _f(f"{_CX}.C.taxes", "Import Taxes", "capex_taxes_keur", FieldType.KEUR, _CX, "C",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.taxes.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=10),
])

_cx_group_d = _section("D", "Development (C.11, C.12, C.15, C.16)", _CX, order=1, fields=[
    _f(f"{_CX}.D.project_acquisition", "Project Acquisition", "capex_project_acquisition_keur", FieldType.KEUR, _CX, "D",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.project_acquisition.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=0),

    _f(f"{_CX}.D.project_rights", "Project Rights", "capex_project_rights_keur", FieldType.KEUR, _CX, "D",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.project_rights.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=1),

    _f(f"{_CX}.D.audit_legal", "Audit & Legal", "capex_audit_legal_keur", FieldType.KEUR, _CX, "D",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.audit_legal.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=2),

    _f(f"{_CX}.D.construction_mgmt_b", "Construction Management B", "capex_construction_mgmt_b_keur", FieldType.KEUR, _CX, "D",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="capex.construction_mgmt_b.amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=3),
])

# C.17 Financing Costs — always read-only.
# IDC: engine-computed via fixed-point iteration (circular: IDC → total CAPEX → debt → IDC).
# bank_fees, commitment_fees, other_financial, and vat_costs are model-provided financing components.
# _READONLY_GROUP_CODES = frozenset({"C.17", "C.18"}) in capex_view_model.py
_cx_group_f = _section("F", "Financing Costs — C.17 (read-only)", _CX, order=2, fields=[
    _f(f"{_CX}.F.idc", "IDC", "capex_idc_keur", FieldType.KEUR, _CX, "F",
       kind=FieldKind.DERIVED_DISPLAY, persisted=False,
       source_of_truth=SourceOfTruth.ENGINE,
       engine_path="capex.idc_keur",
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.DISPLAY_ONLY,
       editable=False, unit="kEUR", decimals=0,
       description="C.17 — IDC computed by the deterministic construction-financing path.",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="IDC (kEUR)", order=0),

    _f(f"{_CX}.F.bank_fees", "Bank Fees", "capex_bank_fees_keur", FieldType.KEUR, _CX, "F",
       kind=FieldKind.TEMPLATE_INPUT, persisted=False,
       source_of_truth=SourceOfTruth.TEMPLATE,
       engine_path="capex.bank_fees_keur",
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.TEMPLATE_LOCKED,
       editable=False, unit="kEUR", decimals=0,
       description="C.17 — financing fee supplied by the current model configuration.",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="Bank Fees (kEUR)", order=1),

    _f(f"{_CX}.F.commitment_fees", "Commitment Fees", "capex_commitment_fees_keur", FieldType.KEUR, _CX, "F",
       kind=FieldKind.TEMPLATE_INPUT, persisted=False,
       source_of_truth=SourceOfTruth.TEMPLATE,
       engine_path="capex.commitment_fees_keur",
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.TEMPLATE_LOCKED,
       editable=False, unit="kEUR", decimals=0,
       description="C.17 — commitment fee supplied by the current model configuration.",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="Commitment Fees (kEUR)", order=2),

    _f(f"{_CX}.F.other_financial", "Other Financial", "capex_other_financial_keur", FieldType.KEUR, _CX, "F",
       kind=FieldKind.TEMPLATE_INPUT, persisted=False,
       source_of_truth=SourceOfTruth.TEMPLATE,
       engine_path="capex.other_financial_keur",
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.TEMPLATE_LOCKED,
       editable=False, unit="kEUR", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=3),

    _f(f"{_CX}.F.vat_costs", "VAT / Recoverable Costs", "capex_vat_costs_keur", FieldType.KEUR, _CX, "F",
       kind=FieldKind.TEMPLATE_INPUT, persisted=False,
       source_of_truth=SourceOfTruth.TEMPLATE,
       engine_path="capex.vat_costs_keur",
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.TEMPLATE_LOCKED,
       editable=False, unit="kEUR", decimals=0,
       description="C.17 — VAT-facility financing cost supplied by the current model configuration.",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=4),
])

# C.18 Reserve Accounts — always read-only. Value is derived from DSRA waterfall engine.
_cx_group_r = _section("R", "Reserve Accounts — C.18 (read-only)", _CX, order=3, fields=[
    _f(f"{_CX}.R.reserve_accounts", "Reserve Accounts", "capex_reserve_accounts_keur", FieldType.KEUR, _CX, "R",
       kind=FieldKind.DERIVED_DISPLAY, persisted=False,
       source_of_truth=SourceOfTruth.ENGINE,
       engine_path="capex.reserve_accounts_keur",
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.DISPLAY_ONLY,
       editable=False, unit="kEUR", decimals=0,
       description="C.18 — DSRA and other reserve account funding derived from the waterfall engine. "
                   "Reserve accounts are tracked by the model rather than assumed as a public reference calibration.",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=0),
])

_cx_summary = _section("summary", "CAPEX Summary", _CX, order=4, fields=[
    # FALSE-EDITABLE: shown as editable in inputs_section.html but derived from per-line CapexItems.
    # Engine derives total_capex from CapexStructure.total_capex (property), not this snapshot field.
    _f(f"{_CX}.summary.total", "Total CAPEX", "total_capex_keur", FieldType.KEUR, _CX, "summary",
       kind=FieldKind.DERIVED_DISPLAY, persisted=True,
       source_of_truth=SourceOfTruth.DERIVED_UI, engine_path=None,
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.PARTIAL,
       editable=False, unit="kEUR", decimals=0,
       description="FALSE-EDITABLE: shown editable in inputs_section.html but the engine derives "
                   "CapexStructure.total_capex from per-line CapexItems. Snapshot value is a "
                   "display anchor, not the authoritative engine input.",
       dependencies=(f"{_CX}.C.epc_contract", f"{_CX}.C.production_units", f"{_CX}.C.epc_other",
                     f"{_CX}.C.grid_connection", f"{_CX}.C.ops_preparation", f"{_CX}.C.insurances",
                     f"{_CX}.C.lease_tax", f"{_CX}.C.construction_mgmt_a", f"{_CX}.C.commissioning",
                     f"{_CX}.C.taxes", f"{_CX}.D.project_acquisition", f"{_CX}.D.project_rights",
                     f"{_CX}.D.audit_legal", f"{_CX}.D.construction_mgmt_b",
                     f"{_CX}.F.idc", f"{_CX}.F.bank_fees", f"{_CX}.R.reserve_accounts"),
       export_mapping="Total CAPEX (kEUR)", order=0),
])

_SHEET_CAPEX = _sheet(_CX, "CAPEX", [_cx_group_c, _cx_group_d, _cx_group_f, _cx_group_r, _cx_summary], icon="🏗️", order=1)


# ---------------------------------------------------------------------------
# Sheet: opex
# ---------------------------------------------------------------------------

_OX = "opex"

_ox_lines = _section("lines", "OPEX Line Items (B.01–B.13)", _OX, order=0, fields=[
    _f(f"{_OX}.lines.technical_management", "Technical Management", "opex_technical_management_y1_keur", FieldType.KEUR, _OX, "lines",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="opex[technical_management].y1_amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR/yr", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="OPEX Technical Management Y1 (kEUR)", order=0),

    _f(f"{_OX}.lines.om_preventive", "O&M Preventive & Corrective", "opex_o_and_m_preventive_and_corrective_y1_keur", FieldType.KEUR, _OX, "lines",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="opex[o_and_m_preventive_and_corrective].y1_amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR/yr", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=1),

    _f(f"{_OX}.lines.site_maintenance", "Site Maintenance", "opex_maintain_site_y1_keur", FieldType.KEUR, _OX, "lines",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="opex[maintain_site].y1_amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR/yr", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=2),

    _f(f"{_OX}.lines.cleaning_materials", "Cleaning & Materials", "opex_clean_material_y1_keur", FieldType.KEUR, _OX, "lines",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="opex[clean_material].y1_amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR/yr", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=3),

    _f(f"{_OX}.lines.security", "Security", "opex_security_y1_keur", FieldType.KEUR, _OX, "lines",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="opex[security].y1_amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR/yr", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=4),

    _f(f"{_OX}.lines.insurance", "Insurance", "opex_insurance_y1_keur", FieldType.KEUR, _OX, "lines",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="opex[insurance].y1_amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR/yr", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=5),

    _f(f"{_OX}.lines.lease_property_tax", "Lease & Property Tax", "opex_lease_and_property_tax_y1_keur", FieldType.KEUR, _OX, "lines",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="opex[lease_and_property_tax].y1_amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR/yr", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=6),

    _f(f"{_OX}.lines.power_expenses", "Power Expenses", "opex_power_expenses_y1_keur", FieldType.KEUR, _OX, "lines",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="opex[power_expenses].y1_amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR/yr", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=7),

    _f(f"{_OX}.lines.audit_accounting_legal", "Audit, Accounting & Legal", "opex_audit_and_accounting_and_legal_y1_keur", FieldType.KEUR, _OX, "lines",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="opex[audit_and_accounting_and_legal].y1_amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR/yr", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=8),

    _f(f"{_OX}.lines.bank_fees", "Bank Fees (OPEX)", "opex_bank_fees_opex_y1_keur", FieldType.KEUR, _OX, "lines",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="opex[bank_fees_opex].y1_amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR/yr", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=9),

    _f(f"{_OX}.lines.environmental_social", "Environmental & Social Management", "opex_environmental_and_social_management_y1_keur", FieldType.KEUR, _OX, "lines",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="opex[environmental_and_social_management].y1_amount_keur",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True, unit="kEUR/yr", decimals=0,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=10),

    _f(f"{_OX}.lines.contingencies", "Contingencies (OPEX)", "opex_contingencies_y1_keur", FieldType.KEUR, _OX, "lines",
       kind=FieldKind.DERIVED_DISPLAY, persisted=False,
       source_of_truth=SourceOfTruth.DERIVED_UI, engine_path=None,
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.DISPLAY_ONLY,
       editable=False, unit="kEUR/yr", decimals=0,
       description="B.13 — always formula-derived (contingency % × non-contingency OPEX). Never user-entered.",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       dependencies=(
           f"{_OX}.lines.technical_management", f"{_OX}.lines.om_preventive",
           f"{_OX}.lines.site_maintenance", f"{_OX}.lines.cleaning_materials",
           f"{_OX}.lines.security", f"{_OX}.lines.insurance",
           f"{_OX}.lines.lease_property_tax", f"{_OX}.lines.power_expenses",
           f"{_OX}.lines.audit_accounting_legal", f"{_OX}.lines.bank_fees",
           f"{_OX}.lines.environmental_social",
       ),
       order=11),
])

# FALSE-EDITABLE: shown editable in inputs_section.html but derived from per-line OpexItems.
_ox_summary = _section("summary", "OPEX Summary", _OX, order=1, fields=[
    _f(f"{_OX}.summary.total_y1", "Total OPEX Y1", "opex_y1_keur", FieldType.KEUR, _OX, "summary",
       kind=FieldKind.DERIVED_DISPLAY, persisted=True,
       source_of_truth=SourceOfTruth.DERIVED_UI, engine_path=None,
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.PARTIAL,
       editable=False, unit="kEUR/yr", decimals=0,
       description="FALSE-EDITABLE: shown editable in inputs_section.html but the engine derives "
                   "OPEX Y1 from per-line OpexItems. Snapshot value is a display anchor.",
       dependencies=tuple(f"{_OX}.lines.{n}" for n in (
           "technical_management", "om_preventive", "site_maintenance", "cleaning_materials",
           "security", "insurance", "lease_property_tax", "power_expenses",
           "audit_accounting_legal", "bank_fees", "environmental_social", "contingencies",
       )),
       export_mapping="Total OPEX Y1 (kEUR)", order=0),
])

_SHEET_OPEX = _sheet(_OX, "OPEX", [_ox_lines, _ox_summary], icon="🔧", order=2)


# ---------------------------------------------------------------------------
# Sheet: revenue
# ---------------------------------------------------------------------------

_RV = "revenue"

_rv_ppa = _section("ppa", "PPA / Commercial", _RV, order=0, fields=[
    _f(f"{_RV}.ppa.base_tariff", "Base Tariff", "rev_ppa_base_tariff", FieldType.FLOAT, _RV, "ppa",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="revenue.ppa_base_tariff",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       required=True, editable=True,
       unit="EUR/MWh", min_value=0, decimals=2,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="PPA Base Tariff (EUR/MWh)", order=0),

    _f(f"{_RV}.ppa.index", "PPA Escalation Index", "rev_ppa_index", FieldType.PCT, _RV, "ppa",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="revenue.ppa_index",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       unit="%/yr", decimals=2, min_value=0, max_value=100,
       description="Stored as UI percentage (e.g. 2.0); adapter divides by 100 before engine (→ 0.02).",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=1),

    _f(f"{_RV}.ppa.term_years", "PPA Term", "rev_ppa_term_years", FieldType.YEARS, _RV, "ppa",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="revenue.ppa_term_years",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       unit="years", min_value=1, max_value=50,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None, order=2),

    _f(f"{_RV}.ppa.production_share", "Production Share", "rev_ppa_production_share", FieldType.PCT, _RV, "ppa",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="revenue.ppa_production_share",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       unit="%", decimals=1, min_value=0, max_value=100,
       description="Stored as UI percentage (e.g. 50.0 or 100.0); adapter divides by 100 before engine (→ 0.50 / 1.00).",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       excel_evidence="UNVERIFIED",
       order=3),

    _f(f"{_RV}.ppa.indexation_policy", "Escalation Base Year Policy", "rev_ppa_indexation_start_policy",
       FieldType.SELECT, _RV, "ppa",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="revenue.ppa_indexation_start_policy",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       options=("FIRST_FULL_CALENDAR_YEAR_AS_BASE", "AFTER_FIRST_FULL_OPERATING_YEAR", "CONTRACT_ANNIVERSARY"),
       description="Determines when PPA tariff escalation begins. "
                   "FIRST_FULL_CALENDAR_YEAR_AS_BASE: escalation starts from the first full "
                   "calendar year after COD (1 Jan boundary, Generic Solar Reference convention). "
                   "AFTER_FIRST_FULL_OPERATING_YEAR: first escalation exactly one year after COD "
                   "(date-anchored COD anniversaries). "
                   "CONTRACT_ANNIVERSARY: escalation follows annual anniversaries of the explicit "
                   "PPA / indexation reference start date (rev_ppa_indexation_start_date, required). "
                   "The first escalation occurs on the first anniversary after that reference date.",
       excel_generic_solar_reference=None, order=4),

    _f(f"{_RV}.ppa.indexation_start_date", "Indexation Start Date", "rev_ppa_indexation_start_date",
       FieldType.DATE, _RV, "ppa",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="revenue.ppa_indexation_start_date",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       description="Required when Escalation Base Year Policy is CONTRACT_ANNIVERSARY. "
                   "ISO-8601 date (YYYY-MM-DD) that is the PPA / indexation reference start date "
                   "(the date from which annual anniversaries are counted). "
                   "The first escalation occurs on the first anniversary after this date. "
                   "Omit or leave blank when using FIRST_FULL_CALENDAR_YEAR_AS_BASE or "
                   "AFTER_FIRST_FULL_OPERATING_YEAR.",
       excel_generic_solar_reference=None,
       excel_evidence="UNVERIFIED",
       order=5),

    # Legacy snapshot keys — persist for backward compatibility; canonical rev_ppa_* keys win.
    _f(f"{_RV}.ppa.tariff_legacy", "Tariff (legacy key)", "tariff_eur_mwh", FieldType.FLOAT, _RV, "ppa",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path=None,
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.PARTIAL,
       editable=True,
       unit="EUR/MWh", decimals=2,
       description="Legacy snapshot key. Canonical key rev_ppa_base_tariff wins when present; "
                   "this field is the fallback for snapshots pre-dating C2B2.",
       order=6),

    _f(f"{_RV}.ppa.ppa_term_legacy", "PPA Term (legacy key)", "ppa_term_years", FieldType.YEARS, _RV, "ppa",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path=None,
       scenario_policy=ScenarioPolicy.NOT_ALLOWED, binding_status=BindingStatus.PARTIAL,
       editable=True,
       description="Legacy snapshot key. Canonical key rev_ppa_term_years wins when present.",
       order=7),
])

_rv_balancing = _section("balancing", "Balancing & CO2", _RV, order=1, fields=[
    # Merchant-only balancing: fraction of gross merchant revenue deducted as balancing cost.
    _f(f"{_RV}.balancing.merchant_pct", "Merchant Balancing (% of spot sales)", "rev_merchant_balancing_pct",
       FieldType.FLOAT, _RV, "balancing",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="revenue.balancing_cost_pv",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       unit="%", decimals=2, min_value=0, max_value=100,
       description="Balancing cost as a fraction of gross merchant electricity revenue. "
                   "Applied only to spot sales (not PPA revenue). Excel CF row 40. "
                   "Synthetic reference assumption.",
       excel_generic_solar_reference=None, order=0),

    # Flat EUR/MWh balancing cost applied to total generation (wind projects).
    # Separate from merchant % balancing above — these two fields serve different structures.
    _f(f"{_RV}.balancing.cost_eur_per_mwh", "Balancing Cost (EUR/MWh)", "rev_balancing_cost_eur_per_mwh",
       FieldType.FLOAT, _RV, "balancing",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="revenue.balancing_cost_eur_per_mwh",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       unit="EUR/MWh", decimals=2, min_value=0,
       description="Flat balancing cost per MWh of total generation. Used for wind projects "
                   "(Excel CF row 40 wind path). Distinct from merchant % balancing above.",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       excel_evidence="UNVERIFIED",
       order=1),

    _f(f"{_RV}.balancing.co2_enabled", "CO2 Revenue Enabled", "rev_co2_enabled", FieldType.BOOL, _RV, "balancing",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="revenue.co2_enabled",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       excel_generic_solar_reference=None,
       excel_evidence="UNVERIFIED",
       order=2),

    # CO2 certificate revenue: EUR/MWh applied to total generation (not EUR/tCO2).
        # Maps to co2_certificate_price_eur_per_mwh (canonical) which takes priority over
    # legacy co2_price_eur in the revenue leaf.
    _f(f"{_RV}.balancing.co2_price_eur_mwh", "CO2 Certificate Price", "rev_co2_price_eur_mwh",
       FieldType.FLOAT, _RV, "balancing",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="revenue.co2_certificate_price_eur_per_mwh",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       unit="EUR/MWh", decimals=2, min_value=0,
       description="CO2 / GoO certificate revenue per MWh of generation. NOT EUR/tCO2 — "
                   "applied as EUR/MWh to total production (Excel CF row 46). "
                   "Synthetic reference assumption.",
       excel_generic_solar_reference=None, order=3),
])

# Merchant price curve: calendar-year synthetic price schedule.
# Stored as JSON: [{"year": 2042, "price_eur_mwh": 75.12}, ...].
# When present this schedule wins over the legacy market_prices_curve tuple.
_rv_merchant = _section("merchant", "Merchant Price Curve", _RV, order=2, fields=[
    _f(f"{_RV}.merchant.price_curve_json", "Merchant Price Curve (JSON)", "rev_merchant_price_curve_json",
       FieldType.TEXT, _RV, "merchant",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="revenue.market_prices_by_calendar_year_eur_mwh",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       description='Calendar-year merchant price schedule as JSON array: '
                   '[{"year": 2042, "price_eur_mwh": 75.12}, ...]. '
                   'Sorted ascending by year. When present, overrides market_prices_curve. '
                   'Synthetic illustrative schedule; no external workbook source is embedded.',
       excel_generic_solar_reference=None, order=0),
])

_SHEET_REVENUE = _sheet(_RV, "Revenue", [_rv_ppa, _rv_balancing, _rv_merchant], icon="💰", order=3)


# ---------------------------------------------------------------------------
# Sheet: debt  (inputs_section is the BOUND path; sheet_senior_debt draft
#               controls are PARTIAL workspace-only workspace-draft)
# ---------------------------------------------------------------------------

_DT = "debt"

_dt_senior = _section("senior", "Senior Debt Inputs", _DT, order=0, fields=[
    _f(f"{_DT}.senior.gearing_pct", "Gearing", "gearing_pct", FieldType.PCT, _DT, "senior",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="financing.gearing_ratio",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       unit="%", min_value=0, max_value=100, decimals=1,
       description="Persisted via inputs_section form. Also shown as workspace-draft control "
                   "in sheet_senior_debt (data-grid-source, not form-submitted — PARTIAL path).",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="Gearing (%)", order=0),

    _f(f"{_DT}.senior.target_dscr", "Target DSCR", "target_dscr", FieldType.FLOAT, _DT, "senior",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="financing.target_dscr",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       unit="x", min_value=1.0, max_value=3.0, decimals=2,
       description=("Target DSCR stored as a plain multiple. With no explicit "
                    "schedule the scalar IS the period authority (FLAT); a "
                    "uniform schedule is rewritten flat; a calibrated "
                    "non-uniform schedule — or an unresolved authority — "
                    "locks the control (R8/N02)."),
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="Target DSCR (x)", order=1),

    _f(f"{_DT}.senior.interest_rate_pct", "All-in Interest Rate", "interest_rate_pct", FieldType.PCT, _DT, "senior",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates",
       engine_path_conditional=(
           "FLAT uniform explicit schedule: the % edit rewrites every period "
           "entry (pct→ratio, once). CALIBRATED non-uniform schedule: control "
           "locked, Save rejected (R8/N02 — assert_debt_scalar_edit_allowed)."),
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       unit="%", min_value=0, max_value=20, decimals=2,
       description=("All-in senior rate stored as PERCENT in the UI/snapshot "
                    "(5.65 == 5.65 %); input_adapter converts to a ratio "
                    "exactly once and rewrites the typed explicit period-rate "
                    "vector (FLAT uniform schedule = editable). A CALIBRATED "
                    "non-uniform schedule — or an unresolved authority — "
                    "locks the control (R8/N02)."),
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="Interest Rate (%)", order=2),

    _f(f"{_DT}.senior.tenor_years", "Tenor", "tenor_years", FieldType.YEARS, _DT, "senior",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="financing.senior_tenor_years",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       unit="years", min_value=1, max_value=30,
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       export_mapping="Tenor (years)", order=3),
])

_SHEET_DEBT = _sheet(_DT, "Senior Debt", [_dt_senior], icon="🏦", order=4)


# ---------------------------------------------------------------------------
# Sheet: tax
# ---------------------------------------------------------------------------
#
# Tax Assumptions — Registry v2.1.0 expansion.
#
# Only CIT Rate and Loss Carryforward Years are added here; these are the
# two scalar TaxParams fields that:
#   (a) are set in every project factory and carried on every project snapshot,
#   (b) are read directly by the waterfall engine (TaxParams.corporate_rate
#       and TaxParams.loss_carryforward_years),
#   (c) have a clean 1:1 mapping from snapshot → domain without coupling to
#       jurisdiction-specific mechanics.
#
# Other TaxParams fields (loss_carryforward_cap, atad_ebitda_limit, etc.) are
# not added here because they require jurisdiction-specific design decisions
# and dedicated test fixtures that go beyond this PR's scope.
#
# Canonical mapping:
#   field_id                           snapshot_key                  engine path
#   tax.assumptions.cit_rate_pct       tax_corporate_rate_pct        tax.corporate_rate   (stored %→ratio /100)
#                                                                                — CONDITIONAL (R4/F06): when the project
#                                                                                has a selected country_tax_policy_id the
#                                                                                same edit binds to
#                                                                                tax.corporate_rate_override instead
#                                                                                (see engine_path_conditional on the field).
#   tax.assumptions.loss_carryforward_years  tax_loss_carryforward_years  tax.loss_carryforward_years  (int)

_TX = "tax"

_tx_assumptions = _section("assumptions", "Tax Assumptions", _TX, order=0, fields=[
    _f(f"{_TX}.assumptions.cit_rate_pct", "CIT Rate", "tax_corporate_rate_pct", FieldType.PCT, _TX, "assumptions",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="tax.corporate_rate",
       engine_path_conditional=(
           "tax.corporate_rate_override (when tax.country_tax_policy_id is set; "
           "%→ratio /100; the selected policy stays the jurisdiction/default "
           "authority and the explicit edit becomes the project-specific rate)"),
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       unit="%", min_value=0, max_value=100, decimals=2,
       description=(
           "Corporate income tax rate stored as % (0–100); input_adapter divides by 100 "
           "→ domain 0.0–1.0. Dual-mode authority (R4/F06): without a selected "
           "country-tax policy the edit binds to tax.corporate_rate; with a selected "
           "policy it binds to tax.corporate_rate_override over that policy."),
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       excel_evidence="UNVERIFIED",
       order=0),

    _f(f"{_TX}.assumptions.loss_carryforward_years", "Loss Carryforward Years", "tax_loss_carryforward_years",
       FieldType.YEARS, _TX, "assumptions",
       kind=FieldKind.INPUT, persisted=True, source_of_truth=SourceOfTruth.INPUT_SET,
       engine_path="tax.loss_carryforward_years",
       scenario_policy=ScenarioPolicy.OVERRIDE, binding_status=BindingStatus.BOUND,
       editable=True,
       unit="years", min_value=0, max_value=30,
       description="Number of years tax losses may be carried forward.",
       excel_generic_wind_reference=None, excel_generic_solar_reference=None,
       excel_evidence="UNVERIFIED",
       order=1),
])

_SHEET_TAX = _sheet(_TX, "Tax", [_tx_assumptions], icon="📋", order=5)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

WORKBOOK = WorkbookSpec(
    version="2.3.0",
    sheets=(
        _SHEET_PROJECT_SETUP,
        _SHEET_CAPEX,
        _SHEET_OPEX,
        _SHEET_REVENUE,
        _SHEET_DEBT,
        _SHEET_TAX,
    ),
)
