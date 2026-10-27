// What the project's vertical is released for.  Text comes from the canonical
// product-capability registry carried by the workspace payload (status, runnable, limitations);
// only the pilot-tier wording is fixed copy.  Presentation only.

import type { VerticalScope } from "./types";

const TIER_TEXT: Record<VerticalScope["pilot_tier"], { badge: string; lead: (name: string) => string }> = {
  PILOT_CANDIDATE: {
    badge: "PILOT CANDIDATE",
    lead: (name) => `${name} is one of the two institutional pilot candidate verticals.`,
  },
  PREVIEW: {
    badge: "PREVIEW VERTICAL",
    lead: (name) => `${name} is a preview. It runs on the shared model engine through a vertical adapter, and its validation coverage is narrower than Solar and Wind. Treat results as exploratory, not as a validated full-vertical financial model.`,
  },
  RELEASE_CLOSED: {
    badge: "RELEASE CLOSED",
    lead: (name) => `${name} is not released for Working Copy Runs.`,
  },
  UNCLASSIFIED: { badge: "SCOPE UNCONFIRMED", lead: () => "The release scope of this project type could not be confirmed. Do not rely on its results for a pilot." },
};

export function VerticalScopeBanner({ vertical }: { vertical?: VerticalScope }) {
  if (!vertical) return null;
  const tier = TIER_TEXT[vertical.pilot_tier] ?? TIER_TEXT.UNCLASSIFIED;
  const name = vertical.public_name || "This vertical";
  return (
    <div className={`rx-vertical rx-vertical-${vertical.pilot_tier.toLowerCase().replace(/_/g, "-")}`} role="note"
      data-vertical={vertical.key || "unknown"} data-pilot-tier={vertical.pilot_tier}>
      <span className="rx-badge">{tier.badge}</span>{" "}
      <span>{tier.lead(name)}</span>
      {vertical.status_note && vertical.pilot_tier !== "PILOT_CANDIDATE" && <span> {vertical.status_note}</span>}
      {vertical.limitations.length > 0 && (
        <details className="rx-vertical-limits">
          <summary>Known limitations</summary>
          <ul>{vertical.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        </details>
      )}
    </div>
  );
}
