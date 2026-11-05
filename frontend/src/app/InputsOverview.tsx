// WF-06B — Inputs overview (A+ workbench): a KPI strip, one search box and group chips, then CAPEX / OPEX summaries.
// Every figure is server-owned and labelled by what it is:
//   * result tiles come from the last committed Run exactly as it published them (never a draft, never computed here);
//   * "saved lines" tiles are the sum of active saved cost lines (not a model result);
//   * unsaved edits are counted separately and never included in any figure.
import { useEffect, useState } from "react";
import "../styles/compact-inputs.css";
import { fetchCostLines, fetchStatements } from "./api";
import { showKeur } from "./costAmounts";
import { groupDisplayName } from "./costGroupDisplay";
import { CostUnitSelect, useCostUnit } from "./CostUnit";
import { useReportPrecision } from "./ReportPrecision";
import { RunIdentityLabel } from "./runIdentity";
import type { CostLineProjectionGroup, CostLinesPayload, StatementsPayload, WorkspacePayload } from "./types";
import { useDirtyTotal } from "./workflow/workflowShared";

type Sheet = "capex" | "opex";
type Groups = { saved: number | null; groups: CostLineProjectionGroup[]; state: "loading" | "ready" | "unavailable" };

/** Read-only cost figures follow the chosen unit and the report precision (default kEUR, 0 decimals); stored amounts are untouched. */
function useShown() {
  const [unit] = useCostUnit();
  const { precision } = useReportPrecision();
  return { unit, KEUR: (n: number | string | null) => showKeur(n, unit, precision) };
}

function useCostGroups(project: string, sheet: Sheet, reloadKey: number): Groups {
  const [value, setValue] = useState<Groups>({ saved: null, groups: [], state: "loading" });
  useEffect(() => {
    let live = true;
    setValue((v) => ({ ...v, state: "loading" }));
    void (async () => {
      const r = await fetchCostLines(project, sheet) as unknown as CostLinesPayload | null;
      if (!live) return;
      const p = r && r.ok === true ? r.projection : null;
      setValue(p ? { saved: p.saved_total_keur, groups: p.groups, state: "ready" } : { saved: null, groups: [], state: "unavailable" });
    })();
    return () => { live = false; };
  }, [project, sheet, reloadKey]);
  return value;
}

function useStatements(project: string, reloadKey: number, snapshot: string | undefined) {
  const [value, setValue] = useState<StatementsPayload | null>(null);
  useEffect(() => {
    let live = true;
    void (async () => {
      const r = await fetchStatements(project) as unknown as StatementsPayload | null;
      if (live) setValue(r && (r as { ok?: unknown }).ok === true ? r : null);
    })();
    return () => { live = false; };
  }, [project, reloadKey, snapshot]);
  return value;
}

