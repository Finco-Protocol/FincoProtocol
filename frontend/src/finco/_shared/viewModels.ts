export type LibraryProjectViewModel = {
  name: string;
  id: string;
  /** Canonical project_id (clone source identity); carried by production callers. */
  projectId?: string;
  technology: string;
  size: string;
  region: string;
  stage: string;
  tone: "blue" | "green" | "gray" | "amber";
  updated: string;
  sponsor: string;
  sourceKind: "reference" | "reference-copy" | "new-demo-project";
  parentReferenceId?: string | null;
  parentReferenceName?: string | null;
};

export type PpaDraftViewModel = {
  contractId: "PPA-A" | "PPA-B" | "PPA-C";
  mode: "Fixed" | "Indexed" | "Scheduled";
  fields: Readonly<Record<string, string>>;
  state: "unsaved" | "demo-saved";
};

export type CostLineViewModel = {
  id: string;
  label: string;
  unit: string;
  periods: readonly string[];
  values: readonly string[];
  editableThroughPeriod: number;
};

export type FacilityDraftViewModel = {
  facilityId: "Senior A" | "Senior B" | "Junior" | "SHL" | "Equity";
  fields: Readonly<Record<string, string>>;
  state: "unsaved" | "demo-saved";
};

export type DemoRunProjection = {
  runId: string;
  freshness: "unknown" | "current" | "stale" | "not run";
  integrity: "not evaluated";
  engineVersion: string | null;
  source: "fixed-synthetic-fixture";
};

/** UI-facing boundary only. These are not production DTOs or API contracts. */
export type FincoDemoViewModel = {
  projectId: string;
  scenarioId: string;
  contractId: PpaDraftViewModel["contractId"];
  facilityId: FacilityDraftViewModel["facilityId"];
  mode: "reference" | "working-copy";
  run: DemoRunProjection;
};
