// WS-2 / M-008 — Save All attempt bookkeeping (pure).
//
// A request id identifies ONE exact request body.  It is reused only while the body is byte-identical
// (an UNKNOWN outcome is re-sent unchanged and the server replays the stored result); any edit after
// an attempt starts a new id, so a changed payload can never be sent under an old id.

import type { SaveAllRequest } from "./saveAll";

// The CSRF token is re-issued on every capability read and is not part of the request's meaning; the id follows the BODY.
const bodyKey = (r: SaveAllRequest) => JSON.stringify({ ...r, request_id: undefined, csrf_token: undefined });

export interface SaveAllSession {
  /** The request to send: same id as the last attempt iff the body is unchanged since then. */
  next: (draft: SaveAllRequest, newId: () => string) => SaveAllRequest;
  /** Forget the attempt (after a definitive outcome: saved, rejected or stale). */
  settle: () => void;
}

export function createSaveAllSession(): SaveAllSession {
  let last: { key: string; id: string } | null = null;
  return {
    next: (draft, newId) => {
      const key = bodyKey(draft);
      const id = last && last.key === key ? last.id : newId();
      last = { key, id };
      return { ...draft, request_id: id };
    },
    settle: () => { last = null; },
  };
}
