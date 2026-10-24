import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
// Host adaptation (Concept B GitHub integration V1): the Replit handoff imports
// `lucide-react`; this host pins the production React dependency surface to
// react + react-dom (tests/test_model_react_source_harvest_v1.py), so the same
// icons are supplied by the local inline-SVG set with identical rendering
// contract (see ./icons.tsx).
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronRight,
  Clock3,
  ExternalLink,
  FilterX,
  LockKeyhole,
  Pause,
  Pencil,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Search,
  ShieldCheck,
  Star,
  Trash2,
  Wallet,
  X,
} from "./icons";
import {
  DEMO_CLOCK_LABEL,
  githubDoc,
  instruments,
  sourceDocs,
  type Instrument,
} from "./_shared/fixtures";
import {
  alertReadiness,
  categoryForRoute,
  createAlertDraft,
  currentLegValue,
  currentPremiumDiscount,
  filterInstruments,
  formatDemoAge,
  handleRadarRowKeyDown,
  handleWatchlistButtonKeyDown,
  illustrativeChartData,
  isRadarDestination,
  lastHistoricalLeg,
  lifecycleForInstrument,
  pairAssessment,
  radarDefaultFilters,
  radarFiltersActive,
  removeAlertAndAdjustEditing,
  saveAlertDraft,
  toggleAlertState,
  toggleWatchlist,
  type AlertDraft,
  type EvidenceStatus,
} from "./_shared/non-model-logic";
import "./concept-b.css";

const ROUTES = [
  "/",
  "/radar",
  "/radar/r-live",
  "/radar/tokenized",
  "/radar/stocks",
  "/radar/crypto",
  "/radar/economy",
  "/crypto",
  "/roadmap",
] as const;

type NonModelRoute = (typeof ROUTES)[number] | "/not-found";
type DemoViewState = "ready" | "loading" | "empty" | "error";
type AccessState = "Public" | "Preview" | "Gated";

export interface FincoNonModelExperienceProps {
  initialRoute?: string;
  initialAccess?: AccessState;
  initialInstrumentId?: string;
  initialDemoState?: DemoViewState;
}

function normalizeRoute(value: string): NonModelRoute {
  return ROUTES.includes(value as (typeof ROUTES)[number])
    ? (value as (typeof ROUTES)[number])
    : "/not-found";
}

function readHashRoute(fallback: string) {
  if (typeof window === "undefined") return normalizeRoute(fallback);
  const hash = window.location.hash;
  return normalizeRoute(hash.startsWith("#") ? hash.slice(1) : fallback);
}

function routeTitle(route: NonModelRoute) {
  if (route.startsWith("/radar")) return `FINCO · ${route === "/radar" ? "Radar overview" : route.split("/").at(-1)?.replace("-", " ")}`;
  if (route === "/crypto") return "FINCO · Crypto preview";
  if (route === "/roadmap") return "FINCO · Public roadmap";
  return route === "/" ? "FINCO · Evidence before inference" : "FINCO · Page not found";
}

function formatValue(value: number | null, unit: string) {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${unit}`;
}

function StatusBadge({ value }: { value: string }) {
  const tone = value === "AVAILABLE" || value === "LIVE / IMPLEMENTED"
    ? "good"
    : value === "STALE" || value.includes("TARGET") || value === "PREVIEW"
      ? "caution"
      : value === "UNAVAILABLE" || value === "GATED"
        ? "quiet"
        : "neutral";
  return <span className={`b-status b-status-${tone}`}>{value}</span>;
}

function BrandMark() {
  return <span className="b-brand-mark" aria-hidden="true"><i /></span>;
}

function SiteHeader({ route }: { route: NonModelRoute }) {
  const nav = [
    { label: "Overview", href: "/" },
    { label: "Radar", href: "/radar" },
    { label: "Crypto", href: "/crypto" },
    { label: "Roadmap", href: "/roadmap" },
  ] as const;
  return (
    <header className="b-header">
      <a className="b-brand" href="#/" aria-label="FINCO overview">
        <BrandMark />
        <span>FINCO <small>PROTOCOL</small></span>
      </a>
      <nav className="b-primary-nav" aria-label="Primary navigation">
        {nav.map((item) => {
          const active = item.href === "/radar" ? isRadarDestination(route) : route === item.href;
          return (
            <a key={item.href} href={`#${item.href}`} className={active ? "active" : ""} aria-current={active ? "page" : undefined}>
              {item.label}
            </a>
          );
        })}
      </nav>
      <div className="b-header-state"><span className="b-live-dot" /> LOCAL DEMO <span className="b-header-divider">/</span> NO LIVE FEED</div>
    </header>
  );
}

// Host adaptation (Concept B GitHub integration V1): in the standalone Replit
// preview the footer could only list in-app hash routes and had to present
// Verify, API, Docs, Methodology, Yield and $FINCO as host-only text. Inside
// the FINCO host each of these labels has a verified canonical destination
// (app/protocol_ui/router.py, app/protocol/router.py, finco_yield/web.py), so
// they render as real same-origin links and never point at an unrelated screen
// or imply capability beyond that page. The Replit-only concept-gallery link
// has no host route and is deliberately not rendered.
const HOST_DESTINATIONS = [
  { label: "Verify", href: "/verify" },
  { label: "API", href: "/api" },
  { label: "Docs", href: "/docs" },
  { label: "Methodology", href: "/model/methodology" },
  { label: "Yield", href: "/yield" },
  { label: "$FINCO", href: "/protocol/finco" },
] as const;

function SiteFooter() {
  return (
    <footer className="b-footer">
      <div className="b-footer-brand"><BrandMark /><span>FINCO PROTOCOL</span></div>
      <p>Evidence and context only. This prototype uses synthetic fixtures and local UI state.</p>
      <nav aria-label="Footer navigation">
        <a href="#/">Landing</a>
        <a href="#/radar">Radar</a>
        <a href="#/crypto">Crypto</a>
        <a href="#/roadmap">Roadmap</a>
      </nav>
      <nav className="b-footer-host-links" aria-label="Canonical host destinations">
        {HOST_DESTINATIONS.map((item) => (
          <a key={item.href} href={item.href}>{item.label}</a>
        ))}
      </nav>
      <p className="b-footer-host-only" role="note">
        Verify, API, Docs, Methodology, Yield, and $FINCO open the existing canonical FINCO host surfaces.
        These links navigate only; they activate no capability of this experience.
      </p>
      <small className="b-footer-disclaimer">No executable quotes, trading, wallet connection, or transaction functionality.</small>
    </footer>
  );
}

