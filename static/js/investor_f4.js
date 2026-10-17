(function () {
  'use strict';
  if (window.fincoF4EditorRegistered) return;
  window.fincoF4EditorRegistered = true;
  // The existing workbook POST lifecycle refreshes the whole Investor sheet.
  // Retain only its presentation disclosure state, never financial data.
  var panelOpen = false;
  var generation = 0;
  function loadPanel(panel) {
    if (!panel || !panel.open || !window.htmx) return;
    var loader = panel.querySelector('[data-f4-load-url]');
    if (!loader || loader.dataset.f4Loading) return;
    loader.dataset.f4Loading = 'true';
    window.htmx.ajax('GET', loader.dataset.f4LoadUrl, {target: loader, swap: 'outerHTML'});
  }
  document.addEventListener('toggle', function (event) {
    if (!event.target.matches('[data-testid="f4-agreement-panel"]')) return;
    panelOpen = event.target.open;
    loadPanel(event.target);
  }, true);
  document.addEventListener('htmx:beforeRequest', function (event) {
    var panel = document.querySelector('[data-testid="f4-agreement-panel"]');
    if (panel) panelOpen = panel.open;
    var detail = event.detail || {}, config = detail.requestConfig || {};
    var path = String(config.path || '');
    if (String(config.verb).toLowerCase() === 'post' && path.indexOf('/v2/workbook/') === 0) {
      generation += 1;
      return;
    }
    if (String(config.verb).toLowerCase() !== 'get' || path.indexOf('/v2/workbook/investor/agreement?') !== 0) return;
    var captured = generation, xhr = detail.xhr, source = detail.elt || event.target;
    function beforeLoad(responseEvent) {
      var response = responseEvent.detail || {};
      if (response.xhr !== xhr) return;
      if (captured !== generation || response.target !== document.getElementById('f4-investor-workspace')) {
        responseEvent.preventDefault();
      }
    }
    source.addEventListener('htmx:beforeOnLoad', beforeLoad);
    xhr.addEventListener('loadend', function () { source.removeEventListener('htmx:beforeOnLoad', beforeLoad); }, {once: true});
  });
  document.addEventListener('htmx:afterSwap', function () {
    var panel = document.querySelector('[data-testid="f4-agreement-panel"]');
    if (panel && panelOpen) {
      panel.open = true;
      loadPanel(panel);
    }
  });
  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-f4-add], [data-f4-remove]');
    if (!button) return;
    var form = button.closest('.f4-agreement-form');
    if (!form) return;
    if (button.hasAttribute('data-f4-remove')) {
      button.closest('tr').remove();
      return;
    }
    var kind = button.dataset.f4Add;
    var template = form.querySelector('[data-f4-template="' + kind + '"]');
    var target = form.querySelector(kind === 'investor' ? '[data-f4-investors]' : '[data-f4-contributions]');
    target.appendChild(template.content.cloneNode(true));
  });
  document.addEventListener('htmx:configRequest', function (event) {
    var form = event.target.closest('.f4-agreement-form');
    if (!form) return;
    function fields(row) {
      var result = {};
      row.querySelectorAll('[data-f4-field]').forEach(function (input) {
        result[input.dataset.f4Field] = input.type === 'number' ? (input.value === '' ? null : Number(input.value)) : input.value;
      });
      return result;
    }
    var investors = Array.from(form.querySelectorAll('[data-f4-investor]')).map(fields);
    investors.forEach(function (row) {
      row.investment_class = 'COMMON_EQUITY';
      if (typeof row.ownership_fraction === 'number') row.ownership_fraction /= 100; // Percent to typed fraction only.
    });
    event.detail.parameters.agreement = JSON.stringify({
      schema_version: 1, agreement_id: form.elements.agreement_id.value,
      version: form.elements.agreement_id.value === form.dataset.agreementId ? Number(form.dataset.version) : 1,
      currency: 'EUR', unit: 'kEUR', policy: 'RESIDUAL_ONLY',
      investors: investors,
      contributions: Array.from(form.querySelectorAll('[data-f4-contribution]')).map(fields)
    });
  });
  // S7-07: make unsaved edits visible. The server renders the clean state; any edit in the agreement form marks it as an unsaved draft.
  function markDraft(event) {
    var form = event.target.closest && event.target.closest('.f4-agreement-form');
    if (!form) return;
    var note = document.querySelector('[data-f4-draft]');
    if (!note || note.dataset.draft === 'dirty') return;
    note.dataset.draft = 'dirty';
    note.textContent = 'Unsaved draft changes: nothing is stored until you select Save agreement. Saving never runs the model.';
  }
  document.addEventListener('input', markDraft);
  document.addEventListener('click', function (event) { if (event.target.closest && event.target.closest('[data-f4-add],[data-f4-remove]')) markDraft(event); });
  document.addEventListener('htmx:responseError', function (event) {
    var form = event.target.closest('.f4-agreement-form');
    if (!form) return;
    var error = form.querySelector('[data-f4-error]');
    var message = 'Agreement could not be saved. Reload to refresh the workspace.';
    try { message = JSON.parse(event.detail.xhr.responseText).error || message; } catch (_) {}
    error.textContent = message;
    error.hidden = false;
  });
}());
