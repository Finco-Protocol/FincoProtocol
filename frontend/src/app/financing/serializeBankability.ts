// INPUT SERIALISATION ONLY — a line-for-line port of the Legacy editor (static/js/model_bankability.js).  Canonical validation and
// all economics are server-owned (`bankability_config.parse_config`); this file only turns typed form state into the JSON document
// the canonical per-field writer expects, and offers advisory range checks so obvious mistakes are caught before the round trip.
import type { BankabilityConfig, BankabilityPeriod, BankabilityView } from "./types";

export type TargetsMode = "inherit" | "scalar" | "periods";
export type RatesMode = "inherit" | "periods";
export type ReserveMode = "inherit" | "none" | "automatic_peak" | "cash_fixed" | "dsrf";

/** Financial Owner release boundary for the React input: only these reserve policies may be NEWLY selected and saved.
 *  Forward-looking coverage (`automatic_peak`) and the DSRF standby facility (`dsrf`) have no complete engine authority yet
 *  (commitment/arrangement fees, drawn interest, replenishment, hybrid cash/facility coverage are a later FIN-V2 workflow).
 *  A configuration that already stores one of them is shown read-only and written back byte-for-byte, never rewritten. */
export const RELEASED_RESERVE_MODES: readonly ReserveMode[] = ["inherit", "none", "cash_fixed"];
export const isReleasedReserveMode = (mode: string): boolean => (RELEASED_RESERVE_MODES as readonly string[]).includes(mode);
export const RESERVE_MODE_LABEL: Record<ReserveMode, string> = {
  inherit: "Existing reserve policy (no override)", none: "NONE", cash_fixed: "CASH_DSRA / fixed amount",
  automatic_peak: "Automatic peak forward debt service", dsrf: "DSRF / standby support",
};

export interface BankabilityDraft {
  sizingMode: string; lenderCase: string; dayCount: string;
  ratesMode: RatesMode; rates: string[];
  targetsMode: TargetsMode; targetScalar: string; targets: string[];
  feesEnabled: boolean; fees: { commitment_pct: string; structuring_pct: string; arrangement_pct: string };
  reserveMode: ReserveMode; months: string; requirement: string; commitment: string; feePct: string;
}

const str = (n: number | null | undefined) => (n === null || n === undefined ? "" : String(n));

/** The draft a user starts from: the saved configuration, with the project's effective values shown in the period grid. */
export function draftFromView(view: BankabilityView): BankabilityDraft {
  const cfg: BankabilityConfig = view.config ?? {};
  const periods: BankabilityPeriod[] = view.periods ?? [];
  const reserve = cfg.reserve;
  return {
    sizingMode: cfg.sizing_mode ?? "", lenderCase: cfg.lender_case ?? "", dayCount: cfg.day_count ?? "",
    ratesMode: cfg.rates_pct !== undefined ? "periods" : "inherit",
    rates: periods.map((p) => str(p.rate_pct)),
    targetsMode: cfg.targets !== undefined ? (cfg.targets.length === 0 ? "scalar" : "periods") : "inherit",
    targetScalar: str(view.scalar_target), targets: periods.map((p) => str(p.target)),
    feesEnabled: cfg.fees !== undefined,
    fees: { commitment_pct: str(view.fees?.commitment_pct), structuring_pct: str(view.fees?.structuring_pct), arrangement_pct: str(view.fees?.arrangement_pct) },
    reserveMode: (reserve?.mode as ReserveMode | undefined) ?? "inherit",
    months: str(reserve?.months || 6), requirement: str(reserve?.requirement_keur ?? 0),
    commitment: str(reserve?.commitment_keur ?? 0), feePct: str(reserve?.fee_pct ?? 0),
  };
}

const numberOrNull = (text: string): number | null => (text.trim() === "" ? null : Number(text));

