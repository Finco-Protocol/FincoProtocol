import React, { useEffect, useMemo, useRef, useState } from "react";
import { fincoBasePath, readProjectContext } from "../_shared/FincoShell";
import { preferredScrollBehavior } from "../_shared/motion";
import { statementCellTabIndex, statementCellText, statementStatusText, type StatementFacilityId, type StatementRow, type StatementSheet, type StatementSheetId, type StatementViewId, type StatementWorkbookProps } from "./statementContract";
import "./statements.css";
import {
  DISPLAY_UNITS, formatStatementCell, formatUnitLabel, classifyRowUnit, formatFromCanonicalUnit, resolveRowFormat, sheetUnitLabel,
  type DisplayUnit, type RowFormat,
} from "../../app/units";

type SheetId = StatementSheetId;
type ViewId = StatementViewId;
type FacilityId = StatementFacilityId;
type Row = StatementRow;
type Sheet = StatementSheet;

const validSheetIds: SheetId[] = ["pl", "balance", "cashflow", "cfads", "debt", "sponsor"];
const initialSheet = (): SheetId => {
  const fromUrl = new URLSearchParams(window.location.search).get("statement");
  return validSheetIds.includes(fromUrl as SheetId) ? (fromUrl as SheetId) : "pl";
};
const initialView = (): ViewId => new URLSearchParams(window.location.search).get("statementView") === "model" ? "model" : "annual";
type UnitDisplay = DisplayUnit;
type DataOrigin = NonNullable<StatementWorkbookProps["status"]["dataOrigin"]>;
const rowFormatOf = (row: Row, sheet: Sheet): RowFormat => resolveRowFormat(row.label, row.unit, sheet.unit);
const rowUnitSource = (row: Row, sheet: Sheet) => classifyRowUnit(row.label, row.unit, sheet.unit).source;
/** The row's canonical (source) unit label, "unit unavailable" when metadata is ambiguous. */
const canonicalUnitText = (row: Row, sheet: Sheet): string => {
  const format = rowFormatOf(row, sheet);
  return format.kind === "money" ? format.base : format.kind === "ratio" ? "x" : format.kind === "percent" ? "%" : "unit unavailable";
};
/** Display conversion only: canonical text in the sheet's canonical unit -> chosen display unit. */
function displayStatementValue(value: string, format: RowFormat, unit: UnitDisplay, precision: number) {
  return formatStatementCell(value, format, unit, precision);
}
const defaultDisplayUnit = (sheets: Sheet[]): UnitDisplay => {
  const canonical = formatFromCanonicalUnit(sheets[0]?.unit);
  return canonical?.kind === "money" ? canonical.base : "kEUR";
};

