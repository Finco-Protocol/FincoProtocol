// WF-React-2 — export of committed Run evidence.
//
// Both exports are read-only canonical routes: the Last Run workbook is built
// from the last COMMITTED Run (never from unsaved or newer Working Copy edits)
// and the historical workbook from one immutable Run History row.  Nothing is
// reconstructed in the browser and no engine runs.

import { useCallback, useState } from "react";
import { fetchRuns } from "../api";
import type { RunsPayload } from "../types";
import { downloadLastRunWorkbook, historicalExportUrl } from "./workflowApi";
import { RunIdentityLabel } from "../runIdentity";
import {
  LoadingNote, StatusNote, UnavailableNote, useCanonicalRead, type StatusMessage,
} from "./workflowShared";

interface Props {
  project: string;
  freshness: string;
  /** Bump after a Run so the identity shown is the new Last Run. */
  refreshKey?: number;
}

const FRESHNESS_COPY: Record<string, string> = {
  CURRENT: "The export matches the project as it is saved now.",
  STALE: "The project changed after this Run. The export contains the prior committed Run, not the current inputs - run the model to refresh it.",
  NOT_RUN: "No committed Run exists, so there is nothing to export.",
};

export function ModelExportView({ project, freshness, refreshKey = 0 }: Props) {
  const fetcher = useCallback(() => fetchRuns(project), [project, refreshKey]);
  const read = useCanonicalRead<RunsPayload>(fetcher, [project], [refreshKey]);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [busy, setBusy] = useState(false);

  if (read.state === "loading") return <LoadingNote label="Loading export options…" />;
  if (read.state === "error") return <UnavailableNote message={read.message} onRetry={read.reload} />;
  const data = read.data;
  const exports = data.exports;
  if (!exports) return <UnavailableNote message="This server does not describe its export options, so no export is offered." />;
  const latest = data.runs[0];
  const lastRunExport = exports.last_run as typeof exports.last_run & {
    unavailable_code?: string | null; historical_fallback?: { history_id: string; url: string } | null };
  const available = lastRunExport.available;
  // When the Last Run export is closed but that Run's own immutable record exists, its historical export IS the Last Run
  // (identical evidence, no working values).  Offered only when the server names the row.
  const fallback = !available ? lastRunExport.historical_fallback ?? null : null;

  const download = async () => {
    setBusy(true);
    setStatus(null);
    const result = await downloadLastRunWorkbook(project, exports.last_run.csrf_token);
    setBusy(false);
    setStatus(result.ok
      ? { tone: "ok", text: `Downloaded ${result.filename} (${result.bytes.toLocaleString()} bytes) from the last committed Run.` }
      : { tone: "error", text: result.message });
  };

  return (
    <section className="fm-card fm-section wf-section" aria-label="Export" data-export-view="true">
      <div className="fm-card-title"><h2>Export</h2><span>committed Run evidence only</span></div>
      <StatusNote status={status} />
      <div data-export-identity={latest ? latest.runtime_snapshot_id ?? "" : "none"} data-export-freshness={freshness}>
        <p className="fm-info-note">
          <strong>Last committed Run:</strong>{" "}
          {latest
            ? <><RunIdentityLabel snapshotId={latest.runtime_snapshot_id} historyId={latest.history_id} ranAt={latest.ran_at} /> · scenario {latest.active_scenario_name ?? "Base Case"}</>
            : "none"}
          {" · "}<strong>{freshness === "NOT_RUN" ? "NOT RUN" : freshness}</strong>
        </p>
        <p className="fm-info-note" role="note">{FRESHNESS_COPY[freshness] ?? "Run state could not be determined."}</p>
      </div>
      <div className="fm-toolbar">
        {fallback
          ? <a className="fm-btn fm-btn-primary" data-export-last-run="true" data-export-last-run-source="immutable-run-record"
               href={historicalExportUrl(project, fallback.history_id)} download aria-describedby="wf-export-note">
              Download Last Run workbook (XLSX) — from its immutable Run record
            </a>
          : <button type="button" className="fm-btn fm-btn-primary" disabled={busy || !available} data-export-last-run="true"
                    aria-describedby="wf-export-note" onClick={() => void download()}>
              {busy ? "Preparing workbook…" : "Download Last Run workbook (XLSX)"}
            </button>}
      </div>
      {!available && <p className="fm-info-note" role="note" data-export-unavailable-reason="true">
        {fallback ? "The standard Last Run export is closed for this Run: " : "Export unavailable: "}
        {exports.last_run.unavailable_reason || "no committed Run for the active scenario."}
      </p>}
      <p id="wf-export-note" className="fm-info-note">{exports.last_run.note} The download is recorded in the project&rsquo;s export log.</p>

      <p className="wf-group-head">Historical Runs</p>
      <div className="wf-table-wrap">
        <table className="fm-table">
          <thead><tr><th scope="col">Run</th><th scope="col">Scenario</th><th scope="col"><span className="fm-sr-only">Download</span></th></tr></thead>
          <tbody>
            {data.runs.map((run) => (
              <tr key={run.history_id ?? run.runtime_snapshot_id}>
                <td><RunIdentityLabel snapshotId={run.runtime_snapshot_id} historyId={run.history_id} ranAt={run.ran_at} /></td>
                <td>{run.active_scenario_name ?? "Base Case"}</td>
                <td>{run.history_id
                  ? <a className="fm-btn" href={historicalExportUrl(project, run.history_id)} download
                       aria-label={`Download the workbook of the Run committed ${run.ran_at ?? ""}`}>Download XLSX</a>
                  : "—"}</td>
              </tr>
            ))}
            {!data.runs.length && <tr><td colSpan={3}><span role="status">NOT RUN - no committed Run to export.</span></td></tr>}
          </tbody>
        </table>
      </div>
      <p className="fm-info-note">{exports.historical.note}</p>

      <p className="fm-info-note" data-export-analysis-pointer="true">Sensitivity analysis and Goal Seek are in the Analysis section. They calculate only when you start them and never change your saved inputs unless you choose to apply a result.</p>
    </section>
  );
}
