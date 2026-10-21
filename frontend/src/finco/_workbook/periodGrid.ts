// Fixed synthetic input samples and UI validation only. No financial formulas.
export type LineSheet = "capex" | "opex";
export type PeriodView = "quarterly" | "semiannual";
export type LineValues = Record<LineSheet, string[][]>;
export type PeriodRow = { id: string; label: string; unit: string; kind: "group" | "amount" | "date" | "fixed"; values: string[] };

const monthlyEnds = Array.from({ length: 18 }, (_, i) => {
  const d = new Date(Date.UTC(2025, 10 + i, 0));
  return d.toISOString().slice(0, 10);
});
const quarterEndAt = (index: number) => new Date(Date.UTC(2027, 9 + index * 3, 0)).toISOString().slice(0, 10);
const halfEndAt = (index: number) => new Date(Date.UTC(2027, 12 + index * 6, 0)).toISOString().slice(0, 10);
const quarterEnds = Array.from({ length: 12 }, (_, index) => quarterEndAt(index));
const halfEnds = Array.from({ length: 6 }, (_, index) => halfEndAt(index));
const stressEditableQuarterLimit = 60;
const cells = (s: string) => s.split("|");
const capexRows: PeriodRow[] = [
  { id: "epc", label: "EPC / equipment", unit: "", kind: "group", values: [] },
  { id: "modules", label: "PV modules", unit: "€m", kind: "amount", values: cells("0.2|0.3|0.5|0.8|1.2|1.6|2.0|2.4|2.8|3.0|2.8|2.4|2.0|1.4|0.8|0.5|0.2|0.1") },
  { id: "bos", label: "Inverters / balance of system", unit: "€m", kind: "amount", values: cells("0.1|0.1|0.2|0.3|0.4|0.6|0.8|0.9|1.0|1.2|1.0|0.9|0.8|0.7|0.5|0.3|0.2|0.1") },
  { id: "civil", label: "Civil / connection", unit: "", kind: "group", values: [] },
  { id: "works", label: "Civil works", unit: "€m", kind: "amount", values: cells("0.4|0.5|0.6|0.7|0.8|0.9|0.8|0.7|0.6|0.5|0.4|0.3|0.2|0.2|0.1|0.1|0|0") },
  { id: "grid", label: "Grid connection", unit: "€m", kind: "amount", values: cells("0|0|0.1|0.1|0.2|0.3|0.4|0.5|0.6|0.8|0.9|0.8|0.6|0.4|0.3|0.2|0.1|0.1") },
  { id: "owner", label: "Owner / risk allowances", unit: "", kind: "group", values: [] },
  { id: "development", label: "Development / advisory fees", unit: "€m", kind: "amount", values: cells("0.2|0.2|0.2|0.1|0.1|0.1|0.1|0.1|0.1|0.1|0.1|0.1|0.1|0.1|0.1|0.1|0.1|0.1") },
  { id: "insurance", label: "Owner insurance / overhead", unit: "€m", kind: "amount", values: cells("0.03|0.03|0.04|0.04|0.05|0.05|0.05|0.06|0.06|0.06|0.06|0.06|0.05|0.05|0.04|0.04|0.03|0.03") },
  { id: "contingency", label: "Contingency allowance", unit: "€m", kind: "amount", values: cells("0.1|0.1|0.1|0.1|0.2|0.2|0.2|0.2|0.2|0.2|0.2|0.2|0.2|0.2|0.1|0.1|0.1|0.1") },
  { id: "milestone-date", label: "Milestone target date · marker only", unit: "ISO date", kind: "date", values: monthlyEnds },
  { id: "fixed-capex", label: "Total CAPEX · FIXED LAST RUN", unit: "€m", kind: "fixed", values: cells("1.1|1.3|1.7|2.1|3.0|3.8|4.4|4.9|5.4|6.0|5.5|4.8|4.0|3.2|2.1|1.4|0.8|0.6") },
  { id: "fixed-draw", label: "Debt draw · FIXED LAST RUN", unit: "€m", kind: "fixed", values: cells("0.7|0.8|1.1|1.4|2.0|2.5|2.9|3.2|3.5|3.9|3.6|3.1|2.6|2.1|1.4|0.9|0.5|0.4") },
  { id: "fixed-equity", label: "Equity contribution · FIXED LAST RUN", unit: "€m", kind: "fixed", values: cells("0.4|0.5|0.6|0.7|1.0|1.3|1.5|1.7|1.9|2.1|1.9|1.7|1.4|1.1|0.7|0.5|0.3|0.2") },
];
const opexDefinitions: { id: string; label: string; unit: string; kind: PeriodRow["kind"]; quarterly?: string; semiannual?: string }[] = [
  { id: "operations", label: "Operations", unit: "", kind: "group" },
  { id: "fixed-om", label: "Fixed O&M", unit: "€m", kind: "amount", quarterly: "0.35|0.35|0.36|0.36|0.36|0.36|0.39|0.39|0.39|0.39|0.40|0.40", semiannual: "0.70|0.72|0.72|0.78|0.78|0.80" },
  { id: "variable-om", label: "Variable O&M", unit: "€m", kind: "amount", quarterly: "0.04|0.03|0.03|0.04|0.04|0.03|0.03|0.04|0.04|0.03|0.03|0.04", semiannual: "0.07|0.07|0.07|0.07|0.07|0.07" },
  { id: "site", label: "Site / insurance", unit: "", kind: "group" },
  { id: "land", label: "Land lease", unit: "€m", kind: "amount", quarterly: "0.04|0.04|0.04|0.04|0.04|0.04|0.05|0.05|0.05|0.05|0.05|0.05", semiannual: "0.08|0.08|0.08|0.10|0.10|0.10" },
  { id: "insurance", label: "Insurance", unit: "€m", kind: "amount", quarterly: "0.02|0.02|0.03|0.03|0.03|0.03|0.03|0.03|0.03|0.03|0.03|0.03", semiannual: "0.04|0.06|0.06|0.06|0.06|0.06" },
  { id: "administration", label: "Administration / reserves", unit: "", kind: "group" },
  { id: "asset-management", label: "Asset management", unit: "€m", kind: "amount", quarterly: "0.02|0.02|0.02|0.02|0.02|0.02|0.03|0.03|0.03|0.03|0.03|0.03", semiannual: "0.04|0.04|0.04|0.06|0.06|0.06" },
  { id: "reserve", label: "Maintenance reserve contribution", unit: "€m", kind: "amount", quarterly: "0.01|0.01|0.01|0.01|0.01|0.01|0.02|0.02|0.02|0.02|0.02|0.02", semiannual: "0.02|0.02|0.02|0.04|0.04|0.04" },
  { id: "escalation", label: "Annual escalation · fixed assumption", unit: "%", kind: "fixed", quarterly: "2|2|2|2|2|2|3|3|3|3|2|2", semiannual: "2|2|2|3|3|2" },
  { id: "step", label: "2029 step-up · fixed allowance", unit: "€m", kind: "fixed", quarterly: "0|0|0|0|0|0|0.03|0.03|0.03|0.03|0.03|0.03", semiannual: "0|0|0|0.06|0.06|0.06" },
  { id: "fixed-total", label: "Total OPEX · FIXED LAST RUN", unit: "€m", kind: "fixed", quarterly: "0.48|0.47|0.49|0.50|0.50|0.49|0.55|0.56|0.56|0.55|0.56|0.57", semiannual: "0.95|0.99|0.99|1.11|1.11|1.13" },
  { id: "fixed-tax", label: "Tax schedule · unavailable", unit: "—", kind: "fixed", quarterly: "—|—|—|—|—|—|—|—|—|—|—|—", semiannual: "—|—|—|—|—|—" },
];
export function periodHeaders(sheet: LineSheet, view: PeriodView, longHorizon: boolean | number = false): string[] {
  if (sheet === "capex") return [...monthlyEnds];
  const quarterlyCount = typeof longHorizon === "number" ? longHorizon : longHorizon ? 60 : quarterEnds.length;
  const count = view === "quarterly" ? quarterlyCount : Math.ceil(quarterlyCount / 2);
  return Array.from({ length: count }, (_, index) => view === "quarterly" ? quarterEndAt(index) : halfEndAt(index));
}
export function periodRows(sheet: LineSheet, view: PeriodView, longHorizon: boolean | number = false): PeriodRow[] {
  const count = periodHeaders(sheet, view, longHorizon).length;
  if (sheet === "capex") return capexRows.map(r => ({ ...r, values: r.values.length ? [...r.values] : Array(count).fill("") }));
  return opexDefinitions.map(r => {
    const authored = r[view] ? cells(r[view]!) : [];
    return {
      id: r.id,
      label: r.label,
      kind: r.kind,
      unit: r.unit,
      values: Array.from({ length: count }, (_, index) => {
        if (authored[index] !== undefined) return authored[index];
        if (view === "quarterly" && longHorizon && r.kind === "amount") {
          return typeof longHorizon === "number" && longHorizon > stressEditableQuarterLimit && index >= stressEditableQuarterLimit ? "—" : "0.00";
        }
        return r.kind === "group" ? "" : "—";
      }),
    };
  });
}
export const initialLineValues: LineValues = {
  capex: periodRows("capex", "quarterly").map(r => [...r.values]),
  opex: periodRows("opex", "quarterly", true).map(r => [...r.values]),
};
export function isEditablePeriodCell(sheet: LineSheet, view: PeriodView, row: number, col: number, longHorizon: boolean | number = false): boolean {
  const rows = periodRows(sheet, view, longHorizon);
  const editablePeriodCount = typeof longHorizon === "number" && longHorizon > stressEditableQuarterLimit
    ? stressEditableQuarterLimit
    : periodHeaders(sheet, view, longHorizon).length;
  return !(sheet === "opex" && view === "semiannual") && row >= 0 && row < rows.length && col >= 0 && col < editablePeriodCount && ["amount", "date"].includes(rows[row].kind);
}
export function periodCellError(row: PeriodRow, value: string): string | undefined {
  if (row.kind !== "amount" && row.kind !== "date") return undefined;
  const text = value.trim();
  if (row.kind === "date") {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return "Use an ISO date: YYYY-MM-DD.";
    const date = new Date(`${text}T00:00:00Z`);
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== text || Number(text.slice(0, 4)) < 2000 || Number(text.slice(0, 4)) > 2100) return "Enter a real calendar date between 2000 and 2100.";
    return undefined;
  }
  if (!text || !/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(text) || !Number.isFinite(Number(text))) return "Use a finite nonnegative decimal, without currency symbols or thousands separators.";
  return undefined;
}
export function lineErrors(values: string[][], sheet: LineSheet): boolean {
  const longHorizon = sheet === "opex";
  const rows = periodRows(sheet, "quarterly", longHorizon), count = periodHeaders(sheet, "quarterly", longHorizon).length;
  return values.length !== rows.length || rows.some((row, i) => values[i]?.length !== count || (["amount", "date"].includes(row.kind) && values[i].some(value => Boolean(periodCellError(row, value)))));
}
export function pastePeriodRectangle(text: string, startRow: number, startCol: number, rows: PeriodRow[], values: string[][], sheet: LineSheet, view: PeriodView, longHorizon: boolean | number = false): { values?: string[][]; error?: string } {
  const reject = (message: string) => ({ error: `Paste rejected: ${message} Entire draft unchanged.` });
  if (!text.trim()) return reject("empty clipboard.");
  const block = text.replace(/\r/g, "").replace(/\n+$/, "").split("\n").map(r => r.split("\t"));
  const width = block[0].length, count = periodHeaders(sheet, view, longHorizon).length;
  if (!block.every(r => r.length === width)) return reject("ragged rectangle; every row must have the same column count.");
  if (!Number.isInteger(startRow) || !Number.isInteger(startCol) || startRow < 0 || startCol < 0 || startRow + block.length > rows.length || startCol + width > count) return reject("rectangle exceeds sheet bounds.");
  for (let r = 0; r < block.length; r++) for (let c = 0; c < width; c++) {
    const row = startRow + r, col = startCol + c;
    if (!isEditablePeriodCell(sheet, view, row, col, longHorizon)) return reject(`${rows[row].label} is locked (row ${row + 1}, period ${col + 1}).`);
    const error = periodCellError(rows[row], block[r][c]);
    if (error) return reject(`${rows[row].label}, period ${col + 1}: ${error}`);
  }
  const next = values.map(r => [...r]);
  for (let r = 0; r < block.length; r++) for (let c = 0; c < width; c++) next[startRow + r][startCol + c] = block[r][c].trim();
  return { values: next };
}
