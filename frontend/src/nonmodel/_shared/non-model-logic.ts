import { DEMO_CLOCK_ISO, type Instrument } from "./fixtures.ts";

export type LegName = "market" | "reference";
export type EvidenceStatus = "AVAILABLE" | "STALE" | "UNAVAILABLE";
export type AlertDraft = {
  name: string;
  threshold: number;
  state: "DRAFT" | "PAUSED";
  fixtureId: string;
};

export function categoryForRoute(path: string) {
  if (path === "/radar/stocks") return "Stocks";
  if (path === "/radar/crypto") return "Crypto";
  if (path === "/radar/tokenized") return "Tokenized Markets";
  if (path === "/radar/economy") return "Economy";
  return "All";
}

export function isRadarDestination(path: string) {
  return ["/radar", "/radar/r-live", "/radar/tokenized", "/radar/stocks", "/radar/crypto", "/radar/economy"].includes(path);
}

export function radarDefaultFilters(path: string) {
  return { query: "", category: categoryForRoute(path), status: "All statuses" };
}

export function radarFiltersActive(path: string, filters: { query: string; category: string; status: string }) {
  const defaults = radarDefaultFilters(path);
  return filters.query !== defaults.query || filters.category !== defaults.category || filters.status !== defaults.status;
}

export function handleRadarRowKeyDown(
  event: { key: string; repeat: boolean; target: unknown; currentTarget: unknown; preventDefault(): void },
  select: () => void,
) {
  // Let nested native controls own their keyboard activation.
  if (event.target !== event.currentTarget || (event.key !== "Enter" && event.key !== " ")) return;
  event.preventDefault();
  if (!event.repeat) select();
}

export function handleWatchlistButtonKeyDown(
  event: { key: string; repeat: boolean; preventDefault(): void; stopPropagation(): void },
  toggle: () => void,
) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  event.stopPropagation();
  if (!event.repeat) toggle();
}

export function demoAgeSeconds(timestamp: string, demoClock = DEMO_CLOCK_ISO): number | null {
  const observed = Date.parse(timestamp);
  const clock = Date.parse(demoClock);
  if (!Number.isFinite(observed) || !Number.isFinite(clock)) return null;
  return (clock - observed) / 1000;
}

export function formatDemoAge(ageSeconds: number | null) {
  if (ageSeconds === null) return "age unavailable";
  if (ageSeconds < 0) return "future timestamp · invalid";
  if (ageSeconds < 60) return `${Math.floor(ageSeconds)}s old`;
  const minutes = Math.floor(ageSeconds / 60);
  const seconds = Math.floor(ageSeconds % 60);
  return `${minutes}m ${String(seconds).padStart(2, "0")}s old`;
}

export function legAgeSeconds(item: Instrument, leg: LegName) {
  return demoAgeSeconds(leg === "market" ? item.marketAt : item.referenceAt);
}

export function legStatusAtDemoClock(item: Instrument, leg: LegName): EvidenceStatus {
  const value = leg === "market" ? item.market : item.reference;
  const declared = leg === "market" ? item.marketStatus : item.referenceStatus;
  const timestamp = leg === "market" ? item.marketAt : item.referenceAt;
  const age = legAgeSeconds(item, leg);
  if (declared === "UNAVAILABLE" || value === null || !Number.isFinite(value) ||
      (leg === "reference" && value <= 0) || age === null) return "UNAVAILABLE";
  if (declared === "STALE" || age < 0 || age > 300) return "STALE";
  if (!Number.isFinite(Date.parse(timestamp))) return "UNAVAILABLE";
  return "AVAILABLE";
}

export function pairAssessment(item: Instrument) {
  const marketAge = legAgeSeconds(item, "market");
  const referenceAge = legAgeSeconds(item, "reference");
  const marketStatus = legStatusAtDemoClock(item, "market");
  const referenceStatus = legStatusAtDemoClock(item, "reference");
  const marketTime = Date.parse(item.marketAt);
  const referenceTime = Date.parse(item.referenceAt);
  const skewSeconds = Number.isFinite(marketTime) && Number.isFinite(referenceTime)
    ? Math.abs(marketTime - referenceTime) / 1000
    : null;
  const numericPairValid = item.market !== null && Number.isFinite(item.market) &&
    item.reference !== null && Number.isFinite(item.reference) && item.reference > 0;
  const eligible = numericPairValid &&
    marketStatus === "AVAILABLE" &&
    referenceStatus === "AVAILABLE" &&
    marketAge !== null && marketAge >= 0 && marketAge <= 300 &&
    referenceAge !== null && referenceAge >= 0 && referenceAge <= 300 &&
    skewSeconds !== null && skewSeconds <= 300;
  const pairStatus: EvidenceStatus = eligible
    ? "AVAILABLE"
    : marketStatus === "UNAVAILABLE" || referenceStatus === "UNAVAILABLE" || !numericPairValid
      ? "UNAVAILABLE"
      : "STALE";
  return { eligible, pairStatus, marketStatus, referenceStatus, marketAge, referenceAge, skewSeconds };
}

export function isCurrentPairEligible(item: Instrument) {
  return pairAssessment(item).eligible;
}

export function currentLegValue(item: Instrument, leg: LegName): number | null {
  if (!pairAssessment(item).eligible) return null;
  const value = leg === "market" ? item.market : item.reference;
  return value !== null && Number.isFinite(value) ? value : null;
}

