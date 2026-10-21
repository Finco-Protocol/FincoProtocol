import type { FreshnessProjection, OutputsProjection } from "../api/types";

// Presentation of the canonical Run status.  The four dimensions (input
// freshness, Run Integrity, engine currency, run context) are independent
// server facts (SC-03) and are displayed independently — none is derived from
// another here.

const FRESHNESS_LABEL: Record<string, string> = {
  NOT_RUN: "NOT RUN",
  CURRENT: "CURRENT",
  STALE: "STALE",
};

export function FreshnessBadge({ freshness }: { freshness: FreshnessProjection }) {
  const cls =
    freshness.state === "CURRENT" ? "rx-badge rx-badge-ok"
    : freshness.state === "STALE" ? "rx-badge rx-badge-stale"
    : "rx-badge";
  const title =
    freshness.state === "NOT_RUN"
      ? "This project has no persisted Run."
      : freshness.state === "CURRENT"
        ? "The persisted Last Run matches the current Working Copy inputs."
        : "The Working Copy changed after the persisted Last Run; a new Run would calculate different economics.";
  return (
    <span className={cls} data-freshness={freshness.state} title={title}>
      {FRESHNESS_LABEL[freshness.state] ?? freshness.state}
    </span>
  );
}

export function IntegrityBadge({ outputs }: { outputs: OutputsProjection }) {
  const status = outputs.integrity.status;
  const cls =
    status === "PASS" ? "rx-badge rx-badge-ok"
    : status === "FAIL" ? "rx-badge rx-badge-stale"
    : "rx-badge";
  return (
    <span className={cls} data-integrity={status} title="Independent Run Integrity verdict committed with this Run.">
      Integrity: {status}
    </span>
  );
}

export function EngineBadge({ outputs }: { outputs: OutputsProjection }) {
  const dim = outputs.status_dimensions;
  if (!dim) return null;
  const currency = dim.engine_currency;
  const title =
    `Engine identity source: ${dim.engine_identity_source} (${dim.engine_reason}). ` +
    `Persisted engine version: ${dim.engine_persisted_version ?? "unavailable"}; ` +
    `current engine version: ${dim.engine_current_version ?? "unavailable"}.`;
  return (
    <span className="rx-badge" data-engine-currency={currency} title={title}>
      Engine: {currency === "CURRENT_ENGINE" ? "current" : currency === "ENGINE_SUPERSEDED" ? "superseded" : "identity unknown"}
    </span>
  );
}

export function RunIdentityLine({ outputs }: { outputs: OutputsProjection }) {
  if (outputs.state === "NOT_RUN" || !outputs.identity) {
    return (
      <p className="rx-run-identity" data-run-state="NOT_RUN">
        No persisted Run. The React PoC never runs the model — use the legacy workbook
        link above to run it.
      </p>
    );
  }
  const identity = outputs.identity;
  return (
    <p className="rx-run-identity" data-run-state={outputs.state}>
      Last Run: snapshot <code>{identity.snapshot_id.slice(0, 12)}</code>
      {" · "}ran {identity.ran_at || "unavailable"}
      {" · "}scenario {identity.scenario_proven ? identity.scenario : "UNAVAILABLE"}
    </p>
  );
}
