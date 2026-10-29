import type { InputsPayload } from "./types";

/** Presentation order only; preserve every canonical field, token and editability decision. */
export function financialInputOrder(payload: InputsPayload): InputsPayload {
  const rank = (id: string) => id.startsWith("project_setup") ? 0 : id === "capex" ? 1
    : id === "opex" ? 2 : id.startsWith("revenue") ? 3 : id.startsWith("debt") ? 4 : 5;
  return { ...payload, grid: { ...payload.grid,
    sections: payload.grid.sections.map((section, index) => ({ section, index }))
      .sort((a, b) => rank(a.section.section_id) - rank(b.section.section_id) || a.index - b.index)
      .map(({ section }) => section),
  } };
}
