import { useMemo, useState } from "react";
import { formatRatio } from "./format";
import type { DmPoint, DmTableRow } from "./types";

const GLYPH: Record<string, string> = { CRITICAL: "✖", WARNING: "▲", OK: "✔", NEUTRAL: "•" };
const RANK: Record<string, number> = { CRITICAL: 0, WARNING: 1, NEUTRAL: 2, OK: 3 };
const ROLE: Record<string, string> = {
  INPUT: "Input (recorded with this Run)", RESULT: "Run result", EXISTING_CONTROL: "Existing control", SIZING_ASSUMPTION: "Sizing assumption · not a covenant", OBSERVATION: "Observation",
};

/** Required / Actual / Headroom / Status for every term.  The status is the server's verdict on raw doubles; this view only displays it. */
export function CovenantTable({ rows, onJump }: { rows: DmTableRow[]; onJump: (periodIndex: number) => void }) {
  const [order, setOrder] = useState<"standard" | "severity">("standard");
  const shown = useMemo(() => (order === "standard" ? rows : [...rows].sort((a, b) => (RANK[a.severity] ?? 9) - (RANK[b.severity] ?? 9))), [rows, order]);
  return (
    <section className="dm-card" data-dm-covenants="true" aria-labelledby="dm-cov-h">
      <div className="dm-card-head">
        <h3 id="dm-cov-h" className="rcm-h3">Covenant monitor</h3>
        <label className="dm-sort">Order <select aria-label="Order the covenant table" value={order} onChange={(e) => setOrder(e.target.value as "standard" | "severity")}>
          <option value="standard">Standard</option><option value="severity">Most severe first</option></select></label>
      </div>
      <div className="dm-scroll" role="region" aria-label="Covenant monitor table" tabIndex={0}>
        <table className="dm-table dm-cov">
          <caption className="sr-only">Required, actual, headroom and status of each DSCR term for this committed Run</caption>
          <thead><tr><th scope="col">Metric</th><th scope="col" className="dm-num">Required</th><th scope="col" className="dm-num">Actual</th><th scope="col" className="dm-num">Headroom</th><th scope="col">Status</th></tr></thead>
          <tbody>
            {shown.map((row) => (
              <tr key={row.id} data-dm-row={row.id} data-dm-status={row.status} data-dm-severity={row.severity}>
                <th scope="row">
                  <div className="dm-metric">{row.label}</div>
                  <div className="dm-role">{ROLE[row.role] ?? row.role}</div>
                  <details className="dm-more"><summary>Basis and periods</summary>
                    <p>{row.description}</p><p className="dm-basis">{row.basis}</p>
                    {row.reason && <p className="dm-why">{row.reason}</p>}
                    {row.periods.length > 0 && <PeriodList points={row.periods} total={row.periods_total} threshold={row.required.v} onJump={onJump} />}
                  </details>
                </th>
                <td className="dm-num" data-dm-cell="required" data-label="Required">{row.required.v === null ? <span className="dm-na">{row.required.note || "Not available"}</span> : <>{row.required.operator} {row.required.d}</>}</td>
                <td className="dm-num" data-dm-cell="actual" data-label="Actual">{row.actual.v === null ? <span className="dm-na">{row.actual.d}</span> : row.actual.d}</td>
                <td className="dm-num" data-dm-cell="headroom" data-label="Headroom">{row.headroom
                  ? <span title={row.headroom.note}>{row.headroom.absolute.d} <span className="dm-rel">({row.headroom.relative.d})</span></span>
                  : <span className="dm-na">—</span>}</td>
                <td data-label="Status"><span className={`dm-status dm-sev-${row.severity.toLowerCase()}`} data-dm-status-label="true"><span aria-hidden="true">{GLYPH[row.severity] ?? "•"} </span>{row.status_label}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="dm-note">An Event-of-Default threshold or covenant status is a model-evaluated condition on the terms entered, not a legally declared default and not proof of a missed payment.</p>
    </section>
  );
}

function PeriodList({ points, total, threshold, onJump }: { points: DmPoint[]; total: number; threshold: number | null; onJump: (i: number) => void }) {
  return (
    <ul className="dm-periods" aria-label="Affected periods">
      {points.map((p) => (
        <li key={p.period_index}>
          <button type="button" className="dm-link" onClick={() => onJump(p.period_index)}>P{p.period_index}{p.date ? ` · ${p.date}` : ""}</button>
          {" "}DSCR {formatRatio(p.dscr, threshold === null ? [1] : [threshold, 1])}
          {typeof p.base_cfads_keur === "number" && typeof p.debt_service_keur === "number" && <span className="dm-sub"> · CFADS {p.base_cfads_keur.toFixed(3)} vs service {p.debt_service_keur.toFixed(3)} kEUR</span>}
        </li>
      ))}
      {total > points.length && <li className="dm-sub">… and {total - points.length} more — see the schedule below.</li>}
    </ul>
  );
}
