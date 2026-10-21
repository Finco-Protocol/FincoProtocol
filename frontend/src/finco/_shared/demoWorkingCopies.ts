import {
  DEMO_SESSION_PREFIX,
  DEMO_WORKING_COPIES_KEY,
  demoSessionStoragePrefix,
} from "./demoSessionKeys.ts";

export type DemoProjectSeed = {
  id: string;
  name: string;
  technology: string;
  size: string;
  region: string;
  sponsor: string;
};

export type DemoWorkingCopy = DemoProjectSeed & {
  parentReferenceId: string | null;
  parentReferenceName: string | null;
  kind: "reference-copy" | "new-demo-project";
  note: "Demo only — not persisted";
};

export interface DemoSessionStorage {
  readonly length: number;
  key(index: number): string | null;
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

const draftToSavedPairs = [
  ["scalar-draft", "scalar-saved"],
  ["cost-line-draft", "cost-line-saved"],
  ["ppa-contract-drafts", "ppa-contract-saved"],
  ["facility-drafts", "facility-saved"],
  ["timeline-draft", "timeline-saved"],
  ["tax-draft", "tax-saved"],
  ["scenario-drafts", "scenario-saved"],
] as const;

const resetAcknowledgementKeys = [
  "scalar-save-acknowledged",
  "module-save-acknowledged",
  "cost-line-save-ack",
  "period-line-save-acknowledgements",
] as const;

function browserSessionStorage(): DemoSessionStorage {
  if (typeof window === "undefined") {
    throw new Error("Demo working copies require this browser tab's session storage.");
  }
  return window.sessionStorage;
}

function uniqueName(base: string, existing: DemoWorkingCopy[]): string {
  const names = new Set(existing.map(copy => copy.name));
  if (!names.has(base)) return base;
  let suffix = 2;
  while (names.has(`${base} (${suffix})`)) suffix += 1;
  return `${base} (${suffix})`;
}

function readCopies(storage: DemoSessionStorage): DemoWorkingCopy[] {
  const serialized = storage.getItem(DEMO_WORKING_COPIES_KEY);
  if (!serialized) return [];
  const parsed: unknown = JSON.parse(serialized);
  if (!Array.isArray(parsed)) throw new Error("The local demo-copy registry is malformed; reset this browser-tab demo session.");
  return parsed.filter((item): item is DemoWorkingCopy =>
    Boolean(item) &&
    typeof item === "object" &&
    typeof (item as DemoWorkingCopy).id === "string" &&
    typeof (item as DemoWorkingCopy).name === "string" &&
    ((item as DemoWorkingCopy).kind === "reference-copy" || (item as DemoWorkingCopy).kind === "new-demo-project")
  );
}

export function listDemoWorkingCopies(storage: DemoSessionStorage = browserSessionStorage()): DemoWorkingCopy[] {
  return readCopies(storage);
}

export function getDemoWorkingCopy(id: string, storage: DemoSessionStorage = browserSessionStorage()): DemoWorkingCopy | undefined {
  return readCopies(storage).find(copy => copy.id === id);
}

function removeScope(storage: DemoSessionStorage, projectId: string): void {
  const prefix = demoSessionStoragePrefix(projectId);
  const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index))
    .filter((key): key is string => Boolean(key && key.startsWith(prefix)));
  keys.forEach(key => storage.removeItem(key));
}

function cloneReferenceDemoState(
  storage: DemoSessionStorage,
  referenceId: string,
  copyId: string,
): void {
  const sourcePrefix = demoSessionStoragePrefix(referenceId, "reference");
  const targetPrefix = demoSessionStoragePrefix(copyId, "working-copy");
  const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index))
    .filter((key): key is string => Boolean(key && key.startsWith(sourcePrefix)));
  const entries = keys.map(key => [key.slice(sourcePrefix.length), storage.getItem(key)] as const)
    .filter((entry): entry is readonly [string, string] => entry[1] !== null)
    .filter(([key]) => !resetAcknowledgementKeys.includes(key as typeof resetAcknowledgementKeys[number]));

  entries.forEach(([key, value]) => storage.setItem(`${targetPrefix}${key}`, value));

  // A copy starts clean: the visible reference draft becomes its local baseline.
  for (const [draftKey, savedKey] of draftToSavedPairs) {
    const draft = storage.getItem(`${sourcePrefix}${draftKey}`);
    if (draft !== null) {
      storage.setItem(`${targetPrefix}${draftKey}`, draft);
      storage.setItem(`${targetPrefix}${savedKey}`, draft);
    }
  }
  for (const key of resetAcknowledgementKeys) {
    const initial = key === "period-line-save-acknowledgements" || key === "cost-line-save-ack"
      ? { capex: false, opex: false }
      : false;
    storage.setItem(`${targetPrefix}${key}`, JSON.stringify(initial));
  }
}

function saveRecord(storage: DemoSessionStorage, record: DemoWorkingCopy): void {
  const copies = readCopies(storage);
  storage.setItem(DEMO_WORKING_COPIES_KEY, JSON.stringify([...copies, record]));
}

function createId(storage: DemoSessionStorage, parentId: string | null, kind: DemoWorkingCopy["kind"]): string {
  const copies = readCopies(storage);
  const ordinal = copies.filter(copy =>
    copy.parentReferenceId === parentId && copy.kind === kind
  ).length + 1;
  const prefix = kind === "reference-copy" ? `DEMO-WC-${parentId}` : "DEMO-LOCAL";
  let candidate = `${prefix}-${String(ordinal).padStart(2, "0")}`;
  let next = ordinal + 1;
  while (copies.some(copy => copy.id === candidate)) {
    candidate = `${prefix}-${String(next).padStart(2, "0")}`;
    next += 1;
  }
  return candidate;
}

export function createDemoWorkingCopy(
  reference: DemoProjectSeed,
  storage: DemoSessionStorage = browserSessionStorage(),
): DemoWorkingCopy {
  const existing = readCopies(storage);
  const id = createId(storage, reference.id, "reference-copy");
  const record: DemoWorkingCopy = {
    ...reference,
    id,
    name: uniqueName(`${reference.name} — Working copy`, existing),
    parentReferenceId: reference.id,
    parentReferenceName: reference.name,
    kind: "reference-copy",
    note: "Demo only — not persisted",
  };
  try {
    cloneReferenceDemoState(storage, reference.id, id);
    saveRecord(storage, record);
  } catch (error) {
    removeScope(storage, id);
    throw new Error(`Could not create a local working copy in this browser tab: ${error instanceof Error ? error.message : "session storage is unavailable"}`);
  }
  return record;
}

export function createLocalDemoProject(
  project: Omit<DemoProjectSeed, "id">,
  storage: DemoSessionStorage = browserSessionStorage(),
): DemoWorkingCopy {
  const existing = readCopies(storage);
  const id = createId(storage, null, "new-demo-project");
  const record: DemoWorkingCopy = {
    ...project,
    id,
    name: uniqueName(project.name, existing),
    parentReferenceId: null,
    parentReferenceName: null,
    kind: "new-demo-project",
    note: "Demo only — not persisted",
  };
  saveRecord(storage, record);
  return record;
}

export function isDemoWorkingCopyId(id: string): boolean {
  return id.startsWith("DEMO-WC-") || id.startsWith("DEMO-LOCAL-");
}

export function demoSessionPrefixForWorkingCopy(id: string): string {
  return `${DEMO_SESSION_PREFIX}${encodeURIComponent(id)}:`;
}
