// Wire types of the RC-M Financing Studio adapter (app/v2/react_financing.py).  The view is the Legacy Debt-sheet context;
// the browser formats it and serialises typed inputs — validation and every economic rule stay on the server.

export interface BankabilityPeriod { number: number; index: number; start: string; end: string; target: number; rate_pct: number | null }

export interface BankabilityConfig {
  version?: number;
  sizing_mode?: string; lender_case?: string; day_count?: string;
  targets?: number[]; target_scalar?: number; rates_pct?: number[];
  fees?: { commitment_pct: number; structuring_pct: number; arrangement_pct: number };
  reserve?: { mode: string; months: number; requirement_keur: number; commitment_keur: number; fee_pct: number };
}

export interface BankabilityView {
  available: boolean;
  reason?: string;
  config?: BankabilityConfig;
  lender?: string; renewable?: boolean; mode?: string; day_count?: string;
  fees_editable?: boolean; reserve_editable?: boolean; automatic_reserve?: boolean;
  fees?: { commitment_pct: number; structuring_pct: number; arrangement_pct: number };
  periods?: BankabilityPeriod[];
  scalar_target?: number;
}

export interface EvidenceMetric { label: string; value: number | null; display: string; source: string; reason: string }
export interface CapitalStackRow {
  instrument_id: string; name: string; type: string; rank: string; junior: boolean; editable: boolean;
  commitment_keur: number; currency: string; rate_type: string; rate_pct: number; day_count: string;
  repayment: string; grace_months: number; maturity_date: string;
  draws: Array<{ date: string; amount_keur: number }>; draws_total_keur: number; upfront_pct: number; commitment_fee_pct: number;
  status: string; executable: boolean; readiness: string | null;
}
export interface CapitalStack {
  available: boolean; reason?: string; status?: string; scope?: string; rows?: CapitalStackRow[];
  working?: { senior_commitments_keur: number; scheduled_draws_keur: number; reconciled: boolean; facility_count: number };
  last_run_label?: string; unsupported?: Array<{ name: string; reason: string; status: string }>; debt_service_priority?: string;
}

export interface SuRow { label: string; value: number | null; display: string; authority: string; reason: string }
export interface SourcesUsesView {
  run_kind: string; freshness: string; has_run: boolean; has_financing_evidence: boolean;
  sources?: SuRow[]; uses?: SuRow[]; total_sources?: SuRow | number | string | null; total_uses?: SuRow | number | string | null;
  residual?: SuRow | number | string | null; balance_status?: string; integrity?: string; integrity_note?: string;
}

export interface DsraCashRow { period: number | string | null; date: string | null; cfads: EvidenceMetric; service: EvidenceMetric; funding: EvidenceMetric; release: EvidenceMetric }
export interface ReserveView { support: string; target: string; months: number | null; requirement: EvidenceMetric; facility: EvidenceMetric }
export interface SponsorView {
  mode: string; equity: EvidenceMetric[]; other: EvidenceMetric[]; shl: EvidenceMetric[]; repayment: string; day_count: string;
  eligibility: number | null; maturity: number | null; returns: EvidenceMetric[];
}

export interface FinancingStudioPayload {
  ok: true;
  project: { code: string; protected_reference: boolean };
  editable: boolean;
  freshness: string;
  identity: { content_hash: string; workbook_version: string; scenario_id: string | null; scenario_name: string | null };
  save: { field_id: string; tokens_from: string };
  bankability: BankabilityView;
  senior_pricing_mode: string; senior_dscr_mode: string;
  debt_actual_senior_keur_display: string | null; debt_actual_gearing_pct_display: string | null;
  financing_evidence: { metrics: EvidenceMetric[]; cash_rows?: DsraCashRow[]; sizing_status?: string; sizing_reason?: string };
  reserve_view: ReserveView;
  sponsor_view: SponsorView;
  senior_detail_rows: Array<[string, string | null]>;
  senior_lock_reason: string | null;
  capital_stack: CapitalStack;
  multisenior: { available?: boolean; active?: boolean; scope?: string };
  sources_uses: { available: boolean; reason?: string; code?: string; view?: SourcesUsesView };
}

// ── Investor & Sponsor agreement (app/v2/react_investors.py) ────────────────────────────────────────────────
export interface AgreementInvestor { investor_id: string; investment_class: string; ownership_fraction: number; commitment_keur: number }
export interface AgreementContribution { investor_id: string; cash_date: string; amount_keur: number }
export interface AgreementDocument {
  schema_version: number; agreement_id: string; version: number; currency: string; unit: string; policy: string;
  investors: AgreementInvestor[]; contributions: AgreementContribution[];
}
export interface InvestorEvidenceRow {
  investor_id: string; ownership_fraction: number; commitment_keur: number; total_paid_in_keur: number; uncalled_capital_keur: number;
  returned_capital_keur: number; residual_distributions_keur: number; unreturned_paid_in_keur: number;
  dpi: number | null; realized_moic: number | null; xirr: number | null; xirr_status: string;
}
export interface SponsorMetric { label: string; value: number | null; display: string; source: string; reason: string }
export interface InvestorPayload {
  ok: true; project: { code: string }; editable: boolean; state: string;
  identity: { content_hash: string; workbook_version: string; scenario_name: string | null };
  terms: AgreementDocument | null;
  workflow: { state: string; text: string };
  evidence: { snapshot_id: string; agreement: { agreement_id: string; version: number }; investors: InvestorEvidenceRow[] } | null;
  unavailable: string;
  funding: Array<{ date: string; paid_in_keur: number }>;
  sponsor: { mode: string; equity: SponsorMetric[]; other: SponsorMetric[]; shl: SponsorMetric[]; repayment: string; day_count: string;
             eligibility: number | null; maturity: number | null; returns: SponsorMetric[] };
  save: { url: string; csrf_token: string; next_version: number; saved_agreement_id: string };
  export_url: string;
  not_released: string[];
}
