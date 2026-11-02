// PR-U1 (owner decision D1, bounded): human-readable DISPLAY names for the cost groups. Presentation only.
//
// * The internal group code (C.01 ... B.13) stays the identity everywhere (rows, Save, profile keys, Run): it is never shown.
// * A display name is NOT proof of financial parity and never changes a group's mapping status (PROVEN / UNRESOLVED / DERIVED stay as the server
//   says); the Run fold (`CAPEX_CATEGORY_TO_FIELD`, C.08 + C.11 -> one audit/legal field) is untouched.
// * Names follow the economic meaning of the canonical group, never a spreadsheet's numbering. Two groups that fold into one economic field
//   (C.08 and C.11) keep two different names, because they are two groups.
// * An unknown code falls back to the server's label with a leading code removed, so a new group can never show a bare code.

const CAPEX: Readonly<Record<string, string>> = {
  "C.01": "Production Units",
  "C.02": "EPC Contract",
  "C.03": "Grid Connection",
  "C.04": "Operation Investments",
  "C.05": "Other EPC Costs",
  "C.06": "Insurances",
  "C.07": "Land, Lease & Property Tax",
  "C.08": "Bank & Closing Costs",
  "C.09": "Construction Management",
  "C.10": "Commissioning",
  "C.11": "Audit, Accounting & Legal Fees",
  "C.12": "Construction Management (additional)",
  "C.13": "Contingencies",
  "C.14": "Taxes & Customs",
  "C.15": "Project Acquisition / Development",
  "C.16": "Project Rights",
  "C.17": "Financing Costs",
  "C.18": "Reserve Accounts",
};

const OPEX: Readonly<Record<string, string>> = {
  "B.01": "Technical Management",
  "B.02": "O&M Preventive & Corrective",
  "B.03": "Site Maintenance",
  "B.04": "Cleaning & Materials",
  "B.05": "Security",
  "B.06": "Insurance",
  "B.07": "Lease & Property Tax",
  "B.08": "Power Expenses",
  "B.09": "Telecom & Other Fees",
  "B.10": "Audit, Accounting & Legal",
  "B.11": "Bank Fees",
  "B.12": "Environmental & Social",
  "B.13": "Contingencies",
};

const LEADING_CODE = /^\s*[A-Z]\.\d{2}(?:\.\d{2})?\s+/;

/** The name a user sees for a group code. `serverLabel` (may start with the code) is only the fallback for a code this map does not know. */
export function groupDisplayName(code: string, serverLabel?: string | null): string {
  const known = CAPEX[code] ?? OPEX[code];
  if (known) return known;
  const stripped = (serverLabel ?? "").replace(LEADING_CODE, "").trim();
  return stripped || "Other costs";
}

/** Removes a visible leading code ("C.01 Production Units" -> "Production Units") from any label. */
export function withoutCode(label: string): string {
  return label.replace(LEADING_CODE, "").trim() || label;
}

/** OPEX group code -> its scalar base field (`opex.lines.<suffix>`), for the six groups whose base amount is an editable canonical field. */
export const OPEX_BASE_FIELD_BY_GROUP: Readonly<Record<string, string>> = {
  "B.04": "opex.lines.cleaning_materials",
  "B.05": "opex.lines.security",
  "B.08": "opex.lines.power_expenses",
  "B.10": "opex.lines.audit_accounting_legal",
  "B.11": "opex.lines.bank_fees",
  "B.12": "opex.lines.environmental_social",
};
