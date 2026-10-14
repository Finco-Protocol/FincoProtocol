/* Native contract serialization only. No browser financial/physical calculations. */
(function () {
  'use strict';
  function init(root) {
    for (const form of root.querySelectorAll('[data-m7-financial-form]')) {
      if (form.dataset.initialized || form.querySelector('fieldset[disabled]')) continue;
      form.dataset.initialized = 'true';
      form.addEventListener('submit', function (event) {
        try {
          const payload = form.querySelector('[data-m7-native-payload]');
          if (form.querySelector('[data-m7-use-native-editor]').checked) {
            payload.value = JSON.stringify(JSON.parse(form.querySelector('[data-m7-native-editor]').value));
            return;
          }
          const native = JSON.parse(payload.value), book = native.configuration;
          for (const input of form.querySelectorAll('[data-m7-battery]')) {
            const value = Number(input.value);
            if (!input.value || !Number.isFinite(value)) throw Error('Supply finite numeric assumptions.');
            book.battery[input.dataset.m7Battery] = input.dataset.fraction === 'true' ? value / 100 : value;
          }
          for (const input of form.querySelectorAll('[data-m7-root]')) book[input.dataset.m7Root] = input.type === 'datetime-local' ? input.value + (input.value.length === 16 ? ':00Z' : 'Z') : input.value;
          native.variable_om_eur_per_dc_mwh = Number(form.querySelector('[data-m7-variable-om]').value);
          for (const row of form.querySelectorAll('[data-m7-point]')) {
            for (const input of row.querySelectorAll('[data-m7-point-field]')) book.dispatch[Number(row.dataset.m7Point)][input.dataset.m7PointField] = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value;
          }
          payload.value = JSON.stringify(native);
        } catch (error) {
          event.preventDefault();
          const message = form.querySelector('[data-m7-error]'); message.hidden = false; message.textContent = error.message;
        }
      });
      form.querySelector('[data-m7-save]').disabled = false;
    }
  }
  init(document);
  document.addEventListener('htmx:afterSwap', function () { init(document); });
  document.addEventListener('htmx:afterRequest', function (event) {
    const detail = event.detail || {}, path = (detail.requestConfig || {}).path || '';
    if (!detail.successful || !(path === '/v2/workbook/run' || path.startsWith('/v2/workbook/scenarios/'))) return;
    const loader = document.querySelector('[data-testid="bess-inputs-loader"]');
    if (loader && window.htmx) window.htmx.ajax('GET', loader.getAttribute('hx-get'), {target: loader, swap: 'innerHTML'});
  });
})();
