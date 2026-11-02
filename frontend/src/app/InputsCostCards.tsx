// PR-U1 — the two cost cards at the top of Inputs: one CAPEX card and one OPEX card, each linking to its single workbench.
// Every figure is server-owned and labelled by what it is:
//   * CAPEX: the sum of ACTIVE saved lines of the groups that take lines (`projection.saved_total_keur`) — calculated groups (contingency,
//     financing costs, reserves) are NOT in it and the card says so; it is not an all-in CAPEX and not a Run result;
//   * OPEX: the saved project's Year-1 LINE ITEMS exactly as the server projects them (per-line escalation), with and without the applied
//     contingency. The six group base amounts are canonical cells that the Run adds on top; the existing projection does not contain them
//     (measured: saving a base changes the Run's OPEX and not this projection), so the card says so and lists them separately instead of
//     calling anything an all-in total. A server-owned all-in figure is a U2b dependency.
// Nothing here sums for authority and nothing here is a committed-Run figure; the Run state is only shown next to them.
import { useEffect, useState } from "react";
import "../styles/compact-inputs.css";
import { fetchCostLines } from "./api";
import { divideDecimalText, showKeur } from "./costAmounts";
import { groupDisplayName } from "./costGroupDisplay";
import { useCostUnit } from "./CostUnit";
import { useReportPrecision } from "./ReportPrecision";
import type { CostLineGroupBase, CostLinesPayload, WorkspacePayload } from "./types";

interface OpexProjection {
  ok: true;
  rows: Array<{ code: string; name: string; derived: boolean; has_data: boolean; values: Array<number | null> }>;
  totals: { excluding_contingency: Array<number | null>; including_contingency: Array<number | null> };
  kpis: { year1_total_keur: number | null; per_mw_year1_keur: number | null };
}

type Card<T> = { state: "loading" | "ready" | "unavailable"; data: T | null };

/** The six saved group base amounts (read-only copy of the canonical cells; the OPEX workbench edits them). */
function useOpexBases(project: string, reloadKey: number): CostLineGroupBase[] | null {
  const [bases, setBases] = useState<CostLineGroupBase[] | null>(null);
  useEffect(() => {
    let live = true;
    void (async () => {
      const r = await fetchCostLines(project, "opex") as unknown as CostLinesPayload | null;
      if (live) setBases(r && r.ok === true ? (r.projection?.bases ?? null) : null);
    })();
    return () => { live = false; };
  }, [project, reloadKey]);
  return bases;
}

function useCapexCard(project: string, reloadKey: number): Card<NonNullable<CostLinesPayload["projection"]>> {
  const [value, setValue] = useState<Card<NonNullable<CostLinesPayload["projection"]>>>({ state: "loading", data: null });
  useEffect(() => {
    let live = true;
    void (async () => {
      const r = await fetchCostLines(project, "capex") as unknown as CostLinesPayload | null;
      if (!live) return;
      const p = r && r.ok === true ? r.projection : null;
      setValue(p ? { state: "ready", data: p } : { state: "unavailable", data: null });
    })();
    return () => { live = false; };
  }, [project, reloadKey]);
  return value;
}

function useOpexCard(project: string, reloadKey: number): Card<OpexProjection> {
  const [value, setValue] = useState<Card<OpexProjection>>({ state: "loading", data: null });
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const r = await fetch(`/v2/model-react/opex-projection?${new URLSearchParams({ project })}`, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
        const body = await r.json().catch(() => null) as OpexProjection | null;
        if (live) setValue(r.ok && body && body.ok === true ? { state: "ready", data: body } : { state: "unavailable", data: null });
      } catch { if (live) setValue({ state: "unavailable", data: null }); }
    })();
    return () => { live = false; };
  }, [project, reloadKey]);
  return value;
}

