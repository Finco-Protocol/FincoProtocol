import { useMemo, useState, type KeyboardEvent } from "react";
import { brokenPath, formatRatio, labelIndexes, linearScale, niceTicks, yDomain } from "./format";
import type { DebtMetricsView, DmPeriod } from "./types";

const W = 760, H = 300, M = { left: 52, right: 74, top: 16, bottom: 46 };

/** DSCR profile over the Run's own committed calendar.  Only persisted series are drawn; a period with no scheduled debt service is a GAP in the
 *  line (never a 0x point); an LLCR curve is not drawn because the Run persists only an aggregate minimum LLCR. */
export function DscrProfileChart({ view }: { view: DebtMetricsView }) {
  const periods = view.periods;
  const th = view.series.thresholds;
  const [active, setActive] = useState<number | null>(null);
  const geometry = useMemo(() => {
    const n = periods.length;
    const innerW = W - M.left - M.right, innerH = H - M.top - M.bottom;
    const x = (i: number) => M.left + ((i + 0.5) / Math.max(1, n)) * innerW;
    const values = periods.flatMap((p) => [p.dscr, p.bank_dscr]);
    const [lo, hi] = yDomain(values, [th.coverage_x, th.eod_x, th.contractual_x, ...periods.map((p) => p.sizing_target_dscr)]);
    const y = linearScale([lo, hi], [M.top + innerH, M.top]);
    return { n, innerW, innerH, x, y, ticks: niceTicks(lo, hi, 5), lo, hi };
  }, [periods, th]);
  const hasSeries = periods.some((p) => p.dscr !== null);
  if (!hasSeries) {
    return (
      <section className="dm-card" data-dm-chart="unavailable" aria-labelledby="dm-chart-h">
        <h3 id="dm-chart-h" className="rcm-h3">DSCR &amp; LLCR profile</h3>
        <p className="dm-na" role="status">Chart unavailable: this Run has no period with scheduled debt service and a persisted DSCR. Nothing is plotted or estimated.</p>
      </section>
    );
  }
  const { x, y, ticks, innerH } = geometry;
  const line = (pick: (p: DmPeriod) => number | null) => brokenPath(periods.map((p, i) => ({ x: x(i), y: pick(p) === null ? null : y(pick(p) as number) })));
  const moveActive = (event: KeyboardEvent<HTMLDivElement>) => {
    const last = periods.length - 1;
    const cur = active ?? -1;
    const next = event.key === "ArrowRight" ? Math.min(last, cur + 1) : event.key === "ArrowLeft" ? Math.max(0, cur - 1)
      : event.key === "Home" ? 0 : event.key === "End" ? last : null;
    if (next === null) return;
    event.preventDefault();
    setActive(next);
  };
  const cur = active === null ? null : periods[active];
  const flags = (p: DmPeriod) => [p.below_one ? "below 1.00x" : "", p.eod_breach ? "below the Minimum DSCR" : "", p.covenant_breach ? "below the contractual DSCR" : "", p.lockup_active ? "lock-up active" : ""].filter(Boolean).join(", ");
  const refs = [1, th.eod_x, th.contractual_x].filter((v): v is number => typeof v === "number");
  return (
    <section className="dm-card" data-dm-chart="available" aria-labelledby="dm-chart-h">
      <h3 id="dm-chart-h" className="rcm-h3">DSCR &amp; LLCR profile</h3>
      <p className="dm-note">Coverage ratios over the debt tenor on the Run&rsquo;s own {view.axis.frequency.toLowerCase()} calendar. Gaps mark periods without scheduled debt service.</p>
      <div className="dm-chart-wrap" tabIndex={0} role="group" aria-label="DSCR profile. Use the left and right arrow keys to inspect a period." onKeyDown={moveActive}
           onBlur={() => setActive(null)} data-dm-chart-focus="true">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`DSCR by period, ${periods.length} periods`} className="dm-chart" preserveAspectRatio="xMidYMid meet">
          {ticks.map((t) => (
            <g key={t}><line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} className="dm-grid" /><text x={M.left - 6} y={y(t) + 4} textAnchor="end" className="dm-axis">{t.toFixed(2)}x</text></g>
          ))}
          {periods.map((p, i) => (p.eod_breach || p.below_one || p.covenant_breach) && (
            <rect key={`b${p.period_index}`} x={x(i) - (geometry.innerW / geometry.n) / 2} y={M.top} width={geometry.innerW / geometry.n} height={innerH}
                  className={p.eod_breach || p.below_one ? "dm-band-crit" : "dm-band-warn"} data-dm-breach={p.period_index} />
          ))}
          <line x1={M.left} x2={W - M.right} y1={y(th.coverage_x)} y2={y(th.coverage_x)} className="dm-rule dm-rule-cov" />
          <text x={W - M.right + 4} y={y(th.coverage_x) + 4} className="dm-rule-label">1.00x</text>
          {th.eod_x !== null && <><line x1={M.left} x2={W - M.right} y1={y(th.eod_x)} y2={y(th.eod_x)} className="dm-rule dm-rule-eod" /><text x={W - M.right + 4} y={y(th.eod_x) + 4} className="dm-rule-label dm-lab-eod">Min {formatRatio(th.eod_x, refs)}</text></>}
          {th.contractual_x !== null && <><line x1={M.left} x2={W - M.right} y1={y(th.contractual_x)} y2={y(th.contractual_x)} className="dm-rule dm-rule-cov2" /><text x={W - M.right + 4} y={y(th.contractual_x) + 4} className="dm-rule-label dm-lab-cov">Covenant {formatRatio(th.contractual_x, refs)}</text></>}
          <path d={line((p) => p.sizing_target_dscr !== null && p.has_debt_service ? p.sizing_target_dscr : null)} className="dm-line dm-line-target" fill="none" />
          <path d={line((p) => p.bank_dscr)} className="dm-line dm-line-bank" fill="none" />
          <path d={line((p) => p.dscr)} className="dm-line dm-line-dscr" fill="none" data-dm-series="dscr" />
          {periods.map((p, i) => p.dscr !== null && (
            <circle key={p.period_index} cx={x(i)} cy={y(p.dscr)} r={active === i ? 5.5 : 3.2}
                    className={p.eod_breach || p.below_one ? "dm-pt dm-pt-crit" : p.covenant_breach ? "dm-pt dm-pt-warn" : "dm-pt"}
                    onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)} />
          ))}
          {labelIndexes(periods.length, 8).map((i) => <text key={i} x={x(i)} y={H - M.bottom + 16} textAnchor="middle" className="dm-axis">{periods[i].label}</text>)}
          {active !== null && <line x1={x(active)} x2={x(active)} y1={M.top} y2={M.top + innerH} className="dm-cursor" />}
        </svg>
      </div>
      <p className="dm-readout" role="status" aria-live="polite" data-dm-readout="true">
        {cur ? <>{cur.label}{cur.date ? ` · ${cur.date}` : ""} — {cur.dscr === null ? "no scheduled debt service in this period" : <>DSCR {formatRatio(cur.dscr, refs)}{cur.bank_dscr !== null ? ` · bank case ${formatRatio(cur.bank_dscr, refs)}` : ""}{flags(cur) ? ` · ${flags(cur)}` : ""}</>}</>
          : "Hover or focus the chart and use the arrow keys to read a period."}
      </p>
      <ul className="dm-legend" aria-label="Chart legend">
        <li><span className="dm-sw dm-sw-dscr" />DSCR (base case)</li><li><span className="dm-sw dm-sw-bank" />DSCR (bank case)</li>
        <li><span className="dm-sw dm-sw-target" />Sizing target (assumption)</li><li><span className="dm-sw dm-sw-cov" />1.00x coverage</li>
        {th.eod_x !== null && <li><span className="dm-sw dm-sw-eod" />Minimum DSCR</li>}
        {th.contractual_x !== null && <li><span className="dm-sw dm-sw-cov2" />Contractual DSCR</li>}
      </ul>
      <p className="dm-note" data-dm-llcr-note="true">LLCR curve: {view.series.llcr.reason}</p>
      <details className="dm-more" data-dm-chart-data="true"><summary>Data table for the chart</summary>
        <div className="dm-scroll" tabIndex={0} role="region" aria-label="DSCR by period">
          <table className="dm-table"><caption className="sr-only">DSCR by period</caption>
            <thead><tr><th scope="col">Period</th><th scope="col">Date</th><th scope="col" className="dm-num">DSCR</th><th scope="col" className="dm-num">Bank case</th><th scope="col">Flags</th></tr></thead>
            <tbody>{periods.map((p) => <tr key={p.period_index}><th scope="row">{p.label}</th><td>{p.date ?? "—"}</td>
              <td className="dm-num">{p.dscr === null ? "n/a" : formatRatio(p.dscr, refs)}</td><td className="dm-num">{p.bank_dscr === null ? "n/a" : formatRatio(p.bank_dscr, refs)}</td><td>{flags(p) || "—"}</td></tr>)}</tbody></table>
        </div>
      </details>
    </section>
  );
}
