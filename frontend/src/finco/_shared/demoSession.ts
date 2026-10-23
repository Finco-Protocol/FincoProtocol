import { useEffect, useState, useSyncExternalStore, type Dispatch, type SetStateAction } from "react";
import { DEMO_SESSION_PREFIX, DEMO_WORKING_COPIES_KEY, LEGACY_SESSION_PREFIX, demoSessionStorageScope } from "./demoSessionKeys";
import {
  getDemoStorageSnapshot,
  persistDemoSessionBatch,
  probeDemoSessionStorage,
  readDemoSessionValue,
  reportDemoStorageFailure,
  reportDemoStorageSuccess,
  subscribeDemoStorage,
  writeDemoSessionValue,
  type DemoSessionWrite,
} from "./demoSessionStorage";

export { DEMO_SESSION_PREFIX, DEMO_WORKING_COPIES_KEY, demoSessionStoragePrefix } from "./demoSessionKeys";
export {
  persistDemoSessionBatch,
  probeDemoSessionStorage,
  reportDemoStorageFailure,
  reportDemoStorageSuccess,
} from "./demoSessionStorage";

export function useDemoSessionStorageHealth() {
  return useSyncExternalStore(subscribeDemoStorage, getDemoStorageSnapshot, getDemoStorageSnapshot);
}

export function persistCurrentDemoSessionBatch(entries: readonly DemoSessionWrite[]): boolean {
  if (typeof window === "undefined") {
    reportDemoStorageFailure("write");
    return false;
  }
  const params = new URLSearchParams(window.location.search);
  const projectId = params.get("projectId")?.trim() || "PRJ-0241";
  const mode = params.get("mode") === "reference" ? "reference" : "working-copy";
  return persistDemoSessionBatch(projectId, entries, mode);
}

function currentProjectScope(): string {
  const projectId = new URLSearchParams(window.location.search).get("projectId")?.trim();
  const mode = new URLSearchParams(window.location.search).get("mode");
  return demoSessionStorageScope(projectId || "PRJ-0241", mode === "reference" ? "reference" : "working-copy");
}

export function useDemoSessionState<T>(
  key: string,
  initialValue: T,
): [T, Dispatch<SetStateAction<T>>] {
  // Project identity is navigation context, not proof of a separate model.
  // It does scope local drafts so switching sample projects cannot leak edits.
  const storageKey = `${DEMO_SESSION_PREFIX}${currentProjectScope()}:${key}`;
  const [value, setValue] = useState<T>(() => {
    const result = readDemoSessionValue(storageKey);
    if (!result.ok || result.value === null) return initialValue;
    try { return JSON.parse(result.value) as T; } catch { return initialValue; }
  });

  useEffect(() => {
    writeDemoSessionValue(storageKey, value);
  }, [storageKey, value]);

  return [value, setValue];
}

export function clearDemoSessionState(): void {
  try {
    const keys = Object.keys(window.sessionStorage).filter(key =>
      key.startsWith(DEMO_SESSION_PREFIX) ||
      key.startsWith(LEGACY_SESSION_PREFIX) ||
      key === DEMO_WORKING_COPIES_KEY
    );
    keys.forEach(key => window.sessionStorage.removeItem(key));
    reportDemoStorageSuccess("clear");
  } catch {
    reportDemoStorageFailure("clear");
  }
}
