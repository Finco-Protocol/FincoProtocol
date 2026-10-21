import React, { Suspense, lazy, useState } from "react";

type FincoRoute = "library" | "workspace" | "results";

const routes: { id: FincoRoute; label: string; component: React.LazyExoticComponent<React.ComponentType> }[] = [
  { id: "library", label: "Project Library", component: lazy(async () => ({ default: (await import("../ProjectLibrary")).ProjectLibrary })) },
  { id: "workspace", label: "Model Workspace", component: lazy(async () => ({ default: (await import("../ModelWorkspace")).ModelWorkspace })) },
  { id: "results", label: "Results & Analysis", component: lazy(async () => ({ default: (await import("../ResultsAnalysis")).ResultsAnalysis })) },
];

/**
 * Internal composition proof: the three existing pages can be composed under
 * one React root without cloning their UI or adding a Canvas frame.
 */
export default function FincoApplicationComposition() {
  const [route, setRoute] = useState<FincoRoute>("library");
  const active = routes.find((item) => item.id === route) || routes[0];
  const Page = active.component;

  return <div data-testid="finco-react-composition">
    <nav aria-label="FINCO application route proof" style={{ display: "flex", gap: 8, padding: 12, background: "#f5f7fa" }}>
      {routes.map((item) => <button
        key={item.id}
        type="button"
        aria-pressed={route === item.id}
        onClick={() => setRoute(item.id)}
      >{item.label}</button>)}
    </nav>
    <Suspense fallback={<div role="status" style={{ padding: 24 }}>Loading selected FINCO demo view…</div>}>
      <Page />
    </Suspense>
  </div>;
}
