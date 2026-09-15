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
  function init() {
    document.querySelectorAll('.v2-overview-chart').forEach(function (el) {
      const type    = el.dataset.chartType;
      const raw     = el.dataset.periods;
      const target  = el.dataset.target;
      if (!raw) return;
      let periods;
      try { periods = JSON.parse(raw); } catch (e) { return; }
      if (!Array.isArray(periods) || !periods.length) return;

      if (type === 'debt-balance') renderDebtBalance(el, periods);
      else if (type === 'dscr')    renderDscr(el, periods, target);
    });
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
