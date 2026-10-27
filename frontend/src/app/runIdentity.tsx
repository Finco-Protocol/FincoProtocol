// One presentation contract for a committed Run's identity (Results, Statements,
// Scenarios, Run History, Exports).
//
// The canonical snapshot id of a committed Run is its UTC commit instant with the
// separators removed, e.g. `20261027T004939.123456+0000` (see run_service).  Showing
// only its first 12 characters (`20261027T004`) is the same for every Run committed
// within the same ten minutes, so the identity is formatted instead of truncated:
// the human-readable commit time to the second plus the canonical sub-second part as
// a stable distinguishing suffix.  Nothing is generated or guessed: both parts are
// read from the canonical identifier, the full identifier (and the history id when
// the surface has it) stays one click away, and an identifier that does not follow
// the canonical shape is shown verbatim and never shortened.

import { useState } from "react";

const SNAPSHOT_SHAPE = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{4})?$/;
// Protected reference Runs are stamped `canonical_last_run__<template>__<UTC time with microseconds, no separators>Z`.
const REFERENCE_SHAPE = /^canonical_last_run__[A-Za-z0-9_]+__(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(\d{1,9})?Z$/;

export interface ParsedRunIdentity {
  /** `2026-10-27 00:49:39 UTC` (the zone is the one the identifier states). */
  label: string;
  /** Canonical sub-second digits (`123456`), or "" when the identifier has none. */
  suffix: string;
  /** ISO-8601 instant for the `<time>` element. */
  iso: string;
}

/** Parses the canonical snapshot id; null when it does not have the canonical shape. */
export function parseRunSnapshotId(snapshotId: string | null | undefined): ParsedRunIdentity | null {
  const text = (snapshotId ?? "").trim();
  const reference = REFERENCE_SHAPE.exec(text);
  const match = reference ?? SNAPSHOT_SHAPE.exec(text);
  if (!match) return null;
  const [, y, mo, d, h, mi, s, fraction = "", zone = reference ? "Z" : ""] = match;
  const calendar = new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s)));
  if (calendar.getUTCFullYear() !== Number(y) || calendar.getUTCMonth() !== Number(mo) - 1 || calendar.getUTCDate() !== Number(d)
    || Number(h) > 23 || Number(mi) > 59 || Number(s) > 59) return null;
  const utc = zone === "" || zone === "Z" || zone === "+0000" || zone === "-0000";
  const zoneText = utc ? "UTC" : `UTC${zone.slice(0, 3)}:${zone.slice(3)}`;
  const isoZone = utc ? "Z" : `${zone.slice(0, 3)}:${zone.slice(3)}`;
  return {
    label: `${y}-${mo}-${d} ${h}:${mi}:${s} ${zoneText}`,
    suffix: fraction,
    iso: `${y}-${mo}-${d}T${h}:${mi}:${s}${fraction ? `.${fraction}` : ""}${isoZone}`,
  };
}

/** Plain-text form of the same contract (tables, accessible names, exports). */
export function runIdentityText(snapshotId: string | null | undefined): string {
  const id = (snapshotId ?? "").trim();
  if (!id) return "No saved Run";
  const parsed = parseRunSnapshotId(id);
  return parsed ? `${parsed.label}${parsed.suffix ? ` · ${parsed.suffix}` : ""}` : id;
}

function CopyButton({ value, what }: { value: string; what: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button type="button" className="rx-run-copy" aria-label={`Copy ${what}`}
      onClick={() => {
        const done = () => { setCopied(true); window.setTimeout(() => setCopied(false), 1500); };
        try {
          void navigator.clipboard?.writeText(value).then(done, () => undefined);
        } catch { /* clipboard unavailable: the identifier stays selectable in the details */ }
      }}>
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

interface RunIdentityProps {
  /** Canonical `runtime_snapshot_id` of the committed Run. */
  snapshotId: string | null | undefined;
  /** Canonical Run History id, when the surface has it. */
  historyId?: string | null;
  /** Optional canonical `ran_at` text, only used when the snapshot id is not parseable. */
  ranAt?: string | null;
}

/**
 * The Run identity of one committed Run.  Renders nothing invented: an empty
 * snapshot id is "No saved Run".
 */
export function RunIdentityLabel({ snapshotId, historyId, ranAt }: RunIdentityProps) {
  const id = (snapshotId ?? "").trim();
  if (!id) return <span className="rx-run-id" data-run-identity="">No saved Run</span>;
  const parsed = parseRunSnapshotId(id);
  const history = (historyId ?? "").trim();
  return (
    <span className="rx-run-id" data-run-identity={id} data-run-history-id={history || undefined}>
      {parsed ? (
        <>
          <time dateTime={parsed.iso} className="rx-run-time">{parsed.label}</time>
          {parsed.suffix && <>{" "}<span className="rx-run-suffix" title="Sub-second part of the Run identifier">· {parsed.suffix}</span></>}
        </>
      ) : (
        <code className="rx-run-raw">{id}</code>
      )}
      {" "}
      <details className="rx-run-details">
        <summary aria-label={`Full Run identifier for ${runIdentityText(id)}`}>ID</summary>
        <span className="rx-run-full">
          <span>Snapshot <code data-run-full-snapshot={id}>{id}</code> <CopyButton value={id} what="the full snapshot identifier" /></span>
          {history && <span>History <code data-run-full-history={history}>{history}</code> <CopyButton value={history} what="the Run History identifier" /></span>}
          {!parsed && ranAt && <span>Ran {ranAt}</span>}
        </span>
      </details>
    </span>
  );
}
