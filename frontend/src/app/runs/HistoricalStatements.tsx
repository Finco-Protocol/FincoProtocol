import { useEffect, useMemo, useState } from "react";
import "../../styles/rcm-analysis.css";
import { friendlyMessage } from "../productLanguage";

interface StCell { v: number | null; text: string; unit: string; neg: boolean }
interface StColumn { index: number; date: string; label: string; year0: boolean }
interface StNode { key: string; label: string; depth: number; parent: string | null; kind: string; children: string[]; total: boolean; cells: StCell[] | null; node_id: string }
interface StView { id: string; columns: StColumn[]; nodes: StNode[] }
interface StStatement { id: string; title: string; views: { model?: StView; annual?: StView } }
interface StPayload {
  ok: true; project: { code: string };
  statements: {
    history_id: string; identity: { snapshot_id: string; ran_at: string; composite_hash: string; scenario: string; engine_version: string };
    status_dimensions: { input_freshness: string | null; integrity: string; engine_currency?: string; engine_persisted_version?: string | null } | null;
    integrity: { status: string; failures?: Array<{ title: string }> };
    drilldown: { context: { banner: string }; statements: StStatement[] };
  };
}

async function fetchStatements(project: string, historyId: string, signal: AbortSignal): Promise<StPayload | { ok: false; code: string; message?: string }> {
  try {
    const query = new URLSearchParams({ project, history_id: historyId });
    const response = await fetch(`/v2/model-react/analysis/run-statements?${query}`, {
      credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json", "X-Finco-React-Request": "1" }, redirect: "error", signal,
    });
    const body = await response.json().catch(() => null) as StPayload | { ok?: false; code?: string; message?: string } | null;
    if (response.ok && body && body.ok === true) return body as StPayload;
    const failed = (body ?? {}) as { code?: string; message?: string };
    return { ok: false, code: failed.code || `HTTP_${response.status}`, message: failed.message };
  } catch (error) {
    if (signal.aborted) throw error;
    return { ok: false, code: "SERVER_UNREACHABLE", message: "The FINCO Model server is unreachable. Nothing was changed." };
  }
}

