// UX-07 — scenario assumption compare (management and the contract editor moved
// to ./workflow in WF-React-2).  Every mutation posts to the EXISTING canonical scenario/contract
// form routes; creating or selecting a scenario never starts a Run; KPI
// deltas are not computed in the browser (persisted evidence projections
// carry them).

import { useCallback, useEffect, useState } from "react";
import { fetchScenarioCompare } from "./api";
import { RunIdentityLabel } from "./runIdentity";
import { labelWithUnit } from "./fieldLabel";

type FetchState<T> = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; data: T };

function useCanonicalView<T>(fetcher: () => Promise<T | { ok: false; code: string; message?: string }>, deps: unknown[]): FetchState<T> & { retry: () => void } {
  const [state, setState] = useState<FetchState<T>>({ state: "loading" });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ state: "loading" });
    fetcher().then((result: T | { ok: false; code: string; message?: string }) => {
      if (!live) return;
      if (!result || (result as { ok?: unknown }).ok !== true) {
        const failure = result as { code: string; message?: string };
        setState({ state: "error", message: failure.message || failure.code || "The server refused this read." });
      } else {
        setState({ state: "ready", data: result as T });
      }
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);
  const retry = useCallback(() => setNonce((n) => n + 1), []);
  return Object.assign(state, { retry }) as FetchState<T> & { retry: () => void };
}

function Note({ message, tone }: { message: string; tone: "ok" | "error" | "conflict" }) {
  return <div className="fm-info-note" role="status" data-tone={tone}>{message}</div>;
}

export function ScenarioCompareView({ project, scenarioId }: { project: string; scenarioId: string }) {
  const fetcher = useCallback(() => fetchScenarioCompare(project, scenarioId), [project, scenarioId]);
  const state = useCanonicalView(fetcher, [project, scenarioId]);
  if (state.state === "loading") return <p className="fm-info-note" role="status">Building the assumption compare…</p>;
  if (state.state === "error") return <Note message={state.message} tone="error" />;
  const data = state.data;
  return (
    <div className="fm-card fm-section" style={{ marginTop: 12 }} aria-label="Scenario assumption compare">
      <div className="fm-card-title"><h3>Assumption compare</h3>
        <span>{data.base.label} vs {data.scenario?.label ?? "selected scenario"}</span>
      </div>
      <div className="fm-table-wrap">
        <table className="fm-table">
          <thead><tr><th>Assumption</th><th>{data.base.label}</th><th>{data.scenario?.label ?? "Scenario"}</th></tr></thead>
          <tbody>
            {data.differences.map((d) => (
              <tr key={d.field_id}>
                <td title={d.field_id} data-compare-field={d.field_id}>{d.label ? labelWithUnit(d.label, d.unit) : d.field_id}</td>
                <td>{d.base_value === null || d.base_value === undefined ? "—" : String(d.base_value)}</td>
                <td>{d.scenario_value === null || d.scenario_value === undefined ? "—" : String(d.scenario_value)}</td>
              </tr>
            ))}
            {!data.differences.length && <tr><td colSpan={3}><span role="status">No assumption differences — the scenario matches the Working Copy on every stored field.</span></td></tr>}
          </tbody>
        </table>
      </div>
      {([
        ["Base", data.base.run_evidence],
        ["Scenario", data.scenario?.run_evidence],
      ] as Array<[string, { state: string; snapshot_id?: string | null; history_id?: string | null; ran_at?: string | null; note?: string } | undefined]>).map(([label, evidence]) => (
        <p key={label} className="fm-info-note" data-run-evidence-state={evidence?.state ?? "UNAVAILABLE"}>
          <strong>{label} Run evidence:</strong>{" "}
          {evidence?.state === "AVAILABLE"
            ? <>committed Run <RunIdentityLabel snapshotId={evidence.snapshot_id} historyId={evidence.history_id} ranAt={evidence.ran_at} /></>
            : <>UNAVAILABLE — {evidence?.note ?? "no committed Run exists for this side."}</>}
        </p>
      ))}
      <p className="fm-info-note">{data.kpi_compare.reason}</p>
    </div>
  );
}
