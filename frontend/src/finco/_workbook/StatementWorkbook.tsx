import React, { useEffect, useMemo, useRef, useState } from "react";
import { fincoBasePath, readProjectContext } from "../_shared/FincoShell";
import { preferredScrollBehavior } from "../_shared/motion";
import { statementCellTabIndex, statementCellText, statementStatusText, type StatementFacilityId, type StatementRow, type StatementSheet, type StatementSheetId, type StatementViewId, type StatementWorkbookProps } from "./statementContract";
import "./statements.css";

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
type UnitDisplay = "EUR" | "kEUR" | "mEUR";
const unitScale: Record<UnitDisplay, number> = { EUR: 1_000_000, kEUR: 1_000, mEUR: 1 };
function displayStatementValue(value: string, label: string, unit: UnitDisplay, precision: number) {
  const trimmed = value.trim();
  if (/^not evaluated$/i.test(trimmed)) return "NOT EVALUATED";
  if (/^not tested$/i.test(trimmed)) return "NOT TESTED";
  if (!trimmed || /^(—|–|-|n\/a|na)$/i.test(trimmed)) return "—";
  const formattedMetric = /irr|moic|dscr|coverage ratio|%|x$/i.test(label);
  const suffix = formattedMetric && /[%x]$/i.test(trimmed) ? trimmed.slice(-1) : "";
  const numericText = suffix ? trimmed.slice(0, -1) : trimmed;
  const negative = /^\(.*\)$/.test(numericText) || numericText.startsWith("-");
  const number = Number(numericText.replace(/[(),]/g, ""));
  if (!Number.isFinite(number)) return value;
  const formatted = new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
    useGrouping: true,
  }).format(Math.abs(number) * (formattedMetric ? 1 : unitScale[unit]));
  return `${negative ? `(${formatted})` : formatted}${suffix}`;
}

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
  dataOrigin: "synthetic-demo" | "caller-provided" | "unavailable";
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
    <span id="fm-sw-grid-help" className="fm-sr-only">Only the active statement value is in the page Tab order. Use the arrow keys to move between values; press Enter to open the source navigation reference. Tab leaves the table.</span>
    <table className="fm-sw-table">
      <caption className="fm-sr-only">{sheet.title}, {dataOrigin === "synthetic-demo" ? "fixed synthetic example rows" : dataOrigin === "caller-provided" ? "caller-provided rows" : "unavailable rows"}, {view === "annual" ? "annual" : "model-period snapshots"}. Not a fully populated engine statement.</caption>
      <thead>
        {view === "annual" ? <tr><th scope="col">Statement line · {sheet.unit}</th><th scope="colgroup" colSpan={periods.length}>Operating years</th></tr> :
          <tr><th scope="col">Statement line · {sheet.unit}</th>{visiblePeriodBands.map((band, index) => {
            const span = index === 0 && !showInitialPeriod ? band.span - 1 : band.span;
            return span > 0 ? <th key={band.label} scope="colgroup" colSpan={span}>{band.label}</th> : null;
          })}</tr>}
        <tr><th scope="col">{dataOrigin === "synthetic-demo" ? "Fixed example rows" : dataOrigin === "caller-provided" ? "Provided rows" : "Unavailable"}</th>{periods.map((period) => <th scope="col" key={period}>{period}</th>)}</tr>
      </thead>
      <tbody>
          {rows.map((item, rowIndex) => {
          const isOpen = Boolean(item.children && expanded[`${sheet.id}:${item.id}`]);
          const values = view === "annual" ? item.annual : item.model;
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
            <tr className={`${item.kind === "section" ? "fm-sw-section" : item.kind === "detail" ? "fm-sw-detail" : ""}${traceOpen ? " fm-sw-row-selected" : ""}`}>
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
                    {item.label}
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
                  aria-label={`${item.label}, ${periods[index]}, ${displayStatementValue(value, item.label, unit, precision)} ${unit}. ${dataOrigin === "synthetic-demo" ? "Open synthetic source trace." : "Open display navigation reference."}`}
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
                >{displayStatementValue(value, item.label, unit, precision)}</button>
              </td>;
              })}
            </tr>
            {traceOpen && <tr className="fm-sw-trace-row">
              <th scope="row" className="fm-sw-trace-cell" colSpan={periods.length + 1}>
                <div className="fm-sw-trace">
                  <div className="fm-sw-trace-copy">
                    <strong>SYNTHETIC SOURCE TRACE · {item.label} · {periods[tracePeriod]}</strong>
                    <span className="fm-sw-trace-code">{formatExpressionLabel(item.label)} = fixed illustrative value · {displayStatementValue(values[periodIndexes[tracePeriod]] || "—", item.label, unit, precision)} {unit}</span>
                    <span>Associated section: {source.label} · Run DEMO-FIXED-018 · {view === "annual" ? "Annual example array" : "Model-period snapshot array"}.</span>
                    <span><strong>Calculation lineage unavailable.</strong> Navigation identifies a relevant design section only; it does not prove numerical dependency on its inputs.</span>
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

export default function StatementWorkbook({ onSheetChange, snapshot, status }: StatementWorkbookProps) {
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
  const [unit, setUnit] = useState<UnitDisplay>("mEUR");
  const [precision, setPrecision] = useState(1);
  const regionRef = useRef<HTMLDivElement>(null);
  const activeSheet = visibleSheets.find((item) => item.id === sheetId) || visibleSheets[0];
  const facilityRows = snapshot?.debtRowsByFacility?.[facility];
  const rows = activeSheet
    ? sheetId === "debt"
      ? facilityRows ?? (facility === "senior" ? activeSheet.rows : [])
      : activeSheet.rows
    : [];
  const displayedSheet = activeSheet
    ? rows === activeSheet.rows
      ? activeSheet
      : { ...activeSheet, title: `${facility === "senior" ? "Senior" : "Mezzanine"} facility debt schedule`, rows }
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
        <p>No statement snapshot was supplied. No synthetic statement rows are substituted.</p>
      </div>
    </section>;
  }

  return <section id="statement-workbook" tabIndex={-1}>
      <section className="fm-sw" aria-label="Financial statement workbook">
        <header className="fm-sw-head">
          <div>
            <div className="fm-eyebrow">{project.id} · Financial statements</div>
            <h1 className="fm-sw-title">Statement workbook</h1>
            <div className="fm-sw-subtitle">{project.name} <span aria-hidden="true">·</span> {project.technology} <span aria-hidden="true">·</span> Illustrative EUR model view</div>
            <div className="fm-sw-tags">
              {dataOrigin === "synthetic-demo" && <span className="fm-sw-tag fm-sw-tag--demo">FIXED SYNTHETIC EXAMPLE</span>}
              {dataOrigin === "caller-provided" && <span className="fm-sw-tag">CALLER-PROVIDED · ORIGIN UNVERIFIED</span>}
              {dataOrigin === "unavailable" && <span className="fm-sw-tag">STATEMENT SOURCE UNAVAILABLE</span>}
              <span className="fm-sw-tag">Partial example rows</span>
              <span className="fm-sw-tag">No engine connection</span>
            </div>
          </div>
            <div className="fm-sw-run" aria-label="Illustrative run status">
            <span>{status.label}</span><strong>{status.runId}</strong>
            <span className="fm-sw-tag">{runStatus.freshness}</span>
            <span className="fm-sw-tag">{runStatus.integrity}</span>
            <span className="fm-sw-tag">{runStatus.engine}</span>
          </div>
        </header>

        <div className="fm-sw-warning" role="note">
          <strong>Display-only workbook.</strong>{" "}
          {dataOrigin === "synthetic-demo"
            ? "Fixed synthetic values are not linked to inputs and do not recalculate. Freshness is unknown because input linkage is absent; integrity has not been evaluated. These independent partial sheet samples are not complete or cross-sheet-reconciled engine statements."
            : dataOrigin === "caller-provided"
              ? "Rows are supplied to this presentation component; their source and financial authority are not verified here. No calculations or reconciliation are performed."
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
                <option value="EUR">EUR</option><option value="kEUR">kEUR</option><option value="mEUR">mEUR</option>
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
                const origin = dataOrigin === "synthetic-demo" ? "fixed synthetic reference" : dataOrigin === "caller-provided" ? "caller-provided display value" : "unavailable";
                return `${address} · ${activeRow?.label || "Selected line"} · ${statementCellText(activeValue[tracePeriod])} ${activeSheet.unit} · ${origin}`;
              })() : dataOrigin === "synthetic-demo" ? "Select a cell to open its synthetic trace" : "Select a cell to inspect its display value"}
            </span>
            {sheetId === "debt" && <label className="fm-sw-field" htmlFor="fm-sw-facility">Facility
              <select id="fm-sw-facility" className="fm-sw-select" aria-label="Statement facility" value={facility} onChange={(event) => { setFacility(event.target.value as FacilityId); setTraceId(null); }}>
                <option value="senior">Senior</option>
                <option value="mezzanine">Mezzanine</option>
              </select>
            </label>}
          </div>
        </div>

        <section id="fm-sw-sheet" role="tabpanel" aria-labelledby={`fm-sw-tab-${sheetId}`}>
          {sheetId === "sponsor" && <div className="fm-sw-subbar">
            <span><strong>Fixed sponsor outputs:</strong> Equity IRR 12.46% · Equity MOIC 1.82x</span>
            <span>Display values only · no return calculation</span>
          </div>}
          {sheetId !== "sponsor" && <div className="fm-sw-subbar">
            <span><strong>{displayedSheet.title}</strong> · Display units: {unit} · formatting only</span>
            <span>{view === "annual" ? `Annual view · ${visibleAnnualPeriods[0]}–${visibleAnnualPeriods.at(-1)}` : "Selected period snapshots · not a full time series"}</span>
          </div>}
          {sheetId === "sponsor" && <div className="fm-sw-subbar">
            <span><strong>{displayedSheet.title}</strong> · Display units: {unit} · formatting only</span>
            <span>{view === "annual" ? `Annual view · ${visibleAnnualPeriods[0]}–${visibleAnnualPeriods.at(-1)}` : "Selected period snapshots · not a full time series"}</span>
          </div>}
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
            /> : <div className="fm-sw-warning fm-sw-unavailable" role="status" aria-live="polite">
              No statement rows are supplied for this sheet or facility.
            </div>}
        </section>
        <footer className="fm-sw-footnote">
          <span><strong>Example coverage:</strong> selected statement lines and period snapshots only; no complete model time series.</span>
          <span>Frequency snapshots are illustrative and carry no production frequency-policy authority.</span>
        </footer>
      </section>
  </section>;
}
