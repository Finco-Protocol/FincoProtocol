// Finance-language copy for the registry-driven editors (U02).
//
// The field registry's `help_text` is written for engineers (adapter names, internal
// controls, ticket codes).  It stays available behind a "Technical note" disclosure, but
// the visible hint is plain language.  Pure presentation: no value, label, unit, binding
// or validation is changed.

/** What to show for one field: a visible plain hint and, when different, the raw registry note. */
export interface FieldHelp { hint?: string; technical?: string }

const TECHNICAL_SIGNS = /\b(R\d+\/N\d+|PARTIAL|CAS|inputs_section|data-grid-source|input_adapter|adapter|ProjectInputs|ScenarioRunner|typed|period-rate|snapshot|authority|serializ\w*|canonical (adapter|Run)|scalar IS|workspace-draft)\b/i;

const PLAIN_BY_FIELD: Record<string, string> = {
  "project_setup.identity.country_market": "Market code: XA, XB or XC for the generic reference markets, or the two-letter ISO country code of a real market.",
  "project_setup.identity.currency": "Display label only. The model calculates in EUR.",
  "project_setup.identity.scenario": "Label of the scenario this Working Copy is set to. Scenarios are managed in the Scenarios section.",
  "project_setup.technical.capacity_factor": "Calculated by the model from operating hours and installed capacity.",
  "debt.senior.gearing_pct": "Senior debt as a share of the funding need.",
  "debt.senior.target_dscr": "Target debt service cover, as a multiple. If the detailed financing schedule sets cover period by period, this control is locked and the schedule controls it.",
  "debt.senior.interest_rate_pct": "All-in senior interest rate. If the detailed financing schedule sets the rate, this control is locked: the interest rate is controlled by the detailed financing schedule.",
  "debt.bankability.configuration": "Detailed bankability settings. They have their own editor in the legacy workbook and are not edited as free text here.",
  "debt.financing.instruments": "Senior facility structure, including a second senior facility. It has its own editor in the legacy workbook; the Run uses only the selected scenario's scope.",
};

export function plainFieldHelp(fieldId: string, helpText: string | null | undefined): FieldHelp {
  const raw = (helpText ?? "").trim();
  const plain = PLAIN_BY_FIELD[fieldId];
  if (plain) return { hint: plain, technical: raw && raw !== plain ? raw : undefined };
  if (raw && TECHNICAL_SIGNS.test(raw)) return { technical: raw };
  return { hint: raw || undefined };
}

/** Why a non-editable field cannot be typed over, by its binding label. */
export const BINDING_PLAIN: Record<string, string> = {
  "display-only": "Calculated by the model; it cannot be edited.",
  "template-locked": "Fixed when the project was created.",
  partial: "Shown for reference. It is not a direct input to the calculation, so it cannot be edited here.",
};

export const STRUCTURED_PLAIN = "Detailed configuration with its own editor in the legacy workbook. It is not edited as free text here.";
