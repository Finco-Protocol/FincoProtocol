// UI constraints only: these checks do not model financial performance.
export const initialAssumptions = {
  capacity: "120", start: "2025-10-01", cod: "2027-07-01", term: "30",
  ppaPrice: "62.50", ppaTenor: "18", contracted: "82", indexation: "1.75", scheduledStep: "2.40",
  capex: "104.8", opex: "1.42", tax: "18",
  debt: "67.0", interest: "5.35", tenor: "18", dscr: "1.25",
  mezzDebt: "6.0", mezzCoupon: "8.25", mezzPik: "1.50", equity: "36.5", ownership: "100",
};
export type InputKey = keyof typeof initialAssumptions;
export type Assumptions = Record<InputKey, string>;
export const assumptionLabels: Record<InputKey, string> = {
  capacity: "Installed capacity", start: "Construction start", cod: "Commercial operation", term: "Operating life",
  ppaPrice: "PPA tariff", ppaTenor: "PPA tenor", contracted: "Contracted generation", indexation: "Annual indexation", scheduledStep: "Scheduled step-up",
  capex: "Total project CAPEX", opex: "Fixed O&M", tax: "Corporate tax", debt: "Senior debt commitment",
  interest: "Margin over EURIBOR", tenor: "Debt tenor", dscr: "Minimum DSCR",
  mezzDebt: "Mezzanine commitment", mezzCoupon: "Cash coupon", mezzPik: "PIK component", equity: "Equity commitment", ownership: "Ownership",
};
export function validateAssumptions(v: Assumptions, ppa: string) {
  const errors: Partial<Record<InputKey, string>> = {};
  const warnings: Partial<Record<InputKey, string>> = {};
  const number = (key: InputKey, min: number, max: number, message: string, integer = false) => {
    const n = Number(v[key]);
    if (!v[key].trim() || !Number.isFinite(n) || n < min || n > max || (integer && !Number.isInteger(n))) errors[key] = message;
  };
  number("capacity", Number.MIN_VALUE, Infinity, "Capacity must be greater than 0.");
  for (const key of ["capex", "opex", "debt", "mezzDebt", "equity"] as const)
    number(key, 0, Infinity, "Enter a finite, nonnegative amount.");
  number("term", 1, 60, "Operating life must be a whole number, 1–60 years.", true);
  number("tax", 0, 100, "Tax must be between 0 and 100%.");
  number("interest", 0, 30, "Debt margin must be between 0 and 30%.");
  number("tenor", 1, 40, "Debt tenor must be a whole number, 1–40 years.", true);
  number("ppaTenor", 1, 40, "PPA tenor must be a whole number, 1–40 years.", true);
  if (!errors.tenor && !errors.term && Number(v.tenor) > Number(v.term)) errors.tenor = "Debt tenor cannot exceed operating life.";
  if (!errors.ppaTenor && !errors.term && Number(v.ppaTenor) > Number(v.term)) errors.ppaTenor = "PPA tenor cannot exceed operating life.";
  number("ppaPrice", 0, Infinity, "Tariff must be a finite, nonnegative amount.");
  number("contracted", 0, 100, "Contracted generation must be between 0 and 100%.");
  number("dscr", Number.MIN_VALUE, Infinity, "Minimum DSCR must be greater than 0.");
  if (!errors.dscr && Number(v.dscr) <= 1) warnings.dscr = "Review: a covenant at or below 1.00x offers no coverage buffer. Not a calculated credit assessment.";
  if (!errors.interest && Number(v.interest) > 15) warnings.interest = "Review: unusually high debt margin for this illustrative case.";
  if (ppa === "Indexed") number("indexation", -10, 20, "Demo indexation range is −10% to 20%.");
  if (ppa === "Scheduled") number("scheduledStep", 0, 100, "Step-up must be between 0 and 100%.");
  for (const key of ["mezzCoupon", "mezzPik"] as const) number(key, 0, 30, "Rate must be between 0 and 30%.");
  number("ownership", 0, 100, "Ownership must be between 0 and 100%.");
  const date = (key: "start" | "cod") => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v[key]) || !Number.isFinite(Date.parse(v[key])) || new Date(v[key]).toISOString().slice(0, 10) !== v[key] || v[key] < "2000-01-01" || v[key] > "2100-12-31")
      errors[key] = "Enter a valid date between 2000 and 2100.";
  };
  date("start"); date("cod");
  if (!errors.start && !errors.cod && v.cod <= v.start) errors.cod = "Commercial operation must follow construction start.";
  return { errors, warnings };
}
