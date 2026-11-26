/** One canonical route and navigation source of truth for the unified React application. */

export const APP_ROUTES = {
  library: "/v2/model-react/",
  newProject: "/v2/model-react/#new-project",
  newProjectTemplate: "/v2/model-react/#new-project/template",
  compareProjects: "/v2/model-react/#compare-projects",
  guide: "/v2/model-react/#guide",
  platform: "/v2/model-react/#platform",
  account: "/v2/model-react/#account",
} as const;

export function projectRoute(code: string, hash = ""): string {
  const base = `/v2/model-react/${encodeURIComponent(code)}`;
  return hash ? `${base}#${hash.replace(/^#/, "")}` : base;
}

export type TopAppRoute =
  | "library"
  | "new-project"
  | "compare-projects"
  | "guide"
  | "platform"
  | "account";

export function parseAppHash(hash: string): TopAppRoute {
  const clean = (hash || "").replace(/^#/, "");
  if (clean === "new-project" || clean.startsWith("new-project/")) return "new-project";
  if (clean === "compare-projects") return "compare-projects";
  if (clean === "guide" || clean === "help" || clean === "methodology" || clean === "known-limitations") return "guide";
  if (clean === "platform" || clean === "api" || clean === "verify") return "platform";
  if (clean === "account") return "account";
  return "library";
}
