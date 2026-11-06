import type { Credit, Evidence, Fields, Scope, Studio, Workspace } from './types';

export type ReadFetch = typeof fetch;
async function get<T>(path: string, scope: Scope, signal: AbortSignal, read: ReadFetch): Promise<T> {
  const url = new URL(path, 'http://finco.invalid'); url.searchParams.set('project', scope.project);
  if (path.endsWith('credit-decision') && scope.historyId) url.searchParams.append('run', scope.historyId);
  const response = await read(`${url.pathname}${url.search}`, { method: 'GET', cache: 'no-store', credentials: 'same-origin', signal });
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
  return { scope, before, after, creditBefore, credit: creditAfter, studio, fields };
}
