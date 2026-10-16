/* Canonical input serialization only; no financing calculation in the browser. */
(() => {
  if (window.fincoMultiSeniorEditorInstalled) return;
  window.fincoMultiSeniorEditorInstalled = true;
  const read = (row, name) => row.querySelector(`[data-f3="${name}"]`).value.trim();
  const number = (row, name) => {
    const raw = read(row, name), value = Number(raw);
    if (!raw || !Number.isFinite(value)) throw new Error('A finite numeric input is required.');
    return value;
  };
  function payload(form) {
    const state = JSON.parse(form.querySelector('[data-f3-state]').textContent);
    const entry = JSON.parse(form.querySelector('[data-f3-entry]').textContent);
    for (const row of form.querySelectorAll('[data-f3-instrument]')) {
      const i = entry.proposal.instruments.find(x => x.instrument_id === row.dataset.f3Instrument);
      i.name = read(row, 'name');
      i.commitment_keur = number(row, 'commitment_keur');
      i.interest.fixed_rate = number(row, 'rate_pct') / 100;
      i.repayment.mode = read(row, 'repayment_mode');
      i.repayment.grace_months = number(row, 'grace_months');
      i.repayment.maturity_date = read(row, 'maturity_date');
      i.drawdowns = read(row, 'draws').split('\n').filter(x => x.trim()).map(line => {
        const parts = line.split(',').map(x => x.trim());
        if (parts.length !== 2 || !/^\d{4}-\d{2}-\d{2}$/.test(parts[0]) || !parts[1] || !Number.isFinite(Number(parts[1]))) throw new Error('Invalid dated draw.');
        return {draw_date: parts[0], amount_keur: Number(parts[1])};
      });
      i.fees = [{kind: 'UPFRONT', basis: 'COMMITMENT', rate: number(row, 'upfront_pct') / 100},
        {kind: 'COMMITMENT', basis: 'UNDRAWN', rate: number(row, 'commitment_pct') / 100}];
    }
    entry.activation = form.querySelector('[data-f3-activate]').checked ? {
      authority: form.querySelector('[data-f3-authority]').value, proposal_digest: 'BIND_ON_SAVE',
      sponsor_funding_mode: 'EQUITY_ONLY', reserve_support_mode: 'NONE'} : null;
    state.scopes[form.querySelector('[data-f3-scope]').value] = entry;
    return JSON.stringify(state);
  }
  document.addEventListener('submit', e => {
    const form = e.target.closest('[data-f3-form]');
    if (!form) return;
    try {
      form.querySelector('[name="value"]').value = payload(form);
      form.querySelector('[data-f3-error]').textContent = '';
    } catch (error) {
      e.preventDefault(); e.stopImmediatePropagation();
      form.querySelector('[data-f3-error]').textContent = error.message;
    }
  }, true);
  document.addEventListener('htmx:configRequest', e => {
    if (e.detail.elt.matches('[data-f3-form]')) e.detail.parameters.value = e.detail.elt.querySelector('[name="value"]').value;
  });
  /* SC-04: a rejected Save keeps every typed cell. The server answers with HX-Reswap: none plus a typed workbook-field-error event; the
     message is shown once, inside the form, with an explicit Reload for a stale-draft conflict. The write is never replayed automatically. */
  document.addEventListener('workbook-field-error', e => {
    const d = (e && e.detail) || {};
    if (d.field_id !== 'debt.financing.instruments') return;
    const form = document.querySelector('[data-f3-form]');
    const box = form && form.querySelector('[data-f3-error]');
    if (!box) return;
    box.textContent = '';
    box.appendChild(document.createTextNode((d.message || 'The financing proposal was not saved.') + ' Your typed values are kept below. '));
    if (d.conflict === true) {
      const reload = document.createElement('button');
      reload.type = 'button';
      reload.setAttribute('data-conflict-reload', '');
      reload.textContent = 'Reload current values';
      reload.addEventListener('click', () => window.location.reload());
      box.appendChild(reload);
    }
    form.dataset.f3Rejected = d.conflict === true ? 'conflict' : 'rejected';
    form.querySelectorAll('[data-f3-save]').forEach(button => { button.disabled = false; });
  });
  /* Capital Stack cell-first editing: presentation only (dirty markers, keyboard, expand). */
  const cells = form => Array.from(form.querySelectorAll('[data-cs-cell]'));
  const mark = form => {
    let count = 0;
    for (const body of form.querySelectorAll('[data-f3-instrument]')) {
      const dirty = Array.from(body.querySelectorAll('[data-cs-cell]')).some(c => c.value !== c.dataset.initial);
      const flag = body.querySelector('[data-cs-mod]');
      if (flag) flag.hidden = !dirty;
      body.classList.toggle('cs-modified', dirty);
      if (dirty) count += 1;
    }
    const badge = form.querySelector('[data-cs-dirty]');
    if (badge) { badge.hidden = count === 0; badge.querySelector('[data-cs-dirty-count]').textContent = String(count); }
  };
  const setup = root => root.querySelectorAll('[data-f3-form]').forEach(form => {
    if (form.dataset.csReady) return;
    form.dataset.csReady = '1';
    cells(form).forEach(c => { c.dataset.initial = c.value; });
    mark(form);
  });
  document.addEventListener('input', e => { const f = e.target.closest && e.target.closest('[data-f3-form]'); if (f) mark(f); });
  document.addEventListener('change', e => { const f = e.target.closest && e.target.closest('[data-f3-form]'); if (f) mark(f); });
  document.addEventListener('click', e => {
    const button = e.target.closest && e.target.closest('[data-cs-expand]');
    if (!button) return;
    const detail = button.closest('tbody').querySelector('[data-cs-detail]');
    const open = detail.hidden;
    detail.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    button.textContent = open ? '▾' : '▸';
  });
  document.addEventListener('keydown', e => {
    const cell = e.target.closest && e.target.closest('[data-cs-cell]');
    const form = cell && cell.closest('[data-f3-form]');
    if (!form) return;
    if (e.key === 'Escape') { cell.value = cell.dataset.initial; mark(form); return; }
    const vertical = e.key === 'Enter' || ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && cell.tagName !== 'SELECT' && cell.tagName !== 'TEXTAREA');
    if (!vertical || (e.key === 'Enter' && cell.tagName === 'TEXTAREA' && !e.ctrlKey)) return;
    e.preventDefault();
    const name = cell.dataset.f3;
    const same = cells(form).filter(c => c.dataset.f3 === name && c.offsetParent !== null);
    const next = same[same.indexOf(cell) + (e.key === 'ArrowUp' || (e.key === 'Enter' && e.shiftKey) ? -1 : 1)];
    mark(form);
    if (next) { next.focus(); if (next.select) next.select(); }
  });
  const init = () => { document.querySelectorAll('[data-f3-save]').forEach(button => { button.disabled = false; }); setup(document); };
  document.addEventListener('htmx:afterSwap', init);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
