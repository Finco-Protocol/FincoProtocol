// WF-06B — a tiny read-only mirror of the Save All state, so the top bar (outside the pending-change provider) can show the SAME Save All action the
// Changes panel offers. It holds no project value: only a count, the availability reason and the shell's own handler. One workspace is mounted at a time.
import { useSyncExternalStore } from "react";

export interface SaveAllBridgeState {
  total: number;
  disabled: boolean;
  reason: string;
  saving: boolean;
  run: (() => void) | null;
}

const EMPTY: SaveAllBridgeState = { total: 0, disabled: true, reason: "", saving: false, run: null };
let state: SaveAllBridgeState = EMPTY;
const listeners = new Set<() => void>();

export function publishSaveAll(next: SaveAllBridgeState | null) {
  state = next ?? EMPTY;
  listeners.forEach((l) => l());
}

export function useSaveAllBridge(): SaveAllBridgeState {
  return useSyncExternalStore((cb) => { listeners.add(cb); return () => { listeners.delete(cb); }; }, () => state, () => EMPTY);
}