/** The JSON text sent as the value of `debt.bankability.configuration` (identical to the Legacy editor's output). */
export function serializeBankability(d: BankabilityDraft): string {
  const cfg: Record<string, unknown> = { version: 1 };
  if (d.sizingMode) cfg.sizing_mode = d.sizingMode;
  if (d.lenderCase) cfg.lender_case = d.lenderCase;
  if (d.dayCount) cfg.day_count = d.dayCount;
  if (d.targetsMode === "periods") cfg.targets = d.targets.map(numberOrNull);
  if (d.targetsMode === "scalar") { cfg.targets = []; cfg.target_scalar = numberOrNull(d.targetScalar); }
  if (d.ratesMode === "periods") cfg.rates_pct = d.rates.map(numberOrNull);
  if (d.feesEnabled) {
    cfg.fees = {
      commitment_pct: numberOrNull(d.fees.commitment_pct), structuring_pct: numberOrNull(d.fees.structuring_pct),
      arrangement_pct: numberOrNull(d.fees.arrangement_pct),
    };
  }
  const mode = d.reserveMode;
  if (mode !== "inherit") {
    cfg.reserve = {
      mode,
      months: mode === "automatic_peak" ? numberOrNull(d.months) : 0,
      requirement_keur: mode === "cash_fixed" || mode === "dsrf" ? numberOrNull(d.requirement) : 0,
      commitment_keur: mode === "dsrf" ? numberOrNull(d.commitment) : 0,
      fee_pct: mode === "dsrf" ? numberOrNull(d.feePct) : 0,
    };
  }
  return JSON.stringify(cfg);
}

const NUMBER = /^-?\d+(?:\.\d+)?$/;

function checkNumber(text: string, label: string, min: number, max: number, out: string[]): void {
  const t = text.trim();
  if (t === "") { out.push(`${label}: enter a number.`); return; }
  if (!NUMBER.test(t)) { out.push(`${label}: “${t}” is not a plain number.`); return; }
  const n = Number(t);
  if (n < min || n > max) out.push(`${label}: must be between ${min} and ${max}.`);
}

/** Advisory checks only (the server is the authority).  Returns human-readable problems; empty means "worth sending". */
export function advisoryProblems(d: BankabilityDraft, view: BankabilityView): string[] {
  const out: string[] = [];
  const periods = view.periods ?? [];
  const savedReserve = draftFromView(view).reserveMode;
  if (!isReleasedReserveMode(d.reserveMode) && d.reserveMode !== savedReserve) {
    out.push(`Reserve policy “${RESERVE_MODE_LABEL[d.reserveMode]}” is not released and cannot be newly saved. Choose a released policy or keep the stored one.`);
  }
  if (d.targetsMode === "scalar") checkNumber(d.targetScalar, "Scalar target DSCR", 1, 3, out);
  if (d.targetsMode === "periods") d.targets.forEach((t, i) => checkNumber(t, `Target DSCR, period ${periods[i]?.number ?? i + 1}`, 1, 3, out));
  if (d.ratesMode === "periods") d.rates.forEach((t, i) => checkNumber(t, `All-in rate, period ${periods[i]?.number ?? i + 1}`, 0, 20, out));
  if (d.feesEnabled) {
    checkNumber(d.fees.commitment_pct, "Commitment fee", 0, 10, out);
    checkNumber(d.fees.structuring_pct, "Structuring fee", 0, 10, out);
    checkNumber(d.fees.arrangement_pct, "Arrangement fee", 0, 10, out);
  }
  if (d.reserveMode === "automatic_peak") {
    checkNumber(d.months, "Coverage months", 1, 12, out);
    if (d.months.trim() !== "" && !/^\d+$/.test(d.months.trim())) out.push("Coverage months: use a whole number.");
  }
  if (d.reserveMode === "cash_fixed" || d.reserveMode === "dsrf") checkNumber(d.requirement, "Required reserve", 0, 1000000, out);
  if (d.reserveMode === "dsrf") {
    checkNumber(d.commitment, "DSRF commitment", 0, 1000000, out);
    checkNumber(d.feePct, "DSRF commitment fee", 0, 10, out);
    if (Number(d.commitment) < Number(d.requirement)) out.push("DSRF commitment must cover the reserve requirement.");
  }
  if (d.targetsMode === "periods" && (d.sizingMode ? d.sizingMode !== "flat_dscr_sculpted" : view.mode !== "flat_dscr_sculpted")) {
    out.push("Period-specific targets require DSCR sculpting; choose that sizing method or use a scalar target.");
  }
  return out;
}

/** Canonical comparison form: the document the draft WOULD save, so "unchanged" means the same bytes the server would persist. */
export const configText = (view: BankabilityView): string => serializeBankability(draftFromView(view));
