/**
 * UI-3A Overview charts — vanilla SVG renderer.
 *
 * Scans for .v2-overview-chart elements after DOM load; reads their
 * data-chart-type and data-periods attributes (JSON arrays of period dicts
 * from the authoritative debt_schedule.periods payload); renders inline SVG.
 *
 * Chart types:
 *   debt-balance  — Senior balance (area) + period debt service (bar overlay)
 *   dscr          — DSCR polyline with optional target-DSCR reference line
 *
 * Authority contract:
 *   Period field values are used VERBATIM from the authoritative engine output.
 *   No financial aggregation, summation, averaging, or series transformation
 *   is performed. Only pure visual/coordinate operations are applied:
 *   axis scaling, coordinate mapping, label thinning, toFixed() formatting.
 *
 * No external dependencies. No financial computation.
 */
(function () {
  'use strict';

  // ── Palette ─────────────────────────────────────────────────────────── //
  const C = {
    balance:    '#1e40af',  // deep blue — debt balance area
    balanceFill:'#dbeafe',
    ds:         '#6366f1',  // indigo — debt service bars
    dscr:       '#0f766e',  // teal — DSCR line
    target:     '#dc2626',  // red  — target DSCR reference
    axis:       '#9ca3af',
    label:      '#6b7280',
    gridLine:   '#f3f4f6',
  };

  // ── SVG helpers ────────────────────────────────────────────────────── //
  const SVG_NS = 'http://www.w3.org/2000/svg';

  function el(tag, attrs) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    return e;
  }

  function svgRoot(w, h) {
    return el('svg', {
      viewBox: `0 0 ${w} ${h}`,
      preserveAspectRatio: 'none',
      width: '100%',
      height: h,
      role: 'img',
      'aria-hidden': 'true',
    });
  }

  // ── Pure visual helpers (no financial meaning) ──────────────────────── //

  function scaleY(v, vMin, vMax, top, bottom) {
    if (vMax === vMin) return (top + bottom) / 2;
    return bottom - ((v - vMin) / (vMax - vMin)) * (bottom - top);
  }

  // ── Tooltip helper ─────────────────────────────────────────────────── //
  function makeTitle(text) {
    const t = document.createElementNS(SVG_NS, 'title');
    t.textContent = text;
    return t;
  }

  // ── Debt Balance + Debt Service chart ──────────────────────────────── //
  //
  // Renders each authoritative period as one visual point (balance) and one bar
  // (debt service). No aggregation. Native debt_schedule period values used verbatim.
  //
  function renderDebtBalance(container, periods) {
    // Use all periods that have at least a date
    const pts = periods.filter(p => p.date);
    if (!pts.length) { container.textContent = 'No debt schedule data.'; return; }

    const W = 620, H = 160, PAD = { t: 12, r: 8, b: 28, l: 52 };
    const plotW = W - PAD.l - PAD.r;
    const plotH = H - PAD.t - PAD.b;
    const n = pts.length;

    // Read authoritative values verbatim; null → 0 for visual axis scaling only
    const balVals = pts.map(p => p.senior_balance_keur ?? 0);
    const dsVals  = pts.map(p => p.senior_ds_keur ?? 0);
    const balMax  = Math.max(...balVals, 1);
    const dsMax   = Math.max(...dsVals, 1);
    // Shared visual axis: DS bars rendered at 25% of balance scale so they are
    // visible alongside the taller balance area. Pure visual proportion.
    const scale   = Math.max(balMax, dsMax * 4);

    const svg = svgRoot(W, H);
    const barW = Math.max(2, (plotW / n) - 1);

    // Grid lines
    for (let i = 0; i <= 3; i++) {
      const y = PAD.t + (plotH / 3) * i;
      svg.appendChild(el('line', { x1: PAD.l, y1: y, x2: W - PAD.r, y2: y, stroke: C.gridLine, 'stroke-width': 1 }));
    }

    // Balance area — each point maps directly to one authoritative period
    const ptsCoords = pts.map((p, i) => {
      const x = PAD.l + (i / (n - 1 || 1)) * plotW;
      const y = scaleY(p.senior_balance_keur ?? 0, 0, scale, PAD.t, PAD.t + plotH);
      return `${x},${y}`;
    });
    const areaPath = [
      `M ${PAD.l},${PAD.t + plotH}`,
      ...pts.map((p, i) => {
        const x = PAD.l + (i / (n - 1 || 1)) * plotW;
        const y = scaleY(p.senior_balance_keur ?? 0, 0, scale, PAD.t, PAD.t + plotH);
        return `L ${x},${y}`;
      }),
      `L ${W - PAD.r},${PAD.t + plotH} Z`,
    ].join(' ');
    svg.appendChild(el('path', { d: areaPath, fill: C.balanceFill, stroke: 'none' }));
    svg.appendChild(el('polyline', { points: ptsCoords.join(' '), fill: 'none', stroke: C.balance, 'stroke-width': 1.5 }));

    // Debt service bars — one bar per authoritative period
    pts.forEach((p, i) => {
      const dsVal = p.senior_ds_keur ?? 0;
      const dsH   = (dsVal / scale) * plotH;
      const x     = PAD.l + (i / (n - 1 || 1)) * plotW - barW / 2;
      const y     = PAD.t + plotH - dsH;
      const rect  = el('rect', {
        x, y, width: barW, height: Math.max(1, dsH),
        fill: C.ds, opacity: 0.65,
      });
      rect.appendChild(makeTitle(`${(p.date || '').slice(0, 10)}: Debt Service = ${dsVal.toFixed(0)} kEUR`));
      svg.appendChild(rect);
    });

    // Balance circle per period — tooltip shows verbatim authoritative value
    pts.forEach((p, i) => {
      const x   = PAD.l + (i / (n - 1 || 1)) * plotW;
      const y   = scaleY(p.senior_balance_keur ?? 0, 0, scale, PAD.t, PAD.t + plotH);
      const c   = el('circle', { cx: x, cy: y, r: 2.5, fill: C.balance });
      const bal = p.senior_balance_keur;
      c.appendChild(makeTitle(`${(p.date || '').slice(0, 10)}: Balance = ${bal != null ? bal.toFixed(0) : '—'} kEUR`));
      svg.appendChild(c);
    });

    // X-axis labels — thinned for readability (purely visual, no data change)
    const step = Math.max(1, Math.floor(n / 8));
    pts.forEach((p, i) => {
      if (i % step !== 0 && i !== n - 1) return;
      const x = PAD.l + (i / (n - 1 || 1)) * plotW;
      const t = el('text', { x, y: H - 6, 'text-anchor': 'middle', fill: C.label, 'font-size': 9 });
      t.textContent = (p.date || '').slice(0, 7);  // YYYY-MM
      svg.appendChild(t);
    });

    // Y-axis label
    const yLbl = el('text', { x: 4, y: PAD.t + plotH / 2, fill: C.label, 'font-size': 9,
                               transform: `rotate(-90 4 ${PAD.t + plotH / 2})`, 'text-anchor': 'middle' });
    yLbl.textContent = 'kEUR';
    svg.appendChild(yLbl);

    // Legend
    const lgx = PAD.l + 4;
    const lgy = PAD.t + 4;
    svg.appendChild(el('rect', { x: lgx, y: lgy, width: 10, height: 4, fill: C.balanceFill, stroke: C.balance, 'stroke-width': 0.8 }));
    const lt1 = el('text', { x: lgx + 13, y: lgy + 4, fill: C.label, 'font-size': 8.5 }); lt1.textContent = 'Balance'; svg.appendChild(lt1);
    svg.appendChild(el('rect', { x: lgx + 58, y: lgy, width: 10, height: 4, fill: C.ds, opacity: 0.65 }));
    const lt2 = el('text', { x: lgx + 71, y: lgy + 4, fill: C.label, 'font-size': 8.5 }); lt2.textContent = 'Debt Service'; svg.appendChild(lt2);

    container.appendChild(svg);
  }

  // ── DSCR Profile chart ─────────────────────────────────────────────── //
  //
  // Each authoritative operation-period's dscr value maps to one visual point.
  // No aggregation. Native values used verbatim.
  //
  function renderDscr(container, periods, targetStr) {
    const opPeriods = periods.filter(p => p.is_operation && p.dscr != null);
    if (!opPeriods.length) { container.textContent = 'No DSCR data.'; return; }

    const W = 620, H = 140, PAD = { t: 12, r: 8, b: 28, l: 44 };
    const plotW = W - PAD.l - PAD.r;
    const plotH = H - PAD.t - PAD.b;
    const n = opPeriods.length;

    const target = targetStr ? parseFloat(targetStr) : null;
    const vals   = opPeriods.map(p => p.dscr);
    const vMin   = Math.max(0, Math.min(...vals, target ?? Infinity) - 0.2);
    const vMax   = Math.max(...vals, target ?? 0) + 0.2;

    const svg = svgRoot(W, H);

    // Grid
    for (let i = 0; i <= 4; i++) {
      const y = PAD.t + (plotH / 4) * i;
      svg.appendChild(el('line', { x1: PAD.l, y1: y, x2: W - PAD.r, y2: y, stroke: C.gridLine, 'stroke-width': 1 }));
    }

    // Target line
    if (target != null) {
      const ty = scaleY(target, vMin, vMax, PAD.t, PAD.t + plotH);
      svg.appendChild(el('line', { x1: PAD.l, y1: ty, x2: W - PAD.r, y2: ty,
                                    stroke: C.target, 'stroke-width': 1, 'stroke-dasharray': '4 3' }));
      const tl = el('text', { x: W - PAD.r + 2, y: ty + 3, fill: C.target, 'font-size': 8 });
      tl.textContent = `${target.toFixed(2)}x`;
      svg.appendChild(tl);
    }

    // DSCR area fill — each point is one authoritative operation period
    const ptsFill = [
      `${PAD.l},${PAD.t + plotH}`,
      ...opPeriods.map((p, i) => {
        const x = PAD.l + (i / (n - 1 || 1)) * plotW;
        const y = scaleY(p.dscr, vMin, vMax, PAD.t, PAD.t + plotH);
        return `${x},${y}`;
      }),
      `${PAD.l + plotW},${PAD.t + plotH}`,
    ].join(' ');
    svg.appendChild(el('polygon', { points: ptsFill, fill: '#ccfbf1', stroke: 'none', opacity: 0.7 }));

    // DSCR polyline
    const dscrPts = opPeriods.map((p, i) => {
      const x = PAD.l + (i / (n - 1 || 1)) * plotW;
      const y = scaleY(p.dscr, vMin, vMax, PAD.t, PAD.t + plotH);
      return `${x},${y}`;
    });
    svg.appendChild(el('polyline', { points: dscrPts.join(' '), fill: 'none', stroke: C.dscr, 'stroke-width': 1.5 }));

    // Point tooltips — verbatim authoritative period DSCR value shown
    opPeriods.forEach((p, i) => {
      if (i % 4 !== 0 && i !== n - 1) return;
      const x = PAD.l + (i / (n - 1 || 1)) * plotW;
      const y = scaleY(p.dscr, vMin, vMax, PAD.t, PAD.t + plotH);
      const c = el('circle', { cx: x, cy: y, r: 2.5, fill: C.dscr });
      c.appendChild(makeTitle(`${(p.date || '').slice(0, 10)}: DSCR = ${p.dscr.toFixed(2)}x`));
      svg.appendChild(c);
    });

    // X-axis labels — thinned for readability (visual only)
    const step = Math.max(1, Math.floor(n / 8));
    opPeriods.forEach((p, i) => {
      if (i % (step * 2) !== 0 && i !== n - 1) return;
      const x = PAD.l + (i / (n - 1 || 1)) * plotW;
      const t = el('text', { x, y: H - 6, 'text-anchor': 'middle', fill: C.label, 'font-size': 9 });
      t.textContent = (p.date || '').slice(0, 7);  // YYYY-MM
      svg.appendChild(t);
    });

    // Y-axis label
    const yLbl = el('text', { x: 6, y: PAD.t + plotH / 2, fill: C.label, 'font-size': 9,
                               transform: `rotate(-90 6 ${PAD.t + plotH / 2})`, 'text-anchor': 'middle' });
    yLbl.textContent = 'DSCR';
    svg.appendChild(yLbl);

    // Legend
    const lgx = PAD.l + 4, lgy = PAD.t + 4;
    svg.appendChild(el('line', { x1: lgx, y1: lgy + 2, x2: lgx + 12, y2: lgy + 2, stroke: C.dscr, 'stroke-width': 1.5 }));
    const lt = el('text', { x: lgx + 15, y: lgy + 5, fill: C.label, 'font-size': 8.5 }); lt.textContent = 'DSCR'; svg.appendChild(lt);
    if (target != null) {
      svg.appendChild(el('line', { x1: lgx + 48, y1: lgy + 2, x2: lgx + 60, y2: lgy + 2, stroke: C.target, 'stroke-width': 1, 'stroke-dasharray': '4 3' }));
      const lt2 = el('text', { x: lgx + 63, y: lgy + 5, fill: C.label, 'font-size': 8.5 }); lt2.textContent = 'Target'; svg.appendChild(lt2);
    }

    container.appendChild(svg);
  }

  // Financial statement cash waterfall series are persisted Last-Run values.
  // Missing values break a line; they are never turned into zero.
  function renderCashSeries(container, periods, series) {
    const pts = periods.filter(p => p.date && series.some(s =>
      typeof p[s.key] === 'number' && Number.isFinite(p[s.key])));
    if (!pts.length) { container.textContent = 'No Last-Run series available.'; return; }
    const W = 620, H = 178, P = {t: 18, r: 12, b: 30, l: 65};
    const values = pts.flatMap(p => series.map(s => p[s.key]).filter(v => typeof v === 'number' && Number.isFinite(v)));
    const low = Math.min(0, ...values), high = Math.max(0, ...values);
    const max = high === low ? low + 1 : high;
    const svg = svgRoot(W, H);
    const baseline = scaleY(0, low, max, P.t, H - P.b);
    svg.appendChild(el('line', {x1:P.l, y1:baseline, x2:W-P.r, y2:baseline, stroke:C.axis, 'stroke-width':1}));
    series.forEach((s, si) => {
      let path = '';
      pts.forEach((p, i) => {
        const val = p[s.key];
        if (typeof val !== 'number' || !Number.isFinite(val)) { path = path.trim() + ' '; return; }
        const x = P.l + i / (pts.length - 1 || 1) * (W - P.l - P.r);
        const y = scaleY(val, low, max, P.t, H - P.b);
        const previous = i > 0 ? pts[i-1][s.key] : null;
        path += `${typeof previous === 'number' && Number.isFinite(previous) ? 'L' : 'M'} ${x} ${y} `;
        const c = el('circle', {cx:x, cy:y, r:2.2, fill:s.color});
        c.appendChild(makeTitle(`${p.date.slice(0,10)} · ${s.label}: ${val.toLocaleString('en-GB', {maximumFractionDigits:2})} kEUR`));
        svg.appendChild(c);
      });
      svg.appendChild(el('path', {d:path, fill:'none', stroke:s.color, 'stroke-width':2}));
      const tx = el('text', {x:P.l + si * 165, y:12, fill:s.color, 'font-size':10});
      tx.textContent = s.label;
      svg.appendChild(tx);
    });
    const step = Math.max(1, Math.ceil(pts.length / 6));
    pts.forEach((p, i) => {
      if (i % step && i !== pts.length-1) return;
      const x = P.l + i / (pts.length-1 || 1) * (W-P.l-P.r);
      const label = el('text', {x, y:H-6, 'text-anchor':'middle', fill:C.label, 'font-size':9});
      label.textContent = p.date.slice(0,7);
      svg.appendChild(label);
    });
    [low, max].forEach(v => {
      const label = el('text', {x:P.l-6, y:scaleY(v, low, max, P.t, H-P.b)+3,
                                'text-anchor':'end', fill:C.label, 'font-size':9});
      label.textContent = v.toLocaleString('en-GB', {maximumFractionDigits:0});
      svg.appendChild(label);
    });
    container.appendChild(svg);
  }

  // ── Tab navigation from Overview links ─────────────────────────────── //
  function initNavLinks() {
    document.querySelectorAll('[data-goto-tab]').forEach(function (link) {
      link.addEventListener('click', function (e) {
        e.preventDefault();
        var targetTab = link.dataset.gotoTab;
        var btn = document.getElementById('tab-' + targetTab);
        if (btn) btn.click();
      });
    });
  }

  // ── Entry point ─────────────────────────────────────────────────────── //
  function initWorkbookChart(el) {
    const type    = el.dataset.chartType;
    const raw     = el.dataset.periods;
    const target  = el.dataset.target;
    if (!raw) return;
    let periods;
    try { periods = JSON.parse(raw); } catch (e) { return; }
    if (!Array.isArray(periods) || !periods.length) return;

    el.replaceChildren();

    if (type === 'debt-balance') renderDebtBalance(el, periods);
    else if (type === 'dscr')    renderDscr(el, periods, target);
    else if (type === 'operating') renderCashSeries(el, periods, [
      {key:'revenue_cash_keur', label:'Revenue', color:'#1e40af'},
      {key:'opex_cash_keur', label:'OPEX (outflow)', color:'#b45309'},
      {key:'ebitda_cash_keur', label:'EBITDA', color:'#0f766e'},
    ]);
    else if (type === 'cash-service') renderCashSeries(el, periods, [
      {key:'fcf_banks_keur', label:'FCF Banks', color:'#0f766e'},
      {key:'senior_total_ds_keur', label:'Debt service (outflow)', color:'#6366f1'},
    ]);
  }

  function init() {
    // Generic dispatch: any element with data-chart-type is a chart root.
    // The legacy .v2-overview-chart workbook elements keep working unchanged.
    document.querySelectorAll('[data-chart-type]').forEach(function (el) {
      if (el.classList.contains('v2-overview-chart')) { initWorkbookChart(el); return; }
      renderElement(el);
    });
  }

  // ── Radar / terminal primitives (Terminal UX V1) ───────────────────── //
  //
  // Same authority contract as the workbook renderers above: values are
  // consumed VERBATIM from the canonical data handed to the element; only
  // pure visual/coordinate operations are applied. Missing values are GAPS —
  // never interpolated, never zero-filled. No external dependencies.
  //
  // Element contract:
  //   data-chart-type   "sparkline" | "line" | "range-bar"
  //   data-points       JSON [{t: isoString, v: number|null}, ...] (null v = gap)
  //   data-series-2     JSON same shape — second line, same unit (line only)
  //   data-low/high/current  numbers (range-bar)
  //   data-zero-line    "true" → dotted zero reference (sparkline/line)
  //   data-theme        "dark" → Radar terminal palette
  //   aria-label        accessible summary text

  const DARK = {
    line:     '#4ade80',  // primary line — terminal green
    line2:    '#60a5fa',  // secondary series — blue
    marker:   '#f8fafc',
    axis:     '#55606b',
    label:    '#8d98a5',
    gridLine: '#232b33',
    rangeBar: '#1a2129',
    rangeNow: '#4ade80',
  };

  function paletteFor(el) {
    return el.dataset.theme === 'dark' ? DARK : C;
  }

  // Safe numeric parse: anything non-numeric becomes a GAP (null), never 0.
  function num(v) {
    if (v == null || v === '') return null;
    const n = typeof v === 'number' ? v : parseFloat(v);
    return isFinite(n) ? n : null;
  }

  function parsePoints(raw) {
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return null;
      return parsed.map(p => ({ t: String(p.t || ''), v: num(p.v) }));
    } catch (e) { return null; }
  }

  // Split a series into gap-free runs; gaps render as gaps (no interpolation).
  function runsOf(points) {
    const runs = [];
    let run = [];
    for (const p of points) {
      if (p.v == null) { if (run.length) runs.push(run); run = []; continue; }
      run.push(p);
    }
    if (run.length) runs.push(run);
    return runs;
  }

  function extentOf(seriesList) {
    let lo = Infinity, hi = -Infinity;
    for (const pts of seriesList) {
      for (const p of pts) {
        if (p.v == null) continue;
        if (p.v < lo) lo = p.v;
        if (p.v > hi) hi = p.v;
      }
    }
    return lo === Infinity ? null : { lo, hi };
  }

  function renderSparkline(container) {
    const points = parsePoints(container.dataset.points);
    if (!points || !points.some(p => p.v != null)) { container.textContent = '—'; return; }
    const pal = paletteFor(container);
    const W = 120, H = 30;
    const ext = extentOf([points]);
    const lo = ext.lo, hi = ext.hi;
    const svg = svgRoot(W, H);
    svg.removeAttribute('aria-hidden');
    svg.setAttribute('aria-label', container.getAttribute('aria-label') || 'sparkline');
    const xOf = i => (i / (points.length - 1 || 1)) * (W - 4) + 2;
    const yOf = v => scaleY(v, lo, hi, 3, H - 3);
    for (const run of runsOf(points)) {
      const start = points.indexOf(run[0]);
      svg.appendChild(el('polyline', {
        points: run.map((p, j) => `${xOf(start + j)},${yOf(p.v)}`).join(' '),
        fill: 'none', stroke: pal.line, 'stroke-width': 1.25,
      }));
    }
    if (container.dataset.zeroLine === 'true' && lo < 0 && hi > 0) {
      svg.appendChild(el('line', { x1: 0, y1: yOf(0), x2: W, y2: yOf(0), stroke: pal.axis, 'stroke-width': 0.75, 'stroke-dasharray': '2 3' }));
    }
    const runs = runsOf(points);
    const lastRun = runs[runs.length - 1] || [];
    const last = lastRun[lastRun.length - 1];
    if (last) {
      const dot = el('circle', {
        cx: xOf(points.indexOf(last)), cy: yOf(last.v), r: 2, fill: pal.marker,
      });
      dot.appendChild(makeTitle(`Latest: ${last.v} at ${last.t.replace('T', ' ').slice(0, 16)}`));
      svg.appendChild(dot);
    }
    container.replaceChildren(svg);
  }

  function renderLine(container) {
    const s1 = parsePoints(container.dataset.points);
    if (!s1 || !s1.some(p => p.v != null)) {
      container.textContent = container.dataset.emptyText || 'Insufficient history — no chart rendered.';
      return;
    }
    const s2 = container.dataset.series2 ? parsePoints(container.dataset.series2) : null;
    const pal = paletteFor(container);
    const W = 560, H = 170, PAD = { t: 14, r: 12, b: 26, l: 56 };
    const plotW = W - PAD.l - PAD.r, plotH = H - PAD.t - PAD.b;
    const seriesList = s2 ? [s1, s2] : [s1];
    const ext = extentOf(seriesList);
    if (!ext) { container.textContent = '—'; return; }
    let lo = ext.lo, hi = ext.hi;
    if (container.dataset.zeroLine === 'true') { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (lo === hi) { lo -= 1; hi += 1; }
    const svg = svgRoot(W, H);
    svg.removeAttribute('aria-hidden');
    svg.setAttribute('aria-label', container.getAttribute('aria-label') || 'line chart');
    // Points map left→right by their OWN canonical timestamps.
    const times = [];
    for (const pts of seriesList) for (const p of pts) if (p.t) times.push(Date.parse(p.t));
    const tMin = Math.min.apply(null, times), tMax = Math.max.apply(null, times);
    const xOf = p => {
      if (!p.t || !isFinite(tMin) || tMax === tMin) return PAD.l;
      return PAD.l + ((Date.parse(p.t) - tMin) / (tMax - tMin)) * plotW;
    };
    const yOf = v => scaleY(v, lo, hi, PAD.t, PAD.t + plotH);
    for (let i = 0; i <= 3; i++) {
      const y = PAD.t + (plotH / 3) * i;
      svg.appendChild(el('line', { x1: PAD.l, y1: y, x2: W - PAD.r, y2: y, stroke: pal.gridLine, 'stroke-width': 1 }));
    }
    if (container.dataset.zeroLine === 'true' && lo < 0 && hi > 0) {
      svg.appendChild(el('line', { x1: PAD.l, y1: yOf(0), x2: W - PAD.r, y2: yOf(0), stroke: pal.axis, 'stroke-width': 1, 'stroke-dasharray': '3 4' }));
    }
    seriesList.forEach((pts, si) => {
      const color = si === 0 ? pal.line : pal.line2;
      for (const run of runsOf(pts)) {
        svg.appendChild(el('polyline', {
          points: run.map(p => `${xOf(p)},${yOf(p.v)}`).join(' '),
          fill: 'none', stroke: color, 'stroke-width': 1.5,
        }));
      }
      const runs = runsOf(pts);
      const lastRun = runs.length ? runs[runs.length - 1] : [];
      if (lastRun.length) {
        const last = lastRun[lastRun.length - 1];
        const dot = el('circle', { cx: xOf(last), cy: yOf(last.v), r: 2.5, fill: color });
        dot.appendChild(makeTitle(`Latest: ${last.v} at ${last.t.replace('T', ' ').slice(0, 16)}`));
        svg.appendChild(dot);
      }
    });
    [lo, hi].forEach(v => {
      const label = el('text', { x: PAD.l - 6, y: yOf(v) + 3, 'text-anchor': 'end', fill: pal.label, 'font-size': 9 });
      label.textContent = v.toLocaleString('en-GB', { maximumFractionDigits: 2 });
      svg.appendChild(label);
    });
    // Deterministic time-label thinning: at most 5 labels.
    const stamped = s1.filter(p => p.t);
    if (stamped.length) {
      const step = Math.max(1, Math.ceil(stamped.length / 5));
      for (let i = 0; i < stamped.length; i += step) {
        const label = el('text', { x: xOf(stamped[i]), y: H - 6, 'text-anchor': 'middle', fill: pal.label, 'font-size': 9 });
        label.textContent = stamped[i].t.replace('T', ' ').slice(5, 16);
        svg.appendChild(label);
      }
    }
    container.replaceChildren(svg);
  }

  function renderRangeBar(container) {
    const lo = num(container.dataset.low), hi = num(container.dataset.high);
    const now = num(container.dataset.current);
    if (lo == null || hi == null || now == null || hi <= lo) {
      container.textContent = '—';
      return;
    }
    const pal = paletteFor(container);
    const W = 120, H = 14;
    const svg = svgRoot(W, H);
    svg.removeAttribute('aria-hidden');
    svg.setAttribute('aria-label', container.getAttribute('aria-label') || 'range bar');
    svg.appendChild(el('rect', { x: 0, y: 5, width: W, height: 4, rx: 2, fill: pal.rangeBar, stroke: pal.axis, 'stroke-width': 0.5 }));
    const frac = Math.min(1, Math.max(0, (now - lo) / (hi - lo)));
    const x = Math.min(W - 3, Math.max(3, frac * (W - 6) + 3));
    const marker = el('circle', { cx: x, cy: 7, r: 3, fill: pal.rangeNow });
    marker.appendChild(makeTitle(`Now ${now} · 24h range ${lo} … ${hi}`));
    svg.appendChild(marker);
    container.replaceChildren(svg);
  }

  function renderElement(el) {
    const type = el.dataset.chartType;
    if (type === 'sparkline') renderSparkline(el);
    else if (type === 'line') renderLine(el);
    else if (type === 'range-bar') renderRangeBar(el);
  }

  // Programmatic seam for async data (Radar pages fetch snapshot/history
  // client-side, then render): render one element or re-scan the document.
  window.FoCharts = { renderElement: renderElement, renderAll: init };

  if (typeof window !== 'undefined') {
    document.addEventListener('fo-charts:refresh', function () { init(); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(); initNavLinks(); });
  } else {
    init();
    initNavLinks();
  }
  // Re-run after HTMX swaps (in case overview panel is lazy-loaded later)
  document.addEventListener('htmx:afterSwap', init);
})();
