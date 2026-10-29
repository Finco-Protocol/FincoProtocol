import { useMemo, useState } from "react";
import { reportAmount } from "../reportFormatting";
import { brokenPath, labelIndexes, linearScale, niceTicks } from "./format";
import type { DebtMetricsView } from "./types";

const W = 420, H = 200, M = { left: 56, right: 12, top: 12, bottom: 34 };
const GRID_LIMIT = 24;

/** Distribution lock-up by the Run's actual periods and the cash DSRA balance it persisted.  A requirement or a facility the Run did not persist is
 *  stated as missing — no zero balance is drawn and no green OPEN label is shown without the underlying evidence. */
export function ReservesPanel({ view, precision }: { view: DebtMetricsView; precision: number }) {
  const reserves = view.reserves;
  const [all, setAll] = useState(false);
  if (!reserves) return null;
  const lock = reserves.lockup;
  const cells = lock.available ? (all ? lock.periods : lock.periods.slice(0, GRID_LIMIT)) : [];
  return (
    <section className="dm-card" data-dm-reserves="true" aria-labelledby="dm-res-h">
      <h3 id="dm-res-h" className="rcm-h3">Distribution &amp; reserves</h3>
      <div className="dm-res-cols">
        <div data-dm-lockup="true">
          <h4 className="dm-h4">Distribution lock-up</h4>
          {lock.available ? <>
            <p className="dm-sub" data-dm-lockup-summary="true">{lock.periods.length - (lock.active_count ?? 0)} open · {lock.active_count ?? 0} locked, of {lock.periods.length} periods with a persisted flag</p>
            <ul className="dm-lock-grid" aria-label="Lock-up by period">
              {cells.map((c) => (
                <li key={c.period_index} className={c.active ? "dm-lock dm-lock-on" : "dm-lock"} data-dm-lock={c.active ? "active" : "inactive"}>
                  <span className="dm-lock-l">{c.label}</span><span className="dm-lock-s">{c.active ? "LOCKED" : "OPEN"}</span>
                </li>
              ))}
            </ul>
            {lock.periods.length > GRID_LIMIT && <button type="button" className="dm-link" onClick={() => setAll((v) => !v)}>{all ? "Show fewer periods" : `Show all ${lock.periods.length} periods`}</button>}
            <p className="dm-note">{lock.note}</p>
          </> : <p className="dm-na" role="status">{lock.reason}</p>}
        </div>
        <div data-dm-dsra="true">
          <h4 className="dm-h4">Cash DSRA balance</h4>
          {!reserves.dsra.available ? <p className="dm-na" role="status">{reserves.dsra.reason}</p>
            : !reserves.dsra.present ? <p className="dm-na" role="status" data-dm-dsra-none="true">{reserves.dsra.reason}</p>
            : <DsraChart view={view} precision={precision} />}
          <p className="dm-note">{reserves.dsra.required?.reason}</p>
          <p className="dm-note" data-dm-dsrf="true">{reserves.dsrf.reason}</p>
        </div>
      </div>
      <div data-dm-gaps="true">
        <h4 className="dm-h4">Not evidenced by this Run</h4>
        <ul className="dm-gaps">
          {reserves.unavailable_conclusions.map((g) => (
            <li key={g.id} data-dm-gap={g.id}><strong>{g.label}</strong> — <span className="dm-na-badge">{g.status}</span>
              <span className="dm-sub"> Needs: {g.missing.join("; ")}.</span></li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function DsraChart({ view, precision }: { view: DebtMetricsView; precision: number }) {
  const periods = view.periods;
  const g = useMemo(() => {
    const innerW = W - M.left - M.right, innerH = H - M.top - M.bottom;
    const vals = periods.map((p) => p.dsra_balance_keur).filter((v): v is number => v !== null);
    const hi = Math.max(0, ...vals);
    const x = (i: number) => M.left + ((i + 0.5) / Math.max(1, periods.length)) * innerW;
    const y = linearScale([0, hi || 1], [M.top + innerH, M.top]);
    return { x, y, innerH, ticks: niceTicks(0, hi || 1, 4) };
  }, [periods]);
  const line = brokenPath(periods.map((p, i) => ({ x: g.x(i), y: p.dsra_balance_keur === null ? null : g.y(p.dsra_balance_keur) })));
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" className="dm-chart dm-chart-small" aria-label="Cash DSRA balance by period (kEUR)">
        {g.ticks.map((t) => <g key={t}><line x1={M.left} x2={W - M.right} y1={g.y(t)} y2={g.y(t)} className="dm-grid" /><text x={M.left - 6} y={g.y(t) + 4} textAnchor="end" className="dm-axis">{reportAmount(t, precision)}</text></g>)}
        <path d={line} className="dm-line dm-line-dsra" fill="none" data-dm-series="dsra" />
        {periods.map((p, i) => (p.dsra_release_keur ?? 0) > 0 ? <text key={`r${i}`} x={g.x(i)} y={H - M.bottom - 4} className="dm-mark-rel" textAnchor="middle">▼</text>
          : (p.dsra_funding_keur ?? 0) > 0 ? <text key={`f${i}`} x={g.x(i)} y={H - M.bottom - 4} className="dm-mark-fund" textAnchor="middle">▲</text> : null)}
        {labelIndexes(periods.length, 5).map((i) => <text key={i} x={g.x(i)} y={H - 10} textAnchor="middle" className="dm-axis">{periods[i].label}</text>)}
      </svg>
      <p className="dm-sub">kEUR · ▲ funding · ▼ release (as persisted){view.reserves?.dsra.initial_funding_keur != null ? ` · initial cash DSRA funding ${reportAmount(view.reserves.dsra.initial_funding_keur, precision)}` : ""}</p>
    </>
  );
}
