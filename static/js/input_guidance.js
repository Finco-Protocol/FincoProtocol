/* SC34-B: navigation helpers for guided input notices (go to a field / open a workbook tab). Presentation only: it focuses or clicks existing
 * controls and never edits, saves or runs anything. Delegated, so it keeps working after HTMX swaps; no inline handlers (strict CSP). */
(function () {
  'use strict';
  if (window.__fincoInputGuidance) return;
  window.__fincoInputGuidance = true;
  document.addEventListener('click', function (event) {
    var field = event.target.closest && event.target.closest('[data-sc34-goto-field]');
    if (field) {
      var row = document.querySelector('[data-field-id="' + field.getAttribute('data-sc34-goto-field') + '"]');
      var input = row && row.querySelector('input[name="value"], select, textarea');
      if (input) { row.scrollIntoView({block: 'center'}); input.focus(); if (input.select) input.select(); }
      return;
    }
    var tab = event.target.closest && event.target.closest('[data-sc34-goto-tab]');
    if (tab) {
      var target = document.getElementById(tab.getAttribute('data-sc34-goto-tab'));
      if (target) { target.click(); target.focus(); }
    }
  });
})();
