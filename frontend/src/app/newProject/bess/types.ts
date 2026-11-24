export interface BessCapability {
  reference_exists: boolean;
  preview_supported: boolean;
  create_supported: boolean;
  save_supported: boolean;
  run_supported: boolean;
  release_state: string;
  persistence: string;
  blockers: Array<{ code: string; message: string }>;
  fields: Array<{ name: string; label: string; unit: string }>;
}

export interface BessDeclaredTerms {
  scope: string;
  native_input_sha256: string;
  identity_scope: string;
  group_order: string[];
  battery: { values: Record<string, string>; units: Record<string, string> };
  dispatch_and_prices: {
    mode: string;
    time_basis: string;
    rows: Array<Record<string, string | boolean>>;
    total_rows: number;
    truncated: boolean;
    units: Record<string, string>;
    capacity: { status: string; value: string | null };
    ancillary: { status: string; value: string | null };
    tolling: { status: string; value: string | null };
  };
  costs: {
    variable_om: { status: string; value: string | null; unit?: string };
    capex: { status: string; value: string | null };
    fixed_opex: { status: string; value: string | null };
    tax: { status: string; value: string | null };
  };
  financing: {
    funding: { status: string; value: string | null };
    debt: { status: string; value: string | null };
    dscr: { status: string; value: string | null };
  };
  review: Record<string, unknown>;
  notes: string[];
}

export interface BessPreview {
  battery: Record<string, string>;
  start: string;
  end: string;
  dispatch_mode: string;
  dispatch_rows: number;
  events: number;
  declared_terms?: BessDeclaredTerms;
  validation_scope: "NATIVE_SCHEMA_ONLY";
  physical_balance_verified: false;
  financial_horizon_verified: false;
  persisted: false;
}

export interface BessResponse {
  ok: boolean;
  code?: string;
  message?: string;
  capability?: BessCapability;
  preview?: BessPreview;
}