export function lastHistoricalLeg(item: Instrument, leg: LegName) {
  return {
    value: leg === "market" ? item.market : item.reference,
    timestamp: leg === "market" ? item.marketAt : item.referenceAt,
    ageSeconds: legAgeSeconds(item, leg),
    status: legStatusAtDemoClock(item, leg),
  };
}

export function currentPremiumDiscount(item: Instrument): number | null {
  if (!isCurrentPairEligible(item)) return null;
  const result = ((item.market! - item.reference!) / item.reference!) * 100;
  return Number.isFinite(result) ? result : null;
}

type IllustrativeRange = "1h" | "24h";

function stableIllustrativeSeed(instrumentId: string, range: IllustrativeRange, series: "a" | "b") {
  const input = `${instrumentId}\u0000${range}\u0000${series}`;
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) % 100_000;
}

function illustrativeCurve(seed: number, count = 28) {
  return Array.from({ length: count }, (_, index) => {
    const wave = Math.sin((index + seed) * 0.57) * 12 +
      Math.cos((index + seed) * 0.19) * 8 + index * 0.7;
    return `${(index / (count - 1)) * 700},${92 - wave}`;
  }).join(" ");
}

export function illustrativeChartData(item: Instrument, range: IllustrativeRange) {
  // Suppressed pairs never contribute data to the illustrative chart.
  if (!isCurrentPairEligible(item)) return null;
  return {
    shapeA: illustrativeCurve(stableIllustrativeSeed(item.id, range, "a")),
    shapeB: illustrativeCurve(stableIllustrativeSeed(item.id, range, "b")),
  };
}

export function isTokenizedRepresentation(item: Instrument) {
  return item.category === "Tokenized Markets" ||
    item.category === "Stablecoins" ||
    item.representation.toLowerCase().includes("synthetic erc-20 wrapper");
}

export function filterInstruments(
  rows: Instrument[],
  { query = "", category = "All", status = "All statuses" }: { query?: string; category?: string; status?: string } = {},
) {
  const normalizedQuery = query.trim().toLowerCase();
  return rows.filter(item => {
    const matchesText = !normalizedQuery ||
      `${item.symbol} ${item.name} ${item.category} ${item.chain} ${item.instrumentId}`.toLowerCase().includes(normalizedQuery);
    const matchesCategory = category === "All" ||
      item.category === category ||
      (category === "Tokenized Markets" && isTokenizedRepresentation(item));
    const eligible = isCurrentPairEligible(item);
    const matchesStatus = status === "All statuses" ||
      (status === "Available" ? eligible : !eligible);
    return matchesText && matchesCategory && matchesStatus;
  });
}

export function toggleWatchlist(current: string[], fixtureId: string): string[] {
  return current.includes(fixtureId)
    ? current.filter(id => id !== fixtureId)
    : [...current, fixtureId];
}

export type AlertValidation = { ok: true; alert: AlertDraft } | { ok: false; error: string };

export function createAlertDraft(name: string, thresholdInput: string, fixtureId = "fx-demo-001"): AlertValidation {
  const normalizedName = name.trim();
  if (!normalizedName) return { ok: false, error: "Enter an alert name." };
  const threshold = Number(thresholdInput);
  if (!thresholdInput || !Number.isFinite(threshold) || threshold <= 0 || threshold > 100) {
    return { ok: false, error: "Enter a threshold greater than 0 and no more than 100." };
  }
  return { ok: true, alert: { name: normalizedName, threshold, state: "DRAFT", fixtureId } };
}

export function saveAlertDraft(alerts: AlertDraft[], alert: AlertDraft, editingIndex: number | null) {
  if (editingIndex === null) return [...alerts, alert];
  return alerts.map((existing, index) => index === editingIndex
    ? { ...alert, state: existing.state }
    : existing);
}

export function toggleAlertState(alert: AlertDraft): AlertDraft {
  return { ...alert, state: alert.state === "DRAFT" ? "PAUSED" : "DRAFT" };
}

export function removeAlert(alerts: AlertDraft[], index: number): AlertDraft[] {
  return alerts.filter((_, currentIndex) => currentIndex !== index);
}

export function removeAlertAndAdjustEditing(
  alerts: AlertDraft[],
  removeIndex: number,
  editingIndex: number | null,
) {
  const nextEditingIndex = editingIndex === null
    ? null
    : editingIndex === removeIndex
      ? null
      : editingIndex > removeIndex
        ? editingIndex - 1
        : editingIndex;
  return { alerts: removeAlert(alerts, removeIndex), editingIndex: nextEditingIndex };
}

export function alertReadiness(item: Instrument | undefined): EvidenceStatus {
  if (!item) return "UNAVAILABLE";
  return pairAssessment(item).pairStatus;
}

export function lifecycleForInstrument(item: Instrument) {
  return [
    {
      canonicalId: item.id,
      at: item.marketAt,
      event: "Market observation",
      detail: `${item.venue} · ${item.marketStatus} · deterministic fixture value.`,
      state: legStatusAtDemoClock(item, "market"),
    },
    {
      canonicalId: item.id,
      at: item.referenceAt,
      event: "Reference observation",
      detail: `Reference evidence · ${item.referenceStatus} · deterministic fixture value.`,
      state: legStatusAtDemoClock(item, "reference"),
    },
    {
      canonicalId: item.id,
      at: DEMO_CLOCK_ISO,
      event: "Identity review",
      detail: `${item.instrumentId} · synthetic identity, not production-verified.`,
      state: "PREVIEW",
    },
  ];
}
