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

export interface BessPreview {
  battery: Record<string, string>;
  start: string;
  end: string;
  dispatch_mode: string;
  dispatch_rows: number;
  events: number;
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
