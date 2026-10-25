// WF-React-2 — client-side early validation and payload editing helpers.
//
// Presentation-only.  Every rule here mirrors a rule of the canonical
// authority (the Revenue V1/V2 contract parser, the cost-line command layer)
// purely so a user sees a field-level message before a round trip.  The server
// stays the validation authority: a value that passes here can still be
// refused, and the refusal text is displayed verbatim.  Nothing in this module
// prices, indexes, rounds or forecasts anything.

export type Parsed = { ok: true; value: number } | { ok: false; message: string };

const DECIMAL = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;

/** Strict decimal text -> number.  No thousands separators, no exponent, no
 *  whitespace-only or locale forms; the canonical parser never sees ambiguity. */
export function parseStrictDecimal(text: string): Parsed {
  const trimmed = text.trim();
  if (trimmed === "") return { ok: false, message: "A value is required." };
  if (!DECIMAL.test(trimmed)) return { ok: false, message: "Enter a plain number (digits and one decimal point)." };
  const value = Number(trimmed);
  if (!Number.isFinite(value)) return { ok: false, message: "The value must be finite." };
  return { ok: true, value };
}

export function parseNonNegative(text: string, maximum?: number): Parsed {
  const parsed = parseStrictDecimal(text);
  if (!parsed.ok) return parsed;
  if (parsed.value < 0) return { ok: false, message: "The value cannot be negative." };
  if (maximum !== undefined && parsed.value > maximum) return { ok: false, message: `The value cannot exceed ${maximum}.` };
  return parsed;
}

/** Real calendar date in strict ISO form (YYYY-MM-DD). */
export function isIsoDate(text: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return false;
  const date = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === text;
}

// ───────────────────────────── Revenue / PPA contract payload ─────────────────────────────

export interface PpaCurvePoint { period_start: string; price_eur_mwh: string }

/** Editable draft of one stream: strings exactly as the user typed them. */
export interface StreamDraft {
  id: string;
  type: string;
  start_date: string;
  end_date: string;
  /** "" means null (no explicit share: the canonical residual rule applies). */
  volume_share: string;
  price_eur_mwh: string;
  indexation_rate: string;
  source_ref: string;
  /** Only meaningful for merchant streams. */
  capture_rate: string;
  /** Present only when the stream already carries an explicit price curve. */
  curve: PpaCurvePoint[] | null;
  /** True for a stream added in this session (identity may still be edited). */
  isNew: boolean;
}

export type ContractClass = "Fixed" | "Indexed" | "Scheduled" | "Merchant" | "CfD";

const PRESERVED_KEYS = ["index_series", "indexation_timing", "price_rounding", "reference_stream_id"] as const;

export interface ContractModel {
  version: number;
  technology: string;
  streams: StreamDraft[];
  /** Per stream: canonical keys the guided editor shows read-only and preserves untouched. */
  preservedKeys: string[][];
}

type JsonRecord = Record<string, unknown>;

function text(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

export type ParseResult = { ok: true; model: ContractModel } | { ok: false; message: string };

/** Parse the canonical `contracts.raw` string into an editable model.  Version 3
 *  (advanced products, release-closed) and anything unrecognised is refused so
 *  the guided editor can never rewrite a payload it does not fully understand. */
export function parseContractModel(raw: string): ParseResult {
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return { ok: false, message: "The stored contract payload is not readable JSON." };
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, message: "The stored contract payload has an unexpected shape." };
  }
  const record = payload as JsonRecord;
  if (record.version !== 1 && record.version !== 2) {
    return { ok: false, message: "This contract payload uses a version the guided editor does not edit (read-only)." };
  }
  if (!Array.isArray(record.streams)) return { ok: false, message: "The stored contract payload has no stream list." };
  const streams: StreamDraft[] = [];
  const preservedKeys: string[][] = [];
  for (const row of record.streams as unknown[]) {
    if (!row || typeof row !== "object" || Array.isArray(row)) return { ok: false, message: "A stored stream has an unexpected shape." };
    const r = row as JsonRecord;
    streams.push({
      id: text(r.id), type: text(r.type), start_date: text(r.start_date), end_date: text(r.end_date),
      volume_share: text(r.volume_share), price_eur_mwh: text(r.price_eur_mwh),
      indexation_rate: text(r.indexation_rate), source_ref: text(r.source_ref),
      capture_rate: text(r.capture_rate),
      curve: Array.isArray(r.price_curve)
        ? (r.price_curve as JsonRecord[]).map((point) => ({
          period_start: text(point.period_start), price_eur_mwh: text(point.price_eur_mwh) }))
        : null,
      isNew: false,
    });
    preservedKeys.push(PRESERVED_KEYS.filter((key) => key in r));
  }
  return { ok: true, model: { version: record.version as number, technology: text(record.technology), streams, preservedKeys } };
}