function PageHeading({
  eyebrow,
  title,
  description,
  right,
}: {
  eyebrow: string;
  title: string;
  description: string;
  right?: ReactNode;
}) {
  return (
    <div className="b-page-heading">
      <div>
        <div className="b-eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {right}
    </div>
  );
}

function LandingScreen() {
  const featured = instruments.find((item) => item.id === "fx-demo-003") ?? instruments[0];
  const chart = illustrativeChartData(featured, "24h");
  const featuredValue = currentLegValue(featured, "market");
  return (
    <main className="b-main b-landing" id="main-content">
      <div className="b-hero-grid">
        <section className="b-hero-copy">
          <div className="b-eyebrow"><span className="b-eyebrow-rule" /> MARKET CONTEXT · EVIDENCE FIRST</div>
          <h1>Market context,<br /><em>with boundaries.</em></h1>
          <p className="b-hero-lede">FINCO organizes market observations and reference evidence with explicit identity, freshness, and authority boundaries.</p>
          <div className="b-hero-actions">
            <a className="b-button b-button-primary" href="#/radar">Explore Radar <ArrowDownRight size={16} /></a>
            <a className="b-button b-button-secondary" href="#/roadmap">View public roadmap <ChevronRight size={15} /></a>
          </div>
          <div className="b-hero-footnote"><ShieldCheck size={15} /> Read-only product prototype · no connected market data</div>
        </section>
        <aside className="b-feature-card" aria-label="Illustrative market evidence preview">
          <div className="b-feature-top">
            <span><Radio size={13} /> SAMPLE INSTRUMENT · {featured.symbol}</span>
            <StatusBadge value="SYNTHETIC" />
          </div>
          <div className="b-feature-value">{featuredValue === null ? "—" : formatValue(featuredValue, featured.unit)}</div>
          <div className="b-feature-label">SYNTHETIC / ILLUSTRATIVE VALUE · NOT A LIVE QUOTE</div>
          {chart ? (
            <svg className="b-feature-chart" viewBox="0 0 700 120" role="img" aria-label="Synthetic illustrative curve only; not a historical time series">
              <path className="b-gridline" d="M0 25H700M0 60H700M0 95H700" />
              <polyline points={chart.shapeA} fill="none" stroke="var(--b-mint)" strokeWidth="2.5" />
              <polyline points={chart.shapeB} fill="none" stroke="var(--b-teal)" strokeWidth="1.4" strokeDasharray="5 5" />
            </svg>
          ) : <div className="b-chart-suppressed">— · evidence does not pass the display guard</div>}
          <div className="b-feature-bottom">
            <span>FIXTURE ID · {featured.id}</span>
            <span>ILLUSTRATION ONLY · NOT HISTORICAL DATA</span>
          </div>
        </aside>
      </div>

      <div className="b-trust-strip" aria-label="Evidence principles">
        <span><b>01</b> Identity is explicit</span>
        <span><b>02</b> Freshness is visible</span>
        <span><b>03</b> Authority is bounded</span>
        <span><b>04</b> Reference ≠ executable</span>
      </div>

      <section className="b-section b-product-section">
        <div className="b-section-head">
          <div><div className="b-eyebrow">PUBLIC EXPERIENCE · 01—03</div><h2>Observe the evidence.<br /><em>Understand the boundary.</em></h2></div>
          <p>Explore the product surfaces represented in this local prototype. Availability, release state, and operational data are distinct.</p>
        </div>
        <div className="b-product-grid">
          <a className="b-product-card" href="#/radar">
            <span className="b-card-index">01 / RADAR</span><Activity size={19} />
            <h3>Evidence terminal</h3>
            <p>Compare market observations and reference evidence with freshness and identity shown separately.</p>
            <span className="b-card-link">Open Radar <ArrowUpRight size={14} /></span>
          </a>
          <a className="b-product-card" href="#/crypto">
            <span className="b-card-index">02 / CRYPTO</span><Wallet size={19} />
            <h3>Access preview</h3>
            <p>Review simulated access states and session-local watchlist and alert drafts. No wallet is connected.</p>
            <span className="b-card-link">Open Crypto preview <ArrowUpRight size={14} /></span>
          </a>
          <a className="b-product-card" href="#/roadmap">
            <span className="b-card-index">03 / ROADMAP</span><BookOpen size={19} />
            <h3>Public roadmap</h3>
            <p>See implemented interface scope, dated targets, and future work without treating targets as promises.</p>
            <span className="b-card-link">Read roadmap <ArrowUpRight size={14} /></span>
          </a>
        </div>
      </section>

      <section className="b-method-section" id="methodology">
        <div className="b-method-heading">
          <div className="b-eyebrow">HOW TO READ THE INTERFACE</div>
          <h2>Evidence before<br /><em>inference.</em></h2>
          <p>The interface preserves the distinction between what was observed, what is referenced, and what is unavailable.</p>
        </div>
        <div className="b-method-steps">
          <article><span>01</span><div><h3>Identify</h3><p>Use the canonical fixture identity and representation details—not a symbol-only match.</p></div></article>
          <article><span>02</span><div><h3>Qualify</h3><p>Read availability and freshness for each evidence leg. Stale is not current.</p></div></article>
          <article><span>03</span><div><h3>Bound</h3><p>Reference context is informational only. It is not an executable quote or action.</p></div></article>
        </div>
      </section>

      <div className="b-disclosure">
        <ShieldCheck size={17} />
        <p><strong>Prototype boundary.</strong> Figures and curves on this page are synthetic illustrations. They are not live quotes, actual historical observations, investment signals, or recommendations. No market feed is connected.</p>
        <a href="#/roadmap">Read the status notes <ArrowUpRight size={13} /></a>
      </div>
    </main>
  );
}

