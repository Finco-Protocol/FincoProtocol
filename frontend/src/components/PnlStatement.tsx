import type { StatementTable } from "../api/types";

// Read-only presentation of the canonical persisted P&L.
//
// Every cell arrives already computed by the canonical statement services; this
// component only renders.  `v === null` is an UNAVAILABLE value (the Run never
// produced it) and renders as an em dash — never as a zero.

function CellValue({ cell }: { cell: { v: number | null; text: string; neg: boolean } }) {
  if (cell.v === null || cell.v === undefined) {
    return (
      <span className="rx-na" data-unavailable="true" title="Not produced by this Run">
        —
      </span>
    );
  }
  return <span className={cell.neg ? "rx-neg" : undefined}>{cell.text}</span>;
}

function StatementTableView({ table, idSuffix }: { table: StatementTable; idSuffix: string }) {
  const unavailable = table.unavailable.length > 0;
  return (
    <figure className="rx-statement">
      <table className="rx-table" data-statement={table.id} data-available={table.available}>
        <caption className="rx-sr-only">{table.title} ({idSuffix})</caption>
        <thead>
          <tr>
            <th scope="col" className="rx-rowhead">Line item</th>
            {table.columns.map((col) => (
              <th scope="col" key={col.index} data-period={col.index} className={col.year0 ? "rx-year0" : undefined}>
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row) => (
            <tr key={row.key} className={row.total ? "rx-total" : undefined} data-row-key={row.key}>
              <th scope="row" className="rx-rowhead" title={row.status_title || undefined}>
                {row.label}
              </th>
              {row.cells.map((cell, i) => (
                <td key={i} data-cell-unit={row.unit}>
                  <CellValue cell={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <figcaption className="rx-note">
        {table.note}
        {unavailable && (
          <> Not produced by this Run: {table.unavailable.join(", ")}.</>
        )}
      </figcaption>
    </figure>
  );
}

export function PnlStatement({ pnl }: { pnl: StatementTable }) {
  return (
    <section className="rx-card" aria-labelledby="rx-pnl-heading" data-statement-state="persisted">
      <h2 id="rx-pnl-heading">{pnl.title}</h2>
      <p className="rx-note">
        Read-only projection of the persisted Last Run. Units: {pnl.rows[0]?.unit ?? "keur"}
        (thousand euros). Values are the canonical persisted evidence — nothing is
        recalculated in the browser.
      </p>
      <StatementTableView table={pnl} idSuffix="period view" />
      {pnl.annual && pnl.annual.rows.length > 0 && (
        <details className="rx-annual">
          <summary>Annual view (canonical annual aggregation)</summary>
          <StatementTableView table={pnl.annual} idSuffix="annual view" />
        </details>
      )}
    </section>
  );
}

export function PnlNotRun({ state }: { state: "NOT_RUN" | "UNAVAILABLE" }) {
  return (
    <section className="rx-card" aria-labelledby="rx-pnl-heading" data-statement-state={state}>
      <h2 id="rx-pnl-heading">Profit &amp; Loss</h2>
      {state === "NOT_RUN" ? (
        <p className="rx-empty" data-statement="NOT_RUN">
          This project has no persisted Run yet, so there are no financial statements to
          show. The React PoC does not run the model; run it from the legacy workbook and
          reload this page.
        </p>
      ) : (
        <p className="rx-empty" data-statement="UNAVAILABLE" role="alert">
          The persisted Run evidence is temporarily unavailable. Reload to refresh.
          Nothing is estimated and no zero is substituted for unavailable values.
        </p>
      )}
    </section>
  );
}