export function contractClass(stream: StreamDraft, preserved: string[]): ContractClass {
  if (stream.type === "merchant") return "Merchant";
  if (stream.type === "cfd") return "CfD";
  if (stream.curve) return "Scheduled";
  const rate = Number(stream.indexation_rate);
  if ((Number.isFinite(rate) && rate > 0) || preserved.includes("index_series") || preserved.includes("indexation_timing")) {
    return "Indexed";
  }
  return "Fixed";
}

export type FieldErrors = Record<string, string>;

/** Early field-level validation.  Keys are `streams.<index>.<field>` and
 *  `streams.<index>.curve.<pointIndex>.<field>` plus `form` for payload-level issues. */
export function validateContractModel(model: ContractModel): FieldErrors {
  const errors: FieldErrors = {};
  if (model.streams.length < 1 || model.streams.length > 24) {
    errors.form = "A contract book needs between 1 and 24 explicit contracts.";
  }
  const seen = new Set<string>();
  model.streams.forEach((s, i) => {
    const key = (field: string) => `streams.${i}.${field}`;
    const id = s.id.trim();
    if (!id || id.length > 200) errors[key("id")] = "A contract identity of 1-200 characters is required.";
    else if (seen.has(id)) errors[key("id")] = "Contract identities must be unique.";
    seen.add(id);
    if (!s.source_ref.trim() || s.source_ref.length > 200) errors[key("source_ref")] = "A source reference of 1-200 characters is required.";
    const startOk = isIsoDate(s.start_date), endOk = isIsoDate(s.end_date);
    if (!startOk) errors[key("start_date")] = "Use a real date in YYYY-MM-DD form.";
    if (!endOk) errors[key("end_date")] = "Use a real date in YYYY-MM-DD form.";
    if (startOk && endOk && s.end_date <= s.start_date) errors[key("end_date")] = "The end date must follow the start date.";
    const price = parseNonNegative(s.price_eur_mwh);
    if (!price.ok) errors[key("price_eur_mwh")] = price.message;
    const index = parseNonNegative(s.indexation_rate, 1);
    if (!index.ok) errors[key("indexation_rate")] = index.message;
    if (s.volume_share.trim() !== "") {
      const share = parseNonNegative(s.volume_share, 1);
      if (!share.ok) errors[key("volume_share")] = share.message;
    } else if (s.type !== "merchant") {
      errors[key("volume_share")] = "An explicit volume share is required (only a merchant contract may take the residual).";
    }
    if (s.type === "merchant" && s.capture_rate.trim() !== "") {
      const capture = parseNonNegative(s.capture_rate, 1);
      if (!capture.ok) errors[key("capture_rate")] = capture.message;
    }
    if (s.curve) {
      if (model.version !== 2) errors[key("curve")] = "Explicit price curves require a version-2 contract book.";
      if (index.ok && index.value !== 0) errors[key("indexation_rate")] = "A contract with an explicit price curve cannot also be indexed (rate must be 0).";
      if (s.curve.length < 1 || s.curve.length > 600) errors[key("curve")] = "Provide between 1 and 600 price points.";
      let previous = "";
      s.curve.forEach((point, p) => {
        const pointKey = `streams.${i}.curve.${p}`;
        if (!isIsoDate(point.period_start)) errors[`${pointKey}.period_start`] = "Use a real date in YYYY-MM-DD form.";
        else {
          if (startOk && endOk && (point.period_start < s.start_date || point.period_start >= s.end_date)) {
            errors[`${pointKey}.period_start`] = "The point lies outside the contract tenor.";
          }
          if (previous && point.period_start <= previous) {
            errors[`${pointKey}.period_start`] = "Points must be strictly ascending (no duplicates or overlaps).";
          }
          previous = point.period_start;
        }
        const pointPrice = parseNonNegative(point.price_eur_mwh);
        if (!pointPrice.ok) errors[`${pointKey}.price_eur_mwh`] = pointPrice.message;
      });
    }
  });
  return errors;
}

