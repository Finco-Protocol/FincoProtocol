import { useReportPrecision } from "../ReportPrecision";
import { useId } from 'react';
import { evidenceDisplay, evidenceUnitLabel, numericCell, timelineGeometry } from './presentation';
import type { RunReference, Timeline } from './types';
import { EvidenceDisclosure } from './EvidenceDisclosure';

function rowUnit(kind: string) { return kind === 'keur' ? 'kEUR' : kind === 'x' ? 'x' : kind === 'flag' ? 'flag' : kind; }

export function CreditTimeline({ project, run, timeline }: { project: string; run: RunReference; timeline: Timeline }) {
  const { precision } = useReportPrecision();
  const chartId = useId();
  if (!timeline.available) return <section className="fi-panel"><h3>Credit timeline</h3><p>{timeline.reason || 'Period results are not available.'}</p></section>;
  return <section className="fi-panel"><h3>Credit timeline</h3>
    <p>Committed model periods · {run.identity.history_id}. Annual presentation unavailable: no authoritative annual mapping.</p>
    <p>{timeline.basis}</p>
    <div className="fi-charts">{timeline.rows.filter(row => row.kind !== 'flag').map(row => {
      const geometry = timelineGeometry(row.cells);
      const title = `${row.label} · ${rowUnit(row.kind)}`;
      return <figure className="fi-chart" key={row.key}>
        <figcaption>{title}</figcaption>
        <svg viewBox="0 0 640 160" role="img" aria-label={`${title}. Values and unavailable intervals are listed in the credit timeline table.`}>
          <line x1="24" x2="616" y1={geometry.zeroY} y2={geometry.zeroY} className="fi-zero" />
          <text x="2" y="12">{geometry.max}</text><text x="2" y="157">{geometry.min}</text>
          {geometry.segments.map((segment, index) => <polyline key={index} points={segment.map(point => `${point.x},${point.y}`).join(' ')} className="fi-line" />)}
          {geometry.points.map((point, index) => point ? <circle key={index} cx={point.x} cy={point.y} r="3" className="fi-point">
            <title>{`${timeline.columns[index]?.date || `Period ${timeline.columns[index]?.index}`} · ${evidenceDisplay(point.value, row.cells[index].d, rowUnit(row.kind), precision)} ${evidenceUnitLabel(point.value, row.cells[index].d, rowUnit(row.kind))}`}</title>
          </circle> : <text key={index} x={24 + index / Math.max(1, row.cells.length - 1) * 592} y="145" textAnchor="middle" className="fi-gap"><title>Unavailable value</title>×</text>)}
        </svg>
        <div className="fi-chart-axis"><span>{timeline.columns[0]?.date || `Period ${timeline.columns[0]?.index ?? 'unavailable'}`}</span>
          <span>{timeline.columns[timeline.columns.length - 1]?.date || `Period ${timeline.columns[timeline.columns.length - 1]?.index ?? 'unavailable'}`}</span></div>
      </figure>;
    })}</div>
    <div className="fi-table-scroll" tabIndex={0} role="region" aria-label="Credit timeline data table">
      <table id={`${chartId}-table`}><caption>Credit timeline · {run.identity.history_id}</caption>
        <thead><tr><th scope="col">Metric / unit</th>{timeline.columns.map(column => <th scope="col" key={column.index}>
          Period {column.index}<br />{column.date || 'Date unavailable'}</th>)}</tr></thead>
        <tbody>{timeline.rows.map(row => <tr key={row.key}><th scope="row">{row.label}<br /><small>{rowUnit(row.kind)}</small></th>
          {timeline.columns.map((column, index) => { const cell = row.cells[index];
            const value = numericCell(cell); const missing = !cell || cell.v === null;
            return <td key={column.index} data-numeric-value={value ?? undefined}>{missing ? <span>Unavailable{cell?.reason && <small>{cell.reason}</small>}</span>
              : row.kind === 'flag' ? cell.d : evidenceDisplay(value, cell.d, rowUnit(row.kind), precision)}</td>;
          })}</tr>)}</tbody></table>
    </div>
    <EvidenceDisclosure project={project} run={run} source="Canonical Credit Decision · committed senior-debt period evidence" period="Committed model periods" />
  </section>;
}
