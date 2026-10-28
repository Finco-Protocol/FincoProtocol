// RC-UX B1 transport contract for GET /v2/model-react/whatif/{options,preview}.  Values are the Q4 authority's own; nothing is computed here.
export interface WhatIfCandidate {
  check_id: string; finding: string; finding_status: string; field_id: string; assumption: string; unit: string;
  original: number | null; eligible: boolean; reason: string;
}
export interface WhatIfOptions {
  ok: true; run_state: string; reason: string; candidates: WhatIfCandidate[];
  semantics: { preview_is_a_run: boolean; creates_scenario_not_run: boolean; note: string };
}
export interface WhatIfPreview {
  ok: true;
  preview: {
    finding: { id: string; status: string; source: string };
    assumption: { field_id: string; unit: string; original: number; proposed: number; delta: number };
    scenario_name: string; stale: boolean; last_run_snapshot: string | null; token: string; commit: { url: string };
    semantics: { is_a_run: boolean; shows_projected_kpi: boolean; note: string };
  };
}
export interface WhatIfFailure { ok: false; code: string; message?: string }
