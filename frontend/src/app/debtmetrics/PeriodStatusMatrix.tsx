import { memo, useCallback, useMemo, useRef, useState } from "react";
import type { DmPeriod, DmPeriodMatrix, DmMatrixRow, MxStatus } from "./types";

const GLYPH: Record<MxStatus, string> = { OK: "✓", ALERT: "×", WARN: "!", NA: "—" };
const WORD: Record<MxStatus, string> = { OK: "Met / open", ALERT: "Breached / shortfall", WARN: "Locked", NA: "Not recorded or not applicable" };
const short = (p: DmPeriod) => { const m = /(H\d|Q\d)$/.exec(p.label); return m ? m[1] : p.date ? p.date.slice(0, 7) : p.label; };

const MatrixRow = memo(function MatrixRow({ row, rowIndex, periods, active, tabCell, onFocusCell, onPick }: {
  row: DmMatrixRow; rowIndex: number; periods: ReadonlyArray<DmPeriod>; active: number; tabCell: [number, number];
  onFocusCell: (r: number, c: number) => void; onPick: (c: number) => void;
}) {
  return (
    <tr data-dm-mx-row={row.id}>
      <th scope="row" className="dm-mx-rowh" title={row.map}><span className="dm-mx-rl">{row.label}</span><span className="dm-mx-src">{row.source}</span></th>
      {row.cells.map(([status, text], c) => (
        <td key={periods[c]?.period_index ?? c} role="gridcell" className={c === active ? "dm-mx-cell dm-mx-on" : "dm-mx-cell"} data-r={rowIndex} data-c={c} data-s={status}
          data-dm-period={periods[c]?.period_index} tabIndex={tabCell[0] === rowIndex && tabCell[1] === c ? 0 : -1} aria-label={text} title={text}
          onFocus={() => onFocusCell(rowIndex, c)} onClick={() => onPick(c)}>
          <span className={`dm-dot dm-dot-${status.toLowerCase()}`} aria-hidden="true">{GLYPH[status]}</span>
        </td>
      ))}
    </tr>
  );
});

/** FINCO Period Status Matrix: metrics as rows, the Run's own periods as columns.  Every status was evaluated on the server from numbers the Run
 *  persisted (and the terms recorded with it); this component only draws them.  A missing figure is a grey dash, never a green tick. */
