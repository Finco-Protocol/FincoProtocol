import type { LibraryProjectViewModel } from "./viewModels";

export const SYNTHETIC_REFERENCE_PROJECTS: readonly LibraryProjectViewModel[] = [
  { name: "Adriatic Solar I", id: "PRJ-0241", technology: "Solar PV", size: "120 MWp", region: "Dalmatia, Croatia", stage: "Credit review", tone: "blue", updated: "18 Jun 2025", sponsor: "Asterion Renewables", sourceKind: "reference" },
  { name: "North Ridge Wind", id: "PRJ-0236", technology: "Onshore wind", size: "86 MW", region: "Zadar County, Croatia", stage: "Base case", tone: "green", updated: "16 Jun 2025", sponsor: "Meridian Energy Partners", sourceKind: "reference" },
  { name: "Vela Storage", id: "PRJ-0228", technology: "Solar + BESS", size: "72 MWp / 40 MW", region: "Istria, Croatia", stage: "Draft", tone: "gray", updated: "12 Jun 2025", sponsor: "Lumen Infrastructure", sourceKind: "reference" },
  { name: "Orsini Solar Park", id: "PRJ-0219", technology: "Solar PV", size: "154 MWp", region: "Puglia, Italy", stage: "Needs review", tone: "amber", updated: "09 Jun 2025", sponsor: "Civitas Power Holdings", sourceKind: "reference" },
  { name: "Balkan Coast Wind", id: "PRJ-0204", technology: "Onshore wind", size: "98 MW", region: "Split-Dalmatia, Croatia", stage: "Credit review", tone: "blue", updated: "04 Jun 2025", sponsor: "Asterion Renewables", sourceKind: "reference" },
];