function RadarScreen({
  route,
  query,
  setQuery,
  category,
  setCategory,
  statusFilter,
  setStatusFilter,
  filtered,
  selected,
  onSelect,
  watchlist,
  onToggleWatch,
  chartRange,
  setChartRange,
  demoState,
  setDemoState,
  onRefresh,
  notice,
}: {
  route: NonModelRoute;
  query: string;
  setQuery: (value: string) => void;
  category: string;
  setCategory: (value: string) => void;
  statusFilter: string;
  setStatusFilter: (value: string) => void;
  filtered: Instrument[];
  selected: Instrument | null;
  onSelect: (item: Instrument | null) => void;
  watchlist: string[];
  onToggleWatch: (id: string) => void;
  chartRange: "1h" | "24h";
  setChartRange: (range: "1h" | "24h") => void;
  demoState: DemoViewState;
  setDemoState: (value: DemoViewState) => void;
  onRefresh: () => void;
  notice: string;
}) {
  const filtersAreActive = radarFiltersActive(route, { query, category, status: statusFilter });
  const isEconomy = route === "/radar/economy";
  const title = route === "/radar/r-live" ? "R-LIVE observations"
    : route === "/radar/tokenized" ? "Tokenized Markets"
      : route === "/radar/stocks" ? "Stocks"
        : route === "/radar/crypto" ? "Radar Crypto"
          : route === "/radar/economy" ? "Economy"
            : "Radar overview";
  const availableCount = filtered.filter((item) => pairAssessment(item).eligible).length;
  return (
    <main className="b-main b-terminal" id="main-content">
      <PageHeading
        eyebrow={`RADAR · ${route === "/radar/r-live" ? "R-LIVE" : "LOCAL FIXTURE TERMINAL"}`}
        title={title}
        description="Read market and reference evidence as separate legs. This interface is a local, synthetic-data prototype."
        right={<div className="b-demo-stamp"><Radio size={13} /> SYNTHETIC DEMO DATA</div>}
      />

      <nav className="b-radar-subnav" aria-label="Radar sections">
        {[
          ["Overview", "/radar"],
          ["R-LIVE", "/radar/r-live"],
          ["Tokenized", "/radar/tokenized"],
          ["Stocks", "/radar/stocks"],
          ["Crypto", "/radar/crypto"],
          ["Economy", "/radar/economy"],
        ].map(([label, href]) => (
          <a key={href} href={`#${href}`} className={route === href ? "active" : ""} aria-current={route === href ? "page" : undefined}>{label}</a>
        ))}
      </nav>

      <div className="b-radar-policy">
        <div><strong>DISPLAY POLICY</strong><span>Current paired figures require both MARKET and REFERENCE legs to be AVAILABLE, fresh, and within 300 seconds of each other.</span></div>
        <div><strong>REFERENCE</strong><span>Informational context only · never an executable quote.</span></div>
        <div><strong>DATA CLOCK</strong><span>{DEMO_CLOCK_LABEL}</span></div>
      </div>

      <div className="b-terminal-toolbar">
        <div className="b-filter-field b-search">
          <label htmlFor="radar-search"><Search size={15} /> Search fixtures</label>
          <input id="radar-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Symbol, name, chain, identity…" autoComplete="off" data-testid="input-radar-search" />
        </div>
        <div className="b-filter-field">
          <label htmlFor="radar-category">Category</label>
          <select id="radar-category" value={category} onChange={(event) => setCategory(event.target.value)} data-testid="select-radar-category">
            {["All", "Tokenized Markets", "Stocks", "Crypto", "Stablecoins", "Economy"].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </div>
        <div className="b-filter-field">
          <label htmlFor="radar-status">Evidence state</label>
          <select id="radar-status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} data-testid="select-radar-status">
            {["All statuses", "Available", "Stale / unavailable"].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </div>
        {filtersAreActive && <button type="button" className="b-clear-filters" onClick={() => { setQuery(""); setCategory(categoryForRoute(route)); setStatusFilter("All statuses"); }} data-testid="button-clear-filters"><FilterX size={14} /> Clear filters</button>}
        <div className="b-filter-field b-demo-state">
          <label htmlFor="demo-view-state">Local view state</label>
          <select id="demo-view-state" value={demoState} onChange={(event) => setDemoState(event.target.value as DemoViewState)} data-testid="select-demo-view-state">
            {["ready", "loading", "empty", "error"].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </div>
        <button type="button" className="b-icon-action" onClick={onRefresh} aria-label="Refresh local demo view; no network request" title="Refresh local demo view; no network request" data-testid="button-refresh-demo"><RefreshCw size={15} /><span>Refresh demo</span></button>
      </div>
      {notice && <div className="b-inline-notice" role="status" aria-live="polite"><Check size={14} /> {notice}</div>}

      {isEconomy ? (
        <section className="b-empty-state b-economy-empty" data-testid="empty-economy">
          <div className="b-empty-icon"><Activity size={20} /></div>
          <div className="b-eyebrow">NO VERIFIED DEMO SERIES</div>
          <h2>Economy data is not configured.</h2>
          <p>No verified source series is available in these fixtures. This screen intentionally shows no invented macroeconomic values or chart.</p>
          <span className="b-muted-tag">EMPTY STATE · HONESTLY UNAVAILABLE</span>
        </section>
      ) : (
        <>
          <div className="b-fixture-summary">
            <div><span>FILTERED FIXTURES</span><strong>{filtered.length.toString().padStart(2, "0")}</strong><small>local sample rows</small></div>
            <div><span>PAIR AVAILABLE</span><strong>{availableCount.toString().padStart(2, "0")}</strong><small>demo policy only</small></div>
            <div><span>UNIVERSE STATUS</span><strong>PREVIEW</strong><small>not a live market feed</small></div>
          </div>
          {demoState === "loading" ? (
            <section className="b-state-panel" role="status" aria-live="polite" data-testid="state-loading"><span className="b-loader" /><div><strong>Loading state preview</strong><p>Local illustration only. No request is being made.</p></div></section>
          ) : demoState === "error" ? (
            <section className="b-state-panel b-state-error" role="alert" data-testid="state-error"><X size={18} /><div><strong>Local error-state preview</strong><p>This example is simulated; there is no backend request to retry.</p></div></section>
          ) : demoState === "empty" || filtered.length === 0 ? (
            <section className="b-state-panel" data-testid="state-empty"><Search size={18} /><div><strong>{demoState === "empty" ? "Empty state preview" : "No fixtures match these filters"}</strong><p>{demoState === "empty" ? "This local state is simulated; the fixture data has not been removed." : "Adjust the search or clear the active filters to see local demo fixtures."}</p></div>
              {filtersAreActive && <button type="button" className="b-text-button" onClick={() => { setQuery(""); setCategory(categoryForRoute(route)); setStatusFilter("All statuses"); }}>Clear filters</button>}
            </section>
          ) : (
            <div className="b-radar-layout">
              <section className="b-panel b-instrument-panel" aria-label="Radar fixture register">
                <div className="b-panel-heading"><div><span className="b-eyebrow">LOCAL FIXTURES · {filtered.length} ROWS</span><h2>Instrument register</h2></div><span className="b-panel-note">Pointer or Enter / Space to inspect</span></div>
                <div className="b-table-scroll" role="region" aria-label="Synthetic Radar instrument results" tabIndex={0} data-testid="instruments-table">
                  <table className="b-instrument-table">
                    <caption className="b-sr-only">Synthetic demo fixtures. Focus an instrument row and press Enter or Space to open its detail; use the watchlist control to toggle the session-only list.</caption>
                    <thead><tr><th scope="col">Instrument / identity</th><th scope="col">Market leg</th><th scope="col">Reference leg</th><th scope="col">Pair state</th><th scope="col"><span className="b-sr-only">Watchlist</span></th></tr></thead>
                    <tbody>
                      {filtered.map((item) => {
                        const evidence = pairAssessment(item);
                        const marketValue = currentLegValue(item, "market");
                        const referenceValue = currentLegValue(item, "reference");
                        const selectedRow = selected?.id === item.id;
                        const watched = watchlist.includes(item.id);
                        return (
                          <tr
                            key={item.id}
                            tabIndex={0}
                            aria-selected={selectedRow}
                            aria-label={`${item.symbol}, ${item.name}, ${evidence.pairStatus}. Press Enter or Space to inspect.`}
                            className={selectedRow ? "selected" : ""}
                            onClick={() => onSelect(item)}
                            onKeyDown={(event) => handleRadarRowKeyDown(event, () => onSelect(item))}
                            data-testid={`row-instrument-${item.id}`}
                          >
                            <td><span className="b-asset-symbol">{item.symbol}</span><span className="b-cell-sub">{item.name}</span><span className="b-cell-id">{item.id}</span></td>
                            <td><span className="b-table-value">{formatValue(marketValue, item.unit)}</span><span className="b-cell-sub">MARKET · {evidence.marketStatus}</span></td>
                            <td><span className="b-table-value">{formatValue(referenceValue, item.unit)}</span><span className="b-cell-sub">REFERENCE · {evidence.referenceStatus}</span><span className="b-cell-sub">NOT EXECUTABLE</span></td>
                            <td><StatusBadge value={evidence.pairStatus} /></td>
                            <td><button type="button" className={`b-watch-button${watched ? " is-watched" : ""}`} aria-label={`${watched ? "Remove" : "Add"} ${item.symbol} ${watched ? "from" : "to"} session watchlist`} aria-pressed={watched} onClick={(event) => { event.stopPropagation(); onToggleWatch(item.id); }} onKeyDown={(event) => handleWatchlistButtonKeyDown(event, () => onToggleWatch(item.id))} data-testid={`button-watch-${item.id}`}><Star size={15} fill={watched ? "currentColor" : "none"} /></button></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="b-panel-footnote">All figures and observation times are deterministic fixture data. Missing or suppressed current values are shown as an em dash, never as zero.</p>
              </section>
              <aside className="b-panel b-detail-panel" aria-label="Selected instrument detail" data-testid="instrument-detail">
                {selected ? <InstrumentDetail item={selected} chartRange={chartRange} setChartRange={setChartRange} onClose={() => onSelect(null)} /> : (
                  <div className="b-detail-empty"><div className="b-eyebrow">DETAIL VIEW</div><h2>Select an instrument</h2><p>Choose a row to inspect its exact fixture identity, MARKET and REFERENCE evidence, freshness, and lifecycle.</p></div>
                )}
              </aside>
            </div>
          )}
          {route === "/radar/tokenized" && (
            <section className="b-source-docs" aria-label="Read-only source documentation">
              <h3>Source documentation · read-only references</h3>
              <div className="b-source-docs-grid">
                {sourceDocs.slice(0, 7).map(([label, path, description]) => (
                  <a key={path} href={githubDoc(path)} target="_blank" rel="noreferrer" title={description}>
                    <span>{label}</span><ExternalLink size={12} aria-hidden="true" />
                  </a>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </main>
  );
}

function InstrumentDetail({
  item,
  chartRange,
  setChartRange,
  onClose,
}: {
  item: Instrument;
  chartRange: "1h" | "24h";
  setChartRange: (range: "1h" | "24h") => void;
  onClose: () => void;
}) {
  const pair = pairAssessment(item);
  const chart = illustrativeChartData(item, chartRange);
  const premium = currentPremiumDiscount(item);
  const identity = [
    ["Fixture ID", item.id],
    ["Instrument ID", item.instrumentId],
    ["Venue", item.venue],
    ["Chain", item.chain],
    ["Contract", item.contract],
    ["Representation", item.representation],
  ];
  return (
    <div className="b-detail-content">
      <div className="b-detail-heading">
        <div><div className="b-eyebrow">EXACT FIXTURE IDENTITY</div><h2>{item.symbol} <span>· {item.name}</span></h2></div>
        <button type="button" className="b-icon-only" onClick={onClose} aria-label="Close instrument detail" data-testid="button-close-detail"><X size={16} /></button>
      </div>
      <div className="b-evidence-warning"><ShieldCheck size={15} /><span>Identity is a deterministic synthetic fixture—not a production-verified or issuer-backed representation.</span></div>
      <dl className="b-identity-grid">
        {identity.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
      <div className="b-leg-grid">
        {(["market", "reference"] as const).map((leg) => {
          const status: EvidenceStatus = leg === "market" ? pair.marketStatus : pair.referenceStatus;
          const value = currentLegValue(item, leg);
          const observation = lastHistoricalLeg(item, leg);
          return (
            <section className="b-evidence-leg" key={leg} data-testid={`evidence-${leg}`}>
              <div className="b-leg-heading"><strong>{leg === "market" ? "MARKET OBSERVATION" : "REFERENCE EVIDENCE"}</strong><StatusBadge value={status} /></div>
              <div className={`b-leg-value${value === null ? " is-suppressed" : ""}`}>{formatValue(value, item.unit)}</div>
              <div className="b-leg-caption">{value === null ? "CURRENT PAIRED VALUE SUPPRESSED" : "SYNTHETIC DEMO VALUE · NOT A QUOTE"}</div>
              <div className="b-leg-time">Fixed demo timestamp: {observation.timestamp}</div>
              {leg === "reference" && <div className="b-leg-caption b-not-executable">REFERENCE IS NOT EXECUTABLE</div>}
            </section>
          );
        })}
      </div>
      <div className="b-premium-row"><span>Current premium / discount</span><strong>{premium === null ? "—" : `${premium > 0 ? "+" : ""}${premium.toFixed(3)}%`}</strong><small>{premium === null ? "Suppressed unless both evidence legs pass the freshness and pair policy." : "Synthetic fixture arithmetic · not a signal."}</small></div>
      <div className="b-snapshot-panel">
        <div className="b-subpanel-head"><strong>FIXTURE OBSERVATION SNAPSHOTS</strong><span>Not actual market history</span></div>
        {(["market", "reference"] as const).map((leg) => {
          const snapshot = lastHistoricalLeg(item, leg);
          return <div className="b-snapshot-row" key={leg}><span>{leg === "market" ? "Market leg" : "Reference leg"}<small>{snapshot.timestamp} · {formatDemoAge(snapshot.ageSeconds)} · {snapshot.status}</small></span><b>{snapshot.value === null || !Number.isFinite(snapshot.value) ? "—" : formatValue(snapshot.value, item.unit)}</b></div>;
        })}
      </div>
      <div className="b-freshness-note"><Clock3 size={14} /><span>Current paired values require each leg to be AVAILABLE and ≤300 seconds old, with ≤300 seconds of pair skew. Future timestamps fail freshness.</span></div>
      <section className="b-chart-module">
        <div className="b-chart-module-head"><div><span className="b-eyebrow">SYNTHETIC / ILLUSTRATIVE</span><h3>Demo curve · {item.id}</h3></div><span>Not historical data</span></div>
        <div className="b-chart-controls" role="group" aria-label="Illustrative chart range">
          <span>Range changes local curve shape only</span>
          {(["1h", "24h"] as const).map((range) => <button key={range} type="button" aria-pressed={chartRange === range} onClick={() => setChartRange(range)} data-testid={`button-range-${range}`}>{range}</button>)}
        </div>
        {chart ? (
          <svg className="b-detail-chart" viewBox="0 0 700 120" role="img" aria-label={`Synthetic illustrative curve for fixture ${item.id}, ${chartRange}; not a historical series`}>
            <path className="b-gridline" d="M0 25H700M0 60H700M0 95H700" />
            <polyline points={chart.shapeA} fill="none" stroke="var(--b-mint)" strokeWidth="2.5" />
            <polyline points={chart.shapeB} fill="none" stroke="var(--b-teal)" strokeWidth="1.3" strokeDasharray="5 5" />
          </svg>
        ) : <div className="b-chart-suppressed" data-testid="chart-suppressed">— · CURVE SUPPRESSED FOR STALE / UNAVAILABLE EVIDENCE</div>}
        <p className="b-chart-caveat">Deterministic synthetic illustration keyed to the full fixture ID and selected range. No actual historical values, live prices, source timestamps, or investable signals are represented.</p>
      </section>
      <div className="b-lifecycle">
        <div className="b-subpanel-head"><strong>FIXTURE LIFECYCLE</strong><span>Local demo events only</span></div>
        {lifecycleForInstrument(item).map((event) => <div className="b-lifecycle-row" key={`${event.canonicalId}-${event.event}`}><span>{event.at}<small>{event.canonicalId}</small></span><div><strong>{event.event}</strong><small>{event.detail}</small></div><StatusBadge value={event.state} /></div>)}
      </div>
      {item.category === "Stablecoins" && <div className="b-evidence-warning"><ShieldCheck size={14} /><span>Asset identity does not imply a USD peg or guaranteed parity.</span></div>}
    </div>
  );
}

function CryptoScreen({
  walletSimulated,
  setWalletSimulated,
  access,
  setAccess,
  watchlist,
  onToggleWatch,
  alerts,
  onEditAlert,
  onToggleAlert,
  onDeleteAlert,
  editingAlertIndex,
  alertName,
  setAlertName,
  alertThreshold,
  setAlertThreshold,
  alertFixtureId,
  setAlertFixtureId,
  alertError,
  onCancelEdit,
  onSubmitAlert,
  notice,
}: {
  walletSimulated: boolean;
  setWalletSimulated: (value: boolean) => void;
  access: AccessState;
  setAccess: (value: AccessState) => void;
  watchlist: string[];
  onToggleWatch: (id: string) => void;
  alerts: AlertDraft[];
  onEditAlert: (index: number) => void;
  onToggleAlert: (index: number) => void;
  onDeleteAlert: (index: number) => void;
  editingAlertIndex: number | null;
  alertName: string;
  setAlertName: (value: string) => void;
  alertThreshold: string;
  setAlertThreshold: (value: string) => void;
  alertFixtureId: string;
  setAlertFixtureId: (value: string) => void;
  alertError: string;
  onCancelEdit: () => void;
  onSubmitAlert: (event: FormEvent<HTMLFormElement>) => void;
  notice: string;
}) {
  const watchedItems = instruments.filter((item) => watchlist.includes(item.id));
  const previewItems = instruments.filter((item) => ["Crypto", "Tokenized Markets", "Stablecoins"].includes(item.category));
  return (
    <main className="b-main b-crypto" id="main-content">
      <PageHeading
        eyebrow="CRYPTO · ACCESS PREVIEW"
        title="Context without execution."
        description="A read-only visual surface for market context and simulated access states. No wallet, identity, or transaction system is connected."
        right={<div className="b-demo-stamp"><ShieldCheck size={13} /> SIMULATED UI ONLY</div>}
      />

      <section className="b-access-hero">
        <div className="b-access-copy">
          <div className="b-eyebrow">LOCAL ACCESS STATE · {access.toUpperCase()}</div>
          <h2>{access === "Gated" ? "Access is not configured." : walletSimulated ? "Simulated state preview." : "A preview, not a connection."}</h2>
          <p>{walletSimulated
            ? "SIMULATED CONNECTED is display copy only. No wallet is connected, no identity is checked, and no access is granted."
            : "This prototype has no wallet, custody, account, or identity integration. The control below changes local display copy only."}</p>
          <div className="b-access-actions">
            <button type="button" className="b-button b-button-secondary" aria-pressed={walletSimulated} onClick={() => setWalletSimulated(!walletSimulated)} data-testid="button-simulated-wallet"><Wallet size={15} /> {walletSimulated ? "Reset wallet simulation" : "Preview simulated wallet"}</button>
            <button type="button" className="b-button b-button-disabled" disabled aria-disabled="true" title="Disabled in this visual prototype" data-testid="button-gated-action"><LockKeyhole size={14} /> Gated action disabled</button>
          </div>
          <p className="b-access-note">No login, wallet signature, trading, deposit, swap, custody, or transaction action is possible here.</p>
        </div>
        <div className="b-access-state">
          <div className="b-state-top"><span>SIMULATION CONTROLS</span><span>LOCAL ONLY</span></div>
          <div className="b-access-choice" role="group" aria-label="Simulated access state">
            {(["Public", "Preview", "Gated"] as const).map((value) => <button key={value} type="button" aria-pressed={access === value} onClick={() => setAccess(value)} data-testid={`button-access-${value.toLowerCase()}`}>{value}</button>)}
          </div>
          <div className="b-access-facts"><div><span>Wallet display</span><strong>SIMULATED · {walletSimulated ? "CONNECTED" : "DISCONNECTED"}</strong></div><div><span>Entitlement</span><strong>{access.toUpperCase()} · DEMO STATE</strong></div><div><span>Access decision</span><strong>NOT PERFORMED</strong></div><div><span>Execution</span><strong>UNAVAILABLE</strong></div></div>
        </div>
      </section>
      {notice && <div className="b-inline-notice" role="status" aria-live="polite"><Check size={14} /> {notice}</div>}

      <section className="b-section b-market-preview">
        <div className="b-section-head">
          <div><div className="b-eyebrow">READ-ONLY · DEMO FIXTURES</div><h2>Market identity,<br /><em>without authority.</em></h2></div>
          <a className="b-button b-button-secondary" href="#/radar/crypto">Open Radar Crypto <ChevronRight size={14} /></a>
        </div>
        <div className="b-crypto-market-grid">
          {previewItems.map((item) => {
            const pair = pairAssessment(item);
            const market = currentLegValue(item, "market");
            const reference = currentLegValue(item, "reference");
            return (
              <article className="b-crypto-market-card" key={item.id} data-testid={`crypto-market-${item.id}`}>
                <div className="b-crypto-market-head"><div><span className="b-asset-symbol">{item.symbol}</span><span className="b-cell-sub">{item.name}</span></div><StatusBadge value={pair.pairStatus} /></div>
                <div className="b-crypto-values"><div><span>MARKET · {pair.marketStatus}</span><strong>{formatValue(market, item.unit)}</strong></div><div><span>REFERENCE · NOT EXECUTABLE</span><strong>{formatValue(reference, item.unit)}</strong></div></div>
                <div className="b-crypto-market-foot"><span>{item.id} · {item.chain}</span><a href="#/radar/crypto" aria-label={`Open Radar Crypto for ${item.symbol}`}>Inspect <ArrowUpRight size={13} /></a></div>
              </article>
            );
          })}
        </div>
        <p className="b-provenance-line">Every displayed value is a SYNTHETIC DEMO FIXTURE. Missing or suppressed data remains “—”; it is never replaced with zero.</p>
      </section>

      <section className="b-section b-personalization">
        <div className="b-section-head">
          <div><div className="b-eyebrow">SESSION-LOCAL · RESET TO DEMO DEFAULTS ON RELOAD</div><h2>Watchlist & alert drafts</h2></div>
          <p>These controls demonstrate local UI behavior only. No account persistence, background scheduler, or notification delivery exists.</p>
        </div>
        <div className="b-personalization-grid">
          <section className="b-panel b-watchlist-panel">
            <div className="b-panel-heading"><div><span className="b-eyebrow">LOCAL STATE</span><h3>Watchlist <span className="b-count">{watchlist.length}</span></h3></div><span className="b-panel-note">Memory only · reload resets defaults</span></div>
            {watchedItems.length === 0 ? <div className="b-local-empty"><Star size={17} /><p>No local watchlist items yet. Add one from the fixture rows below.</p></div> : (
              <div className="b-watchlist-list">{watchedItems.map((item) => <div className="b-watchlist-row" key={item.id}><div><strong>{item.symbol}</strong><small>{item.name} · {item.id}</small></div><button type="button" className="b-text-button" onClick={() => onToggleWatch(item.id)} aria-label={`Remove ${item.symbol} from session watchlist`} data-testid={`button-remove-watch-${item.id}`}>Remove</button></div>)}</div>
            )}
            <div className="b-watch-options"><span>Add / remove demo fixtures</span>{previewItems.map((item) => {
              const watched = watchlist.includes(item.id);
              return <button type="button" key={item.id} aria-pressed={watched} className={watched ? "selected" : ""} onClick={() => onToggleWatch(item.id)} data-testid={`button-crypto-watch-${item.id}`}><Star size={13} fill={watched ? "currentColor" : "none"} /> {watched ? "Watching" : `Watch ${item.symbol}`}</button>;
            })}</div>
          </section>

          <section className="b-panel b-alert-panel">
            <div className="b-panel-heading"><div><span className="b-eyebrow">LOCAL DRAFTS · NO DELIVERY</span><h3>{editingAlertIndex === null ? "Alert configuration" : "Edit alert draft"}</h3></div><span className="b-panel-note">No scheduler</span></div>
            <form className="b-alert-form" onSubmit={onSubmitAlert} noValidate>
              <label>Draft name<input value={alertName} onChange={(event) => setAlertName(event.target.value)} placeholder="e.g. Reference review" data-testid="input-alert-name" /></label>
              <label>Threshold (%)<input type="number" min="0.01" max="100" step="0.01" value={alertThreshold} onChange={(event) => setAlertThreshold(event.target.value)} placeholder="2.5" data-testid="input-alert-threshold" /></label>
              <label className="b-alert-asset">Fixture<select value={alertFixtureId} onChange={(event) => setAlertFixtureId(event.target.value)} data-testid="select-alert-fixture">{instruments.map((item) => <option value={item.id} key={item.id}>{item.symbol} · {item.id}</option>)}</select></label>
              {alertError && <p className="b-form-error" role="alert">{alertError}</p>}
              <div className="b-alert-form-actions"><button className="b-button b-button-primary" type="submit" data-testid="button-save-alert"><Plus size={14} /> {editingAlertIndex === null ? "Save local draft" : "Update draft"}</button>{editingAlertIndex !== null && <button className="b-button b-button-secondary" type="button" onClick={onCancelEdit}>Cancel edit</button>}</div>
            </form>
            <div className="b-alert-disclaimer"><ShieldCheck size={14} /> Drafts remain in this browser session only. No alert is scheduled or sent.</div>
            {alerts.length === 0 ? <div className="b-local-empty b-alert-empty"><Clock3 size={16} /><p>No alert drafts in this session.</p></div> : (
              <div className="b-alert-list">
                {alerts.map((alert, index) => {
                  const fixture = instruments.find((item) => item.id === alert.fixtureId);
                  const readiness = alertReadiness(fixture);
                  return (
                    <article className="b-alert-row" key={`${alert.fixtureId}-${alert.name}-${index}`}>
                      <div className="b-alert-row-main"><div><strong>{alert.name}</strong><StatusBadge value={alert.state} /></div><small>{alert.threshold}% · {fixture?.symbol ?? "Unknown"} · DATA READINESS: {readiness} · NO DELIVERY</small></div>
                      <div className="b-alert-row-actions">
                        <button type="button" aria-label={`Edit alert draft ${alert.name}`} onClick={() => onEditAlert(index)} data-testid={`button-edit-alert-${index}`}><Pencil size={13} /></button>
                        <button type="button" aria-label={`${alert.state === "DRAFT" ? "Pause" : "Resume"} alert draft ${alert.name}`} onClick={() => onToggleAlert(index)} data-testid={`button-toggle-alert-${index}`}>{alert.state === "DRAFT" ? <Pause size={13} /> : <Play size={13} />}</button>
                        <button type="button" aria-label={`Delete alert draft ${alert.name}`} onClick={() => onDeleteAlert(index)} data-testid={`button-delete-alert-${index}`}><Trash2 size={13} /></button>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      </section>

      <div className="b-disclosure"><LockKeyhole size={16} /><p><strong>Gated actions remain disabled.</strong> The simulated wallet/access controls do not connect a wallet, grant entitlement, submit a transaction, or enable trading.</p><a href="#/radar/tokenized">Explore Tokenized Markets <ArrowUpRight size={13} /></a></div>
    </main>
  );
}

function RoadmapScreen() {
  const stages = [
    {
      status: "LIVE / IMPLEMENTED",
      title: "Prototype interfaces",
      copy: "This isolated prototype contains local Landing, Radar, Crypto, and Roadmap interfaces with hash navigation and synthetic fixtures. Interface implementation is not evidence of deployed service availability or accepted release state.",
      items: ["Local-only navigation and fixture filters", "Synthetic Radar display with evidence labels", "Simulated Crypto access and disabled gated actions"],
    },
    {
      status: "Q4 2026 TARGET",
      title: "Product cohesion & read-only API",
      copy: "Product cohesion, read-only API work, and access-readiness are targets only. They are not commitments, active services, or guarantees of release.",
      items: ["Target: align public product surfaces", "Target: document read-only API boundaries", "Operational availability remains unverified here"],
    },
    {
      status: "Q1 2027 TARGET",
      title: "Future access and account concepts",
      copy: "Later access and account concepts remain future work. No wallet, entitlement, signing, custody, or execution capability is activated by this prototype.",
      items: ["Target timing only; subject to change", "No production activation represented", "Gating and deployment details remain unconfigured"],
    },
    {
      status: "LATER",
      title: "Further product surfaces",
      copy: "Additional asset coverage and product capabilities are future scope, not a statement that data sources or collection processes are available.",
      items: ["Future asset-class exploration", "Future operational and evidence review", "No dates or availability promise"],
    },
  ];
  return (
    <main className="b-main b-roadmap" id="main-content">
      <PageHeading eyebrow="PUBLIC ROADMAP · STATUS IS NOT A PROMISE" title="A clear view of what exists—and what does not." description="Roadmap stages distinguish interface implementation, operational data availability, and future targets." right={<div className="b-demo-stamp"><BookOpen size={13} /> PUBLIC STATUS NOTES</div>} />
      <div className="b-roadmap-caveat"><ShieldCheck size={16} /><p><strong>Targets are not guarantees.</strong> Dates and planned work can change. Source documentation or UI presence alone does not establish staging acceptance, live data, or production availability.</p></div>
      <div className="b-roadmap-list">
        {stages.map((stage, index) => (
          <section className="b-roadmap-stage" key={stage.status} data-testid={`roadmap-stage-${index}`}>
            <div className="b-stage-index">{String(index + 1).padStart(2, "0")}<span /></div>
            <div className="b-stage-content">
              <div className="b-stage-meta"><StatusBadge value={stage.status} /><span>FINCO PROTOCOL · PUBLIC</span></div>
              <h2>{stage.title}</h2>
              <p>{stage.copy}</p>
              <ul>{stage.items.map((item) => <li key={item}><span />{item}</li>)}</ul>
            </div>
            <ChevronRight className="b-stage-chevron" size={17} />
          </section>
        ))}
      </div>
      <div className="b-roadmap-bottom">
        <div><div className="b-eyebrow">RADAR RELEASE BOUNDARY</div><h2>UI presence is not release acceptance.</h2><p>Radar V1 is documented as DEV CLOSEOUT / DRAFT / NOT STAGING ACCEPTED. This local prototype does not alter that status or establish live data availability.</p></div>
        <a className="b-button b-button-secondary" href="#/radar">Open Radar demo <ArrowDownRight size={15} /></a>
      </div>
    </main>
  );
}

function NotFoundScreen() {
  return <main className="b-main b-not-found" id="main-content"><div className="b-eyebrow">ROUTE NOT FOUND</div><h1>This prototype route is not supported.</h1><p>Use the in-app hash navigation. This experience supports `#/` routes; path-style URLs are not part of this prototype.</p><a className="b-button b-button-primary" href="#/">Return to Landing <ArrowDownRight size={15} /></a></main>;
}

export function FincoNonModelExperience({
  initialRoute = "/",
  initialAccess = "Public",
  initialInstrumentId,
  initialDemoState = "ready",
}: FincoNonModelExperienceProps) {
  const [route, setRoute] = useState<NonModelRoute>(() => readHashRoute(initialRoute));
  const [selectedId, setSelectedId] = useState<string | null>(initialInstrumentId ?? null);
  const [filters, setFilters] = useState(() => radarDefaultFilters(readHashRoute(initialRoute)));
  const [watchlist, setWatchlist] = useState<string[]>(["fx-demo-001", "fx-demo-003"]);
  const [alerts, setAlerts] = useState<AlertDraft[]>([]);
  const [walletSimulated, setWalletSimulated] = useState(false);
  const [access, setAccess] = useState<AccessState>(initialAccess);
  const [chartRange, setChartRange] = useState<"1h" | "24h">("1h");
  const [demoState, setDemoState] = useState<DemoViewState>(initialDemoState);
  const [notice, setNotice] = useState("");
  const [editingAlertIndex, setEditingAlertIndex] = useState<number | null>(null);
  const [alertName, setAlertName] = useState("");
  const [alertThreshold, setAlertThreshold] = useState("");
  const [alertFixtureId, setAlertFixtureId] = useState(instruments[0].id);
  const [alertError, setAlertError] = useState("");
  const previousRoute = useRef<NonModelRoute>(readHashRoute(initialRoute));

  useEffect(() => {
    const onHashChange = () => setRoute(readHashRoute("/"));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    if (previousRoute.current === route) return;
    setFilters(radarDefaultFilters(route));
    setDemoState("ready");
    setNotice("");
    previousRoute.current = route;
  }, [route]);

  useEffect(() => {
    document.title = routeTitle(route);
  }, [route]);

  const selected = useMemo(() => selectedId ? instruments.find((item) => item.id === selectedId) ?? null : null, [selectedId]);
  const filtered = useMemo(() => filterInstruments(instruments, filters), [filters]);
  const currentRouteIsRadar = isRadarDestination(route);
  const setFilterValue = (key: keyof typeof filters, value: string) => setFilters((current) => ({ ...current, [key]: value }));
  const handleRefresh = () => {
    setDemoState("ready");
    setNotice("Local fixture view refreshed. No network request was made.");
  };
  const toggleWatch = (id: string) => setWatchlist((current) => toggleWatchlist(current, id));
  const cancelAlertEdit = () => {
    setEditingAlertIndex(null);
    setAlertName("");
    setAlertThreshold("");
    setAlertError("");
  };
  const submitAlert = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const result = createAlertDraft(alertName, alertThreshold, alertFixtureId);
    if (!result.ok) {
      setAlertError(result.error);
      return;
    }
    setAlerts((current) => saveAlertDraft(current, result.alert, editingAlertIndex));
    setNotice(editingAlertIndex === null ? "Local alert draft saved. Nothing was scheduled or sent." : "Local alert draft updated. Nothing was scheduled or sent.");
    cancelAlertEdit();
  };
  const editAlert = (index: number) => {
    const alert = alerts[index];
    if (!alert) return;
    setEditingAlertIndex(index);
    setAlertName(alert.name);
    setAlertThreshold(String(alert.threshold));
    setAlertFixtureId(alert.fixtureId);
    setAlertError("");
  };
  const deleteAlert = (index: number) => {
    const next = removeAlertAndAdjustEditing(alerts, index, editingAlertIndex);
    setAlerts(next.alerts);
    if (next.editingIndex === null && editingAlertIndex === index) cancelAlertEdit();
    else setEditingAlertIndex(next.editingIndex);
  };

  let screen;
  if (route === "/") screen = <LandingScreen />;
  else if (currentRouteIsRadar) {
    screen = (
      <RadarScreen
        route={route}
        query={filters.query}
        setQuery={(value) => setFilterValue("query", value)}
        category={filters.category}
        setCategory={(value) => setFilterValue("category", value)}
        statusFilter={filters.status}
        setStatusFilter={(value) => setFilterValue("status", value)}
        filtered={filtered}
        selected={selected}
        onSelect={(item) => setSelectedId(item?.id ?? null)}
        watchlist={watchlist}
        onToggleWatch={toggleWatch}
        chartRange={chartRange}
        setChartRange={setChartRange}
        demoState={demoState}
        setDemoState={(value) => { setDemoState(value); setNotice("Local display state changed; no network request was made."); }}
        onRefresh={handleRefresh}
        notice={notice}
      />
    );
  } else if (route === "/crypto") {
    screen = (
      <CryptoScreen
        walletSimulated={walletSimulated}
        setWalletSimulated={setWalletSimulated}
        access={access}
        setAccess={setAccess}
        watchlist={watchlist}
        onToggleWatch={toggleWatch}
        alerts={alerts}
        onEditAlert={editAlert}
        onToggleAlert={(index) => setAlerts((current) => current.map((alert, currentIndex) => currentIndex === index ? toggleAlertState(alert) : alert))}
        onDeleteAlert={deleteAlert}
        editingAlertIndex={editingAlertIndex}
        alertName={alertName}
        setAlertName={(value) => { setAlertName(value); setAlertError(""); }}
        alertThreshold={alertThreshold}
        setAlertThreshold={(value) => { setAlertThreshold(value); setAlertError(""); }}
        alertFixtureId={alertFixtureId}
        setAlertFixtureId={setAlertFixtureId}
        alertError={alertError}
        onCancelEdit={cancelAlertEdit}
        onSubmitAlert={submitAlert}
        notice={notice}
      />
    );
  } else if (route === "/roadmap") screen = <RoadmapScreen />;
  else screen = <NotFoundScreen />;

  return (
    <div className="finco-b-app" data-testid="finco-concept-b">
      <a className="b-skip-link" href="#main-content">Skip to content</a>
      <SiteHeader route={route} />
      {screen}
      <SiteFooter />
    </div>
  );
}
