import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { DEMO_SESSION_PREFIX, DEMO_WORKING_COPIES_KEY, LEGACY_SESSION_PREFIX, demoSessionStorageScope } from "./demoSessionKeys";

export { DEMO_SESSION_PREFIX, DEMO_WORKING_COPIES_KEY, demoSessionStoragePrefix } from "./demoSessionKeys";

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
    try {
      const stored = window.sessionStorage.getItem(storageKey);
      return stored === null ? initialValue : (JSON.parse(stored) as T);
    } catch {
      return initialValue;
    }
  });

  useEffect(() => {
    try {
      window.sessionStorage.setItem(storageKey, JSON.stringify(value));
    } catch {
      // This remains a local in-memory demo if browser storage is unavailable.
    }
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
  } catch {
    // The reset is best-effort when browser storage is blocked.
  }
}
