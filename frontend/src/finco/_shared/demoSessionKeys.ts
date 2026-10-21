export const DEMO_SESSION_PREFIX = "finco-design-demo:v2:";
export const LEGACY_SESSION_PREFIX = "finco-design-demo:v1:";
export const DEMO_WORKING_COPIES_KEY = "finco-demo-working-copies:v1";

export function demoSessionStorageScope(projectId: string, mode: "reference" | "working-copy" = "working-copy"): string {
  const identity = mode === "reference" ? `reference:${projectId}` : projectId;
  return encodeURIComponent(identity);
}

export function demoSessionStoragePrefix(projectId: string, mode: "reference" | "working-copy" = "working-copy"): string {
  return `${DEMO_SESSION_PREFIX}${demoSessionStorageScope(projectId, mode)}:`;
}