const traceSources: Record<string, { label: string; sheet: string }> = {
  revenue: { label: "Revenue / PPA", sheet: "revenue" },
  "ppa-revenue": { label: "Revenue / PPA", sheet: "revenue" },
  "merchant-revenue": { label: "Revenue / merchant residual", sheet: "revenue" },
  ebitda: { label: "Revenue / OPEX assumptions", sheet: "revenue" },
  ebit: { label: "OPEX / tax assumptions", sheet: "opex" },
  pbt: { label: "Tax & timing", sheet: "tax" },
  "net-income": { label: "Tax & timing", sheet: "tax" },
  "sponsor-contributions": { label: "Investor / sponsor equity", sheet: "investor" },
  opex: { label: "OPEX / operating profiles", sheet: "opex" },
  "site-costs": { label: "OPEX / operating profiles", sheet: "opex" },
  "service-costs": { label: "OPEX / operating profiles", sheet: "opex" },
  depreciation: { label: "CAPEX / Tax", sheet: "tax" },
  "depreciation-detail": { label: "CAPEX / Tax", sheet: "tax" },
  amortisation: { label: "CAPEX / Tax", sheet: "tax" },
  tax: { label: "Tax & timing", sheet: "tax" },
  "cash-tax": { label: "Tax & timing", sheet: "tax" },
  "cash-tax-interest": { label: "Tax & timing", sheet: "tax" },
  "working-capital": { label: "OPEX / operating profiles", sheet: "opex" },
  "net-change": { label: "Cash Flow statement fixture", sheet: "sources-uses" },
  "cash-opening": { label: "Sources & Uses / cash context", sheet: "sources-uses" },
  "cash-closing": { label: "Sources & Uses / cash context", sheet: "sources-uses" },
  "finance-cost": { label: "Financing / facilities", sheet: "senior-debt" },
  "interest-expense": { label: "Financing / facilities", sheet: "senior-debt" },
  "fees-amortised": { label: "Financing / facilities", sheet: "senior-debt" },
  "senior-interest": { label: "Financing / Senior facility", sheet: "senior-debt" },
  "senior-principal": { label: "Financing / Senior facility", sheet: "senior-debt" },
  "senior-closing": { label: "Financing / Senior facility", sheet: "senior-debt" },
  "senior-fee": { label: "Financing / Senior facility", sheet: "senior-debt" },
  "debt-balance": { label: "Financing / debt schedule", sheet: "senior-debt" },
  "debt-cf": { label: "Financing / debt schedule", sheet: "senior-debt" },
  "senior-draw": { label: "Financing / debt schedule", sheet: "senior-debt" },
  "senior-opening": { label: "Financing / debt schedule", sheet: "senior-debt" },
  "senior-service": { label: "Financing / debt schedule", sheet: "senior-debt" },
  "mezz-draw": { label: "Financing / debt schedule", sheet: "senior-debt" },
  "cfads-total": { label: "CFADS / fixed statement", sheet: "cfads" },
  "scheduled-service": { label: "Debt schedule / fixed statement", sheet: "debt" },
  "cash-equity": { label: "Investor / sponsor returns", sheet: "investor" },
  "sponsor-net-cash": { label: "Investor / sponsor returns", sheet: "investor" },
  "sponsor-distributions": { label: "Investor / sponsor returns", sheet: "investor" },
  "sponsor-irr": { label: "Investor / sponsor returns", sheet: "investor" },
  "sponsor-moic": { label: "Investor / sponsor returns", sheet: "investor" },
};
const traceParentByChild: Record<string, string> = {
  "ppa-revenue": "revenue", "merchant-revenue": "revenue", "site-costs": "opex", "service-costs": "opex",
  "depreciation-detail": "depreciation", amortisation: "depreciation", "interest-expense": "finance-cost",
  "fees-amortised": "finance-cost", "cash-receipts": "operating-cf", "cash-operating": "operating-cf",
  "cash-tax-interest": "operating-cf", capex: "investing-cf", "reserve-funding": "investing-cf",
  "debt-cf": "financing-cf", "equity-cf": "financing-cf", "cfads-revenue": "cfads-ebitda",
  "cfads-costs": "cfads-ebitda", dsra: "reserve-movement", "maintenance-reserve": "reserve-movement",
  "principal-service": "scheduled-service", "interest-service": "scheduled-service",
  "senior-construction-draw": "senior-draw", "senior-fee-draw": "senior-draw",
  "senior-idc-cap": "senior-idc", "mezz-construction-draw": "mezz-draw",
  "mezz-fee-draw": "mezz-draw", "mezz-idc-cap": "mezz-idc",
  "sponsor-operating-distribution": "sponsor-distributions", "sponsor-exit-distribution": "sponsor-distributions",
};
function initialExpandedState() {
  const params = new URLSearchParams(window.location.search);
  const sheet = initialSheet();
  const parent = traceParentByChild[params.get("traceRow") || ""];
  let restored: Record<string, boolean> = {};
  try {
    const raw = params.get("returnExpanded");
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, boolean>;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) restored = parsed;
    }
  } catch {
    restored = {};
  }
  return parent ? { ...restored, [`${sheet}:${parent}`]: true } : restored;
}

function formatExpressionLabel(label: string) {
  return label.toUpperCase().replace(/[^\w]+/g, "_").replace(/^_|_$/g, "");
}

