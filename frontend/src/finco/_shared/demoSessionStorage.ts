import { DEMO_SESSION_PREFIX, demoSessionStoragePrefix, type DemoDraftStorage } from "./demoSessionKeys.ts";

export type DemoStorageState = "checking" | "available" | "unavailable" | "recovered";
export type DemoStorageOperation = "read" | "write" | "working-copy" | "clear" | "check";

export type DemoStorageSnapshot = {
  state: DemoStorageState;
  operation: DemoStorageOperation | null;
};

export type DemoSessionStorageLike = DemoDraftStorage & {
  length?: number;
  key?: (index: number) => string | null;
};

export type DemoSessionWrite = readonly [key: string, value: unknown];

let snapshot: DemoStorageSnapshot = { state: "checking", operation: null };
let probeSequence = 0;
const listeners = new Set<() => void>();

function publish(next: DemoStorageSnapshot) {
  if (snapshot.state === next.state && snapshot.operation === next.operation) return;
  snapshot = next;
  listeners.forEach(listener => listener());
}

function getStorage(storage?: DemoSessionStorageLike): DemoSessionStorageLike {
  if (storage) return storage;
  if (typeof window === "undefined") throw new Error("Browser storage is not available.");
  return window.sessionStorage;
}

export function getDemoStorageSnapshot(): DemoStorageSnapshot {
  return snapshot;
}

export function subscribeDemoStorage(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function reportDemoStorageFailure(operation: DemoStorageOperation) {
  publish({ state: "unavailable", operation });
}

export function reportDemoStorageSuccess(operation: DemoStorageOperation = "write") {
  if (snapshot.state === "checking") {
    publish({ state: "available", operation });
  } else if (snapshot.state === "unavailable") {
    publish({ state: "recovered", operation });
  }
}

export function probeDemoSessionStorage(storage?: DemoSessionStorageLike): boolean {
  let target: DemoSessionStorageLike | undefined;
  let key = "";
  try {
    target = getStorage(storage);
    key = `${DEMO_SESSION_PREFIX}health-probe:${Date.now()}:${++probeSequence}`;
    const value = `ready-${probeSequence}`;
    target.setItem(key, value);
    if (target.getItem(key) !== value) throw new Error("Storage check could not be read back.");
    target.removeItem(key);
    reportDemoStorageSuccess("check");
    return true;
  } catch {
    if (target && key) {
      try { target.removeItem(key); } catch { /* Best-effort probe cleanup. */ }
    }
    reportDemoStorageFailure("check");
    return false;
  }
}

export function writeDemoSessionValue(
  storageKey: string,
  value: unknown,
  storage?: DemoSessionStorageLike,
): boolean {
  try {
    const target = getStorage(storage);
    const serialized = JSON.stringify(value);
    target.setItem(storageKey, serialized);
    if (target.getItem(storageKey) !== serialized) throw new Error("Storage write could not be verified.");
    reportDemoStorageSuccess("write");
    return true;
  } catch {
    reportDemoStorageFailure("write");
    return false;
  }
}

export function readDemoSessionValue(
  storageKey: string,
  storage?: DemoSessionStorageLike,
): { ok: true; value: string | null } | { ok: false; value: null } {
  try {
    return { ok: true, value: getStorage(storage).getItem(storageKey) };
  } catch {
    reportDemoStorageFailure("read");
    return { ok: false, value: null };
  }
}

/**
 * Persist a local Save checkpoint before the UI acknowledges it. If any write
 * fails, restore the old keys where possible and return false so callers keep
 * their values staged instead of showing a successful Save.
 */
export function persistDemoSessionBatch(
  projectId: string,
  entries: readonly DemoSessionWrite[],
  mode: "reference" | "working-copy" = "working-copy",
  storage?: DemoSessionStorageLike,
): boolean {
  if (mode === "reference") {
    reportDemoStorageFailure("write");
    return false;
  }

  let target: DemoSessionStorageLike | undefined;
  let prior: Array<[string, string | null]> = [];
  try {
    target = getStorage(storage);
    const prefix = demoSessionStoragePrefix(projectId, mode);
    const writes = entries.map(([key, value]) => [prefix + key, JSON.stringify(value)] as const);
    prior = writes.map(([key]) => [key, target!.getItem(key)]);
    for (const [key, value] of writes) target.setItem(key, value);
    for (const [key, value] of writes) {
      if (target.getItem(key) !== value) throw new Error("Storage write could not be verified.");
    }
    reportDemoStorageSuccess("write");
    return true;
  } catch {
    if (target) {
      for (const [key, oldValue] of prior.reverse()) {
        try {
          if (oldValue === null) target.removeItem(key);
          else target.setItem(key, oldValue);
        } catch {
          // The failed operation is reported below; rollback is best-effort.
        }
      }
    }
    reportDemoStorageFailure("write");
    return false;
  }
}

export function resetDemoStorageSnapshotForTests() {
  snapshot = { state: "checking", operation: null };
  listeners.clear();
}

export type { DemoDraftStorage };
