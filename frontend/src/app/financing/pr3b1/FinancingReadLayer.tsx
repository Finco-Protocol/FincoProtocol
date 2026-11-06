import { useEffect, useState } from 'react';
import { FinancingOverview } from './FinancingOverview';
import { readEvidence } from './readEvidence';
import type { Evidence, Scope } from './types';

/** Scope-keyed child drops all previous responses immediately on project/scenario/history switch. */
export function FinancingReadLayer({ scope, reloadKey = 0 }: { scope: Scope; reloadKey?: number }) {
  return <ScopedRead key={JSON.stringify(scope)} scope={scope} reloadKey={reloadKey} />;
}
function ScopedRead({ scope, reloadKey }: { scope: Scope; reloadKey: number }) {
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
  if (loaded?.key !== key) return <p role="status">Loading Financing evidence…</p>;
  if (!loaded.evidence) return <div role="alert"><p>{loaded.error}</p><button type="button" onClick={() => setNonce(n => n + 1)}>Reload evidence</button></div>;
  return <FinancingOverview evidence={loaded.evidence} onReload={() => setNonce(n => n + 1)} onHistoryChange={setHistoryId} />;
}
