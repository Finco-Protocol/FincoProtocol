import type { ReactNode } from "react";

/** Read-only integration boundary. WS2 owns staging and persistence, WS1 owns the shell. */
/** Structural subset of PR #397's PendingEdit, not a second staging authority. */
export interface PendingChangeSummary {
  id: string;
  section: "inputs" | "ppa" | "capex" | "opex" | "financing";
  key: string;
  label: string;
  unit: string;
  baseline: string;
  value: string;
  canonical?: string;
  error?: string;
}

/** Structurally identical to WS2 EditIdentity at cc48391b. */
export interface WorkspaceEditIdentity {
  projectId: string;
  workbookVersion: string;
  contentHash: string;
  activeScenario: string | null;
  lastRunSnapshotId: string | null;
}

export interface WorkspaceExtensionContext extends WorkspaceEditIdentity {
  activeScenarioName: string | null;
  pendingChanges: readonly PendingChangeSummary[];
  validation: readonly { path: string; message: string }[];
  draftState: "clean" | "dirty" | "conflict" | "unknown";
  onCommitted: () => void;
  onRefetch: () => Promise<void>;
}

export interface WorkspaceExtensions {
  /** WS2 can mount its provider once around this content after reviewed integration. */
  wrapWorkspace?: (context: WorkspaceExtensionContext, content: ReactNode) => ReactNode;
  /** Supply from WS2's provider. Never invent a shell-level pending-edit store. */
  renderChanges?: (context: WorkspaceExtensionContext) => ReactNode;
  pendingChanges?: readonly PendingChangeSummary[];
  validation?: WorkspaceExtensionContext["validation"];
  draftState?: WorkspaceExtensionContext["draftState"];
}

export interface ConfirmedRun {
  historyId: string;
  snapshotId: string;
  runIntentId: string;
}

export function WorkspaceExtensionBoundary({ extensions, context, children }: {
  extensions?: WorkspaceExtensions; context: WorkspaceExtensionContext; children: ReactNode;
}) {
  return extensions?.wrapWorkspace ? extensions.wrapWorkspace(context, children) : children;
}
