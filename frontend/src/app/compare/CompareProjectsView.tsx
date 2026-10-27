import { useCallback, useEffect, useMemo, useState } from "react";
import "../../styles/rcm-analysis.css";
import { FriendlyError } from "../productLanguage";

/** My Projects > Compare projects: the latest saved Run of up to five of the user's own projects, side by side.  Every figure is the server's
 *  persisted Last Run summary; a project without a Run is shown as unavailable — never calculated, never zero.  Templates are not projects. */
interface Column {
  code: string; name: string; technology: string; country: string; capacity: string; stage: string; perspective: string; run_state: string;
  run_identity: string; runnable: boolean; ran_at: string; ebitda_margin: string; metrics: Record<string, string>; run_url: string | null;
}
interface Payload {
  ok: true; max_projects: number; metrics: Array<{ key: string; label: string }>; sort: string; technology: string; technologies: string[];
  columns: Column[]; left_out: Array<{ code: string; reason: string }>; picker: Array<{ code: string; name: string; technology: string }>; basis: string;
}
type Failure = { code: string; message?: string };
const LEFT_OUT: Record<string, string> = { NOT_FOUND: "was not found", TEMPLATE: "is a template, not a project", LIMIT: "was left out (at most 5 projects are compared)" };
const STATE: Record<string, string> = { CURRENT: "Up to date", STALE: "Out of date", NOT_RUN: "Not run", UNKNOWN: "Unknown" };

const readCodes = () => new URLSearchParams(window.location.search).getAll("compare");

async function load(codes: string[], sort: string, technology: string): Promise<Payload | Failure> {
  const params = new URLSearchParams();
  codes.forEach((c) => params.append("code", c));
  if (sort) params.set("sort", sort);
  if (technology) params.set("technology", technology);
  try {
    const response = await fetch(`/v2/model-react/compare-projects?${params}`, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => null) as (Payload | (Failure & { ok: false })) | null;
    if (response.ok && body && body.ok === true) return body;
    return { code: (body as Failure | null)?.code ?? `HTTP_${response.status}`, message: (body as Failure | null)?.message };
  } catch {
    return { code: "SERVER_UNREACHABLE" };
  }
}