function StatementTable({
  sheet,
  periods,
  view,
  expanded,
  onToggleGroup,
  traceId,
  setTraceId,
  tracePeriod,
  setTracePeriod,
  unit,
  precision,
  showInitialPeriod,
  facility,
  periodBands: visiblePeriodBands,
  regionRef,
  dataOrigin,
  runId,
}: {
  sheet: Sheet;
  periods: string[];
  view: ViewId;
  expanded: Record<string, boolean>;
  onToggleGroup: (id: string) => void;
  traceId: string | null;
  setTraceId: (id: string | null) => void;
  tracePeriod: number;
  setTracePeriod: (period: number) => void;
  unit: UnitDisplay;
  precision: number;
  showInitialPeriod: boolean;
  facility: FacilityId;
  periodBands: { label: string; span: number }[];
  regionRef: React.RefObject<HTMLDivElement>;
  dataOrigin: DataOrigin;
  runId: string;
}) {
  const periodIndexes = periods.map((_, index) => view === "model" && !showInitialPeriod ? index + 1 : index);
  const rows = useMemo(() => {
    const visible: Row[] = [];
    sheet.rows.forEach((item) => {
      visible.push(item);
      if (item.children && expanded[`${sheet.id}:${item.id}`]) visible.push(...item.children);
    });
    return visible;
  }, [expanded, sheet]);
  return <div
    className="fm-sw-region"
    role="region"
    aria-label={`${sheet.title}, scrollable financial periods`}
    aria-describedby="fm-sw-scroll-help fm-sw-grid-help"
    tabIndex={0}
    ref={regionRef}
    onKeyDown={(event) => {
      if (event.target !== event.currentTarget) return;
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        event.currentTarget.scrollBy({ left: event.key === "ArrowRight" ? 120 : -120 });
      }
    }}
  >
    <span id="fm-sw-grid-help" className="fm-sr-only">Only the active statement value is in the page Tab order. Use the arrow keys to move between values; press Enter to {dataOrigin === "canonical-run" ? "show the canonical source" : "open the source navigation reference"}. Tab leaves the table.</span>
    <table className="fm-sw-table">
      <caption className="fm-sr-only">{sheet.title}, {dataOrigin === "synthetic-demo" ? "fixed synthetic example rows" : dataOrigin === "canonical-run" ? "persisted Run rows" : dataOrigin === "caller-provided" ? "supplied rows" : "unavailable rows"}, {view === "annual" ? "annual" : "model periods"}.{dataOrigin === "canonical-run" ? ` Values in ${unit} unless a row states another unit.` : " Illustrative financial statement with selected sample rows."}</caption>
      <thead>
        {view === "annual" ? <tr><th scope="col">Statement line · {dataOrigin === "canonical-run" ? unit : sheet.unit}</th><th scope="colgroup" colSpan={periods.length}>Operating years</th></tr> :
          <tr><th scope="col">Statement line · {dataOrigin === "canonical-run" ? unit : sheet.unit}</th>{visiblePeriodBands.map((band, index) => {
            const span = index === 0 && !showInitialPeriod ? band.span - 1 : band.span;
            return span > 0 ? <th key={band.label} scope="colgroup" colSpan={span}>{band.label}</th> : null;
          })}</tr>}
        <tr><th scope="col">{dataOrigin === "synthetic-demo" ? "Fixed example rows" : dataOrigin === "canonical-run" ? "Line items" : dataOrigin === "caller-provided" ? "Provided rows" : "Unavailable"}</th>{periods.map((period) => <th scope="col" key={period}>{period}</th>)}</tr>
      </thead>
      <tbody>
          {rows.map((item, rowIndex) => {
          const isOpen = Boolean(item.children && expanded[`${sheet.id}:${item.id}`]);
          const values = view === "annual" ? item.annual : item.model;
          const format = rowFormatOf(item, sheet);
          const rowUnit = formatUnitLabel(format, unit);
          const traceOpen = traceId === item.id;
            const source = traceSources[item.id] || { label: "Workbook source category", sheet: "input-grid" };
            const inputParams = new URLSearchParams(window.location.search);
            inputParams.delete("statement");
            inputParams.set("sheet", source.sheet);
            inputParams.set("returnStatement", sheet.id);
            inputParams.set("returnView", view);
            inputParams.set("returnRow", item.id);
            inputParams.set("returnPeriod", String(tracePeriod));
            inputParams.set("returnShowInitial", showInitialPeriod ? "1" : "0");
            inputParams.set("returnFacility", facility);
            inputParams.set("returnExpanded", JSON.stringify(expanded));
            inputParams.set("returnScrollLeft", String(regionRef.current?.scrollLeft || 0));
            inputParams.set("returnScrollY", String(Math.round(window.scrollY)));
            const sourceHref = `${fincoBasePath()}ModelWorkspace?${inputParams.toString()}#workbook`;
          return <React.Fragment key={item.id}>
            <tr data-unit-source={rowUnitSource(item, sheet)} data-row-unit={rowUnit} className={`${item.kind === "section" ? "fm-sw-section" : item.kind === "detail" ? "fm-sw-detail" : ""}${traceOpen ? " fm-sw-row-selected" : ""}`}>
              <th scope="row" className="fm-sw-label">
                <span className="fm-sw-row-select">
                  {item.children && <button
                    className="fm-sw-row-select"
                    type="button"
                    aria-label={`${isOpen ? "Collapse" : "Expand"} ${item.label} detail rows`}
                    aria-expanded={isOpen}
                    onClick={() => onToggleGroup(item.id)}
                  ><span className="fm-sw-chevron" aria-hidden="true">{isOpen ? "▾" : "▸"}</span></button>}
                  <button className="fm-sw-row-select" type="button" aria-expanded={traceOpen} onClick={() => setTraceId(traceOpen ? null : item.id)}>
                    {item.label}{dataOrigin === "canonical-run" && format.kind !== "money" && <span className="fm-sw-row-unit"> ({rowUnit})</span>}
                  </button>
                </span>
              </th>
              {periodIndexes.map((sourceIndex, index) => {
                const value = values[sourceIndex] || "—";
                return <td key={`${item.id}-${sourceIndex}`} className={`${traceOpen && tracePeriod === index ? "fm-sw-cell-selected" : traceId && tracePeriod === index ? "fm-sw-col-selected" : ""}${traceOpen ? " fm-sw-row-active-cell" : ""}`}>
                <button
                  type="button"
                  className="fm-sw-cell-button"
                  tabIndex={statementCellTabIndex(item.id, index, traceId, tracePeriod, rowIndex === 0 && index === 0)}
                  data-statement-row={item.id}
                  data-statement-col={index}
                  aria-label={`${item.label}, ${periods[index]}, ${displayStatementValue(value, format, unit, precision)} ${rowUnit}. ${dataOrigin === "synthetic-demo" ? "Open synthetic source trace." : dataOrigin === "canonical-run" ? "Show canonical source." : "Open display navigation reference."}`}
                  onClick={() => { setTraceId(item.id); setTracePeriod(index); }}
                  onKeyDown={event => {
                    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
                    event.preventDefault();
                    const nextRow = Math.max(0, Math.min(rows.length - 1, rowIndex + (event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0)));
                    const nextColumn = Math.max(0, Math.min(periods.length - 1, index + (event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0)));
                    const targetRowId = rows[nextRow].id;
                    setTraceId(targetRowId);
                    setTracePeriod(nextColumn);
                    event.currentTarget.closest("table")?.querySelector<HTMLButtonElement>(`button[data-statement-row="${targetRowId}"][data-statement-col="${nextColumn}"]`)?.focus();
                  }}
                >{displayStatementValue(value, format, unit, precision)}</button>
              </td>;
              })}
            </tr>
            {traceOpen && dataOrigin === "canonical-run" && <tr className="fm-sw-trace-row" data-canonical-source="true">
              <th scope="row" className="fm-sw-trace-cell" colSpan={periods.length + 1}>
                <div className="fm-sw-trace">
                  <div className="fm-sw-trace-copy">
                    <strong>CANONICAL SOURCE · {item.label} · {periods[tracePeriod]}</strong>
                    <span className="fm-sw-trace-code">{displayStatementValue(values[periodIndexes[tracePeriod]] || "—", format, unit, precision)} {rowUnit} · persisted value {statementCellText(values[periodIndexes[tracePeriod]])} {canonicalUnitText(item, sheet)}</span>
                    <span>Statement: {sheet.title} · persisted Run {runId}. Unit conversion and rounding are display-only.</span>
                  </div>
                  <button className="fm-sw-trace-close" type="button" onClick={() => setTraceId(null)}>Close</button>
                </div>
              </th>
            </tr>}
            {traceOpen && dataOrigin !== "canonical-run" && <tr className="fm-sw-trace-row">
              <th scope="row" className="fm-sw-trace-cell" colSpan={periods.length + 1}>
                <div className="fm-sw-trace">
                  <div className="fm-sw-trace-copy">
                    <strong>SYNTHETIC SOURCE TRACE · {item.label} · {periods[tracePeriod]}</strong>
                    <span className="fm-sw-trace-code">{formatExpressionLabel(item.label)} = fixed illustrative value · {displayStatementValue(values[periodIndexes[tracePeriod]] || "—", format, unit, precision)} {rowUnit}</span>
                    <span>Related section: {source.label} · Example reference DEMO-FIXED-018 · {view === "annual" ? "Annual example" : "Selected model periods"}.</span>
                    <span><strong>Calculation link unavailable.</strong> This opens a related section only; it does not show how the displayed value was calculated.</span>
                  </div>
                  <a className="fm-sw-trace-open" href={sourceHref}>Open {source.label} →</a>
                  <button className="fm-sw-trace-close" type="button" onClick={() => setTraceId(null)}>Close trace</button>
                </div>
              </th>
            </tr>}
          </React.Fragment>;
        })}
      </tbody>
    </table>
  </div>;
}

