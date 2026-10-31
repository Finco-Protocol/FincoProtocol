// Orientation for the Inputs workspace: where each group lives and exactly what each Save writes.
// Presentation only — it never saves, runs or reads financial data.

export type InputsJump = { id: string; label: string; kind: "anchor" | "cost-sheet" | "section"; sheet?: "capex" | "opex"; section?: string };

export const INPUT_JUMPS: ReadonlyArray<InputsJump> = [
  { id: "wf-inputs-setup", label: "Project setup", kind: "anchor" },
  { id: "wf-inputs-grid", label: "Assumptions", kind: "anchor" },
  { id: "wf-inputs-costs", label: "CAPEX", kind: "cost-sheet", sheet: "capex" },
  { id: "wf-inputs-costs", label: "OPEX", kind: "cost-sheet", sheet: "opex" },
  { id: "wf-inputs-revenue", label: "Revenue & PPA", kind: "anchor" },
  { id: "wf-inputs-studios", label: "Studios", kind: "anchor" },
  { id: "financing", label: "Financing", kind: "section", section: "financing" },
];

export function InputsJumpNav({ onJump }: { onJump: (jump: InputsJump) => void }) {
  return (
    <nav className="wf-jump" aria-label="Inputs groups" data-inputs-jump="true">
      {INPUT_JUMPS.map((jump) => (
        <a key={`${jump.id}-${jump.label}`} href={`#${jump.id}`} data-jump-target={jump.id} data-jump-label={jump.label}
          onClick={(event) => { event.preventDefault(); event.stopPropagation(); onJump(jump); }}>
          {jump.label}{jump.kind === "section" && <span aria-hidden="true"> →</span>}
        </a>
      ))}
    </nav>
  );
}

const SCOPES: ReadonlyArray<{ editor: string; saves: string; control: string }> = [
  { editor: "Project setup", saves: "One field at a time.", control: "Save beside the edited field" },
  { editor: "Assumptions", saves: "All edited cells together, all or none.", control: "Save staged cells" },
  { editor: "CAPEX line items", saves: "All edited CAPEX lines together, all or none.", control: "Save staged lines (CAPEX)" },
  { editor: "OPEX line items", saves: "All edited OPEX lines together, all or none.", control: "Save staged lines (OPEX)" },
  { editor: "Revenue & PPA contracts", saves: "The whole contract list.", control: "Save contracts" },
  { editor: "Revenue assumptions (Studios)", saves: "One field at a time.", control: "Save beside the edited field" },
  { editor: "CAPEX spending profile", saves: "The monthly profile of the CAPEX items, all or none.", control: "Save profile to the project" },
  { editor: "Financing", saves: "One field at a time (Financing section).", control: "Save beside the edited field" },
  { editor: "Scenario overrides", saves: "One override at a time (Scenarios section).", control: "Save beside the override" },
];

/** What the single all-or-none Save All transaction can carry.  Mirrors `editing/saveAll.ts` (sections cells, contracts, cost_lines) and the
 *  excluded collections in `editing/pendingEdits.ts` (SAVE_ALL_EXCLUDED_KEYS); the server advertises the capability per project. */
export const SAVE_ALL_INCLUDES = "Staged Assumptions and Project setup cells, single Financing values, CAPEX and OPEX lines, and PPA contract changes";
export const SAVE_ALL_EXCLUDES = "Financing collections (capital stack and facilities) and the multi-stream revenue contract list";

/** One honest table of what each Save control writes.  Nothing autosaves and no Save runs the model.  Save All exists only when the server
 *  advertises it for the open project; this static guide never claims it is active. */
export function SaveScopeGuide() {
  return (
    <details className="rx-save-guide" data-save-scope-guide="true">
      <summary>What each Save writes</summary>
      <div className="fm-table-wrap rx-lines-scroll" role="region" tabIndex={0} aria-label="Save scope of every editor, scrollable">
      <table className="rx-table rx-save-table">
        <caption className="fm-sr-only">Save scope of every editor</caption>
        <thead><tr><th scope="col">Editor</th><th scope="col">One Save writes</th><th scope="col">Control</th></tr></thead>
        <tbody>
          {SCOPES.map((row) => (
            <tr key={row.editor}><th scope="row">{row.editor}</th><td>{row.saves}</td><td>{row.control}</td></tr>
          ))}
          <tr data-save-all-row="true"><th scope="row">Save All (when offered)</th>
            <td>Every staged change below in one all-or-none step, or nothing at all.</td>
            <td>Save All, in the Changes panel</td></tr>
          <tr><th scope="row">Run</th><td>Nothing is edited. It calculates new results from what is already saved.</td><td>Run model, in the bar above</td></tr>
        </tbody>
      </table>
      </div>
      <p className="rx-note" data-save-all-scope="true">Save All appears in the Changes panel only when the server enables it for this project; it is not available
        on a read-only project. When offered, it can save: {SAVE_ALL_INCLUDES}. Not included: {SAVE_ALL_EXCLUDES}; they keep their own Save.
        If any staged change cannot be carried, Save All is refused as a whole and nothing is partly saved.</p>
      <p className="rx-note">Each editor still has its own Save and you can use it at any time. Nothing saves automatically, no Save runs the model,
        and after any Save the last Run is outdated until you choose Run model.</p>
    </details>
  );
}