export function PeriodStatusMatrix({ matrix, periods, onJump }: { matrix: DmPeriodMatrix; periods: ReadonlyArray<DmPeriod>; onJump: (periodIndex: number) => void }) {
  const [cell, setCell] = useState<[number, number]>([0, 0]);
  const table = useRef<HTMLTableElement>(null);
  const years = useMemo(() => {
    const out: Array<{ key: string; year: number | null; span: number }> = [];
    periods.forEach((p) => {
      const last = out[out.length - 1];
      if (last && last.year === p.year) last.span += 1; else out.push({ key: `${p.year ?? "n"}-${out.length}`, year: p.year, span: 1 });
    });
    return out;
  }, [periods]);
  const focusCell = useCallback((r: number, c: number) => {
    setCell([r, c]);
    table.current?.querySelector<HTMLElement>(`td[data-r="${r}"][data-c="${c}"]`)?.focus({ preventScroll: false });
  }, []);
  const onFocusCell = useCallback((r: number, c: number) => setCell([r, c]), []);
  const pick = useCallback((c: number) => { const p = periods[c]; if (p) onJump(p.period_index); }, [periods, onJump]);
  if (!matrix.available) return <section className="dm-card" data-dm-matrix-unavailable="true"><h3 className="rcm-h3">Period status</h3><p className="dm-na" role="status">{matrix.reason}</p></section>;
  const rows = matrix.rows, cols = periods.length;
  const keys = (e: React.KeyboardEvent) => {
    const [r, c] = cell;
    const move: Record<string, [number, number]> = { ArrowRight: [r, Math.min(cols - 1, c + 1)], ArrowLeft: [r, Math.max(0, c - 1)], ArrowDown: [Math.min(rows.length - 1, r + 1), c],
      ArrowUp: [Math.max(0, r - 1), c], Home: [r, 0], End: [r, cols - 1] };
    if (move[e.key]) { e.preventDefault(); focusCell(move[e.key][0], move[e.key][1]); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(c); }
  };
  const active = cell[1];
  const p = periods[active];
  return (
    <section className="dm-card dm-mx" data-dm-matrix="true" aria-labelledby="dm-mx-h">
      <div className="dm-card-head"><h3 id="dm-mx-h" className="rcm-h3">Period status matrix</h3>
        <ul className="dm-mx-legend" aria-label="Legend">{(["OK", "ALERT", "WARN", "NA"] as MxStatus[]).map((s) => <li key={s}><span className={`dm-dot dm-dot-${s.toLowerCase()}`} aria-hidden="true">{GLYPH[s]}</span>{matrix.legend?.[s] ?? WORD[s]}</li>)}</ul></div>
      <ul className="dm-mx-sum" data-dm-mx-summary="true" aria-label="Summary of the saved Run">
        <li><strong>{matrix.periods ?? cols}</strong> periods</li>
        {matrix.summary.map((s) => (
          <li key={s.id} data-dm-mx-count={s.id}>{s.label}: <strong>{s.alerts === null ? "Not recorded" : s.alerts}</strong>
            {s.alerts !== null && s.evaluated < s.applicable ? <span className="dm-sub"> {s.evaluated} of {s.applicable} periods evaluated</span> : null}</li>
        ))}
      </ul>
      <div className="dm-mx-scroll" data-dm-mx-scroll="true">
        <table ref={table} className="dm-mx-table" role="grid" aria-label="Period status by metric; arrow keys move between periods, Enter shows the period in the schedule" onKeyDown={keys}>
          <thead>
            <tr><th scope="col" className="dm-mx-corner" rowSpan={2}>Metric</th>
              {years.map((y) => <th key={y.key} scope="colgroup" colSpan={y.span} className="dm-mx-year">{y.year ?? "—"}</th>)}</tr>
            <tr>{periods.map((q, c) => <th key={q.period_index} scope="col" className={c === active ? "dm-mx-ph dm-mx-on" : "dm-mx-ph"} title={`${q.label}${q.date ? ` · ${q.date}` : ""}`}>{short(q)}</th>)}</tr>
          </thead>
          <tbody>{rows.map((row, r) => <MatrixRow key={row.id} row={row} rowIndex={r} periods={periods} active={active} tabCell={cell} onFocusCell={onFocusCell} onPick={pick} />)}</tbody>
        </table>
      </div>
      <div className="dm-mx-detail" data-dm-mx-detail="true" role="status" aria-live="polite">
        <strong>{p ? `${p.label}${p.date ? ` · ${p.date}` : ""}` : ""}</strong>
        <ul>{rows.map((row) => <li key={row.id} data-s={row.cells[active]?.[0]}><span className={`dm-dot dm-dot-${(row.cells[active]?.[0] ?? "NA").toLowerCase()}`} aria-hidden="true">{GLYPH[row.cells[active]?.[0] ?? "NA"]}</span>{row.cells[active]?.[1]}</li>)}</ul>
        <button type="button" className="dm-link" onClick={() => pick(active)} data-dm-mx-jump="true">Show this period in the debt schedule</button>
      </div>
      {matrix.gaps.length > 0 && <ul className="dm-mx-gaps" data-dm-mx-gaps="true">{matrix.gaps.map((g) => <li key={g.id} data-dm-mx-gap={g.id}><span className="dm-dot dm-dot-na" aria-hidden="true">—</span><strong>{g.label}</strong> <span className="dm-na-badge">{g.status}</span> {g.reason}</li>)}</ul>}
      <p className="dm-note">Statuses come from the saved Run and the terms recorded with it; a grey dash means the figure was not recorded or is not applicable, never a pass. An open lock-up is not a proof of bankability, and a breached Minimum DSCR is a model-evaluated condition, not a legally adjudicated default.</p>
    </section>
  );
}
