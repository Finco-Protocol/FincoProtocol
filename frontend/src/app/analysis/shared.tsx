import type { VerticalInfo } from "./types";

/** Preview / closed verticals say so, so no one reads their analysis as pilot-ready. */
export function TierNote({ vertical }: { vertical: VerticalInfo }) {
  if (vertical.pilot_tier === "PILOT_CANDIDATE") return null;
  return (
    <p className="rx-note rcm-tier-note" data-vertical-tier={vertical.pilot_tier}>
      <strong>{vertical.public_name} · {vertical.pilot_tier === "PREVIEW" ? "PREVIEW" : "NOT RELEASED"}</strong> — narrower validation than Solar and Wind.
      {vertical.limitations[0] ? ` ${vertical.limitations[0]}` : ""}
    </p>
  );
}

const csvCell = (value: string) => (/[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value);

/** Copy the table exactly as displayed (tab-separated) — display strings only, nothing recomputed. */
export async function copyTsv(rows: string[][]): Promise<void> {
  const text = rows.map((r) => r.join("\t")).join("\n");
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); } finally { document.body.removeChild(area); }
  }
}

export function downloadCsv(filename: string, rows: string[][]): void {
  const blob = new Blob([rows.map((r) => r.map(csvCell).join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
