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
  "revenue.ppa.indexation_policy": "When the tariff starts to escalate. \u201cContract anniversary\u201d counts annual steps from the Indexation Start Date below, which is then required.",
  "revenue.ppa.indexation_start_date": "Reference date from which annual escalation steps are counted. Required only when the policy is \u201cContract anniversary\u201d; leave blank otherwise.",
  "debt.bankability.configuration": "Detailed bankability settings. Edit them in the Bankability tab; they are not edited as free text here.",
  "debt.financing.instruments": "Senior facility structure, including a second senior facility. Editing it is not available yet; the Run uses only the selected scenario's scope.",
};

export function plainFieldHelp(fieldId: string, helpText: string | null | undefined): FieldHelp {
  const raw = (helpText ?? "").trim();
  const plain = PLAIN_BY_FIELD[fieldId];
  if (plain) return { hint: plain, technical: raw && raw !== plain ? raw : undefined };
  if (raw && TECHNICAL_SIGNS.test(raw)) return { technical: raw };
  return { hint: raw || undefined };
}

/** Plain labels for the stored option values of registry selects (the stored value is unchanged; only what is read on screen). */
const PLAIN_OPTION_LABELS: Record<string, Record<string, string>> = {
  "revenue.ppa.indexation_policy": {
    FIRST_FULL_CALENDAR_YEAR_AS_BASE: "First full calendar year is the base year",
    AFTER_FIRST_FULL_OPERATING_YEAR: "Escalate after the first full operating year",
    CONTRACT_ANNIVERSARY: "Contract anniversary (from the Indexation Start Date)",
  },
};
export const plainOptionLabel = (fieldId: string, option: string): string | undefined => PLAIN_OPTION_LABELS[fieldId]?.[option];

/** Why a non-editable field cannot be typed over, by its binding label. */
export const BINDING_PLAIN: Record<string, string> = {
  "display-only": "Calculated by the model; it cannot be edited.",
  "template-locked": "Fixed when the project was created.",
  partial: "Shown for reference. It is not a direct input to the calculation, so it cannot be edited here.",
};

export const STRUCTURED_PLAIN = "Detailed configuration. It is not edited as free text here.";