export default function StatementWorkbook({ onSheetChange, onExplain, snapshot, status }: StatementWorkbookProps) {
  const project = readProjectContext();
  const visibleSheets = snapshot?.sheets ?? [];
  const visibleAnnualPeriods = snapshot?.annualPeriods ?? [];
  const visibleModelPeriods = snapshot?.modelPeriods ?? [];
  const visiblePeriodBands = snapshot?.periodBands ?? [];
  const runStatus = statementStatusText(status);
  const dataOrigin = status.dataOrigin ?? "synthetic-demo";
  const [sheetId, setSheetId] = useState<SheetId>(() => {
    const requested = initialSheet();
    return visibleSheets.some((item) => item.id === requested) ? requested : visibleSheets[0]?.id ?? "pl";
  });
  const [view, setView] = useState<ViewId>(initialView);
  const [facility, setFacility] = useState<FacilityId>(() => new URLSearchParams(window.location.search).get("returnFacility") === "mezzanine" ? "mezzanine" : "senior");
  const [showInitialPeriod, setShowInitialPeriod] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return (params.get("returnShowInitial") ?? params.get("statementShowInitial")) !== "0";
  });
  const [expanded, setExpanded] = useState<Record<string, boolean>>(initialExpandedState);
  const [traceId, setTraceId] = useState<string | null>(() => new URLSearchParams(window.location.search).get("traceRow"));
  const [tracePeriod, setTracePeriod] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    const candidate = Number(params.get("returnPeriod") || 0);
    const modelView = initialView() === "model";
    const hiddenInitial = (params.get("returnShowInitial") ?? params.get("statementShowInitial")) === "0";
    const count = modelView ? visibleModelPeriods.length - (hiddenInitial ? 1 : 0) : visibleAnnualPeriods.length;
    return Number.isFinite(candidate) ? Math.max(0, Math.min(count - 1, candidate)) : 0;
  });
  const [unit, setUnit] = useState<UnitDisplay>(() => dataOrigin === "canonical-run" ? defaultDisplayUnit(visibleSheets) : "mEUR");
  const [precision, setPrecision] = useState(1);
  const regionRef = useRef<HTMLDivElement>(null);
  const activeSheet = visibleSheets.find((item) => item.id === sheetId) || visibleSheets[0];
  const facilityKeys = Object.keys(snapshot?.debtRowsByFacility ?? {});
  const canonicalFacilities = dataOrigin === "canonical-run" && facilityKeys.length > 1;
  const effectiveFacility = (canonicalFacilities && !facilityKeys.includes(facility) ? facilityKeys[0] : facility) as FacilityId;
  const facilityRows = snapshot?.debtRowsByFacility?.[effectiveFacility];
  const rows = activeSheet
    ? sheetId === "debt"
      ? facilityRows ?? (facility === "senior" || dataOrigin === "canonical-run" ? activeSheet.rows : [])
      : activeSheet.rows
    : [];
  const displayedSheet = activeSheet
    ? rows === activeSheet.rows
      ? activeSheet
      : { ...activeSheet, title: canonicalFacilities ? `${effectiveFacility} facility debt schedule` : `${facility === "senior" ? "Senior" : "Mezzanine"} facility debt schedule`, rows }
    : null;
  const periods = view === "annual" ? visibleAnnualPeriods : showInitialPeriod ? visibleModelPeriods : visibleModelPeriods.slice(1);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("returnTrace") !== "1") return;
    const scrollLeft = Number(params.get("returnScrollLeft") || 0);
    const scrollY = Number(params.get("returnScrollY") || 0);
    const returnRow = params.get("traceRow");
    const returnPeriod = Number(params.get("returnPeriod") || 0);
    const timer = window.setTimeout(() => {
      regionRef.current?.scrollTo({ left: scrollLeft });
      if (scrollY > 0) window.scrollTo(0, scrollY);
      requestAnimationFrame(() => {
        const cell = Array.from(regionRef.current?.querySelectorAll<HTMLButtonElement>(".fm-sw-cell-button") || [])
          .find(item => item.dataset.statementRow === returnRow && Number(item.dataset.statementCol) === returnPeriod);
        cell?.focus({ preventScroll: true });
      });
    }, 40);
    return () => window.clearTimeout(timer);
  }, []);

  function chooseSheet(id: SheetId) {
    setSheetId(id);
    onSheetChange?.(id);
    setTraceId(null);
    const url = new URL(window.location.href);
    url.searchParams.set("statement", id);
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }
  function toggleGroup(id: string) {
    const key = `${sheetId}:${id}`;
    setExpanded((current) => ({ ...current, [key]: !current[key] }));
  }
  function toggleAllGroups(open: boolean) {
    const next: Record<string, boolean> = {};
    activeSheet?.rows.forEach(item => { if (item.children) next[`${sheetId}:${item.id}`] = open; });
    setExpanded(current => ({ ...current, ...next }));
  }
  function scrollPeriods(direction: -1 | 1) {
    regionRef.current?.scrollBy({ left: direction * 240, behavior: preferredScrollBehavior() });
  }

  if (!snapshot || visibleSheets.length === 0 || !activeSheet || !displayedSheet) {
    return <section id="statement-workbook" tabIndex={-1}>
      <div className="fm-sw-warning fm-sw-unavailable" role="status" aria-live="polite">
        <h2>Statement data unavailable</h2>
        <p>No statement data has been supplied. No sample statement rows are shown.</p>
      </div>
    </section>;
  }

  return <section id="statement-workbook" tabIndex={-1}>
      <section className="fm-sw" aria-label="Financial statement workbook">
        <header className="fm-sw-head">
          <div>
            <div className="fm-eyebrow">{project.id} · Financial statements</div>
            <h1 className="fm-sw-title">Statement workbook</h1>
            <div className="fm-sw-subtitle">{project.name} <span aria-hidden="true">·</span> {project.technology} <span aria-hidden="true">·</span> {dataOrigin === "canonical-run" ? `Persisted Run · canonical unit ${sheetUnitLabel(visibleSheets[0]?.unit)}` : "Illustrative EUR model view"}</div>
            <div className="fm-sw-tags">
              {dataOrigin === "synthetic-demo" && <span className="fm-sw-tag fm-sw-tag--demo">FIXED SYNTHETIC EXAMPLE</span>}
              {dataOrigin === "canonical-run" && <span className="fm-sw-tag" data-statement-origin="canonical-run">Persisted Run values</span>}
              {dataOrigin === "caller-provided" && <span className="fm-sw-tag">Source not provided</span>}
              {dataOrigin === "unavailable" && <span className="fm-sw-tag">Statement not available</span>}
              {dataOrigin === "canonical-run"
                ? <span className="fm-sw-tag">Display units are formatting only</span>
                : <><span className="fm-sw-tag">Partial example rows</span>
                  <span className="fm-sw-tag">Calculations are not available here</span></>}
            </div>
          </div>
            <div className="fm-sw-run" aria-label={dataOrigin === "canonical-run" ? "Persisted Run status" : "Illustrative results status"}
              data-run-freshness={runStatus.freshness}
              data-check-status={runStatus.integrity}
              data-model-version={runStatus.engine}>
            <span>{status.label}</span><strong>{status.runId}</strong>
            <span className="fm-sw-tag">{status.freshness === "current" ? "Up to date" : status.freshness === "stale" ? "Earlier results shown" : status.freshness === "not run" ? "No results yet" : "Update status unavailable"}</span>
            <span className="fm-sw-tag">{dataOrigin === "canonical-run" ? runStatus.integrity : /not[- ]evaluated/i.test(runStatus.integrity) ? "Review status not assessed" : "Review status supplied"}</span>
            <span className="fm-sw-tag">{dataOrigin === "canonical-run" ? `Engine: ${status.engineVersion || "identity unavailable"}` : /unknown|not connected/i.test(runStatus.engine) ? "Calculation details not supplied" : "Calculation details supplied"}</span>
          </div>
        </header>

        <div className="fm-sw-warning" role="note">
          <strong>{dataOrigin === "canonical-run" ? "Persisted Run statements." : "Display-only workbook."}</strong>{" "}
          {dataOrigin === "canonical-run"
            ? "Every figure is the value persisted by the Run, in its canonical unit. Changing units or precision only re-expresses those values; nothing is recalculated in the browser."
            : dataOrigin === "synthetic-demo"
            ? "Fixed illustrative values are not linked to inputs and do not recalculate. Calculation status is unavailable in this preview. These independent examples are not complete financial statements or reconciled across sheets."
            : dataOrigin === "caller-provided"
              ? "The source of these rows has not been confirmed. No calculations or reconciliation are performed."
              : "No statement data is available. No synthetic rows are substituted."}
        </div>

        <div className="fm-sw-toolbar">
          <div className="fm-sw-tabs" role="tablist" aria-label="Financial statement sheets">
            {visibleSheets.map((item) => <button
              key={item.id}
              type="button"
              role="tab"
              id={`fm-sw-tab-${item.id}`}
              aria-selected={sheetId === item.id}
              aria-controls="fm-sw-sheet"
              className="fm-sw-tab"
              onClick={() => chooseSheet(item.id)}
            >{item.label}</button>)}
          </div>
          <div className="fm-sw-controls">
            <label className="fm-sw-field" htmlFor="fm-sw-view">View
              <select id="fm-sw-view" className="fm-sw-select" value={view} onChange={(event) => {
                const next = event.target.value as ViewId;
                setView(next); setTraceId(null);
                const params = new URLSearchParams(window.location.search);
                params.set("statementView", next);
                window.history.replaceState(window.history.state, "", `${window.location.pathname}?${params}${window.location.hash}`);
              }}>
                <option value="annual">Annual</option>
                <option value="model">Model periods</option>
              </select>
            </label>
            <label className="fm-sw-field" htmlFor="fm-sw-unit">Units
              <select id="fm-sw-unit" className="fm-sw-select" value={unit} onChange={event => setUnit(event.target.value as UnitDisplay)}>
                {DISPLAY_UNITS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label className="fm-sw-field" htmlFor="fm-sw-precision">Precision
              <select id="fm-sw-precision" className="fm-sw-select" value={precision} onChange={event => setPrecision(Number(event.target.value))}>
                <option value={0}>0 decimals</option><option value={1}>1 decimal</option><option value={2}>2 decimals</option><option value={3}>3 decimals</option>
              </select>
            </label>
            {view === "model" && <button
              type="button"
              className="fm-sw-period-toggle"
              aria-pressed={showInitialPeriod}
              onClick={() => {
                const next = !showInitialPeriod;
                setShowInitialPeriod(next);
                setTracePeriod((current) => Math.max(0, Math.min(visibleModelPeriods.length - (next ? 1 : 2), current)));
                setTraceId(null);
                const params = new URLSearchParams(window.location.search);
                params.set("statementShowInitial", next ? "1" : "0");
                window.history.replaceState(window.history.state, "", `${window.location.pathname}?${params}${window.location.hash}`);
              }}
            >Initial period: {showInitialPeriod ? "shown" : "hidden"}</button>}
            <div className="fm-sw-expand-controls" aria-label="Statement row groups">
              <button type="button" className="fm-sw-scroll-btn" onClick={() => toggleAllGroups(true)}>Expand all</button>
              <button type="button" className="fm-sw-scroll-btn" onClick={() => toggleAllGroups(false)}>Collapse all</button>
            </div>
            <span className="fm-sw-active-cell" aria-live="polite">
              {traceId ? (() => {
                const activeRow = rows.find(item => item.id === traceId);
                const activeValue = activeRow?.[view] ?? [];
                const address = `${String.fromCharCode(66 + tracePeriod)}${Math.max(2, rows.findIndex(item => item.id === traceId) + 2)}`;
                const origin = dataOrigin === "synthetic-demo" ? "fixed synthetic reference" : dataOrigin === "canonical-run" ? "persisted Run value" : dataOrigin === "caller-provided" ? "caller-provided display value" : "unavailable";
                return `${address} · ${activeRow?.label || "Selected line"} · ${statementCellText(activeValue[tracePeriod])} ${activeRow ? canonicalUnitText(activeRow, activeSheet) : activeSheet.unit} · ${origin}`;
              })() : dataOrigin === "synthetic-demo" ? "Select a cell to open its synthetic trace" : "Select a cell to inspect its display value"}
            </span>
            {traceId && onExplain && (() => {
              const selectedRow = rows.find((item) => item.id === traceId);
              if (!selectedRow) return null;
              const rowValues = view === "annual" ? selectedRow.annual : selectedRow.model;
              const source = traceSources[selectedRow.id];
              const period = periods[tracePeriod] || "Period unavailable";
              return <button
                type="button"
                className="fm-sw-scroll-btn fm-sw-explain"
                data-testid="statement-explain-selected"
                onClick={event => {
                  event.currentTarget.focus();
                  onExplain({
                  id: `statement-${sheetId}-${selectedRow.id}-${tracePeriod}`,
                  kind: "Statement row",
                  title: selectedRow.label,
                  value: displayStatementValue(rowValues[tracePeriod] || "—", rowFormatOf(selectedRow, activeSheet), unit, precision),
                  unit: activeSheet.unit,
                  period,
                  basis: dataOrigin === "synthetic-demo"
                    ? status.freshness === "stale"
                      ? `Earlier fixed illustrative statement value from ${status.runId}. It does not reflect current edits; any related section is navigation only.`
                      : `Fixed illustrative statement value from ${status.runId}. Any related section is a navigation association only; no calculation path is supplied.`
                    : "Displayed value only. No source or calculation path is supplied.",
                  destination: source ? { sheet: source.sheet, label: source.label } : undefined,
                  });
                }}
              >Explain selected row</button>;
            })()}
            {sheetId === "debt" && canonicalFacilities && <label className="fm-sw-field" htmlFor="fm-sw-facility">Facility
              <select id="fm-sw-facility" className="fm-sw-select" aria-label="Statement facility" value={effectiveFacility} onChange={(event) => { setFacility(event.target.value as FacilityId); setTraceId(null); }}>
                {facilityKeys.map((key) => <option key={key} value={key}>{key}</option>)}
              </select>
            </label>}
            {sheetId === "debt" && dataOrigin !== "canonical-run" && <label className="fm-sw-field" htmlFor="fm-sw-facility">Facility
              <select id="fm-sw-facility" className="fm-sw-select" aria-label="Statement facility" value={facility} onChange={(event) => { setFacility(event.target.value as FacilityId); setTraceId(null); }}>
                <option value="senior">Senior</option>
                <option value="mezzanine">Mezzanine</option>
              </select>
            </label>}
          </div>
        </div>

        <section id="fm-sw-sheet" role="tabpanel" aria-labelledby={`fm-sw-tab-${sheetId}`}>
          {sheetId === "sponsor" && dataOrigin === "synthetic-demo" && <div className="fm-sw-subbar">
            <span><strong>Fixed sponsor outputs:</strong> Equity IRR 12.46% · Equity MOIC 1.82x</span>
            <span>Display values only · no return calculation</span>
          </div>}
          <div className="fm-sw-subbar">
            <span><strong>{displayedSheet.title}</strong> · Display units: {unit} · formatting only</span>
            <span>{view === "annual" ? `Annual view · ${visibleAnnualPeriods[0]}–${visibleAnnualPeriods.at(-1)}` : dataOrigin === "canonical-run" ? `Model periods · ${visibleModelPeriods.length} persisted periods` : "Selected model periods · not a full time series"}</span>
          </div>
          <div className="fm-sw-subbar">
            <span id="fm-sw-scroll-help">Scroll periods horizontally · Focus table and use ← / →</span>
            <div className="fm-sw-scroll-controls">
              <button type="button" className="fm-sw-scroll-btn" aria-label="Scroll statement periods left" onClick={() => scrollPeriods(-1)}>←</button>
              <button type="button" className="fm-sw-scroll-btn" aria-label="Scroll statement periods right" onClick={() => scrollPeriods(1)}>→</button>
            </div>
          </div>
          {rows.length > 0 ? <StatementTable
              sheet={displayedSheet}
              periods={periods}
              view={view}
              expanded={expanded}
              onToggleGroup={toggleGroup}
              traceId={traceId}
              setTraceId={setTraceId}
              tracePeriod={tracePeriod}
              setTracePeriod={setTracePeriod}
              unit={unit}
              precision={precision}
              showInitialPeriod={showInitialPeriod}
              facility={facility}
              periodBands={visiblePeriodBands}
              regionRef={regionRef}
              dataOrigin={dataOrigin}
              runId={status.runId}
            /> : <div className="fm-sw-warning fm-sw-unavailable" role="status" aria-live="polite">
              No statement rows are supplied for this sheet or facility.
            </div>}
        </section>
        {dataOrigin === "canonical-run"
          ? <footer className="fm-sw-footnote" data-statement-notes="true">
            <span><strong>{displayedSheet.title}:</strong> {activeSheet.note || "As persisted by the Run."}</span>
            {activeSheet.unavailable && activeSheet.unavailable.length > 0 && <span>Not persisted by this Run: {activeSheet.unavailable.join(", ")}</span>}
          </footer>
          : <footer className="fm-sw-footnote">
          <span><strong>Example coverage:</strong> selected statement lines and periods only; this is not a complete model time series.</span>
          <span>Displayed period frequency is illustrative and does not set a live model frequency.</span>
        </footer>}
      </section>
  </section>;
}
