// PR-U2a — hand-over of the item the user clicked on CAPEX · Lines to CAPEX · Monthly schedule (same page, one in-memory value, read once).
let pending: string | null = null;

export function requestProfileFocus(itemKey: string): void {
  pending = itemKey;
}

export function takeProfileFocus(): string | null {
  const key = pending;
  pending = null;
  return key;
}

/** Lines a user added carry a `C.NN.U###` code; the saved profile document does not accept that key yet (contract gap G-U2-1). */
export function isUserLineKey(itemKey: string): boolean {
  return /^C\.\d{2}\.U\d{3}$/.test(itemKey);
}
