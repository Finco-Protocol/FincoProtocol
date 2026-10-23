export type PreviewStateId =
  | "up-to-date"
  | "unsaved"
  | "saved-not-calculated"
  | "calculating"
  | "calculation-failed"
  | "attention"
  | "no-results"
  | "reference-read-only"
  | "project-changed"
  | "scenario-no-results";

export type PlainLanguageStatus = {
  label: string;
  tone: "green" | "blue" | "amber" | "gray";
  detail: string;
  banner: boolean;
  action: "none" | "review-inputs" | "run-demo" | "create-copy" | "conflict-details" | "choose-scenario";
};

export const previewStateOptions: readonly { id: PreviewStateId; label: string }[] = [
  { id: "up-to-date", label: "Results are up to date" },
  { id: "unsaved", label: "You have unsaved changes" },
  { id: "saved-not-calculated", label: "Changes saved — results not yet calculated" },
  { id: "calculating", label: "Calculating…" },
  { id: "calculation-failed", label: "Calculation failed — review the highlighted inputs" },
  { id: "attention", label: "Some inputs need attention" },
  { id: "no-results", label: "No results yet — run the model" },
  { id: "reference-read-only", label: "This is a read-only reference — create a working copy to edit" },
  { id: "project-changed", label: "This project changed since you opened it. Reload to continue" },
  { id: "scenario-no-results", label: "Results for this scenario aren’t available yet" },
];

const previewStatuses: Record<PreviewStateId, PlainLanguageStatus> = {
  "up-to-date": {
    label: "Results are up to date",
    tone: "green",
    detail: "Development preview state only. The figures remain fixed examples and are not recalculated.",
    banner: false,
    action: "none",
  },
  unsaved: {
    label: "You have unsaved changes",
    tone: "amber",
    detail: "Your changes are still in this browser tab and have not been acknowledged by the local Save demo.",
    banner: true,
    action: "review-inputs",
  },
  "saved-not-calculated": {
    label: "Changes saved — results not yet calculated",
    tone: "blue",
    detail: "Save only acknowledges a local example. It does not calculate or update financial results.",
    banner: true,
    action: "run-demo",
  },
  calculating: {
    label: "Calculating…",
    tone: "blue",
    detail: "This is a display example only. No calculation is running.",
    banner: true,
    action: "none",
  },
  "calculation-failed": {
    label: "Calculation failed — review the highlighted inputs",
    tone: "amber",
    detail: "This failure message is illustrative. No financial calculation was attempted.",
    banner: true,
    action: "review-inputs",
  },
  attention: {
    label: "Some inputs need attention",
    tone: "amber",
    detail: "Review highlighted fields. Blocking input errors disable the local Save and Run demo actions.",
    banner: true,
    action: "review-inputs",
  },
  "no-results": {
    label: "No results yet — run the model",
    tone: "gray",
    detail: "Run demo opens fixed illustrative figures; it does not calculate results.",
    banner: true,
    action: "run-demo",
  },
  "reference-read-only": {
    label: "This is a read-only reference — create a working copy to edit",
    tone: "blue",
    detail: "You can inspect this reference. Create a local working copy before editing.",
    banner: true,
    action: "create-copy",
  },
  "project-changed": {
    label: "This project changed since you opened it. Reload to continue",
    tone: "amber",
    detail: "A real reload may discard local changes. This preview does not refresh project data.",
    banner: true,
    action: "conflict-details",
  },
  "scenario-no-results": {
    label: "Results for this scenario aren’t available yet",
    tone: "gray",
    detail: "No fixed result example is supplied for the selected scenario.",
    banner: true,
    action: "choose-scenario",
  },
};

export function parsePreviewState(value: string | null | undefined): PreviewStateId | null {
  return previewStateOptions.some((item) => item.id === value) ? value as PreviewStateId : null;
}

export function resolvePlainLanguageStatus(
  selected: PreviewStateId | null,
  context: { readOnly?: boolean; invalidInputs?: boolean; warnings?: boolean; unsaved?: boolean; saved?: boolean },
): PlainLanguageStatus {
  if (context.readOnly || selected === "reference-read-only") {
    return {
      label: "This is a read-only reference — create a working copy to edit",
      tone: "blue",
      detail: "You can inspect this reference. Create a local working copy before editing.",
      banner: true,
      action: "create-copy",
    };
  }
  if (context.invalidInputs || context.warnings) return previewStatuses.attention;
  if (context.unsaved) return previewStatuses.unsaved;
  if (selected) return previewStatuses[selected];
  if (context.saved) return previewStatuses["saved-not-calculated"];
  return previewStatuses["no-results"];
}