/** Produce the canonical payload JSON: the ORIGINAL payload with only the
 *  guided scalar fields replaced.  Keys the editor does not own (index series,
 *  indexation timing, price rounding, CfD reference, settlement, basis) are
 *  carried over byte-identically from `originalRaw`; a new stream receives only
 *  the explicit canonical PPA keys.  Returns null if the original is unreadable. */
export function buildContractPayload(originalRaw: string, model: ContractModel): string | null {
  let original: JsonRecord;
  try {
    original = JSON.parse(originalRaw) as JsonRecord;
  } catch {
    return null;
  }
  const originalStreams = Array.isArray(original.streams) ? (original.streams as JsonRecord[]) : [];
  const streams = model.streams.map((s, i) => {
    const base: JsonRecord = !s.isNew && originalStreams[i] ? { ...originalStreams[i] } : { settlement: "SAME_PERIOD" };
    base.id = s.id.trim();
    base.type = s.type;
    base.start_date = s.start_date;
    base.end_date = s.end_date;
    base.volume_share = s.volume_share.trim() === "" ? null : Number(s.volume_share);
    base.price_eur_mwh = Number(s.price_eur_mwh);
    base.indexation_rate = Number(s.indexation_rate);
    base.source_ref = s.source_ref.trim();
    if (s.type === "merchant" && s.capture_rate.trim() !== "") base.capture_rate = Number(s.capture_rate);
    if (s.curve) {
      base.price_curve = s.curve.map((p) => ({ period_start: p.period_start, price_eur_mwh: Number(p.price_eur_mwh) }));
    }
    return base;
  });
  return JSON.stringify({ ...original, streams });
}

/** `base`, `base-2`, `base-3`… not already present in `existing`. */
export function nextUniqueId(existing: string[], base: string): string {
  const taken = new Set(existing.map((id) => id.trim()));
  if (!taken.has(base)) return base;
  for (let n = 2; n < 10_000; n += 1) {
    const candidate = `${base}-${n}`;
    if (!taken.has(candidate)) return candidate;
  }
  return `${base}-${Date.now()}`;
}

export function newPpaStream(existing: StreamDraft[], operatingWindow: { start: string; end: string } | null): StreamDraft {
  return {
    id: nextUniqueId(existing.map((s) => s.id), "ppa"),
    type: "ppa",
    start_date: operatingWindow?.start ?? "",
    end_date: operatingWindow?.end ?? "",
    volume_share: "",
    price_eur_mwh: "",
    indexation_rate: "0",
    source_ref: "",
    capture_rate: "",
    curve: null,
    isNew: true,
  };
}

/** Number of leaf edits between the persisted model and the draft. */
export function countContractEdits(saved: ContractModel, draft: ContractModel): number {
  let count = Math.abs(saved.streams.length - draft.streams.length);
  const fields: Array<keyof StreamDraft> = ["id", "start_date", "end_date", "volume_share", "price_eur_mwh", "indexation_rate", "source_ref", "capture_rate"];
  draft.streams.forEach((s, i) => {
    const before = saved.streams[i];
    if (!before) { count += 1; return; }
    for (const field of fields) if (before[field] !== s[field]) count += 1;
    if (JSON.stringify(before.curve) !== JSON.stringify(s.curve)) count += 1;
  });
  return count;
}

// ───────────────────────────── Cost lines ─────────────────────────────

export interface NewCostLineDraft { group: string; label: string; amount_keur: string; inflation_pct: string; notes: string }

export function validateNewCostLine(draft: NewCostLineDraft, sheet: "capex" | "opex", eligible: string[]): FieldErrors {
  const errors: FieldErrors = {};
  if (!eligible.includes(draft.group)) errors.group = "Choose a group that accepts custom lines.";
  if (!draft.label.trim()) errors.label = "A line label is required.";
  else if (draft.label.trim().length > 200) errors.label = "Keep the label within 200 characters.";
  const amount = parseStrictDecimal(draft.amount_keur);
  if (!amount.ok) errors.amount_keur = amount.message;
  if (sheet === "opex") {
    const infl = parseStrictDecimal(draft.inflation_pct);
    if (!infl.ok) errors.inflation_pct = infl.message;
  }
  return errors;
}

// ───────────────────────────── Scenario overrides ─────────────────────────────

export function validateOverrideValue(textValue: string): string | null {
  const parsed = parseNonNegative(textValue);
  return parsed.ok ? null : parsed.message;
}
