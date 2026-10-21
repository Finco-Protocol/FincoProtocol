export type FincoPageId = "library" | "workspace" | "results";

export type FincoRoute =
  | { page: "library"; projectId: string | null; pathname: string; search: string; hash: string }
  | { page: "workspace"; projectId: string; pathname: string; search: string; hash: string }
  | { page: "results"; projectId: string; pathname: string; search: string; hash: string }
  | { page: "not-found"; projectId: string | null; pathname: string; search: string; hash: string };

export const FINCO_ROUTE_CONFIG = [
  { id: "library", path: "/projects", component: "ProjectLibrary" },
  { id: "workspace", path: "/projects/:projectId/workbook", component: "ModelWorkspace" },
  { id: "results", path: "/projects/:projectId/results", component: "ResultsAnalysis" },
] as const;

const LEGACY_PAGE_PATHS: Record<string, FincoPageId> = {
  ProjectLibrary: "library",
  ModelWorkspace: "workspace",
  ResultsAnalysis: "results",
};

function stripBase(pathname: string, basePath: string): string | null {
  const base = basePath.endsWith("/") ? basePath : `${basePath}/`;
  const baseWithoutSlash = base.slice(0, -1);
  if (pathname === baseWithoutSlash || pathname === base) return "/";
  if (!pathname.startsWith(base)) return null;
  return `/${pathname.slice(base.length)}` || "/";
}

export function resolveFincoRoute(
  pathname: string,
  search: string,
  basePath: string,
): FincoRoute {
  const localPath = stripBase(pathname, basePath);
  const params = new URLSearchParams(search);
  const projectIdFromQuery = params.get("projectId");

  if (localPath === null) {
    return { page: "not-found", projectId: projectIdFromQuery, pathname, search, hash: "" };
  }

  if (localPath === "/" || localPath === "/projects" || localPath === "/ProjectLibrary") {
    return { page: "library", projectId: projectIdFromQuery, pathname, search, hash: "" };
  }

  const legacy = localPath.match(/^\/(ModelWorkspace|ResultsAnalysis)$/);
  if (legacy) {
    const projectId = projectIdFromQuery || "PRJ-0241";
    return {
      page: LEGACY_PAGE_PATHS[legacy[1]] as "workspace" | "results",
      projectId,
      pathname,
      search,
      hash: "",
    };
  }

  const route = localPath.match(/^\/projects\/([^/]+)\/(workbook|results)$/);
  if (route) {
    const projectId = decodeURIComponent(route[1]);
    return {
      page: route[2] === "workbook" ? "workspace" : "results",
      projectId,
      pathname,
      search,
      hash: "",
    };
  }

  return { page: "not-found", projectId: projectIdFromQuery, pathname, search, hash: "" };
}

export function canonicalFincoHref(
  href: string,
  basePath: string,
  currentProjectId: string,
): string | null {
  const target = new URL(href, window.location.origin);
  const route = resolveFincoRoute(target.pathname, target.search, basePath);
  if (route.page === "not-found") return null;
  const base = basePath.endsWith("/") ? basePath : `${basePath}/`;
  if (route.page === "library") return `${base}projects${target.search}${target.hash}`;

  const projectId = route.projectId || currentProjectId;
  const query = new URLSearchParams(target.search);
  if (!query.has("projectId")) query.set("projectId", projectId);
  const suffix = route.page === "workspace" ? "workbook" : "results";
  return `${base}projects/${encodeURIComponent(projectId)}/${suffix}?${query.toString()}${target.hash}`;
}

export function contextFromRoute(route: FincoRoute, search: string) {
  const params = new URLSearchParams(search);
  return {
    projectId: route.projectId || params.get("projectId") || "PRJ-0241",
    projectName: params.get("project") || "Adriatic Solar I",
    technology: params.get("technology") || "Solar PV",
    mode: params.get("mode") === "reference" ? "reference" as const : "working-copy" as const,
    scenarioId: params.get("scenario") || "base",
    contractId: params.get("contract") || "PPA-A",
    facilityId: params.get("facility") || params.get("tranche") || "Senior A",
  };
}