function Tree({ view, year0 }: { view: StView; year0: boolean }) {
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const byKey = useMemo(() => new Map(view.nodes.map((n) => [n.key, n])), [view]);
  const hidden = (node: StNode): boolean => {
    let parent = node.parent;
    while (parent) {
      if (collapsed.has(parent)) return true;
      parent = byKey.get(parent)?.parent ?? null;
    }
    return false;
  };
  const columns = view.columns.map((c, i) => ({ c, i })).filter(({ c }) => year0 || !c.year0);
  const toggle = (key: string) => setCollapsed((current) => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  return (
    <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Statement (scrolls horizontally)">
      <table className="rcm-table rcm-statement" data-hist-tree="true">
        <thead><tr><th scope="col" className="rcm-left rcm-sticky">Line item</th>{columns.map(({ c }) => <th scope="col" key={c.index} title={c.date} data-year0={c.year0 ? "1" : undefined}>{c.label}</th>)}</tr></thead>
        <tbody>
          {view.nodes.filter((n) => !hidden(n)).map((n) => (
            <tr key={n.node_id} className={n.total ? "is-base" : undefined} data-hist-row={n.key} aria-level={n.depth + 1}>
              <th scope="row" className="rcm-left rcm-sticky" style={{ paddingLeft: `${8 + n.depth * 14}px` }}>
                {n.children.length > 0 && (
                  <button type="button" className="rx-link-button" aria-expanded={!collapsed.has(n.key)} aria-label={`${collapsed.has(n.key) ? "Expand" : "Collapse"} ${n.label} detail`}
                          onClick={() => toggle(n.key)}>{collapsed.has(n.key) ? "▸" : "▾"}</button>
                )}{" "}{n.label}
              </th>
              {columns.map(({ i }) => {
                const cell = n.cells ? n.cells[i] : null;
                if (!n.cells) return <td key={i} aria-label="no value on a group line" />;
                if (!cell || cell.v === null) return <td key={i} className="rcm-na" title="Not available in the saved Run">—<span className="sr-only">not available</span></td>;
                return <td key={i} className={cell.neg ? "rcm-neg" : undefined} data-raw={cell.v}>{cell.text}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Financial statements of ONE earlier committed Run, in React (no Legacy page).  Every value is what that Run saved; nothing is
 *  recalculated and the current inputs are never shown as this Run's inputs. */
export function HistoricalStatements({ project, historyId, onBack }: { project: string; historyId: string; onBack: () => void }) {
  const [payload, setPayload] = useState<StPayload | null>(null);
  const [error, setError] = useState("");
  const [basis, setBasis] = useState<"annual" | "model">("annual");
  const [year0, setYear0] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setPayload(null); setError("");
    void fetchStatements(project, historyId, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) setPayload(result); else setError(friendlyMessage(result.code, result.message));
    }).catch(() => { /* effect cancelled */ });
    return () => controller.abort();
  }, [project, historyId]);

  if (!payload) return <p className="rx-boot-loading" role="status" data-hist-loading="true">{error || "Reading the saved statements of this Run…"}</p>;
  const s = payload.statements;
  const dims = s.status_dimensions;
  return (
    <section className="rx-card rcm-analysis" data-historical-statements="true" data-history-id={s.history_id} aria-labelledby="hist-st-title">
      <h2 id="hist-st-title" className="rcm-h3">Financial statements of an earlier Run <span className="rcm-badge" data-historical-badge="true">EARLIER RUN</span></h2>
      <p className="rx-note" data-hist-identity="true">Run {s.identity.ran_at} · {s.identity.scenario}</p>
      <p className="rx-banner rx-banner-stale" role="status" data-historical-banner="true">Saved record of this Run. The statement values are exactly what this Run saved; nothing is recalculated. {dims?.input_freshness === "CURRENT" ? "The project inputs are unchanged since this Run." : dims?.input_freshness === "STALE" ? "The project inputs have changed since this Run." : "Whether the inputs changed since this Run could not be checked."}</p>
      {s.integrity.status === "FAIL" && <p className="rx-banner rx-banner-fail" role="alert">Model checks failed for this Run: {(s.integrity.failures ?? []).map((f) => f.title).join("; ")}. The values below are the Run&rsquo;s evidence, shown unchanged.</p>}
      <div className="rcm-controls" role="group" aria-label="Display options (formatting only; never recalculates)">
        <label>Basis <select value={basis} data-hist-basis="true" onChange={(e) => setBasis(e.target.value as "annual" | "model")}><option value="annual">Annual</option><option value="model">Model periods · full tenor</option></select></label>
        <label className="rcm-check"><input type="checkbox" checked={year0} data-hist-year0="true" onChange={(e) => setYear0(e.target.checked)} /> Year 0 (initial period): {year0 ? "shown" : "hidden"}</label>
        <button type="button" className="rx-button rx-button-secondary" data-hist-back="true" onClick={onBack}>Back to Run history</button>
      </div>
      {s.drilldown.statements.length === 0 && <p className="rx-empty" role="status">This Run did not save statements. Nothing is estimated.</p>}
      {s.drilldown.statements.map((st) => {
        const view = st.views[basis] ?? st.views.annual ?? st.views.model;
        if (!view) return null;
        return (
          <section key={st.id} className="rcm-fin" data-hist-statement={st.id} aria-labelledby={`hist-st-${st.id}`}>
            <h3 id={`hist-st-${st.id}`} className="rcm-h3">{st.title}</h3>
            <Tree key={`${st.id}-${basis}`} view={view} year0={year0} />
          </section>
        );
      })}
      <details className="rcm-audit" data-hist-advanced="true">
        <summary>Advanced details / audit trail</summary>
        <dl className="rcm-facts">
          <div><dt>Run reference</dt><dd>{s.history_id}</dd></div>
          <div><dt>Run record</dt><dd>{s.identity.snapshot_id}</dd></div>
          <div><dt>Saved inputs version</dt><dd style={{ overflowWrap: "anywhere" }}>{s.identity.composite_hash || "unavailable"}</dd></div>
          <div><dt>Engine</dt><dd>{s.identity.engine_version || "unavailable"}</dd></div>
        </dl>
      </details>
    </section>
  );
}
