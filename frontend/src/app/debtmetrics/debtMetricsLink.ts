/** Navigation to the Debt Metrics view (a tab of the Financing section).
 *
 *  The workspace intercepts every non-hash anchor and turns it into a guarded full-document navigation, so internal links are hash-only
 *  (`#financing`).  The tab and the selected Run travel in the query string, which is set just before the browser applies the hash. */
export const DEBT_METRICS_TAB = "debt-metrics";
export const RUN_PARAM = "dm_run";

/** The URL search that selects the Debt Metrics tab (and optionally one Run) while keeping every other query parameter. */
export function debtMetricsSearch(runId: string | null | undefined, currentSearch: string): string {
  const params = new URLSearchParams(currentSearch);
  params.set("financing", DEBT_METRICS_TAB);
  if (runId) params.set(RUN_PARAM, runId); else params.delete(RUN_PARAM);
  return `?${params.toString()}`;
}

export const debtMetricsHref = (): string => "#financing";

/** Call from the link's onClick.  An unmodified primary click selects the tab/Run before the native `#financing` navigation (same document, no
 *  reload); a modified click (new tab/window) is left alone so the current page is never altered. */
export function prepareDebtMetrics(event: { button: number; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean }, runId?: string | null) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  window.history.replaceState(null, "", `${window.location.pathname}${debtMetricsSearch(runId, window.location.search)}${window.location.hash}`);
}

export function selectedRunFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  const value = new URLSearchParams(window.location.search).get(RUN_PARAM);
  return value && value.length <= 128 ? value : null;
}
