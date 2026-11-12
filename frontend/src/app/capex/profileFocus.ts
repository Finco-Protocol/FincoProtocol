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

/** Lines a user added carry a `C.NN.U###` code. The server accepts that key in the saved profile document only while it names an active line of THIS
 *  project's ledger (G-U2-1); the browser merely labels such a line, it never decides eligibility (the server's item list does). */
export function isUserLineKey(itemKey: string): boolean {
  return /^C\.\d{2}\.U\d{3}$/.test(itemKey);
}
