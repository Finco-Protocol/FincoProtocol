import type { HistoryPayload, InsightsPayload, InsightsResult } from './types';

async function read<T>(path: string, signal?: AbortSignal): Promise<InsightsResult<T>> {
  try {
    const response = await fetch(path, { method: 'GET', credentials: 'same-origin', cache: 'no-store',
      headers: { Accept: 'application/json' }, redirect: 'error', signal });
    const body: unknown = await response.json();
    if (!response.ok || !body || typeof body !== 'object' || !('ok' in body) || body.ok !== true) {
      return { ok: false, code: `HTTP_${response.status}`, message: 'Committed Run evidence could not be read.' };
    }
    return body as T;
  } catch (error) {
    if (signal?.aborted) throw error;
    return { ok: false, code: 'EVIDENCE_UNAVAILABLE', message: 'Committed Run evidence could not be read.' };
  }
}
export function fetchInsightsHistory(project: string, signal?: AbortSignal) {
  return read<HistoryPayload>(`/v2/model-react/insights/history?${new URLSearchParams({ project })}`, signal);
}
export function fetchInsights(project: string, historyIds: readonly string[], signal?: AbortSignal) {
  if (historyIds.length < 1 || historyIds.length > 3 || new Set(historyIds).size !== historyIds.length || historyIds.some(id => !id.trim())) {
    return Promise.resolve<InsightsResult<InsightsPayload>>({ ok: false, code: 'EXPLICIT_RUN_SELECTION_REQUIRED',
      message: 'Select one to three distinct committed Runs.' });
  }
  const query = new URLSearchParams({ project });
  historyIds.forEach(id => query.append('run', id));
  return read<InsightsPayload>(`/v2/model-react/insights?${query}`, signal);
}
