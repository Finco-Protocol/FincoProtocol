/** Syntax only. No cap, forecast, annual schedule or financial calculation. */
export type AnnualQuantityDraft = { amount: string; unit: "MWh" | "GWh" };

export function quantityIssue(value: AnnualQuantityDraft): string | null {
  if (value.unit !== "MWh" && value.unit !== "GWh") return "Choose MWh or GWh.";
  if (value.amount.length > 128 || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value.amount)) {
    return "Enter a positive decimal amount without an exponent.";
  }
  if (/^0(?:\.0+)?$/.test(value.amount)) return "Annual quantity must be greater than zero.";
  return null;
}

/** Server-formatted declared-period facts; never derived from the browser draft. */
export type DeclaredPeriodDisplay = {
  scope: "DECLARED_PERIOD_DELIVERY_CAP_ONLY";
  annual_semantics_verified: false;
  production_supported: false;
  case: string;
  interval: string;
  available: string;
  allocated: string;
  remaining: string;
  unit: "MWh" | "GWh";
};