export function InputsCostCards({ project, workspace, reloadKey = 0, onOpen }: {
  project: string; workspace: WorkspacePayload; reloadKey?: number; onOpen: (sheet: "capex" | "opex") => void;
}) {
  const capex = useCapexCard(project, reloadKey);
  const opex = useOpexCard(project, reloadKey);
  const bases = useOpexBases(project, reloadKey);
  const [unit] = useCostUnit();
  const { precision } = useReportPrecision();
  const shown = (n: number | string | null | undefined) => showKeur(n === undefined ? null : n, unit, precision);
  const state = workspace.freshness.state;
  const runNote = state === "NOT_RUN" ? "No Run yet" : state === "STALE" ? "Last Run is outdated" : "Last Run is up to date";

  const cap = capex.data;
  const capexGroups = (cap?.groups ?? []).filter((g) => g.counts_toward_sheet_total && g.saved_total_keur !== null && g.saved_total_keur !== 0)
    .sort((a, b) => (b.saved_total_keur ?? 0) - (a.saved_total_keur ?? 0)).slice(0, 6);
  const capexPerMw = cap?.capacity?.available && cap.capacity.mw ? divideDecimalText(String(cap.saved_total_keur), cap.capacity.mw) : null;

  const ox = opex.data;
  const y1Excl = ox?.totals.excluding_contingency[0] ?? null;
  const y1Incl = ox?.totals.including_contingency[0] ?? null;
  const opexGroups = (ox?.rows ?? []).filter((r) => !r.derived && r.has_data && (r.values[0] ?? 0) !== 0)
    .sort((a, b) => (b.values[0] ?? 0) - (a.values[0] ?? 0)).slice(0, 6);

  return (
    <section className="ci-cost-cards" aria-label="CAPEX and OPEX" data-ci-cost-cards="true">
      <article className="ci-card" data-ci-card="capex" aria-labelledby="ci-card-capex">
        <h3 id="ci-card-capex">CAPEX</h3>
        <p className="ci-card-total" data-ci-card-total="capex" data-exact={cap ? String(cap.saved_total_keur) : undefined}>
          {capex.state === "loading" ? "…" : cap ? <>{shown(cap.saved_total_keur)} <small>{unit}</small></> : "Unavailable"}
        </p>
        <p className="ci-card-sub">Saved lines — {capexPerMw !== null ? <>{shown(capexPerMw)} {unit}/MW</> : <>per MW {cap?.capacity?.note ? "not available" : "—"}</>}</p>
        <ul className="ci-card-groups" aria-label="Largest CAPEX groups">
          {capexGroups.map((g) => <li key={g.code}><span>{groupDisplayName(g.code, g.label)}</span><span className="ci-num">{shown(g.saved_total_keur)}</span></li>)}
        </ul>
        <p className="ci-card-note">Includes the active saved lines of the groups that take lines. Contingency, financing costs and reserves are calculated when you run the model and are not in this figure. Saved inputs, not a Run result. {runNote}.</p>
        <button type="button" className="fm-btn fm-btn-primary" data-open-workbench="capex" onClick={() => onOpen("capex")}>View / edit CAPEX →</button>
      </article>
      <article className="ci-card" data-ci-card="opex" aria-labelledby="ci-card-opex">
        <h3 id="ci-card-opex">OPEX</h3>
        <p className="ci-card-total" data-ci-card-total="opex">
          {opex.state === "loading" ? "…" : ox && y1Excl !== null ? <>{shown(y1Excl)} <small>{unit} / year 1 · line items</small></> : "Unavailable"}
        </p>
        <p className="ci-card-sub">
          Line items, year 1, before contingency{y1Incl !== null && <> · {shown(y1Incl)} {unit} with the applied contingency{ox?.kpis.per_mw_year1_keur != null && <> ({shown(ox.kpis.per_mw_year1_keur)} {unit}/MW/yr)</>}</>}
        </p>
        <ul className="ci-card-groups" aria-label="Largest OPEX groups">
          {opexGroups.map((r) => <li key={r.code}><span>{groupDisplayName(r.code, r.name)}</span><span className="ci-num">{shown(r.values[0])}</span></li>)}
        </ul>
        <p className="ci-card-sub" data-ci-opex-bases={bases === null ? "unknown" : "known"}>
          {bases === null ? "Group base amounts: not available."
            : bases.some((b) => b.used_by_run && b.value !== "" && Number(b.value) !== 0)
              ? <>Group base amounts saved (not in the figure above): {bases.filter((b) => b.used_by_run && b.value !== "" && Number(b.value) !== 0).map((b) => `${groupDisplayName(b.group, "")} ${shown(b.value)}`).join(" · ")} {unit}/yr</>
              : "No group base amounts saved."}
        </p>
        <p className="ci-card-note">Year 1 of the saved line items with each line's own inflation. The six group base amounts are edited in the OPEX workbench and are added by the model when it runs, except a base the workbench marks as not used; an all-in OPEX figure that includes them is not available yet. Saved inputs, not a Run result. {runNote}.</p>
        <button type="button" className="fm-btn fm-btn-primary" data-open-workbench="opex" onClick={() => onOpen("opex")}>View / edit OPEX →</button>
      </article>
    </section>
  );
}
