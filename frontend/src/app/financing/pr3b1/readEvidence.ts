import type { Credit, Evidence, Fields, Scope, Studio, Workspace } from './types';

export type ReadFetch = typeof fetch;
async function get<T>(path: string, scope: Scope, signal: AbortSignal, read: ReadFetch): Promise<T> {
  const query = new URLSearchParams({ project: scope.project });
  if ((path.endsWith('credit-decision') || path.endsWith('financing/studio')) && scope.historyId) query.append('run', scope.historyId);
  const response = await read(`${path}?${query.toString()}`, { method: 'GET', cache: 'no-store', credentials: 'same-origin', signal });
  if (!response.ok) throw new Error(`Financing read unavailable (${response.status}). Reload.`);
  const body = await response.json();
  if (body.ok !== true) throw new Error('Financing read unavailable. Reload.');
  return body as T;
}
/** Sequential bookends deliberately surround the three independent reads. All calls are GET. */
export async function readEvidence(scope: Scope, signal: AbortSignal, read: ReadFetch = fetch): Promise<Evidence> {
  const workspace = '/v2/model-react/workspace', credit = '/v2/model-react/analysis/credit-decision';
  const before = await get<Workspace>(workspace, scope, signal, read);
  const creditBefore = await get<Credit>(credit, scope, signal, read);
  const [studio, fields] = await Promise.all([
    get<Studio>('/v2/model-react/financing/studio', scope, signal, read),
    get<Fields>('/v2/model-react/fields/debt', scope, signal, read),
  ]);
  const creditAfter = await get<Credit>(credit, scope, signal, read);
  const after = await get<Workspace>(workspace, scope, signal, read);
  // Reject cross-scope Working Copy data before any overview can render it.
  // Run freshness/totals remain the separate Last Run gate in the component.
  if ([before, after, studio, fields, creditBefore, creditAfter].some(x => x?.project?.code !== scope.project)
      || before?.workbook?.scenario_id !== scope.scenarioId || after?.workbook?.scenario_id !== scope.scenarioId
      || studio?.identity?.scenario_id !== scope.scenarioId
      || (creditBefore.data?.project_code != null && creditBefore.data.project_code !== scope.project)
      || (creditAfter.data?.project_code != null && creditAfter.data.project_code !== scope.project)) {
    throw new Error('Financing scope changed. Reload evidence.');
  }
  return { scope, before, after, creditBefore, credit: creditAfter, studio, fields };
}
