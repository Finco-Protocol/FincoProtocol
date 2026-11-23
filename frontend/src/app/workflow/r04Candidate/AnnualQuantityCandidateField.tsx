/** Unmounted preparatory component. No Save/Run, source import or cap math. */
import { useId } from "react";
import { quantityIssue, type AnnualQuantityDraft, type DeclaredPeriodDisplay } from "./AnnualQuantityDraft";

type Props = {
  value: AnnualQuantityDraft;
  onChange: (next: AnnualQuantityDraft) => void;
  readOnly?: boolean;
  serverReview?: DeclaredPeriodDisplay;
};

export function AnnualQuantityCandidateField({ value, onChange, readOnly = false, serverReview }: Props) {
  const id = useId();
  const issue = quantityIssue(value);
  return (
    <section aria-labelledby={`${id}-title`} data-r04-quantity-candidate="unreleased">
      <h3 id={`${id}-title`}>Annual PPA quantity</h3>
      <label htmlFor={`${id}-amount`}>Annual quantity</label>
      <input id={`${id}-amount`} type="text" inputMode="decimal" value={value.amount} readOnly={readOnly}
        aria-invalid={Boolean(issue)} aria-describedby={`${id}-policy${issue ? ` ${id}-error` : ""}`}
        onChange={(event) => onChange({ ...value, amount: event.target.value })} />
      <label htmlFor={`${id}-unit`}>Energy unit</label>
      <select id={`${id}-unit`} value={value.unit} disabled={readOnly}
        onChange={(event) => onChange({ ...value, unit: event.target.value as AnnualQuantityDraft["unit"] })}>
        <option value="MWh">MWh/year</option><option value="GWh">GWh/year</option>
      </select>
      {issue && <p id={`${id}-error`} role="alert">{issue}</p>}
      <p id={`${id}-policy`} role="status">Annual delivery rules are not approved. Save and Run are unavailable for this candidate.</p>
      {serverReview ? (
        <div aria-label="Declared period review only">
          <p>{serverReview.case} · {serverReview.interval} · declared period quantities only</p>
          <dl>
            <dt>Available</dt><dd>{serverReview.available} {serverReview.unit}</dd>
            <dt>Allocated</dt><dd>{serverReview.allocated} {serverReview.unit}</dd>
            <dt>Remaining</dt><dd>{serverReview.remaining} {serverReview.unit}</dd>
          </dl>
        </div>
      ) : <p>No server period review is available.</p>}
    </section>
  );
}
