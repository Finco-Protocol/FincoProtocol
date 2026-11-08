import { useEffect, useState } from 'react';
import { RUN_PARAM } from "../../debtmetrics/debtMetricsLink";
import { FinancingOverview } from './FinancingOverview';
import { readEvidence } from './readEvidence';
import type { Evidence, Scope } from './types';
import { FinancingEditing } from '../pr3b2/FinancingEditing';

/** Scope-keyed child drops all previous responses immediately on project/scenario/history switch. */
export function FinancingReadLayer({ scope, reloadKey = 0, onOpenExisting, onSaved }: { scope: Scope; reloadKey?: number; onOpenExisting?: (view: string) => void; onSaved?: () => void }) {
  return <ScopedRead key={JSON.stringify([scope.project, scope.scenarioId])} scope={scope} reloadKey={reloadKey} onOpenExisting={onOpenExisting} onSaved={onSaved} />;
}
function ScopedRead({ scope, reloadKey, onOpenExisting, onSaved }: { scope: Scope; reloadKey: number; onOpenExisting?: (view: string) => void; onSaved?: () => void }) {
  const [historyId, setHistoryId] = useState(scope.historyId);
  const [nonce, setNonce] = useState(0);
  const [loaded, setLoaded] = useState<{ key: string; evidence?: Evidence; error?: string } | null>(null);
  const key = JSON.stringify([scope, historyId, reloadKey, nonce]);
  useEffect(() => {
    const abort = new AbortController();
    readEvidence({ ...scope, historyId }, abort.signal).then(evidence => {
      if (!abort.signal.aborted) setLoaded({ key, evidence });
    }).catch((err: unknown) => {
      if (!abort.signal.aborted) setLoaded({ key, error: err instanceof Error ? err.message : 'Financing evidence unavailable.' });
    });
    return () => abort.abort();
  }, [key]); // key contains the full request scope; no prior-scope evidence is rendered while pending
  let content;
  if (loaded?.key !== key) content = <p role="status">Loading Financing evidence…</p>;
  else if (!loaded.evidence) content = <div role="alert"><p>{loaded.error}</p><button type="button" onClick={() => setNonce(n => n + 1)}>Reload evidence</button>
    {onOpenExisting && <details><summary>Existing Financing views</summary><nav aria-label="Available existing Financing views">
      {([['terms','Debt terms'],['bankability','Bankability / reserves'],['facilities','Facilities'],['investors','Investor agreement / sponsor'],['debt-metrics','Debt schedule / history'],['sources-uses','Sources & Uses detail'],['overview','Detailed financing evidence']] as const).map(([view,label]) =>
        <button key={view} type="button" className="rx-button rx-button-secondary" onClick={() => onOpenExisting(view)}>{label}</button>)}
      <a href="#results">Returns and valuation</a>
    </nav><p>Evidence is unavailable here. Existing views check their own access and edit permissions.</p></details>}
  </div>;
  else content = <FinancingOverview embedded={!!onSaved} evidence={loaded.evidence} onOpenExisting={onOpenExisting} onReload={() => setNonce(n => n + 1)} onHistoryChange={id => {
    setHistoryId(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set(RUN_PARAM, id); else url.searchParams.delete(RUN_PARAM);
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  }} />;
  return <>{onSaved && <><h2>Financing</h2><FinancingEditing project={scope.project} scenarioId={scope.scenarioId} reloadKey={reloadKey}
    onSaved={() => { setNonce(n => n + 1);onSaved(); }} /></>}{content}</>;
}
