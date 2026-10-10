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
  const init = () => document.querySelectorAll('[data-f3-save]').forEach(button => { button.disabled = false; });
  document.addEventListener('htmx:afterSwap', init);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
