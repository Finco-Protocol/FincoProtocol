import { forwardRef, useImperativeHandle, useMemo, useRef } from "react";
import { reportAmount } from "../reportFormatting";
import { formatRatio, scheduleCsv } from "./format";
import type { DebtMetricsView } from "./types";

export interface ScheduleHandle { jumpTo: (periodIndex: number) => void }

/** Dated period-by-period debt schedule and covenant detail.  Rows exist only when the Run persisted them; sticky labels, horizontal scrolling and
 *  keyboard focus; amounts follow the shared report precision, ratios keep their own precision. */
export const PeriodSchedule = forwardRef<ScheduleHandle, { view: DebtMetricsView; precision: number; runId: string }>(function PeriodSchedule({ view, precision, runId }, ref) {
  const wrap = useRef<HTMLDivElement>(null);
  const periods = view.periods;
  const th = view.series.thresholds;
  const refs = useMemo(() => [1, th.eod_x, th.contractual_x].filter((v): v is number => typeof v === "number"), [th]);
  useImperativeHandle(ref, () => ({
    jumpTo(periodIndex) {
      const header = wrap.current?.querySelector<HTMLElement>(`[data-dm-col="${periodIndex}"]`);
      if (!header) return;
      header.scrollIntoView({ inline: "center", block: "nearest" });
      header.focus({ preventScroll: true });
    },
  }), []);
  const years = useMemo(() => {
    const out: Array<{ year: number | null; span: number }> = [];
    for (const p of periods) {
      const last = out[out.length - 1];
      if (last && last.year === p.year) last.span += 1; else out.push({ year: p.year, span: 1 });
    }
    return out;
  }, [periods]);
  const download = () => {
    const blob = new Blob([scheduleCsv(periods, view.schedule)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `debt-metrics-${runId.slice(0, 8)}.csv`; a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const cell = (unit: string, value: number | boolean | null, key: string, index: number): { text: string; cls: string } => {
    if (value === null) return { text: "n/a", cls: "dm-na" };
    if (unit === "flag") return { text: value ? "Yes" : "—", cls: value ? "dm-flag-on" : "" };
    if (typeof value !== "number") return { text: "n/a", cls: "dm-na" };
    if (unit === "x") {
      const p = periods[index];
      const bad = key === "dscr" && (p.eod_breach || p.below_one) ? "dm-cell-crit" : key === "dscr" && p.covenant_breach ? "dm-cell-warn" : "";
      return { text: formatRatio(value, refs), cls: bad };
    }
    return { text: reportAmount(value, precision), cls: key === "shortfall_keur" && value > 0 ? "dm-cell-crit" : "" };
  };
  return (
    <section className="dm-card" data-dm-schedule="true" aria-labelledby="dm-sched-h">
      <div className="dm-card-head">
        <h3 id="dm-sched-h" className="rcm-h3">Debt schedule &amp; covenant detail</h3>
        <button type="button" className="rcm-btn dm-export" onClick={download} data-dm-export="csv">Export CSV (raw values)</button>
      </div>
      <p className="dm-note">Period columns follow the Run&rsquo;s committed calendar ({view.axis.frequency.toLowerCase()}, {periods.length} periods). Amounts in kEUR; ratios in x. “n/a” means the Run did not persist the value.</p>
      <div className="dm-scroll dm-sched-wrap" ref={wrap} role="region" tabIndex={0} aria-label="Debt schedule, scroll horizontally" data-dm-sched-scroll="true">
        <table className="dm-table dm-sched">
          <caption className="sr-only">Period-by-period debt schedule and covenant detail for this committed Run</caption>
          <thead>
            <tr className="dm-yearrow"><th scope="col" className="dm-stick" />{years.map((y, i) => <th key={i} scope="colgroup" colSpan={y.span} className="dm-year">{y.year ?? ""}</th>)}</tr>
            <tr><th scope="col" className="dm-stick">Line</th>
              {periods.map((p) => <th key={p.period_index} scope="col" tabIndex={-1} data-dm-col={p.period_index} className="dm-num dm-colhead">
                <span>{p.label}</span><span className="dm-sub">{p.date ?? ""}</span></th>)}</tr>
          </thead>
          {view.schedule.map((g) => (
            <tbody key={g.id} data-dm-group={g.id}>
              <tr className="dm-group"><th scope="rowgroup" colSpan={periods.length + 1} className="dm-stick">{g.label}</th></tr>
              {g.rows.map((r) => (
                <tr key={r.key} data-dm-line={r.key} data-available={r.available}>
                  <th scope="row" className="dm-stick" title={r.available ? r.label : `${r.label} — ${r.reason}`}>{r.label}<span className="dm-unit">{r.unit === "flag" ? "" : ` (${r.unit})`}</span></th>
                  {periods.map((p, i) => { const c = cell(r.unit, r.available ? r.values[i] ?? null : null, r.key, i); return <td key={p.period_index} className={`dm-num ${c.cls}`}>{c.text}</td>; })}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </section>
  );
});
