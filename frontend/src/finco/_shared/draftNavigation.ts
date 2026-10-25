export type DraftNavigationReason = "project" | "reference" | "scenario" | null;

export const FINCO_DRAFT_HISTORY_INDEX = "__fincoDraftHistoryIndex";

export function classifyDraftNavigation(currentHref: string, targetHref: string): DraftNavigationReason {
  let current: URL;
  let target: URL;
  try {
    current = new URL(currentHref);
    target = new URL(targetHref, current);
  } catch {
    return null;
  }
  if (current.origin !== target.origin) return null;
  if (/\/ProjectLibrary\/?$/i.test(target.pathname)) return "project";

  const currentMode = current.searchParams.get("mode") || "working-copy";
  const targetMode = target.searchParams.get("mode") || "working-copy";
  if (targetMode === "reference" && currentMode !== "reference") return "reference";

  const currentProject = current.searchParams.get("projectId") || "PRJ-0241";
  const targetProject = target.searchParams.get("projectId") || "PRJ-0241";
  if (targetProject !== currentProject || targetMode !== currentMode) return "project";

  const currentScenario = current.searchParams.get("scenario") || "base";
  const targetScenario = target.searchParams.get("scenario") || "base";
  if (targetScenario !== currentScenario) return "scenario";
  return null;
}

export function withDraftHistoryIndex(state: unknown, index: number): Record<string, unknown> {
  const preserved = state && typeof state === "object" && !Array.isArray(state)
    ? state as Record<string, unknown>
    : state === null || state === undefined
      ? {}
      : { __fincoOriginalHistoryState: state };
  return { ...preserved, [FINCO_DRAFT_HISTORY_INDEX]: index };
}

export function readDraftHistoryIndex(state: unknown): number | null {
  if (!state || typeof state !== "object") return null;
  const index = (state as Record<string, unknown>)[FINCO_DRAFT_HISTORY_INDEX];
  return typeof index === "number" && Number.isInteger(index) && index >= 0 ? index : null;
}