export function CompareProjectsView({ onBack }: { onBack: () => void }) {
  const [codes, setCodes] = useState<string[]>(readCodes);
  const [sort, setSort] = useState("");
  const [technology, setTechnology] = useState("");
  const [data, setData] = useState<Payload | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);

  useEffect(() => {
    let live = true;
    void load(codes, sort, technology).then((r) => { if (!live) return; if ("columns" in r) { setData(r); setFailure(null); } else setFailure(r); });
    return () => { live = false; };
  }, [codes, sort, technology]);

  const choose = useCallback((next: string[]) => {
    const url = new URL(window.location.href);
    url.searchParams.delete("compare");
    next.forEach((c) => url.searchParams.append("compare", c));
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    setCodes(next);
  }, []);
  const toggle = (code: string) => {
    if (codes.includes(code)) choose(codes.filter((c) => c !== code));
    else if (codes.length < (data?.max_projects ?? 5)) choose([...codes, code]);
  };
  const open = useMemo(() => new Set(codes), [codes]);

  return (
    <main className="rx-page" role="main" data-compare-projects="true">
      <header className="rx-header">
        <div><p className="rx-brand">FINCO Protocol · Model</p><h1 className="rx-title">Compare projects</h1></div>
        <nav aria-label="My Projects"><a className="rx-legacy-link" href="/v2/model-react/" data-compare-back="true" onClick={(e) => { e.preventDefault(); onBack(); }}>← My Projects</a></nav>
      </header>
      <section className="rx-card rcm-analysis" aria-label="Choose projects">
        <p className="rx-note">Compare the latest saved Run of up to {data?.max_projects ?? 5} of your projects. A project that has not been run yet is shown as unavailable.</p>
        {failure && <FriendlyError code={failure.code} message={failure.message} />}
        {data && data.picker.length === 0 && <p className="rx-empty" role="status" data-compare-empty="true">You have no projects yet. Create a project from My Projects first.</p>}
        {data && data.picker.length > 0 && (
          <fieldset className="rcm-controls" data-compare-picker="true">
            <legend>Projects ({codes.length} of {data.max_projects} selected)</legend>
            {data.picker.map((p) => (
              <label key={p.code} className="rcm-field">
                <input type="checkbox" checked={open.has(p.code)} disabled={!open.has(p.code) && codes.length >= data.max_projects} data-compare-pick={p.code} onChange={() => toggle(p.code)} />
                {" "}{p.name}{p.technology ? ` · ${p.technology}` : ""}
              </label>
            ))}
          </fieldset>
        )}
        {data && (
          <div className="rcm-controls">
            <label className="rcm-field">Rank by
              <select value={sort} data-compare-sort="true" onChange={(e) => setSort(e.target.value)}>
                <option value="">Selection order</option>
                {data.metrics.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
              </select>
            </label>
            {data.technologies.length > 1 && (
              <label className="rcm-field">Technology
                <select value={technology} data-compare-tech="true" onChange={(e) => setTechnology(e.target.value)}>
                  <option value="">All</option>
                  {data.technologies.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
            )}
          </div>
        )}
        {data?.left_out.map((x) => <p key={x.code} className="rx-note" role="status" data-compare-left-out={x.reason}>“{x.code}” {LEFT_OUT[x.reason] ?? "was left out"}.</p>)}
      </section>

      {data && data.columns.length === 0 && codes.length === 0 && data.picker.length > 0 && <p className="rx-empty" role="status" data-compare-none="true">Select at least two projects to compare them.</p>}
      {data && data.columns.length > 0 && (
        <section className="rx-card rcm-analysis" aria-label="Project comparison">
          <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Comparison table">
            <table className="fm-table rcux-compare-projects" data-compare-table="true">
              <thead><tr><th scope="col">Measure</th>{data.columns.map((c) => <th key={c.code} scope="col" data-compare-col={c.code}>{c.name}</th>)}</tr></thead>
              <tbody>
                <tr><th scope="row">Technology · country</th>{data.columns.map((c) => <td key={c.code}>{c.technology} · {c.country}</td>)}</tr>
                <tr><th scope="row">Capacity</th>{data.columns.map((c) => <td key={c.code}>{c.capacity}</td>)}</tr>
                <tr><th scope="row">Result status</th>{data.columns.map((c) => <td key={c.code} data-compare-state={`${c.code}:${c.run_state}`}>{STATE[c.run_state] ?? c.run_state}</td>)}</tr>
                <tr><th scope="row">Last Run</th>{data.columns.map((c) => <td key={c.code}>{c.runnable ? c.ran_at : "—"}</td>)}</tr>
                {data.metrics.map((m) => (
                  <tr key={m.key} data-compare-row={m.key}>
                    <th scope="row">{m.label}</th>
                    {data.columns.map((c) => <td key={c.code} className="fm-num" data-compare-cell={`${m.key}:${c.code}`}>{c.runnable ? (c.metrics[m.key] ?? "—") : "—"}</td>)}
                  </tr>
                ))}
                <tr data-compare-row="ebitda_margin"><th scope="row">EBITDA margin</th>{data.columns.map((c) => <td key={c.code} className="fm-num">{c.runnable ? c.ebitda_margin : "—"}</td>)}</tr>
                <tr><th scope="row">Open</th>{data.columns.map((c) => (
                  <td key={c.code}>{c.run_url ? <a href={c.run_url} data-compare-open={c.code}>Results →</a> : <span role="status" data-compare-unavailable={c.code}>No Run yet — unavailable for comparison</span>}</td>
                ))}</tr>
              </tbody>
            </table>
          </div>
          <p className="rx-note">{data.basis}</p>
          <details className="rx-tech-details"><summary>Advanced details / Audit trail</summary>
            <p className="fm-mono">{data.columns.map((c) => `${c.name}: run ${c.run_identity || "—"}`).join(" · ")}</p></details>
        </section>
      )}
    </main>
  );
}
