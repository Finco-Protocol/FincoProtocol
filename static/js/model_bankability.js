/* Input serialization only. Canonical validation and all economics are server-owned. */
(() => {
  if (window.fincoBankabilityEditorInstalled) return;
  window.fincoBankabilityEditorInstalled = true;
  const field = (form, name) => form.querySelector(`[data-f2="${name}"]`);
  const value = (form, name) => field(form, name)?.value || '';
  const numeric = (form, name) => value(form, name).trim() === '' ? null : Number(value(form, name));
  function refresh(form) {
    const targets = value(form, 'targets_mode');
    form.querySelectorAll('[data-f2-target]').forEach(x => { x.disabled = targets !== 'periods'; });
    field(form, 'target_scalar').disabled = targets !== 'scalar';
    form.querySelectorAll('[data-f2-rate]').forEach(x => { x.disabled = value(form, 'rates_mode') !== 'periods'; });
    form.querySelectorAll('[data-f2-fee]').forEach(x => { x.disabled = !field(form, 'fees_enabled')?.checked; });
    const mode = value(form, 'reserve_mode');
    for (const name of ['months', 'requirement_keur', 'commitment_keur', 'fee_pct']) {
      const input = field(form, name);
      if (input) input.disabled = name === 'months' ? mode !== 'automatic_peak' : name === 'requirement_keur' ? !['cash_fixed', 'dsrf'].includes(mode) : mode !== 'dsrf';
    }
    form.querySelectorAll('button').forEach(x => { x.disabled = false; });
  }
  function payload(form) {
    const cfg = {version: 1};
    for (const key of ['sizing_mode', 'lender_case', 'day_count']) if (value(form, key)) cfg[key] = value(form, key);
    const inputNumber = x => x.value.trim() === '' ? null : Number(x.value);
    if (value(form, 'targets_mode') === 'periods') cfg.targets = [...form.querySelectorAll('[data-f2-target]')].map(inputNumber);
    if (value(form, 'targets_mode') === 'scalar') { cfg.targets = []; cfg.target_scalar = numeric(form, 'target_scalar'); }
    if (value(form, 'rates_mode') === 'periods') cfg.rates_pct = [...form.querySelectorAll('[data-f2-rate]')].map(inputNumber);
    if (field(form, 'fees_enabled')?.checked) {
      cfg.fees = {};
      form.querySelectorAll('[data-f2-fee]').forEach(x => { cfg.fees[x.dataset.f2Fee] = inputNumber(x); });
    }
    const mode = value(form, 'reserve_mode');
    if (mode && mode !== 'inherit') cfg.reserve = {mode,
      months: mode === 'automatic_peak' ? numeric(form, 'months') : 0,
      requirement_keur: ['cash_fixed', 'dsrf'].includes(mode) ? numeric(form, 'requirement_keur') : 0,
      commitment_keur: mode === 'dsrf' ? numeric(form, 'commitment_keur') : 0,
      fee_pct: mode === 'dsrf' ? numeric(form, 'fee_pct') : 0};
    return JSON.stringify(cfg);
  }
  document.addEventListener('change', e => { const form = e.target.closest('[data-f2-form]'); if (form) refresh(form); });
  document.addEventListener('submit', e => {
    const form = e.target.closest('[data-f2-form]');
    if (form) form.querySelector('[name="value"]').value = e.submitter?.hasAttribute('data-f2-reset') ? '' : payload(form);
  }, true);
  document.addEventListener('htmx:configRequest', e => {
    if (!e.detail.elt.matches('[data-f2-form]')) return;
    // The submitter has already serialized the selected inputs; HTMX owns CAS tokens.
    e.detail.parameters.value = e.detail.elt.querySelector('[name="value"]').value;
  });
  const init = () => document.querySelectorAll('[data-f2-form]').forEach(refresh);
  document.addEventListener('htmx:afterSwap', init);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
