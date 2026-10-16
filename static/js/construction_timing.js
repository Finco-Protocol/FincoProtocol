/* Construction timing: Start Date + Duration -> End Date (= COD), saved through the existing atomic batch writer.
 *
 * The workbook's authoritative inputs are the Commercial Operation Date (cod_date) and the Construction Duration in months
 * (construction_months). The construction start is DERIVED by the model (COD minus the duration, month-end clamped; the engine then requires
 * start + duration == COD). This control only helps the user compute those two inputs; it creates no timeline authority of its own and never runs
 * the model. A combination the engine could not reproduce exactly is refused here instead of failing at the next Run.
 */
(function () {
  'use strict';
  if (window.__fincoConstructionTiming) return;
  window.__fincoConstructionTiming = true;
  const D = () => window.FincoDates;
  function mount(card) {
    if (!card || card.dataset.ctReady === 'true' || !D()) return;
    card.dataset.ctReady = 'true';
    const dd = card.querySelector('[data-dd-root]');
    const save = card.querySelector('[data-ct-save]');
    const msg = card.querySelector('[data-ct-msg]');
    const q = (n) => dd.querySelector('[data-dd="' + n + '"]');
    D().mount(dd);
    const saved = () => ({cod: card.dataset.cod, months: parseInt(card.dataset.months, 10)});
    // initial display: the model-derived start (COD - duration), shown in years when the duration is whole years
    (function init() {
      const s = saved();
      if (!D().parse(s.cod) || !Number.isInteger(s.months)) { msg.textContent = 'Construction timing is not available for this project.'; return; }
      q('start').value = D().addMonths(s.cod, -s.months);
      q('unit').value = s.months % 12 === 0 ? 'years' : 'months';
      q('duration').value = String(s.months % 12 === 0 ? s.months / 12 : s.months);
      dd.ddRecalc();
      if (q('end').value !== s.cod) {                    // not reproducible as start + duration: keep the saved COD visible as a manual end
        q('manual').checked = true; q('end').value = s.cod; dd.ddRecalc();
      }
      refresh();
    })();
    // Identity is read at save time from the page's single authority markers (kept current by every Save / Run), never from a copy made at render.
    function identity() {
      const shell = document.getElementById('v2-workbook-shell'), authority = document.getElementById('v2-scenario-edit-authority');
      return {hash: (authority && authority.dataset.contentHash) || (shell && shell.dataset.contentHash) || card.dataset.contentHash,
              version: (authority && authority.dataset.workbookVersion) || (shell && shell.dataset.workbookVersion) || card.dataset.workbookVersion,
              scenario: authority ? authority.dataset.activeScenarioId : card.dataset.scenarioId};
    }
    function plan() {
      const st = dd.ddState(), s = saved();
      if (!st.valid) return {ok: false, message: st.message};
      const n = st.months;
      if (!Number.isInteger(n)) return {ok: false, message: 'The end date must be a whole number of months after the start date.'};
      if (n < 1 || n > 120) return {ok: false, message: 'Construction can last from 1 to 120 months.'};
      // The engine requires (COD - n months) + n months == COD with month-end clamping; refuse what it could not reproduce.
      if (D().addMonths(D().addMonths(st.end, -n), n) !== st.end)
        return {ok: false, message: 'This end date cannot be represented exactly with a ' + D().describe(n) + ' duration (month-end). Choose another date or duration.'};
      return {ok: true, end: st.end, months: n, changed: st.end !== s.cod || n !== s.months,
              derivedStart: D().addMonths(st.end, -n), start: st.start};
    }
    function refresh() {
      const p = plan();
      save.disabled = !p.ok || !p.changed;
      if (!p.ok) msg.textContent = p.message;
      else if (!p.changed) msg.textContent = 'COD ' + p.end + ' · ' + D().describe(p.months) + ' · saved.';
      else msg.textContent = 'Will set COD to ' + p.end + ' and construction duration to ' + D().describe(p.months) + '.' +
        (p.derivedStart !== p.start ? ' The model derives the start as ' + p.derivedStart + ' (month-end).' : '');
    }
    dd.addEventListener('dd:change', refresh);
    save.addEventListener('click', () => {
      const p = plan();
      if (!p.ok || !p.changed || save.dataset.busy === 'true') return;
      save.dataset.busy = 'true'; save.disabled = true; msg.textContent = 'Saving…';
      const cells = [];
      if (p.end !== saved().cod) cells.push({field_id: 'project_setup.technical.cod_date', value: p.end});
      if (p.months !== saved().months) cells.push({field_id: 'project_setup.technical.construction_months', value: String(p.months)});
      fetch('/v2/workbook/grid/save', {
        method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body: JSON.stringify({project: card.dataset.project, csrf_token: card.dataset.csrf, workbook_version: identity().version,
          content_hash: identity().hash, scenario_id: identity().scenario || null, cells})
      }).then(r => r.json().catch(() => ({ok: false})).then(j => ({status: r.status, body: j}))).then(({status, body}) => {
        save.dataset.busy = 'false';
        if (!body.ok) {
          // SC-04: a rejected Save keeps the typed dates. A stale-page conflict offers an explicit Reload (never an automatic replay).
          const text = status === 409 ? 'The model changed since this page loaded, so nothing was saved. Your typed dates are kept here; reload to see the current values.'
            : (body.message || 'The timing was not saved. Check the dates and try again.');
          refresh();
          msg.textContent = text;
          if (status === 409) {
            const reload = document.createElement('button');
            reload.type = 'button'; reload.setAttribute('data-conflict-reload', ''); reload.textContent = 'Reload current values';
            reload.addEventListener('click', () => window.location.reload());
            msg.appendChild(document.createTextNode(' ')); msg.appendChild(reload);
          }
          return;
        }
        card.dataset.cod = p.end; card.dataset.months = String(p.months);
        card.dataset.contentHash = body.content_hash; card.dataset.workbookVersion = body.workbook_version;
        window.FincoInputGrid?.applyIdentity?.(body.content_hash, body.workbook_version, body.run_state);
        msg.textContent = 'Saved · COD ' + p.end + (body.run_state === 'STALE' ? ' · Last Run is now STALE: run the model to refresh results.' : ' · model not run.');
        document.dispatchEvent(new CustomEvent('ct:saved', {detail: {cod: p.end, months: p.months, runState: body.run_state}}));
        if (window.htmx) {                              // refresh the field editors so they show the saved values and the new CAS hash
          window.htmx.ajax('GET', '/v2/workbook/grid/sheet?project=' + encodeURIComponent(card.dataset.project) + '&sheet=project_setup',
            {source: '#v2-sheet-project-setup', target: '#v2-sheet-project-setup', swap: 'outerHTML'});
        }
        refresh();
      }).catch(() => { save.dataset.busy = 'false'; msg.textContent = 'Connection problem: nothing was saved.'; refresh(); });
    });
  }
  function scan() { document.querySelectorAll('[data-construction-timing]').forEach(mount); }
  document.addEventListener('DOMContentLoaded', scan);
  document.addEventListener('htmx:afterSettle', scan);
  scan();
})();