export function InputsOverview({ project, workspace, reloadKey = 0, query, onQuery, railOpen, onRail }: {
  project: string; workspace: WorkspacePayload; reloadKey?: number; query: string; onQuery: (q: string) => void; railOpen: boolean; onRail: () => void;
}) {
  const statements = useStatements(project, reloadKey, workspace.identity?.snapshot_id);
  const { total: staged } = useDirtyTotal();
  const { unit, KEUR } = useShown();

  const identity = workspace.identity;
  const state = workspace.freshness.state;
  const committed = Boolean(identity) && statements?.snapshot !== null && statements?.status?.runId === identity?.snapshot_id;
  const metrics = statements?.results?.metrics ?? [];
  const lender = statements?.results?.lender_metrics ?? [];
  const pick = (label: string) => metrics.find((m) => m.label === label);
  const lenderPick = (key: string) => lender.find((m) => m.key === key);
  const result = (id: string, label: string, display: string | null | undefined, ok: boolean | undefined) => ({
    id, label, text: !identity ? "—" : !committed ? "…" : ok && display ? display : "Not in this Run", result: true,
  });
  const tiles = [
    result("project-irr", "Project IRR", pick("Project IRR")?.display, pick("Project IRR")?.available),
    result("sponsor-irr", "Total Sponsor IRR", pick("Total Sponsor IRR")?.display, pick("Total Sponsor IRR")?.available),
    result("min-dscr", "Min DSCR", lenderPick("min_dscr")?.display ?? undefined, lenderPick("min_dscr")?.available),
  ];
  const senior = statements?.results?.senior_debt ?? null;
  const seniorText = !identity ? "—" : !committed ? "…" : senior?.available && senior.value_keur !== null ? `${KEUR(senior.value_keur)} ${unit}` : "Not in this Run";
  const llcr = result("min-llcr", "LLCR", lenderPick("min_llcr")?.display ?? undefined, lenderPick("min_llcr")?.available);

  return (
    <section className="ci-overview" aria-label="Inputs overview" data-inputs-overview="true" data-run-state={state}>
      <details className="ux-result-disclosure" open={Boolean(identity)}><summary>Last Run results{!identity && " · NOT_RUN"}</summary>
      <div className="ci-kpis" data-ci-kpis="true">
        {tiles.map((t) => (
          <div className="ci-kpi" key={t.id}>
            <span className="ci-kpi-label">{t.label}</span>
            <strong className="ci-kpi-value" data-ci-metric={t.id}>{t.text}</strong>
          </div>
        ))}
        <div className="ci-kpi" data-ci-senior-debt={senior?.available ? "run" : "none"}>
          <span className="ci-kpi-label">Senior debt</span>
          <strong className="ci-kpi-value" data-ci-metric="senior-debt">{seniorText}</strong>
        </div>
        <div className="ci-kpi">
          <span className="ci-kpi-label">{llcr.label}</span>
          <strong className="ci-kpi-value" data-ci-metric={llcr.id}>{llcr.text}</strong>
        </div>
      </div>
      </details>
      <p className="ci-source" data-ci-source="true">
        {!identity
          ? <span data-ci-norun="true">No Run yet — results appear after you run the model. Saving never runs it.</span>
          : <>
            <span className="rx-badge" data-ci-freshness={state}>{state === "STALE" ? "OUTDATED" : state === "CURRENT" ? "UP TO DATE" : "NOT RUN"}</span>
            {" "}Results from Run <span data-ci-run-id={identity.snapshot_id}><RunIdentityLabel snapshotId={identity.snapshot_id} /></span>
            {state === "STALE" && <strong className="ci-stale" role="status" data-ci-stale="true"> Inputs changed after this Run — run the model again to update.</strong>}
          </>}
        <br />
        <span className="ci-sourcenote">The CAPEX and OPEX cards show saved inputs; they are not model results.</span>
        {" "}<span data-ci-staged={staged}>{staged === 0 ? "No unsaved edits." : `${staged} unsaved edit${staged === 1 ? "" : "s"} — not included in any figure above.`}</span>
      </p>
      <div className="ci-find" role="search">
        <input type="search" className="fm-input ci-search" data-ci-search="true" value={query} placeholder="Find any input or cost line…"
               aria-label="Find any input or cost line" onChange={(e) => onQuery(e.target.value)} />
        <CostUnitSelect />
        <button type="button" className="fm-btn ci-railtoggle" data-ci-rail-toggle="true" aria-pressed={railOpen} onClick={onRail}>{railOpen ? "Hide details" : "Show details"}</button>
      </div>
    </section>
  );
}

function SummaryTable({ title, sheet, data, onOpen, unit }: { title: string; sheet: Sheet; data: Groups; onOpen: (sheet: Sheet) => void; unit: string }) {
  const { KEUR } = useShown();
  const rows = data.groups.filter((g) => g.counts_toward_sheet_total || g.row_kind === "derived_runtime");
  return (
    <div className="ci-summary" data-ci-summary={sheet}>
      <h3>{title}</h3>
      <div className="fm-table-wrap ci-summary-scroll" role="region" tabIndex={0} aria-label={`${title}, scrollable`}>
      <table className="rx-table ci-summary-table">
        <caption className="fm-sr-only">{title}</caption>
        <thead><tr><th scope="col">Group</th><th scope="col" className="ci-num">{unit}</th><th scope="col" className="ci-num">Lines</th><th scope="col">Status</th></tr></thead>
        <tbody>
          {data.state === "loading" && <tr><td colSpan={4}>Loading…</td></tr>}
          {data.state === "unavailable" && <tr><td colSpan={4}>The summary is not available right now.</td></tr>}
          {rows.map((g) => (
            <tr key={g.code} data-ci-summary-row={g.code}>
              <th scope="row">{groupDisplayName(g.code, g.label)}</th>
              <td className="ci-num">{g.saved_total_keur === null ? "—" : KEUR(g.saved_total_keur)}</td>
              <td className="ci-num">{g.active_line_count}</td>
              <td>
                {g.mapping_status === "DERIVED" ? <span className="ws2-chip" data-mapping-status="DERIVED">Calculated by the model</span>
                  : g.mapping_status === "UNRESOLVED" ? <span className="ws2-chip" data-mapping-status="UNRESOLVED">To be confirmed</span>
                  : <button type="button" className="ci-link" onClick={() => onOpen(sheet)}>Open</button>}
              </td>
            </tr>
          ))}
        </tbody>
        {data.saved !== null && <tfoot><tr><th scope="row">Total, saved lines</th><td className="ci-num" data-ci-summary-total={sheet} data-exact={String(data.saved)}>{KEUR(data.saved)}</td><td /><td /></tr></tfoot>}
      </table>
      </div>
    </div>
  );
}

