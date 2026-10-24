import type { ResultsDisplayValue } from "./resultsContract.ts";

export type SyntheticRunPeriod = {
  period: string;
  cfads: ResultsDisplayValue;
  debtService: ResultsDisplayValue;
  dscr: ResultsDisplayValue;
};

export type SyntheticRunPeriodSet = {
  frequency: string;
  periods: SyntheticRunPeriod[];
};

const amount = (text: string): ResultsDisplayValue => ({ kind: "value", text });
const unavailable = (reason: string): ResultsDisplayValue => ({ kind: "unavailable", text: "Unavailable", reason });

/**
 * Fixed illustrative schedules for the Run Compare design. Each run retains
 * its own authored period labels; this fixture performs no period alignment.
 */
export const SYNTHETIC_RUN_PERIODS: Record<string, SyntheticRunPeriodSet> = {
  "DEMO-FIXED-018": {
    frequency: "Annual",
    periods: [
      { period: "2027", cfads: amount("8.4"), debtService: amount("6.7"), dscr: amount("1.25x") },
      { period: "2028", cfads: amount("10.6"), debtService: amount("8.4"), dscr: amount("1.26x") },
      { period: "2029", cfads: amount("10.9"), debtService: amount("8.5"), dscr: amount("1.28x") },
    ],
  },
  "DEMO-FIXED-017": {
    frequency: "Quarterly · 3M",
    periods: [
      { period: "2027 Q1", cfads: amount("1.8"), debtService: amount("1.7"), dscr: amount("1.06x") },
      { period: "2027 Q2", cfads: unavailable("No Q2 CFADS supplied."), debtService: amount("1.7"), dscr: unavailable("No Q2 DSCR supplied.") },
      { period: "2027 Q4", cfads: amount("1.9"), debtService: amount("1.8"), dscr: amount("1.05x") },
    ],
  },
  "DEMO-FIXED-014": {
    frequency: "Semiannual · 6M",
    periods: [
      { period: "2026 H2", cfads: amount("3.2"), debtService: amount("2.6"), dscr: amount("1.23x") },
      { period: "2027 H1", cfads: amount("3.6"), debtService: amount("3.4"), dscr: amount("1.06x") },
      { period: "2027 H2", cfads: amount("3.8"), debtService: unavailable("No H2 debt-service value supplied."), dscr: unavailable("No H2 DSCR supplied.") },
    ],
  },
};

export function displayPeriodValue(value: ResultsDisplayValue): string {
  return value.kind === "value" ? value.text : value.text || "Unavailable";
}
