import type { DebtMetricsView, DmKpi } from "./types";

const ORDER: Array<keyof DebtMetricsView["kpis"]> = ["achieved_min_dscr", "average_dscr", "llcr", "plcr", "gearing", "debt_maturity"];

/** Compact KPI strip.  Every tile states its basis; a value the Run did not persist reads "Not available" with the reason — never 0. */
export function KpiRow({ view }: { view: DebtMetricsView }) {
  const terms = view.contract_terms;
  const requirement = (key: string): string[] => {
    if (key !== "achieved_min_dscr" || !terms.recorded) return [];
    const out: string[] = [];
    if (terms.eod_minimum_dscr.status === "CONFIGURED") out.push(`EoD threshold ≥ ${terms.eod_minimum_dscr.raw}x`);
    if (terms.contractual_dscr.status === "CONFIGURED") out.push(`Contractual ≥ ${terms.contractual_dscr.raw}x`);
    return out;
  };
  return (
    <section className="dm-card" data-dm-kpis="true" aria-labelledby="dm-kpi-h">
      <h3 id="dm-kpi-h" className="rcm-h3">Key debt metrics</h3>
      <dl className="dm-kpis">
        {ORDER.map((key) => {
          const k: DmKpi | undefined = view.kpis[key];
          if (!k) return null;
          const reqs = requirement(key);
          return (
            <div key={key} className="dm-kpi" data-dm-kpi={key} data-available={k.available}>
              <dt>{k.label}{key === "achieved_min_dscr" && <span className="dm-tag">Run result</span>}</dt>
              <dd className={k.available ? "dm-kpi-v" : "dm-kpi-v dm-na"}>{k.available ? k.display : "Not available"}</dd>
              {reqs.map((r) => <dd key={r} className="dm-kpi-req">{r}</dd>)}
              {key === "achieved_min_dscr" && k.period && <dd className="dm-sub">in {k.period.date ?? `P${k.period.period_index}`}</dd>}
              <dd className="dm-sub" title={k.basis}>{k.available ? k.basis : k.reason || k.basis}</dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
