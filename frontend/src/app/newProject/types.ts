// Wire types of the RC-M New Project adapter (app/v2/react_new_project.py).
// Every value is read from the canonical registries/factories on the server; the browser holds
// no financial default and computes nothing.

export type PilotTier = "PILOT_CANDIDATE" | "PREVIEW" | "RELEASE_CLOSED" | "UNCLASSIFIED";

export interface WizardTimeline {
  financial_close: string;
  construction_months: number;
  cod_date: string;
  horizon_years: number;
}

export interface WizardTechnology {
  key: string;
  public_name: string;
  pilot_tier: PilotTier;
  runnable: boolean;
  limitations: string[];
  status_note: string;
  creatable: boolean;
  reason: string;
  preview_acknowledgement_required: boolean;
  /** Present only when `creatable`. */
  template_source?: string;
  default_country?: string;
  capacity_label?: string;
  default_capacity_mw?: number;
  timeline?: WizardTimeline;
}

export interface WizardOptions {
  ok: true;
  technologies: WizardTechnology[];
  countries: Array<{ code: string; label: string }>;
  bounds: { capacity_min_mw: number; capacity_max_mw: number; name_max_length: number };
  request_id: string;
  csrf_token: string;
}

export interface WizardFieldError { field: string; message: string }

export interface WizardInput {
  name: string;
  technology: string;
  country: string;
  capacity_mw: string;
}

export interface WizardEffective {
  capacity_mw: number;
  capacity_label: string;
  reference_capacity_mw: number;
  scale_ratio: number;
  total_capex_keur: number;
  total_capex_display: string;
  opex_y1_keur: number;
  opex_y1_display: string;
  country: string;
  country_label: string;
  tax_template: string;
  timeline: WizardTimeline;
}

export interface WizardPreview {
  ok: true;
  normalised: { name: string; technology: string; country: string; capacity_mw: number };
  effective: WizardEffective;
  writes_nothing: boolean;
}

export interface CreatedProject { code: string; project_id: string; name: string; template_source: string; workspace_url: string; freshness: string }

export type PreviewResult =
  | { kind: "ok"; preview: WizardPreview }
  | { kind: "invalid"; errors: WizardFieldError[] }
  | { kind: "failed"; message: string };

export type CreateResult =
  | { kind: "created"; project: CreatedProject; replayed: boolean }
  /** Definitive refusal: the server wrote nothing. */
  | { kind: "refused"; code: string; message: string; errors?: WizardFieldError[] }
  /** Ambiguous: the Create may have been committed.  Never retried automatically. */
  | { kind: "unknown"; message: string };

export type StatusResult =
  | { kind: "created"; project: CreatedProject }
  | { kind: "not_found" }
  | { kind: "failed" };

/** What a reload found about a Create request whose outcome this browser never saw. */
export type PendingNotice =
  | { kind: "created"; project: CreatedProject }
  | { kind: "unknown" };
