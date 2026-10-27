import { useMemo, useState } from "react";
import { runIdentityText } from "../runIdentity";
import { resultStatus, runStateLabel } from "../productLanguage";
import { historicalExportUrl } from "../workflow/workflowApi";
import type { HistoryPayload, RunReference } from "../insights";

type SortOrder = "newest" | "oldest";
const STATE_ALL = "all";
const MAX_COMPARE = 3;

function chipClass(state: string): string {
  if (state.includes("CURRENT")) return "rcm-chip ok";
  if (state.includes("STALE")) return "rcm-chip warn";
  return "rcm-chip";
}

/** Filter + sort over the canonical Run History projection.  Selection is explicit and local: it never selects a scenario,
 *  saves or runs.  "Matches Working Copy" is a hash-equality label only; it never turns a historical Run into the Last Run. */
export function RunHistoryList({ project, history, workbookHash, selected, onSelect, busy = false }: {
  project: string; history: HistoryPayload; workbookHash: string; selected: string[]; onSelect: (ids: string[]) => void; busy?: boolean;
}) {
  const [text, setText] = useState("");
  const [scenario, setScenario] = useState(STATE_ALL);
  const [state, setState] = useState(STATE_ALL);
  const [order, setOrder] = useState<SortOrder>("newest");

  const scenarios = useMemo(() => Array.from(new Set(history.history.map((r) => r.identity.scenario))).sort(), [history]);
  const states = useMemo(() => Array.from(new Set(history.history.map((r) => r.identity.state))).sort(), [history]);
  const rows = useMemo(() => {
    const needle = text.trim().toLowerCase();
    const kept = history.history.filter((r: RunReference) => {
      const i = r.identity;
      if (scenario !== STATE_ALL && i.scenario !== scenario) return false;
      if (state !== STATE_ALL && i.state !== state) return false;
      if (!needle) return true;
      return [i.history_id, i.snapshot_id, i.scenario, i.composite_hash, i.engine_version ?? "", i.ran_at].some((v) => v.toLowerCase().includes(needle));
    });
    // `ran_at` is an ISO-8601 string: lexical order is chronological order.
    return [...kept].sort((a, b) => (order === "newest" ? b.identity.ran_at.localeCompare(a.identity.ran_at) : a.identity.ran_at.localeCompare(b.identity.ran_at)));
  }, [history, text, scenario, state, order]);

  const toggle = (id: string, on: boolean) => onSelect(on ? [...selected, id] : selected.filter((x) => x !== id));
  const filtered = text !== "" || scenario !== STATE_ALL || state !== STATE_ALL;

  return (
    <section className="rx-card" aria-label="Run history" data-run-history-list="true">
      <h2>Run history <span className="rcm-badge">IMMUTABLE EVIDENCE</span></h2>
      <p className="rx-note">
        Committed Runs of this project, newest evidence first. Historical Runs never change; Save and Run are separate. Project results:
        {" "}<strong data-working-copy-freshness={history.working_copy.freshness}>{resultStatus(history.working_copy.freshness)}</strong>
        {" · "}<a href="#inputs" data-open-working-copy="true">Open the project inputs</a>.
      </p>
      <div className="rcm-controls" role="search" aria-label="Filter Runs">
        <label className="rcm-field">Search
          <input value={text} placeholder="scenario, Run id, snapshot, hash" data-run-filter-text="true" onChange={(e) => setText(e.target.value)} />
        </label>
        <label className="rcm-field">Scenario
          <select value={scenario} data-run-filter-scenario="true" onChange={(e) => setScenario(e.target.value)}>
            <option value={STATE_ALL}>All scenarios</option>
            {scenarios.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="rcm-field">State
          <select value={state} data-run-filter-state="true" onChange={(e) => setState(e.target.value)}>
            <option value={STATE_ALL}>All states</option>
            {states.map((s) => <option key={s} value={s}>{runStateLabel(s)}</option>)}
          </select>
        </label>
        <label className="rcm-field">Order
          <select value={order} data-run-sort="true" onChange={(e) => setOrder(e.target.value as SortOrder)}>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </select>
        </label>
        {filtered && <div className="rcm-controls-actions">
          <button type="button" className="rx-button rx-button-secondary" data-run-filter-clear="true"
            onClick={() => { setText(""); setScenario(STATE_ALL); setState(STATE_ALL); }}>Clear filters</button>
        </div>}
      </div>
      <p className="rx-note" role="status" aria-live="polite" data-run-count="true">
        {rows.length} of {history.history.length} Run{history.history.length === 1 ? "" : "s"} shown
        {history.history_limit_reached ? ` (the ${history.history_limit} most recent are listed)` : ""}. Selected for comparison: {selected.length} of {MAX_COMPARE}.
      </p>
      <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Run history table (scrolls horizontally)">
        <table className="rcm-table" data-run-history-table="true">
          <thead>
            <tr><th scope="col" className="rcm-left">Compare</th><th scope="col" className="rcm-left">Run</th><th scope="col" className="rcm-left">Scenario</th>
              <th scope="col" className="rcm-left">State</th><th scope="col" className="rcm-left">Engine</th><th scope="col" className="rcm-left">Provenance</th>
              <th scope="col" className="rcm-left">Actions</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const i = r.identity;
              const isSelected = selected.includes(i.history_id);
              const matches = Boolean(workbookHash) && i.composite_hash === workbookHash;
              return (
                <tr key={i.history_id} data-run-history-row={i.history_id} data-run-state={i.state} className={isSelected ? "is-base" : ""}>
                  <td className="rcm-left">
                    <input type="checkbox" checked={isSelected} disabled={busy || (!isSelected && selected.length >= MAX_COMPARE)}
                      aria-label={`Select ${i.scenario} Run ${runIdentityText(i.snapshot_id)} for comparison`} data-run-select={i.history_id}
                      onChange={(e) => toggle(i.history_id, e.target.checked)} />
                  </td>
                  <td className="rcm-left">{runIdentityText(i.snapshot_id)}<span className="rcm-delta">{i.ran_at}</span></td>
                  <td className="rcm-left">{i.scenario}</td>
                  <td className="rcm-left"><span className={chipClass(i.state)}>{runStateLabel(i.state)}</span>
                    {matches && <span className="rcm-tag" data-matches-working-copy="true" title="This Run used exactly the inputs the project has saved now. It is still an earlier Run.">SAME INPUTS AS NOW</span>}
                  </td>
                  <td className="rcm-left">{i.engine_version ?? "unavailable"}<span className="rcm-delta">workbook {i.workbook_version ?? "unavailable"}</span></td>
                  <td className="rcm-left">
                    <details><summary>Provenance</summary>
                      <dl className="rcm-facts">
                        <div><dt>Run reference</dt><dd>{i.history_id}</dd></div>
                        <div><dt>Run record</dt><dd>{i.snapshot_id}</dd></div>
                        <div><dt>Saved inputs version</dt><dd style={{ overflowWrap: "anywhere" }}>{i.composite_hash || "unavailable"}</dd></div>
                        <div><dt>Origin</dt><dd>{i.runtime_origin ?? "unavailable"}</dd></div>
                      </dl>
                    </details>
                  </td>
                  <td className="rcm-left">
                    <a href={historicalExportUrl(project, i.history_id)} data-run-export={i.history_id}>Download XLSX</a>
                  </td>
                </tr>
              );
            })}
            {!rows.length && <tr><td colSpan={7} className="rcm-na"><span role="status" data-run-empty="true">
              {history.history.length ? "No Run matches these filters." : "NOT RUN — no committed Run exists for this project yet."}</span></td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