export function CostSummaries({ project, reloadKey = 0, onOpen }: { project: string; reloadKey?: number; onOpen: (sheet: Sheet) => void }) {
  const capex = useCostGroups(project, "capex", reloadKey);
  const opex = useCostGroups(project, "opex", reloadKey);
  const { unit } = useShown();
  // Open on desktop; folded on small screens so the page stays short (one tap shows it).
  const [open, setOpen] = useState(() => !(typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(max-width: 900px)").matches));
  return (
    <details className="ci-summaries" aria-label="CAPEX and OPEX summary" data-ci-summaries="true" open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="ci-summaries-title">CAPEX and OPEX summary</summary>
      <div className="ci-summaries-grid">
        <SummaryTable title="CAPEX summary" sheet="capex" data={capex} onOpen={onOpen} unit={unit} />
        <SummaryTable title="OPEX summary" sheet="opex" data={opex} onOpen={onOpen} unit={`${unit} / yr`} />
      </div>
    </details>
  );
}


export interface FocusedField { label: string; unit: string; saved: string; state: string; reason: string; min: number | null; max: number | null }

/** The range the server itself enforces for this field (registry min/max); null when the field has none. Never invented. */
export function allowedRange(f: Pick<FocusedField, "min" | "max" | "unit">): string | null {
  if (f.min === null && f.max === null) return null;
  const u = f.unit ? ` ${f.unit}` : "";
  if (f.min !== null && f.max !== null) return `${f.min} to ${f.max}${u}`;
  return f.min !== null ? `at least ${f.min}${u}` : `at most ${f.max}${u}`;
}

/** Right-hand "Details and checks" panel: what the focused field is, what is saved, and which cost groups still need confirming. Read-only. */
export function InputsRail({ project, reloadKey = 0, focus }: { project: string; reloadKey?: number; focus: FocusedField | null }) {
  const capex = useCostGroups(project, "capex", reloadKey);
  const opex = useCostGroups(project, "opex", reloadKey);
  const pending = [...capex.groups, ...opex.groups].filter((g) => g.mapping_status === "UNRESOLVED" && g.line_count > 0);
  return (
    <aside className="ci-rail" aria-label="Details and checks" data-ci-rail="true">
      <h3>Details and checks</h3>
      <p className="ci-rail-k">Focused field</p>
      <p className="ci-rail-v" data-ci-rail-field="true">{focus ? focus.label : "Select a field to see its details."}</p>
      {focus && (
        <dl className="ci-rail-dl">
          <div><dt>Saved value</dt><dd>{focus.saved || "—"}</dd></div>
          <div><dt>Unit</dt><dd>{focus.unit || "—"}</dd></div>
          <div><dt>Status</dt><dd>{focus.state}</dd></div>
          <div data-ci-rail-range={allowedRange(focus) ? "known" : "none"}><dt>Allowed range</dt><dd>{allowedRange(focus) ?? "No range is set for this field."}</dd></div>
          {focus.reason && <div><dt>Note</dt><dd>{focus.reason}</dd></div>}
        </dl>)}
      <div className="ci-rail-box">
        <strong>Validation</strong>
        <p>The server checks every value when you save and refuses anything it cannot accept.</p>
      </div>
      <div className={`ci-rail-box${pending.length ? " ci-rail-warn" : ""}`} data-ci-rail-warnings="true">
        <strong>{pending.length ? `${pending.length} group${pending.length === 1 ? "" : "s"} to confirm` : "Nothing to confirm"}</strong>
        {pending.length > 0 && <ul>{pending.map((g) => <li key={g.code}>{groupDisplayName(g.code, g.label)}</li>)}</ul>}
      </div>
    </aside>
  );
}
