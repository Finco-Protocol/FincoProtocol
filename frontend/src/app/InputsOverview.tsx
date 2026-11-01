// WF-06B — Compact Inputs overview: two server-owned columns that are never mixed.
//   LEFT  "Saved inputs": identity, the saved CAPEX / OPEX line totals (server projection) and the staged-edit count.
//   RIGHT "Last committed Run": headline results exactly as the committed Run published them, with the Run's id/date/scenario and CURRENT/STALE.
// Nothing is computed here: no IRR, DSCR, debt or CFADS arithmetic, no draft KPI. A saved line total is the sum of active saved lines, not a
// model result; staged edits are listed separately and are never included in either column.
import { useEffect, useState } from "react";
import "../styles/compact-inputs.css";
import { fetchCostLines, fetchStatements } from "./api";
import { RunIdentityLabel } from "./runIdentity";
import type { CostLinesPayload, StatementsPayload, WorkspacePayload } from "./types";
import { useDirtyTotal } from "./workflow/workflowShared";

type Totals = { capex: number | null; opex: number | null; state: "loading" | "ready" | "unavailable" };

const KEUR = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 2 });

function headline(statements: StatementsPayload | null) {
  const metrics = statements?.results?.metrics ?? [];
  const lender = statements?.results?.lender_metrics ?? [];
  const pick = (label: string) => metrics.find((m) => m.label === label);
  const dscr = lender.find((m) => m.key === "min_dscr");
  return [
    { id: "project-irr", label: "Project IRR", display: pick("Project IRR")?.display, ok: pick("Project IRR")?.available },
    { id: "sponsor-irr", label: "Total Sponsor IRR", display: pick("Total Sponsor IRR")?.display, ok: pick("Total Sponsor IRR")?.available },
    { id: "min-dscr", label: "Minimum DSCR (lowest period)", display: dscr?.display ?? undefined, ok: dscr?.available },
  ];
}

export function InputsOverview({ project, workspace, reloadKey = 0 }: { project: string; workspace: WorkspacePayload; reloadKey?: number }) {
  const [totals, setTotals] = useState<Totals>({ capex: null, opex: null, state: "loading" });
  const [statements, setStatements] = useState<StatementsPayload | null>(null);
  const { total: staged } = useDirtyTotal();

  useEffect(() => {
    let live = true;
    setTotals((t) => ({ ...t, state: "loading" }));
    void (async () => {
      const [capex, opex] = await Promise.all([fetchCostLines(project, "capex"), fetchCostLines(project, "opex")]);
      if (!live) return;
      const saved = (r: unknown) => {
        const p = r as CostLinesPayload | null;
        return p && p.ok === true && p.projection ? p.projection.saved_total_keur : null;
      };
      const c = saved(capex), o = saved(opex);
      setTotals({ capex: c, opex: o, state: c === null && o === null ? "unavailable" : "ready" });
    })();
    return () => { live = false; };
  }, [project, reloadKey]);

  useEffect(() => {
    let live = true;
    void (async () => {
      const r = await fetchStatements(project) as unknown as StatementsPayload | null;
      if (live) setStatements(r && (r as { ok?: unknown }).ok === true ? r : null);
    })();
    return () => { live = false; };
  }, [project, reloadKey, workspace.identity?.snapshot_id]);

  const identity = workspace.identity;
  const state = workspace.freshness.state;
  const committed = Boolean(identity) && statements?.snapshot !== null && statements?.status?.runId === identity?.snapshot_id;
  const scenario = workspace.workbook.scenario_name || "Base Case";

  return (
    <section className="ci-overview rx-card" aria-label="Inputs overview" data-inputs-overview="true" data-run-state={state}>
      <div className="ci-col" data-ci-col="saved">
        <h2 className="ci-h">Saved inputs</h2>
        <p className="ci-id" data-ci-identity="true"><strong>{workspace.project.name}</strong> · <code>{workspace.project.code}</code> · scenario {scenario}</p>
        <dl className="ci-facts">
          <div><dt>CAPEX lines saved</dt><dd data-ci-capex={totals.capex ?? "unavailable"}>{totals.state === "loading" ? "…" : totals.capex === null ? "Unavailable" : `${KEUR(totals.capex)} kEUR`}</dd></div>
          <div><dt>OPEX lines saved</dt><dd data-ci-opex={totals.opex ?? "unavailable"}>{totals.state === "loading" ? "…" : totals.opex === null ? "Unavailable" : `${KEUR(totals.opex)} kEUR`}</dd></div>
          <div><dt>Unsaved edits</dt><dd data-ci-staged={staged}>{staged === 0 ? "None" : `${staged} (not included in any figure here)`}</dd></div>
        </dl>
        <p className="ci-note">Saved line totals are the sum of active saved lines. They are not a model result; the model reads them when you run it.</p>
      </div>
      <div className="ci-col" data-ci-col="run">
        <h2 className="ci-h">Last committed Run <span className="rx-badge" data-ci-freshness={state}>{state === "NOT_RUN" ? "NOT RUN" : state}</span></h2>
        {!identity
          ? <p className="ci-note" data-ci-norun="true">No committed Run yet. Saving never runs the model; use Run model.</p>
          : <>
            <p className="ci-id" data-ci-run-id={identity.snapshot_id}>Run <RunIdentityLabel snapshotId={identity.snapshot_id} /> · {identity.ran_at.slice(0, 16).replace("T", " ")} UTC · scenario {identity.scenario_proven ? identity.scenario : "not available"}</p>
            {state === "STALE" && <p className="ci-stale" role="status" data-ci-stale="true">STALE — these results are from the Run above; inputs changed after it.</p>}
            {committed
              ? <dl className="ci-facts">{headline(statements).map((m) => (
                  <div key={m.id}><dt>{m.label}</dt><dd data-ci-metric={m.id}>{m.ok && m.display ? m.display : "Not available in this Run"}</dd></div>))}</dl>
              : <p className="ci-note" role="status">Reading the committed Run…</p>}
          </>}
      </div>
    </section>
  );
}
