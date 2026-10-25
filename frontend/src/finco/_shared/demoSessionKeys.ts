export const DEMO_SESSION_PREFIX = "finco-design-demo:v2:";
export const LEGACY_SESSION_PREFIX = "finco-design-demo:v1:";
export const DEMO_WORKING_COPIES_KEY = "finco-demo-working-copies:v1";
export const demoLastRunStorageKey = (projectId: string) =>
  `${DEMO_SESSION_PREFIX}last-run:${encodeURIComponent(projectId)}`;

export function demoSessionStorageScope(projectId: string, mode: "reference" | "working-copy" = "working-copy"): string {
  const identity = mode === "reference" ? `reference:${projectId}` : projectId;
  return encodeURIComponent(identity);
}

export function demoSessionStoragePrefix(projectId: string, mode: "reference" | "working-copy" = "working-copy"): string {
  return `${DEMO_SESSION_PREFIX}${demoSessionStorageScope(projectId, mode)}:`;
}

export interface DemoDraftStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export type DemoLastRunReference = {
  runId: "DEMO-FIXED-018";
  scenarioId: "base" | "downside" | "upside";
  freshness: "CURRENT_DEMO_SNAPSHOT";
};

export function saveDemoLastRunReference(
  storage: DemoDraftStorage,
  projectId: string,
  context: DemoLastRunReference,
): void {
  const key = demoLastRunStorageKey(projectId);
  const serialized = JSON.stringify(context);
  storage.setItem(key, serialized);
  if (storage.getItem(key) !== serialized) {
    throw new Error("The local demo result selection could not be confirmed in this browser tab.");
  }
}

export function readDemoLastRunReference(
  storage: DemoDraftStorage,
  projectId: string,
): DemoLastRunReference | null {
  try {
    const serialized = storage.getItem(demoLastRunStorageKey(projectId));
    if (!serialized) return null;
    const parsed = JSON.parse(serialized) as Partial<DemoLastRunReference>;
    if (parsed.runId !== "DEMO-FIXED-018" || parsed.freshness !== "CURRENT_DEMO_SNAPSHOT") return null;
    if (!["base", "downside", "upside"].includes(parsed.scenarioId || "")) return null;
    return parsed as DemoLastRunReference;
  } catch {
    return null;
  }
}

const draftSavePairs = [
  ["scalar-draft", "scalar-saved"],
  ["cost-line-draft", "cost-line-saved"],
  ["ppa-contract-drafts", "ppa-contract-saved"],
  ["facility-drafts", "facility-saved"],
  ["timeline-draft", "timeline-saved"],
  ["tax-draft", "tax-saved"],
  ["scenario-drafts", "scenario-saved"],
] as const;

/**
 * Discard only the unsaved draft values in one project scope. The last local
 * save checkpoints, other projects, the working-copy registry, and fixed
 * illustrative results are deliberately left untouched.
 */
export function discardDemoDraftsToLastSave(
  storage: DemoDraftStorage,
  projectId: string,
  mode: "reference" | "working-copy" = "working-copy",
): string[] {
  const prefix = demoSessionStoragePrefix(projectId, mode);
  const restored: string[] = [];
  const changes = draftSavePairs.map(([draftKey, savedKey]) => {
    const draftStorageKey = `${prefix}${draftKey}`;
    return {
      draftKey,
      draftStorageKey,
      previous: storage.getItem(draftStorageKey),
      next: storage.getItem(`${prefix}${savedKey}`),
    };
  });
  const applied: typeof changes = [];
  try {
    for (const change of changes) {
      if (change.next === null) storage.removeItem(change.draftStorageKey);
      else storage.setItem(change.draftStorageKey, change.next);
      applied.push(change);
    }
  } catch (error) {
    for (const change of applied.reverse()) {
      try {
        if (change.previous === null) storage.removeItem(change.draftStorageKey);
        else storage.setItem(change.draftStorageKey, change.previous);
      } catch {
        // Preserve the original storage error; the caller keeps the draft open.
      }
    }
    throw error;
  }
  changes.forEach(change => restored.push(change.draftKey));
  return restored;
}
