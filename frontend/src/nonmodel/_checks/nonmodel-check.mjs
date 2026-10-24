// Concept B NON-MODEL integration check for the FINCO GitHub host.
//
// Combines the two scoped checks shipped in the Replit handoff
// (non-model-logic.test.mjs and render-check.mjs) into one runner adapted to
// this host: modules load through vite's SSR transform (no new tooling), and
// the footer destination contract reflects the HOST integration — the four
// in-surface routes stay hash links, while Verify / API / Docs / Methodology /
// Yield / $FINCO must be real same-origin links to their verified canonical
// destinations and must never be in-surface hash links.
//
// Run: `npm run check:nonmodel` (see frontend/package.json).
import assert from "node:assert/strict";
import { createServer } from "vite";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

const server = await createServer({
  server: { middlewareMode: true },
  appType: "custom",
});

try {
  const { FincoNonModelExperience } = await server.ssrLoadModule(
    "/src/nonmodel/FincoNonModelExperience.tsx",
  );
  const logic = await server.ssrLoadModule("/src/nonmodel/_shared/non-model-logic.ts");
  const { instruments } = await server.ssrLoadModule("/src/nonmodel/_shared/fixtures.ts");

  // ───────────── logic contract (ported from non-model-logic.test.mjs) ─────────────

  assert.deepEqual(logic.radarDefaultFilters("/radar/stocks"), {
    query: "",
    category: "Stocks",
    status: "All statuses",
  });
  assert.equal(logic.categoryForRoute("/radar/tokenized"), "Tokenized Markets");
  assert.equal(logic.radarFiltersActive("/radar/stocks", logic.radarDefaultFilters("/radar/stocks")), false);
  assert.equal(logic.radarFiltersActive("/radar/stocks", { query: "nvda", category: "Stocks", status: "All statuses" }), true);
  console.log("PASS route defaults remain contextual; Clear filters detects active changes");

  assert.deepEqual(logic.filterInstruments(instruments, { query: "finco:demo:crypto:BTC" }).map((item) => item.id), ["fx-demo-003"]);
  assert.deepEqual(logic.filterInstruments(instruments, { category: "Stocks" }).map((item) => item.symbol), ["xTSLA", "xNVDA"]);
  assert.deepEqual(logic.filterInstruments(instruments, { status: "Available" }).map((item) => item.id), ["fx-demo-001", "fx-demo-003", "fx-demo-004"]);
  console.log("PASS fixture filtering is searchable and status-aware");

  {
    const row = {};
    const nestedButton = {};
    let selections = 0;
    let prevented = 0;
    const event = (key, target, repeat = false) => ({
      key,
      repeat,
      target,
      currentTarget: row,
      preventDefault() { prevented += 1; },
    });
    logic.handleRadarRowKeyDown(event("Enter", row), () => { selections += 1; });
    logic.handleRadarRowKeyDown(event(" ", nestedButton), () => { selections += 1; });
    logic.handleRadarRowKeyDown(event("Enter", row, true), () => { selections += 1; });
    assert.equal(selections, 1);
    assert.equal(prevented, 2);
  }
  console.log("PASS row keyboard activation selects once and nested controls are isolated");

  {
    let toggles = 0;
    let prevented = 0;
    let stopped = 0;
    const event = (key, repeat = false) => ({
      key,
      repeat,
      preventDefault() { prevented += 1; },
      stopPropagation() { stopped += 1; },
    });
    logic.handleWatchlistButtonKeyDown(event("Enter"), () => { toggles += 1; });
    logic.handleWatchlistButtonKeyDown(event("Enter", true), () => { toggles += 1; });
    logic.handleWatchlistButtonKeyDown(event(" "), () => { toggles += 1; });
    assert.equal(toggles, 2);
    assert.equal(prevented, 3);
    assert.equal(stopped, 3);
  }
  console.log("PASS nested watchlist button Enter and Space each toggle once, including key repeat");

  {
    const first = instruments.find((item) => item.id === "fx-demo-001");
    assert.ok(first);
    const equalLengthDifferentId = { ...first, id: "fx-demo-002" };
    assert.equal(first.id.length, equalLengthDifferentId.id.length);
    assert.notEqual(first.id, equalLengthDifferentId.id);
    assert.deepEqual(logic.illustrativeChartData(first, "1h"), logic.illustrativeChartData(first, "1h"));
    assert.notDeepEqual(logic.illustrativeChartData(first, "1h"), logic.illustrativeChartData(first, "24h"));
    assert.notDeepEqual(logic.illustrativeChartData(first, "1h"), logic.illustrativeChartData(equalLengthDifferentId, "1h"));
  }
  console.log("PASS synthetic curves are reproducible by full fixture ID and range");

  {
    const stale = instruments.find((item) => item.id === "fx-demo-002");
    const unavailable = instruments.find((item) => item.id === "fx-demo-006");
    assert.ok(stale && unavailable);
    assert.equal(logic.pairAssessment(stale).pairStatus, "STALE");
    assert.equal(logic.currentLegValue(stale, "market"), null);
    assert.equal(logic.currentLegValue(stale, "reference"), null);
    assert.equal(logic.illustrativeChartData(stale, "24h"), null);
    assert.equal(logic.illustrativeChartData(unavailable, "1h"), null);
    assert.equal(logic.pairAssessment(unavailable).pairStatus, "UNAVAILABLE");
  }
  console.log("PASS stale or unavailable evidence suppresses current legs, premium and chart");

  {
    const watched = logic.toggleWatchlist([], "fx-demo-003");
    assert.deepEqual(watched, ["fx-demo-003"]);
    assert.deepEqual(logic.toggleWatchlist(watched, "fx-demo-003"), []);
    const created = logic.createAlertDraft("Reference review", "2.5", "fx-demo-003");
    assert.equal(created.ok, true);
    if (created.ok) {
      const saved = logic.saveAlertDraft([], created.alert, null);
      assert.equal(saved.length, 1);
      assert.equal(logic.toggleAlertState(saved[0]).state, "PAUSED");
      assert.deepEqual(logic.removeAlertAndAdjustEditing(saved, 0, 0), { alerts: [], editingIndex: null });
    }
  }
  console.log("PASS watchlist and alert draft helpers remain local CRUD state");

  // ───────────── static render contract (ported from render-check.mjs) ─────────────

  const inScopeRoutes = [
    "/", "/roadmap", "/radar", "/radar/r-live", "/radar/tokenized",
    "/radar/stocks", "/radar/crypto", "/radar/economy", "/crypto",
  ];
  // Verified canonical host destinations (integration V1 footer mapping).
  const hostDestinations = ["/verify", "/api", "/docs", "/model/methodology", "/yield", "/protocol/finco"];
  const hostLabels = ["Verify", "API", "Docs", "Methodology", "Yield", "$FINCO"];

  for (const path of inScopeRoutes) {
    const html = renderToStaticMarkup(createElement(FincoNonModelExperience, { initialRoute: path }));
    assert.ok(html.includes("<main"), `${path}: main landmark`);
    assert.ok(html.includes("FINCO"), `${path}: brand`);
    assert.ok(html.includes("Evidence and context only"), `${path}: demo disclaimer`);
    assert.ok(!html.includes("Page not found"), `${path}: destination rendered`);
    for (const destination of ["/", "/radar", "/crypto", "/roadmap"]) {
      assert.ok(html.includes(`href="#${destination}"`), `${path}: supported footer destination ${destination}`);
    }
    for (const destination of hostDestinations) {
      assert.ok(html.includes(`href="${destination}"`), `${path}: canonical host destination ${destination} is a real link`);
    }
    for (const destination of ["/verify", "/api", "/docs", "/methodology", "/yield", "/finco"]) {
      assert.ok(!html.includes(`href="#${destination}"`), `${path}: host destination ${destination} is not an in-surface hash link`);
    }
    assert.ok(!html.includes("finco-visual-concept"), `${path}: Replit-only concept gallery has no host route`);
    for (const hostDestination of hostLabels) {
      assert.ok(html.includes(hostDestination), `${path}: host destination ${hostDestination} present`);
    }
    if (path.startsWith("/radar")) {
      assert.ok(html.includes("SYNTHETIC DEMO DATA"), `${path}: synthetic label`);
      if (path === "/radar/economy") {
        assert.ok(html.includes("empty-economy"), "Economy preserves honest empty state");
      } else {
        assert.ok(html.includes("instruments-table"), `${path}: table`);
      }
    }
    if (path === "/crypto") assert.ok(html.includes("SIMULATED"), "wallet/access state is disclosed");
    if (path === "/") assert.ok(html.includes("Explore Radar"), "Landing has a Radar destination");
    if (path === "/roadmap") {
      for (const target of ["LIVE / IMPLEMENTED", "Q4 2026 TARGET", "Q1 2027 TARGET", "LATER"]) {
        assert.ok(html.includes(target), `roadmap stage ${target}`);
      }
      assert.ok(html.includes("They are not commitments"), "roadmap target caveat");
    }
    console.log(`PASS static render ${path}`);
  }

  const unknown = renderToStaticMarkup(createElement(FincoNonModelExperience, { initialRoute: "/verify" }));
  assert.ok(unknown.includes("ROUTE NOT FOUND"), "unsupported host route is explicitly unavailable");
  console.log("PASS unsupported host route has explicit fallback");
  console.log("Concept B NON-MODEL integration check completed.");
} finally {
  await server.close();
}
// Vite's canvas instrumentation owns an auxiliary watcher after server.close.
// Assertions above throw before this point; explicitly release the check process on success.
process.exit(0);
