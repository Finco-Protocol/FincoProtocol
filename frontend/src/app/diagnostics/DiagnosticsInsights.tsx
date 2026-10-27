import { useMemo, useState } from "react";
import "../../styles/rcm-analysis.css";

/** Model checks > quality advisory score, weighted coverage and the period risk heatmap.  Every number and every cell status is the server's
 *  (the canonical diagnostics projection); the browser only lays them out.  Missing evidence is shown as such — never as a pass, never as zero. */
interface HeatCell {
  index: number; date: string; label: string; proven_fail: number; warning: number; unavailable: number; pass: number; applicable: number;
  highest: string | null; groups: Record<string, { fail: number; warning: number; unavailable: number; pass: number }>;
  failed_checks: Array<{ check_id: string; status: string; severity: string; group: string }>;
}
interface Heatmap { axis: string; groups: string[]; cells: HeatCell[]; global_findings: Array<{ check_id: string; title: string; status: string; severity: string; note: string }>; rules: string }
interface Score {
  score?: number | null; score_display?: string; score_note?: string; score_status?: string; readiness_label?: string;
  coverage_weighted_pct?: number | null; coverage_count_pct?: number | null; min_coverage_pct?: number | null; blocked?: boolean;
}

type Status = "fail" | "warning" | "unavailable" | "pass" | "none";
const MARK: Record<Status, string> = { fail: "✕", warning: "!", unavailable: "?", pass: "✓", none: "" };
const TEXT: Record<Status, string> = { fail: "Failed", warning: "Warning", unavailable: "Not evaluated", pass: "Passed", none: "Not applicable" };

function groupStatus(g?: { fail: number; warning: number; unavailable: number; pass: number }): Status {
  if (!g) return "none";
  if (g.fail > 0) return "fail";
  if (g.warning > 0) return "warning";
  if (g.pass > 0 && g.unavailable === 0) return "pass";
  if (g.unavailable > 0) return g.pass > 0 ? "warning" : "unavailable";
  return g.pass > 0 ? "pass" : "none";
}

const pct = (v: number | null | undefined) => (v === null || v === undefined || Number.isNaN(v) ? "Unavailable" : `${v.toFixed(1)}%`);

export function DiagnosticsInsights({ diagnostics }: { diagnostics: Record<string, unknown> }) {
  const score = (diagnostics.score ?? null) as Score | null;
  const heatmap = ((diagnostics.v2 as { heatmap?: Heatmap } | undefined)?.heatmap ?? null) as Heatmap | null;
  const [selected, setSelected] = useState<number | null>(null);
  const cell = useMemo(() => heatmap?.cells.find((c) => c.index === selected) ?? null, [heatmap, selected]);
  if (!score && !heatmap) return null;
  return (
    <>
      {score && (
        <section className="fm-card fm-section" aria-label="Quality advisory score" data-diagnostics-score="true">
          <div className="fm-card-title"><h3>Quality advisory</h3><span>{score.score_status ?? "—"}</span></div>
          <dl className="rcm-facts">
            <div><dt>Advisory score</dt><dd data-score-value="true">{score.score_display ?? (score.score === null || score.score === undefined ? "Unavailable" : String(score.score))}</dd></div>
            <div><dt>Weighted coverage</dt><dd data-coverage-weighted="true">{pct(score.coverage_weighted_pct)}</dd></div>
            <div><dt>Checks evaluated</dt><dd data-coverage-count="true">{pct(score.coverage_count_pct)}</dd></div>
            {score.min_coverage_pct !== null && score.min_coverage_pct !== undefined && <div><dt>Minimum coverage for a score</dt><dd>{pct(score.min_coverage_pct)}</dd></div>}
          </dl>
          <p className="fm-info-note" data-score-label="true">{score.readiness_label ?? ""}</p>
          <p className="fm-info-note">{score.score_note ?? "Advisory only."} A high score means no problems were found in the checks that could be evaluated; it is not a validation of the project.</p>
        </section>
      )}
      {heatmap && heatmap.cells.length > 0 && (
        <section className="fm-card fm-section" aria-label="Period risk heatmap" data-diagnostics-heatmap="true">
          <div className="fm-card-title"><h3>Period risk heatmap</h3><span>{heatmap.cells.length} periods</span></div>
          <p className="fm-info-note">Each cell is one period and one check group, taken from the saved Run. ✓ passed · ! warning · ✕ failed · ? not evaluated. Select a column to see what is behind it.</p>
          <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Period risk heatmap table">
            <table className="fm-table rcux-heatmap">
              <thead>
                <tr><th scope="col">Check group</th>
                  {heatmap.cells.map((c) => (
                    <th key={c.index} scope="col" className={selected === c.index ? "active" : undefined}>
                      <button type="button" className="rx-button rx-button-secondary" data-hm-period={c.index} aria-pressed={selected === c.index}
                        aria-label={`Period ${c.label}`} onClick={() => setSelected(selected === c.index ? null : c.index)}>P{c.index}</button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {heatmap.groups.map((group) => (
                  <tr key={group}>
                    <th scope="row">{group}</th>
                    {heatmap.cells.map((c) => {
                      const s = groupStatus(c.groups[group]);
                      return <td key={c.index} data-hm-cell={`${group}:${c.index}`} data-hm-status={s} className={`rcux-hm rcux-hm-${s}`} title={`${group} · ${c.label}: ${TEXT[s]}`}><span aria-hidden="true">{MARK[s]}</span><span className="rx-sr-only">{TEXT[s]}</span></td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {cell && (
            <div className="rcm-result" data-hm-detail={cell.index} role="status">
              <p><strong>{cell.label}</strong> — {cell.applicable} check{cell.applicable === 1 ? "" : "s"} evaluated for this period: {cell.pass} passed, {cell.warning} warning, {cell.proven_fail} failed, {cell.unavailable} not evaluated.</p>
              {cell.failed_checks.length > 0
                ? <ul>{cell.failed_checks.map((f) => <li key={`${f.check_id}`}>{f.group}: {f.check_id} — {TEXT[f.status === "FAIL" ? "fail" : "warning"]} ({f.severity.toLowerCase()})</li>)}</ul>
                : <p className="fm-info-note">No failed or warning checks in this period.</p>}
            </div>
          )}
          {heatmap.global_findings.length > 0 && (
            <div data-hm-global="true">
              <h4>Findings that are not tied to one period</h4>
              <ul>{heatmap.global_findings.map((g) => <li key={`${g.check_id}-${g.status}`}>{g.title} — {g.status.toLowerCase()} ({g.severity.toLowerCase()}). {g.note}</li>)}</ul>
            </div>
          )}
          <details className="rx-tech-details"><summary>Advanced details / Audit trail</summary><p className="fm-info-note">{heatmap.axis}</p><p className="fm-info-note">{heatmap.rules}</p></details>
        </section>
      )}
    </>
  );
}
