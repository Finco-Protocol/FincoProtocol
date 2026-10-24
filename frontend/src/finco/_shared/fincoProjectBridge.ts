// Production-safe bridge for the OPTIONAL local working-copy session features of
// the harvested design components (UX-02 quarantine seam).
//
// The harvested `FincoShell.readProjectContext` / `ProjectLibrary` originally
// imported the demo session modules directly, which would pull demo state into
// any production bundle that renders them.  The dependency is now inverted: the
// components call THIS neutral bridge, and only the isolated transfer harness
// (frontend/transfer) installs the demo implementation.  Production simply never
// installs one — the components then behave as "no local session copies".

export type FincoWorkingCopySummary = {
  id: string;
  name: string;
  technology: string;
  size: string;
  region: string;
  /** Demo-harness discriminator ("reference-copy" | "new-demo-project"); unused in production. */
  kind?: string;
  parentReferenceId?: string | null;
  parentReferenceName?: string | null;
  registeredWorkingCopy?: boolean;
};

export type FincoWorkingCopyBridge = {
  list: () => FincoWorkingCopySummary[];
  read: (id: string) => FincoWorkingCopySummary | undefined;
  create: (project: {
    id: string;
    name: string;
    technology: string;
    size: string;
    region: string;
    templateSource?: string;
  }) => FincoWorkingCopySummary;
  /** Demo-harness only: create a blank local project.  Production never installs it. */
  createBlank?: (seed: { name: string; technology: string; size: string; region: string; sponsor: string }) => FincoWorkingCopySummary;
  clear: () => void;
};

let bridge: FincoWorkingCopyBridge | undefined;

export function setFincoWorkingCopyBridge(value: FincoWorkingCopyBridge | undefined): void {
  bridge = value;
}

export function fincoWorkingCopyBridge(): FincoWorkingCopyBridge | undefined {
  return bridge;
}
