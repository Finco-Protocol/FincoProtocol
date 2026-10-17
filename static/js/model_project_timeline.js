/* WF-10 Project Timeline V1: read-only view of the SAVED Project Setup dates (COD, construction months, horizon years).
 *
 * It owns no timeline authority and persists nothing: the construction start is derived exactly like the existing construction-timing editor
 * (FincoDates.addMonths: calendar months, month-end clamped), and the exact operating end date is deliberately NOT derived here (the period
 * calendar produces it at Run). Saved values come from the server-rendered data-* attributes; after an accepted Construction Timing Save
 * ('ct:saved') the accepted values are shown, and an unsaved draft ('dd:change') is only flagged as not reflected. It never saves, never
 * fetches and never runs the model.
 */
(function () {
  'use strict';
  if (window.__fincoProjectTimeline) return;
  window.__fincoProjectTimeline = true;
  const D = () => window.FincoDates;
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const wholeInt = (v) => { const t = String(v == null ? '' : v).trim(); return /^\d+$/.test(t) ? parseInt(t, 10) : null; };

  // Pure evaluation of the saved values -> what to show and what to review. No DOM access.
  function evaluate(cod, monthsRaw, horizonRaw) {
    const out = {cod: null, start: null, months: null, horizon: null, warnings: []};
    const dates = D();
    const codText = String(cod == null ? '' : cod).trim();
    if (!codText) out.warnings.push('The Commercial Operation Date (COD) is not set. Set it in Construction timing.');
    else if (!dates || !dates.parse(codText)) out.warnings.push('The COD "' + codText + '" is not a valid calendar date (expected YYYY-MM-DD). Review it in Project Setup.');
    else out.cod = codText;
    const m = wholeInt(monthsRaw);
    if (String(monthsRaw == null ? '' : monthsRaw).trim() === '') out.warnings.push('The construction duration is not set. Set it in Construction timing.');
    else if (m === null || m < 1) out.warnings.push('The construction duration "' + monthsRaw + '" is not a positive whole number of months. Review it in Construction timing.');
    else out.months = m;
    const h = wholeInt(horizonRaw);
    if (String(horizonRaw == null ? '' : horizonRaw).trim() === '') out.warnings.push('The project horizon is not set. Review it in Project Setup.');
    else if (h === null || h < 1) out.warnings.push('The project horizon "' + horizonRaw + '" is not a positive whole number of years. Review it in Project Setup.');
    else out.horizon = h;
    if (out.cod && out.months !== null) {
      const start = dates.addMonths(out.cod, -out.months);
      if (!start || start >= out.cod) out.warnings.push('The derived construction start is not before the COD. Review the COD and duration.');
      else if (dates.addMonths(start, out.months) !== out.cod)
        out.warnings.push('The COD ' + out.cod + ' cannot be reproduced exactly as construction start + ' + dates.describe(out.months) + ' under the month-end convention (derived start ' + start + '). Review the COD or duration.');
      else out.start = start;
      if (!out.start && start && start < out.cod) out.startApprox = start;
    }
    return out;
  }

  function row(dl, term, value, tag) {
    dl.appendChild(el('dt', null, term));
    const dd = el('dd', null, value);
    if (tag) dd.appendChild(el('span', 'pt-tag', tag));
    dl.appendChild(dd);
    return dd;
  }

  function render(root, saved, draftNote) {
    const dates = D();
    const ev = evaluate(saved.cod, saved.months, saved.horizon);
    const view = root.querySelector('[data-pt-view]');
    if (!view) return;
    view.replaceChildren();
    const stages = el('ol', 'pt-stages');
    stages.setAttribute('data-testid', 'project-timeline-stages');
    const c = el('li', 'pt-stage'); c.dataset.stage = 'construction';
    c.appendChild(el('h4', null, '1 · Construction'));
    const cdl = el('dl'); cdl.setAttribute('data-testid', 'project-timeline-construction');
    const startShown = ev.start || ev.startApprox || null;
    row(cdl, 'Construction start', startShown || 'Not available', startShown ? 'derived: COD − duration' : null).setAttribute('data-pt-start', startShown || '');
    row(cdl, 'Duration', ev.months !== null ? dates.describe(ev.months) : 'Not available', ev.months !== null ? 'saved input' : null).setAttribute('data-pt-months', ev.months !== null ? String(ev.months) : '');
    row(cdl, 'COD (end of construction)', ev.cod || 'Not available', ev.cod ? 'saved input' : null).setAttribute('data-pt-cod', ev.cod || '');
    c.appendChild(cdl);
    const o = el('li', 'pt-stage'); o.dataset.stage = 'operations';
    o.appendChild(el('h4', null, '2 · Operations'));
    const odl = el('dl'); odl.setAttribute('data-testid', 'project-timeline-operations');
    row(odl, 'Operations begin', ev.cod ? 'COD ' + ev.cod : 'Not available', ev.cod ? 'anchor' : null);
    row(odl, 'Project horizon', ev.horizon !== null ? ev.horizon + (ev.horizon === 1 ? ' year' : ' years') : 'Not available', ev.horizon !== null ? 'saved input' : null).setAttribute('data-pt-horizon', ev.horizon !== null ? String(ev.horizon) : '');
    row(odl, 'Modeled end date', 'Set by the model period calendar at Run', 'not derived here');
    o.appendChild(odl);
    stages.appendChild(c); stages.appendChild(o);
    view.appendChild(stages);
    if (ev.months !== null && ev.horizon !== null) {            // proportional bar in months: relative durations only, no dates implied
      const total = ev.months + ev.horizon * 12;
      const bar = el('div', 'pt-bar'); bar.setAttribute('role', 'img');
      bar.setAttribute('aria-label', 'Construction ' + dates.describe(ev.months) + ' then operations ' + ev.horizon + (ev.horizon === 1 ? ' year' : ' years') + ' (relative lengths)');
      const a = el('span', 'pt-seg-c'), b = el('span', 'pt-seg-o');
      a.style.flexGrow = String(ev.months); b.style.flexGrow = String(ev.horizon * 12); a.style.flexBasis = '0'; b.style.flexBasis = '0';
      bar.appendChild(a); bar.appendChild(b); view.appendChild(bar);
      view.appendChild(el('p', 'pt-bar-caption', 'Relative lengths: construction ' + ev.months + ' of ' + total + ' months (' + Math.round(ev.months / total * 100) + '%), then operations. Text above is authoritative.'));
    }
    const notes = el('ul', 'pt-notes'); notes.setAttribute('data-testid', 'project-timeline-notes');
    ev.warnings.forEach((w) => { const li = el('li', 'pt-warn', w); li.setAttribute('data-pt-warning', ''); notes.appendChild(li); });
    if (draftNote) { const li = el('li', 'pt-draft', draftNote); li.setAttribute('data-pt-draft', ''); li.setAttribute('role', 'status'); notes.appendChild(li); }
    if (notes.children.length) view.appendChild(notes);
    root.dataset.ptState = ev.warnings.length ? 'review' : 'ok';
  }

  function savedOf(root) { return {cod: root.dataset.cod, months: root.dataset.months, horizon: root.dataset.horizon}; }
  function mountAll() {
    document.querySelectorAll('[data-project-timeline]').forEach((root) => {
      if (root.dataset.ptReady === 'true' || !D()) return;
      root.dataset.ptReady = 'true';
      render(root, savedOf(root), '');
    });
  }
  // An accepted Save: show the values the server accepted (the sheet is then re-rendered from the saved inputs by the existing editor).
  document.addEventListener('ct:saved', (e) => {
    const d = e.detail || {};
    document.querySelectorAll('[data-project-timeline]').forEach((root) => {
      root.dataset.ptDraftNote = '';
      if (d.cod) root.dataset.cod = d.cod;
      if (d.months != null) root.dataset.months = String(d.months);
      render(root, savedOf(root), '');
    });
  });
  // The editor's typed draft is NOT saved: say so, never display it as the timeline.
  document.addEventListener('dd:change', (e) => {
    if (!e.target || !e.target.closest || !e.target.closest('[data-construction-timing]')) return;
    const st = e.detail || {};
    document.querySelectorAll('[data-project-timeline]').forEach((root) => {
      const differs = st.valid && (st.end !== root.dataset.cod || String(st.months) !== String(root.dataset.months));
      const invalid = st.valid === false;
      const note = (differs || invalid) ? 'The Construction timing editor holds an unsaved draft that is not reflected in this timeline. This timeline shows the last saved values.' : '';
      if (root.dataset.ptDraftNote === note) return;
      root.dataset.ptDraftNote = note;
      render(root, savedOf(root), note);
    });
  });
  window.FincoProjectTimeline = {evaluate};                   // pure; exposed for acceptance tests only
  document.addEventListener('DOMContentLoaded', mountAll);
  document.addEventListener('htmx:afterSettle', mountAll);
  mountAll();
})();
