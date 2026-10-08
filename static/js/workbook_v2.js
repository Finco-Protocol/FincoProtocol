// ── Tab navigation ──────────────────────────────────────────────
(function () {
  var tabs = Array.prototype.slice.call(document.querySelectorAll('#v2-sheet-tabs .v2-tab'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('.v2-sheet-panel'));

  function activateTab(btn) {
    tabs.forEach(function(t) {
      t.setAttribute('aria-selected', 'false');
      t.setAttribute('tabindex', '-1');
    });
    panels.forEach(function(p) { p.hidden = true; });
    btn.setAttribute('aria-selected', 'true');
    btn.setAttribute('tabindex', '0');
    var panel = document.getElementById(btn.getAttribute('aria-controls'));
    if (panel) panel.hidden = false;
  }

  tabs.forEach(function(btn, idx) {
    btn.addEventListener('click', function() { activateTab(btn); btn.focus(); });
    btn.addEventListener('keydown', function(e) {
      var newIdx;
      if (e.key === 'ArrowRight') { newIdx = (idx + 1) % tabs.length; }
      else if (e.key === 'ArrowLeft') { newIdx = (idx + tabs.length - 1) % tabs.length; }
      else if (e.key === 'Enter' || e.key === ' ') { activateTab(btn); e.preventDefault(); return; }
      else { return; }
      e.preventDefault();
      activateTab(tabs[newIdx]);
      tabs[newIdx].focus();
    });
  });

  if (tabs.length > 0) {
    // Honour ?sheet=<name> URL param so New Project lands on the correct tab.
    var sheetParam = new URLSearchParams(window.location.search).get('sheet');
    var initialTab = sheetParam
      ? tabs.find(function(t) { return t.id === 'tab-' + sheetParam; }) || tabs[0]
      : tabs[0];
    activateTab(initialTab);
  }

  document.addEventListener('htmx:afterSwap', function() {
    var selectedTab = tabs.find(function(t) {
      return t.getAttribute('aria-selected') === 'true';
    });
    if (selectedTab) {
      var panelId = selectedTab.getAttribute('aria-controls');
      var panel = document.getElementById(panelId);
      if (panel) panel.hidden = false;
    }
  });
})();

// Scenario-switch coherence: read the server-issued composite identity only
// AFTER the primary scenario sheet and all HTMX OOB fragments have settled.
// No economic writes, no CAS retries, and no cross-tab token broadcasts.
(function () {
  var scenarioResponse = /^\/v2\/workbook\/scenarios\/(?:create|select|archive|update-overrides|remove-override)$/;
  document.addEventListener('htmx:afterSettle', function (event) {
    var xhr = event.detail && event.detail.xhr;
    if (!xhr || xhr.status !== 200 || !xhr.responseURL) return;
    var path;
    try { path = new URL(xhr.responseURL, window.location.href).pathname; }
    catch (_) { return; }
    if (!scenarioResponse.test(path)) return;

    var authority = document.getElementById('v2-scenario-edit-authority');
    if (!authority) return;
    var hash = authority.getAttribute('data-content-hash');
    var version = authority.getAttribute('data-workbook-version');
    if (!hash || !version) return;  // Missing authority: do not guess a hash.

    document.querySelectorAll('input[name="content_hash"]').forEach(function (input) {
      input.value = hash;
    });
    document.querySelectorAll('input[name="workbook_version"]').forEach(function (input) {
      input.value = version;
    });
    var shell = document.getElementById('v2-workbook-shell');
    if (shell) {
      shell.setAttribute('data-content-hash', hash);
      shell.setAttribute('data-workbook-version', version);
      shell.setAttribute('data-active-scenario-id',
                         authority.getAttribute('data-active-scenario-id') || '');
    }
  });
})();

// Scoped HTMX handling for controlled Slice 1 application errors.
(function () {
  var SLICE1_UPDATE_ENDPOINT = '/v2/workbook/inputs-slice1/update';
  var CONTROLLED_SWAP_STATUSES = { 409: true, 422: true };

  window.v2ShouldSwapSlice1ErrorResponse = function (event) {
    var detail = (event && event.detail) || {};
    var xhr = detail.xhr || {};
    var status = xhr.status;
    var requestPath = '';

    if (xhr.responseURL) {
      requestPath = xhr.responseURL;
    } else if (detail.pathInfo && detail.pathInfo.requestPath) {
      requestPath = detail.pathInfo.requestPath;
    } else if (detail.requestConfig && detail.requestConfig.path) {
      requestPath = detail.requestConfig.path;
    }

    return !!(
      CONTROLLED_SWAP_STATUSES[status] &&
      requestPath.indexOf(SLICE1_UPDATE_ENDPOINT) !== -1
    );
  };

  document.addEventListener('htmx:beforeSwap', function (event) {
    if (!window.v2ShouldSwapSlice1ErrorResponse(event)) return;
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  });
}());

// P0-A: calculation capacity BUSY is a real HTTP 429 (not a calculation failure). HTMX does not
// swap 4xx responses by default, so swap only a 429 that carries the model-busy marker header;
// the fragment is a user-safe banner ("Calculation capacity is currently busy. Please retry.").
(function () {
  window.v2ShouldSwapModelBusyResponse = function (event) {
    var xhr = (event && event.detail && event.detail.xhr) || {};
    return xhr.status === 429 && typeof xhr.getResponseHeader === 'function' &&
      xhr.getResponseHeader('X-Finco-Model-Busy') === '1';
  };
  document.addEventListener('htmx:beforeSwap', function (event) {
    if (!window.v2ShouldSwapModelBusyResponse(event)) return;
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  });
}());

// ── Field editor: pending / saving / saved / error state machine ──────────
(function () {
  if (window.__v2FieldEditorInitialised) return;
  window.__v2FieldEditorInitialised = true;

  // --- Run queue state ---
  var _runQueued = false;
  var _inFlightSaveCount = 0;  // explicit counter; HX-Trigger fires BEFORE htmx:afterRequest

  function _row(input) { return input.closest('.v2-field-row'); }

  window.v2MarkPending = function (input) {
    input.setAttribute('data-pending', 'true');
    var row = _row(input);
    if (row) { row.classList.add('v2-field-pending'); row.classList.remove('v2-field-saving', 'v2-field-error'); }
  };

  window.v2ClearPending = function (input) {
    input.setAttribute('data-pending', 'false');
    var row = _row(input);
    if (row) row.classList.remove('v2-field-pending');
  };

  function _markSaving(form) {
    var row = form.closest('.v2-field-row');
    if (row) {
      row.classList.add('v2-field-saving');
      row.classList.remove('v2-field-pending', 'v2-field-error');
      row.setAttribute('aria-busy', 'true');
    }
  }

  function _markSaved(form) {
    var row = form.closest('.v2-field-row');
    if (row) { row.classList.remove('v2-field-saving', 'v2-field-pending'); row.removeAttribute('aria-busy'); }
  }

  function _markError(form) {
    var row = form.closest('.v2-field-row');
    if (row) {
      row.classList.add('v2-field-error');
      row.classList.remove('v2-field-saving', 'v2-field-pending');
      row.removeAttribute('aria-busy');
    }
  }

  function _fieldIdOf(node) {
    var row = node && node.closest ? node.closest('.v2-field-row') : null;
    return row ? row.getAttribute('data-field-id') : null;
  }

  function _hasPendingOrSaving() {
    return !!(
      document.querySelector('.v2-field-input[data-pending="true"]') ||
      document.querySelector('.v2-field-row.v2-field-saving')
    );
  }

  function _setRunBtnState(label, disabled) {
    var btns = document.querySelectorAll('.v2-run-btn');
    btns.forEach(function(btn) {
      btn.disabled = disabled;
      if (label) btn.textContent = label;
    });
  }

  function _submitAllPendingForms() {
    var pendingInputs = Array.prototype.slice.call(
      document.querySelectorAll('.v2-field-input[data-pending="true"]')
    );
    pendingInputs.forEach(function(inp) {
      var form = inp.closest('form');
      if (form && form.classList.contains('v2-field-form')) {
        _markSaving(form);
        v2ClearPending(inp);
        form.requestSubmit();
      }
    });
  }

  function _tryFireQueuedRun() {
    if (!_runQueued) return;
    // HX-Trigger (workbook-field-saved) fires BEFORE htmx:afterRequest in HTMX 1.9.x,
    // so the form may still carry v2-field-saving when this is called from the
    // saved-event handler. The in-flight counter is the authoritative gate.
    if (_inFlightSaveCount > 0) return;
    if (_hasPendingOrSaving()) return;  // belt-and-suspenders for any race

    _runQueued = false;
    _setRunBtnState(null, false);

    var runForm = document.querySelector('.v2-run-form');
    if (!runForm) return;

    // Use htmx.ajax() directly so the request is always sent via HTMX with
    // HX-Request:true — regardless of whether the run form was replaced by an
    // OOB swap between the field-save response and this call (which would leave
    // requestSubmit() racing against HTMX re-initialising the new element).
    var action = runForm.getAttribute('action') || '/v2/workbook/run';
    var values = {};
    Array.prototype.forEach.call(runForm.querySelectorAll('input'), function(inp) {
      if (inp.name) values[inp.name] = inp.value;
    });
    htmx.ajax('POST', action, {
      source: runForm,
      target: 'body',
      swap: 'none',
      values: values
    });
  }

  // input event marks field pending
  document.addEventListener('input', function (e) {
    var inp = e.target;
    if (!inp.classList.contains('v2-field-input')) return;
    v2MarkPending(inp);
  });

  window.v2FieldKeydown = function (event) {
    var input = event.target;
    if (event.key === 'Enter') {
      event.preventDefault();
      var form = input.closest('form');
      if (form) { _markSaving(form); v2ClearPending(input); form.requestSubmit(); }
    } else if (event.key === 'Escape') {
      event.preventDefault();
      var original = input.getAttribute('data-original-value');
      if (original !== null) input.value = original;
      v2ClearPending(input);
      if (window.v2FieldValidationUx) window.v2FieldValidationUx.clear(_fieldIdOf(input));
      input.blur();
    }
  };

  window.v2FieldBlur = function (event) {
    var input = event.target;
    if (input.getAttribute('data-pending') === 'true') {
      var form = input.closest('form');
      if (form) { _markSaving(form); v2ClearPending(input); form.requestSubmit(); }
    }
  };

  document.addEventListener('htmx:beforeRequest', function (event) {
    var form = event.detail.elt;
    if (!form || !form.classList || !form.classList.contains('v2-field-form')) return;
    _inFlightSaveCount++;
    _markSaving(form);
    var input = form.querySelector('.v2-field-input');
    var idEl = form.querySelector('input[name="field_id"]');
    if (input && idEl && window.v2FieldValidationUx) {
      window.v2FieldValidationUx.noteSubmitted(idEl.value, input.value);
    }
    if (input) v2ClearPending(input);
  });

  document.addEventListener('htmx:afterRequest', function (event) {
    var form = event.detail.elt;
    // When hx-target outerHTML swap replaces the panel, elt may be the new target
    // element rather than the original form. Fall back to URL matching.
    var isFieldForm = form && form.classList && form.classList.contains('v2-field-form');
    if (!isFieldForm) {
      var xhr = event.detail.xhr;
      if (!xhr || xhr.responseURL.indexOf('/v2/workbook/update') === -1) return;
      // elt is not the field form — decrement counter and gate queued run by URL match
      _inFlightSaveCount = Math.max(0, _inFlightSaveCount - 1);
      if (event.detail.successful) {
        _tryFireQueuedRun();
      } else if (_runQueued) {
        _runQueued = false;
        _setRunBtnState(null, false);
      }
      return;
    }
    if (!form) return;
    // Always decrement — pairs with the increment in htmx:beforeRequest.
    _inFlightSaveCount = Math.max(0, _inFlightSaveCount - 1);
    if (event.detail.successful) {
      _markSaved(form);
      var input = form.querySelector('.v2-field-input');
      if (input) input.setAttribute('data-original-value', input.value);
      // Primary gate: try queued Run now that saving state AND counter are clear.
      // (workbook-field-saved may have already tried and been blocked by the counter.)
      _tryFireQueuedRun();
    } else {
      _markError(form);
      var failedIdEl = form.querySelector('input[name="field_id"]');
      if (failedIdEl && window.v2FieldValidationUx) {
        window.v2FieldValidationUx.registerIfAbsent(failedIdEl.value, {
          message: 'The save could not be completed. Check your connection and try again.',
          untyped: true   // transport failure: no value verdict exists from anyone
        });
      }
      if (_runQueued) {
        _runQueued = false;
        _setRunBtnState(null, false);
      }
    }
  });

  // Listen for server save signals (HX-Trigger headers)
  document.addEventListener('workbook-field-saved', function (e) {
    var detail = e.detail || {};
    if (detail.field_id && window.v2FieldValidationUx) window.v2FieldValidationUx.clear(detail.field_id);
    var newHash = detail.new_hash;
    if (newHash) {
      // Update all hash inputs in Run form and shell
      document.querySelectorAll('input[name="content_hash"]').forEach(function(inp) {
        inp.value = newHash;
      });
      var shell = document.getElementById('v2-workbook-shell');
      if (shell) shell.setAttribute('data-content-hash', newHash);
    }
    _tryFireQueuedRun();
  });

  document.addEventListener('workbook-field-error', function (e) {
    var detail = (e && e.detail) || {};
    if (detail.field_id && window.v2FieldValidationUx) {
      window.v2FieldValidationUx.register(detail.field_id, {
        message: detail.message,
        // `error_class` present (even null) means the server spoke: it is the only authority.
        hasServerClass: Object.prototype.hasOwnProperty.call(detail, 'error_class'),
        errorClass: detail.error_class
      });
    }
    if (_runQueued) {
      _runQueued = false;
      _setRunBtnState(null, false);
    }
  });

  // Intercept Run submit: if pending/saving fields exist, queue run and save first
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!form.classList.contains('v2-run-form')) return;
    if (_hasPendingOrSaving()) {
      event.preventDefault();
      event.stopImmediatePropagation();
      _runQueued = true;
      _setRunBtnState('Saving changes…', true);
      _submitAllPendingForms();
    }
  }, true);

  // Also intercept HTMX-driven Run requests
  document.addEventListener('htmx:confirm', function (event) {
    var elt = event.detail.elt;
    if (!elt || !elt.classList || !elt.classList.contains('v2-run-form')) return;
    if (_hasPendingOrSaving()) {
      event.preventDefault();
      _runQueued = true;
      _setRunBtnState('Saving changes…', true);
      _submitAllPendingForms();
    }
  });
}());

// ── FS: period selector and inner tab functions ───────────────────────────
// These were previously inline in sheet_financial_statements.html.
// Centralised here so they are available on initial page load and after
// any HTMX swap, without re-defining them per-render.

function v2FsPeriodSwitch(val) {
  document.querySelectorAll('.v2-fs-period-tab').forEach(function (el) {
    var isActive = el.getAttribute('data-period-view') === val;
    el.classList.toggle('v2-fs-period-tab-active', isActive);
    el.setAttribute('aria-selected', isActive ? 'true' : 'false');
    el.setAttribute('tabindex', isActive ? '0' : '-1');
  });
  document.querySelectorAll('.v2-fs-table-model').forEach(function (el) {
    el.style.display = val === 'model' ? '' : 'none';
  });
  document.querySelectorAll('.v2-fs-table-annual').forEach(function (el) {
    el.style.display = val === 'annual' ? '' : 'none';
  });
  try { sessionStorage.setItem('v2FsPeriodView', val); } catch (e) {}
}

function v2FsPeriodKeydown(event, val) {
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault();
    var other = val === 'model' ? 'annual' : 'model';
    v2FsPeriodSwitch(other);
    var otherBtn = document.querySelector(
      '.v2-fs-period-tab[data-period-view="' + other + '"]');
    if (otherBtn) otherBtn.focus();
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    v2FsPeriodSwitch(val);
  }
}

function v2FsInnerTabSwitch(panelId) {
  document.querySelectorAll('.v2-fs-inner-tab').forEach(function (t) {
    var active = t.getAttribute('data-panel') === panelId;
    t.setAttribute('aria-selected', active ? 'true' : 'false');
    t.setAttribute('tabindex', active ? '0' : '-1');
  });
  document.querySelectorAll('.v2-fs-inner-panel').forEach(function (p) {
    p.classList.toggle('v2-fs-inner-panel-active', p.id === panelId);
  });
  try { sessionStorage.setItem('v2FsInnerTab', panelId); } catch (e) {}
}

function v2FsInnerTabKeydown(event, panelId) {
  var tabs = Array.prototype.slice.call(
    document.querySelectorAll('.v2-fs-inner-tab'));
  var idx = tabs.findIndex(function (t) {
    return t.getAttribute('data-panel') === panelId;
  });
  var newIdx;
  if (event.key === 'ArrowRight') { newIdx = (idx + 1) % tabs.length; }
  else if (event.key === 'ArrowLeft') { newIdx = (idx + tabs.length - 1) % tabs.length; }
  else if (event.key === 'Enter' || event.key === ' ') {
    v2FsInnerTabSwitch(panelId);
    event.preventDefault();
    return;
  } else { return; }
  event.preventDefault();
  var nextId = tabs[newIdx].getAttribute('data-panel');
  v2FsInnerTabSwitch(nextId);
  tabs[newIdx].focus();
}

function _v2FsRestoreState() {
  try {
    var savedTab = sessionStorage.getItem('v2FsInnerTab');
    if (savedTab && document.getElementById(savedTab)) {
      v2FsInnerTabSwitch(savedTab);
    } else {
      v2FsInnerTabSwitch('fs-inner-panel-pnl');
    }
    var savedView = sessionStorage.getItem('v2FsPeriodView');
    if (savedView === 'model' || savedView === 'annual') {
      v2FsPeriodSwitch(savedView);
    } else {
      v2FsPeriodSwitch('annual');  // Annual is the first-use default
    }
  } catch (e) {
    v2FsInnerTabSwitch('fs-inner-panel-pnl');
    v2FsPeriodSwitch('annual');
  }
}

// Restore on initial page load (all sheets are eagerly included in workbook.html)
document.addEventListener('DOMContentLoaded', function () {
  if (document.getElementById('v2-sheet-financial-statements')) {
    _v2FsRestoreState();
  }
});

// ── FS UI state restore after HTMX swap ──────────────────────────────────
document.addEventListener('htmx:afterSettle', function (e) {
  var elt = e.detail && e.detail.elt;
  if (!elt) return;
  var fsPanel = elt.id === 'v2-sheet-financial-statements' ? elt :
                elt.querySelector && elt.querySelector('#v2-sheet-financial-statements');
  if (!fsPanel && !document.getElementById('v2-sheet-financial-statements')) return;
  _v2FsRestoreState();
});

// ── Merchant Price Curve grid ────────────────────────────────────────────
(function () {
  'use strict';

  function getMerchantRows() {
    return Array.from(document.querySelectorAll('#v2-merchant-grid-body .v2-mg-row'));
  }

  function buildMerchantRow(year, price) {
    var tr = document.createElement('tr');
    tr.className = 'v2-mg-row';
    tr.dataset.year = String(year);
    tr.innerHTML =
      '<td class="v2-mg-cell-year">' + year + '</td>' +
      '<td class="v2-mg-cell-price">' +
        '<input type="number" step="0.01" class="v2-mg-price-input" ' +
        'value="' + (price != null ? price : '') + '" ' +
        'aria-label="Price for ' + year + '">' +
      '</td>' +
      '<td class="v2-mg-cell-action">' +
        '<button type="button" class="v2-mg-delete-row" ' +
        'aria-label="Delete year ' + year + '">&#10005;</button>' +
      '</td>';
    tr.querySelector('.v2-mg-delete-row').addEventListener('click', function () {
      tr.remove();
      merchantGridMarkDirty();
    });
    tr.querySelector('.v2-mg-price-input').addEventListener('change', merchantGridMarkDirty);
    tr.querySelector('.v2-mg-price-input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        merchantGridSerialise();
        var form = document.getElementById('v2-merchant-curve-form');
        if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
      }
    });
    return tr;
  }

  function merchantGridMarkDirty() {
    var btn = document.querySelector('.v2-mg-save');
    if (btn) btn.classList.add('v2-field-save--pending');
  }

  function merchantGridSerialise() {
    var rows = getMerchantRows();
    var curve = rows.map(function (tr) {
      var yearCell = tr.querySelector('.v2-mg-cell-year');
      var priceInput = tr.querySelector('.v2-mg-price-input');
      return {
        year: parseInt(yearCell.textContent.trim(), 10),
        price_eur_mwh: parseFloat(priceInput.value)
      };
    });
    var textarea = document.getElementById('v2-merchant-json-value');
    if (textarea) textarea.value = JSON.stringify(curve);
  }

  function merchantGridInit() {
    var table = document.getElementById('v2-merchant-grid-table');
    if (!table) return;
    var jsonStr = table.dataset.curveJson || '[]';
    var tbody = document.getElementById('v2-merchant-grid-body');
    if (!tbody) return;
    try {
      var items = JSON.parse(jsonStr);
      items.sort(function (a, b) { return a.year - b.year; });
      items.forEach(function (item) {
        tbody.appendChild(buildMerchantRow(item.year, item.price_eur_mwh));
      });
    } catch (e) {
      // Invalid JSON — leave grid empty; user must re-enter.
    }

    // Add Year button
    var addBtn = document.querySelector('.v2-mg-add-row');
    if (addBtn) {
      addBtn.addEventListener('click', function () {
        var rows = getMerchantRows();
        var lastYear = rows.length > 0
          ? parseInt(rows[rows.length - 1].dataset.year, 10)
          : 2042;
        var newRow = buildMerchantRow(lastYear + 1, '');
        tbody.appendChild(newRow);
        newRow.querySelector('.v2-mg-price-input').focus();
        merchantGridMarkDirty();
      });
    }

    // Bind serialise to form submit event (handles both button click and Enter key)
    var form = document.getElementById('v2-merchant-curve-form');
    if (form) {
      form.addEventListener('submit', function (e) {
        merchantGridSerialise();
        // Allow htmx to handle submission normally.
      });
    }

    // Save button onclick fallback (belt-and-suspenders for HTMX flows)
    var saveBtn = document.querySelector('.v2-mg-save');
    if (saveBtn) {
      saveBtn.addEventListener('click', function () {
        merchantGridSerialise();
      });
    }
  }

  // Expose for HTMX re-render re-initialization
  window.v2MerchantGridInit = merchantGridInit;

  // Initialize on first load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', merchantGridInit);
  } else {
    merchantGridInit();
  }

  // Re-initialize after HTMX outerHTML swap
  document.addEventListener('htmx:afterSwap', function (e) {
    if (e.target && e.target.id === 'v2-sheet-revenue') {
      merchantGridInit();
    }
  });

  // Also handle htmx:afterSettle for cases where swap doesn't fire target directly
  document.addEventListener('htmx:afterSettle', function () {
    if (document.getElementById('v2-merchant-grid-table')) {
      merchantGridInit();
    }
  });
})();

// ── Workspace productivity v1: field validation UX + jump-to-field ────────
// Presentation only.  Reuses the existing `workbook-field-error` /
// `workbook-field-saved` HX-Trigger events (no second transport).
//
// Authority chain: FieldValidationError.error_class (server) -> HX event
// `error_class` -> row state -> Smart Panel summary.  When the event carries
// the key, the server is the ONLY authority: a canonical class is used as-is,
// `null` (stale draft, protected project, non-editable field, authority gate)
// and any unrecognised value become SAVE_REJECTED — never a guessed input
// class and never an arbitrary string in a CSS/data attribute.  Only when NO
// server authority exists (transport failure, an emitter without the key) does
// the field's own constraints (browser constraint validation: required / min /
// max / badInput) serve as a fallback; a transport failure is SAVE_REJECTED.  The human-readable message is display
// text and is never parsed.
(function () {
  'use strict';
  if (window.v2FieldValidationUx) return;

  var CLASS_LABELS = {
    REQUIRED_MISSING: 'Required',
    INVALID: 'Invalid',
    OUT_OF_BOUNDS: 'Out of bounds',
    SAVE_REJECTED: 'Save rejected'
  };
  var SUMMARY_CLASSES = ['REQUIRED_MISSING', 'INVALID', 'OUT_OF_BOUNDS', 'SAVE_REJECTED'];
  var INTEGER_TYPES = { int: true, months: true, years: true };

  var _errors = {};     // field_id -> { fieldId, message, value, errorClass, reannounce }
  var _submitted = {};  // field_id -> raw value sent with the most recent save

  function _rowFor(fieldId) {
    var rows = document.querySelectorAll('.v2-field-row[data-fc-row][data-field-id]');
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].getAttribute('data-field-id') === fieldId) return rows[i];
    }
    return null;
  }

  function _inputOf(row) { return row ? row.querySelector('.v2-field-input') : null; }

  function _msgId(fieldId) { return 'v2-err-' + String(fieldId).replace(/[^A-Za-z0-9_-]/g, '_'); }

  // Deterministic, string-free classification of what was submitted.
  function classify(input, row) {
    if (!input) return 'SAVE_REJECTED';
    var raw = String(input.value == null ? '' : input.value).trim();
    var required = !!(input.required || (row && row.getAttribute('data-required') === 'true'));
    if (raw === '') return required ? 'REQUIRED_MISSING' : 'SAVE_REJECTED';
    var v = input.validity;
    if (v) {
      if (v.rangeUnderflow || v.rangeOverflow) return 'OUT_OF_BOUNDS';
      if (v.badInput || v.typeMismatch) return 'INVALID';
      var t = row ? row.getAttribute('data-field-type') : '';
      if (v.stepMismatch && INTEGER_TYPES[t]) return 'INVALID';
    }
    return 'SAVE_REJECTED';
  }

  var SERVER_CLASSES = { REQUIRED_MISSING: true, INVALID: true, OUT_OF_BOUNDS: true };

  // The server's typed class wins; only an absent server verdict falls back.
  function _resolveClass(info, row, value) {
    if (info && info.untyped) return 'SAVE_REJECTED';
    if (info && info.hasServerClass) {
      var c = info.errorClass;
      return (typeof c === 'string' && Object.prototype.hasOwnProperty.call(SERVER_CLASSES, c))
        ? c : 'SAVE_REJECTED';
    }
    return _classifySubmitted(row, value);
  }

  function _classifySubmitted(row, value) {
    var input = _inputOf(row);
    if (!input || input.tagName !== 'INPUT') {
      // <select>/bool controls can only submit one of their own options.
      return (input && input.required && String(value == null ? '' : value).trim() === '')
        ? 'REQUIRED_MISSING' : 'SAVE_REJECTED';
    }
    var probe = input.cloneNode(false);   // detached copy keeps min/max/step/required
    probe.value = value == null ? '' : value;
    return classify(probe, row);
  }

  function _decorate(entry, announce) {
    var row = _rowFor(entry.fieldId);
    if (!row) return false;
    var input = _inputOf(row);
    var id = _msgId(entry.fieldId);
    if (input) {
      // Preserve what the user entered (the sheet re-render shows the persisted
      // value).  It is NOT an unsaved edit, so it must not auto-resubmit on blur.
      if (entry.value != null && input.value !== entry.value) input.value = entry.value;
      input.setAttribute('data-pending', 'false');
      input.setAttribute('aria-invalid', 'true');
      input.setAttribute('aria-describedby', id);
    }
    row.classList.add('v2-field-error');
    row.classList.remove('v2-field-pending', 'v2-field-saving');
    row.removeAttribute('aria-busy');
    row.setAttribute('data-error-class', entry.errorClass);

    var msg = row.querySelector('.v2-field-error-msg');
    if (!msg) {
      msg = document.createElement('span');
      msg.className = 'v2-field-error-msg';
      msg.id = id;
      if (announce) msg.setAttribute('role', 'alert');
      row.appendChild(msg);
    }
    msg.textContent = '';
    var label = document.createElement('span');
    label.className = 'v2-field-error-msg-class';
    label.textContent = CLASS_LABELS[entry.errorClass] + ': ';
    msg.appendChild(label);
    msg.appendChild(document.createTextNode(entry.message || 'This value was not saved.'));
    return true;
  }

  function _undecorate(fieldId) {
    var row = _rowFor(fieldId);
    if (!row) return;
    var input = _inputOf(row);
    if (input) {
      input.removeAttribute('aria-invalid');
      input.removeAttribute('aria-describedby');
    }
    row.classList.remove('v2-field-error');
    row.removeAttribute('data-error-class');
    var msg = row.querySelector('.v2-field-error-msg');
    if (msg) msg.remove();
  }

  function _tabLabelFor(row) {
    var panel = row.closest('.v2-sheet-panel');
    if (!panel) return '';
    var tab = document.querySelector('#v2-sheet-tabs .v2-tab[aria-controls="' + panel.id + '"]');
    return tab ? tab.textContent.trim() : '';
  }

  function renderSummary() {
    var panel = document.getElementById('model-smart-panel');
    if (!panel) return;
    var keys = Object.keys(_errors);
    var any = false;
    SUMMARY_CLASSES.forEach(function (cls) {
      var li = panel.querySelector('[data-summary-class="' + cls + '"]');
      if (!li) return;
      var entries = keys.map(function (k) { return _errors[k]; })
        .filter(function (e) { return e.errorClass === cls && _rowFor(e.fieldId); });
      li.hidden = entries.length === 0;
      var count = li.querySelector('[data-summary-count]');
      if (count) count.textContent = String(entries.length);
      var list = li.querySelector('[data-summary-fields]');
      if (list) {
        list.textContent = '';
        entries.forEach(function (e) {
          var row = _rowFor(e.fieldId);
          var item = document.createElement('li');
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'v2-smart-panel-jump';
          btn.setAttribute('data-jump-field', e.fieldId);
          btn.textContent = (row && row.getAttribute('data-field-label')) || e.fieldId;
          item.appendChild(btn);
          var ctx = row ? _tabLabelFor(row) : '';
          if (ctx) {
            var c = document.createElement('span');
            c.className = 'v2-summary-field-context';
            c.textContent = ctx;
            item.appendChild(c);
          }
          if (e.message) {
            var m = document.createElement('span');
            m.className = 'v2-summary-field-message';
            m.textContent = e.message;
            item.appendChild(m);
          }
          list.appendChild(item);
        });
      }
      if (entries.length) any = true;
    });
    var empty = panel.querySelector('[data-summary-empty]');
    if (empty) empty.hidden = any;

    var ro = panel.querySelector('[data-summary-class="NON_EDITABLE"]');
    if (ro) {
      var n = document.querySelectorAll('.v2-field-readonly[data-fc-row][data-field-id]').length;
      ro.hidden = n === 0;
      var roCount = ro.querySelector('[data-summary-count]');
      if (roCount) roCount.textContent = String(n);
    }
  }

  function _reapplyAll() {
    Object.keys(_errors).forEach(function (k) {
      var entry = _errors[k];
      // The first decoration after a sheet re-render replaces the node that was
      // announced at registration time, so announce it once more; unrelated
      // swaps afterwards stay silent.
      if (_decorate(entry, entry.reannounce)) entry.reannounce = false;
    });
    renderSummary();
  }

  function noteSubmitted(fieldId, value) {
    if (fieldId) _submitted[fieldId] = value;
  }

  function register(fieldId, info) {
    if (!fieldId) return false;
    var row = _rowFor(fieldId);
    // Only editable macro rows can fail a save; locked / calculated / protected
    // rows stay exactly as rendered.
    if (!row || !row.classList.contains('v2-field-editable')) return false;
    var value = Object.prototype.hasOwnProperty.call(_submitted, fieldId)
      ? _submitted[fieldId] : (_inputOf(row) ? _inputOf(row).value : null);
    _errors[fieldId] = {
      fieldId: fieldId,
      message: (info && info.message) || '',
      value: value,
      errorClass: _resolveClass(info, row, value),
      reannounce: true
    };
    _decorate(_errors[fieldId], true);
    renderSummary();
    return true;
  }

  function registerIfAbsent(fieldId, info) {
    if (!fieldId || _errors[fieldId]) return false;
    return register(fieldId, info);
  }

  function clear(fieldId) {
    if (!fieldId) return;
    delete _submitted[fieldId];
    if (_errors[fieldId]) {
      delete _errors[fieldId];
      _undecorate(fieldId);
      renderSummary();
    }
  }

  function _highlight(row) {
    row.classList.remove('v2-field-jump-highlight');
    void row.offsetWidth;            // restart the animation
    row.classList.add('v2-field-jump-highlight');
    if (row.__v2HighlightTimer) clearTimeout(row.__v2HighlightTimer);
    row.__v2HighlightTimer = setTimeout(function () {
      row.classList.remove('v2-field-jump-highlight');
    }, 1900);
  }

  // Activate the owning sheet tab, open collapsed <details> ancestors, scroll,
  // focus through the existing C1 registry/focus modules, then highlight.
  function jump(fieldId) {
    var row = _rowFor(fieldId);
    if (!row) return false;

    var panel = row.closest('.v2-sheet-panel');
    if (panel && panel.hidden) {
      var tab = document.querySelector('#v2-sheet-tabs .v2-tab[aria-controls="' + panel.id + '"]');
      if (tab) tab.click();
    }
    for (var node = row.parentElement; node; node = node.parentElement) {
      if (node.tagName === 'DETAILS' && !node.open) node.open = true;
    }

    var gridRoot = row.closest('[data-fc-grid]');
    var valueCell = row.querySelector('.v2-fc-value-cell[data-fc-cell]');
    if (gridRoot && valueCell && window.FcGridRegistry && window.FcActiveCellManager) {
      var gridId = gridRoot.getAttribute('data-fc-grid');
      var record = window.FcGridRegistry.getAddr(gridId, valueCell.getAttribute('data-fc-addr'));
      if (record) window.FcActiveCellManager.setActiveCell(gridId, record);
    }

    row.scrollIntoView({ block: 'center', inline: 'nearest' });
    // The value cell is display:contents (not focusable); read-only rows focus
    // their rendered value so keyboard and screen-reader users still land on
    // the field — it stays read-only (no control is created).
    var target = _inputOf(row) || row.querySelector('.v2-field-value') || row.querySelector('.v2-field-label');
    if (target && typeof target.focus === 'function') {
      if (!target.hasAttribute('tabindex') && target.tagName !== 'INPUT' && target.tagName !== 'SELECT') {
        target.setAttribute('tabindex', '-1');
      }
      target.focus({ preventScroll: true });
    }
    if (window.FcFocusManager && typeof window.FcFocusManager.syncFocus === 'function') {
      window.FcFocusManager.syncFocus();
    }
    _highlight(row);
    return true;
  }

  document.addEventListener('click', function (event) {
    var btn = event.target && event.target.closest ? event.target.closest('[data-jump-field]') : null;
    if (!btn || btn.disabled) return;
    event.preventDefault();
    jump(btn.getAttribute('data-jump-field'));
  });

  ['htmx:afterSwap', 'htmx:afterSettle', 'htmx:oobAfterSwap'].forEach(function (name) {
    document.addEventListener(name, _reapplyAll);
  });
  document.addEventListener('DOMContentLoaded', renderSummary);

  window.v2FieldValidationUx = {
    classify: classify,
    register: register,
    registerIfAbsent: registerIfAbsent,
    noteSubmitted: noteSubmitted,
    clear: clear,
    jump: jump,
    renderSummary: renderSummary,
    state: function () {
      return Object.keys(_errors).map(function (k) {
        var e = _errors[k];
        return { fieldId: e.fieldId, errorClass: e.errorClass, message: e.message, value: e.value };
      });
    }
  };
  window.v2JumpToField = jump;
})();

// ── Cost grid (CAPEX / OPEX): direct-cell editing ────────────────────────────────────────
// One guarded save per committed row edit (existing composite-hash + row_version CAS),
// a serial save queue (each save needs the fresh tokens from the previous one), at most
// one focused editor, explicit dirty/saving/saved/failed state, and no automatic retry of
// an economic write after a failure.  No financial value is calculated here: totals come
// from the server response that is swapped in.
(function () {
  if (window.__v2CostGridInit) return;
  window.__v2CostGridInit = true;

  var ROW = 'form[data-cost-row]';
  var queue = [];          // row ids waiting to be saved (FIFO)
  var activeId = null;     // row id currently in flight
  var snapshots = {};      // row id -> {vals, failed, message}
  var idleCallbacks = [];  // actions waiting for the grid to become idle
  var hadFailure = false;

  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function rowOf(el) { return el && el.closest ? el.closest(ROW) : null; }
  function cellsOf(row) { return qsa('input[data-cost-cell]', row); }
  function visible(el) { return !!(el && (el.offsetParent !== null || el.getClientRects().length)); }

  function normNumber(raw) {
    var v = String(raw == null ? '' : raw).replace(/\s+/g, '');
    if (v.indexOf(',') >= 0 && v.indexOf('.') >= 0) v = v.replace(/,/g, '');
    else if (v.indexOf(',') >= 0) v = v.replace(',', '.');
    return v;
  }
  function isNumeric(input) { return input.getAttribute('data-cost-cell') !== 'label'; }
  function valueOf(input) { return isNumeric(input) ? normNumber(input.value) : input.value.trim(); }
  function originalOf(input) {
    var o = input.getAttribute('data-original') || '';
    return isNumeric(input) ? normNumber(o) : o.trim();
  }
  function isDirty(row) {
    return cellsOf(row).some(function (i) { return valueOf(i) !== originalOf(i); });
  }
  function valuesOf(row) {
    var out = {};
    cellsOf(row).forEach(function (i) { out[i.name] = i.value; });
    return out;
  }

  function setState(row, kind, text) {
    if (!row) return;
    row.setAttribute('data-save-state', kind || '');
    var el = row.querySelector('[data-cost-state]');
    if (el) el.textContent = text || '';
    if (kind === 'saving') row.setAttribute('aria-busy', 'true'); else row.removeAttribute('aria-busy');
    if (row.__stateTimer) { clearTimeout(row.__stateTimer); row.__stateTimer = null; }
    if (kind === 'saved') {
      row.__stateTimer = setTimeout(function () {
        if (row.getAttribute('data-save-state') === 'saved') setState(row, '', '');
      }, 2500);
    }
  }

  function gridBusy() {
    return !!activeId || queue.length > 0 || qsa(ROW).some(function (r) {
      return isDirty(r) && r.getAttribute('data-save-state') !== 'failed';
    });
  }

  // ── tokens ────────────────────────────────────────────────────────────────────────
  function syncTokens(authority) {
    if (!authority) return;
    var hash = authority.getAttribute('data-content-hash');
    var version = authority.getAttribute('data-workbook-version');
    if (!hash || !version) return;   // never guess a token
    qsa('input[name="content_hash"]').forEach(function (i) { i.value = hash; });
    qsa('input[name="workbook_version"]').forEach(function (i) { i.value = version; });
    var shell = document.getElementById('v2-workbook-shell');
    if (shell) { shell.setAttribute('data-content-hash', hash); shell.setAttribute('data-workbook-version', version); }
  }

  // ── queue ─────────────────────────────────────────────────────────────────────────
  function commitRow(row) {
    if (!row || !row.id) return;
    var st = row.getAttribute('data-save-state');
    if (st === 'queued' || st === 'saving') return;          // Enter + blur never double-submit
    if (st === 'failed' && !row.__explicit) return;          // failed values are never auto-resubmitted
    if (!isDirty(row)) { if (st === 'dirty') setState(row, '', ''); return; }
    var bad = null;
    cellsOf(row).forEach(function (i) {
      if (isNumeric(i) && !/^[-+]?(\d+\.?\d*|\.\d+)$/.test(normNumber(i.value))) bad = i;
      if (!isNumeric(i) && i.required && !i.value.trim()) bad = i;
    });
    if (bad) {
      setState(row, 'invalid', isNumeric(bad) ? 'Enter a number' : 'Description required');
      row.setAttribute('data-invalid', 'true');
      return;
    }
    row.removeAttribute('data-invalid');
    cellsOf(row).forEach(function (i) {
      if (!isNumeric(i)) return;
      // An untouched number is submitted with its exact stored value, never the rounded
      // display text (editing another cell must not silently round this one).
      if (valueOf(i) === originalOf(i) && i.getAttribute('data-exact')) i.value = i.getAttribute('data-exact');
      else i.value = normNumber(i.value);
    });
    row.__explicit = false;
    setState(row, 'queued', 'Waiting…');
    queue.push(row.id);
    pump();
  }

  function pump() {
    if (activeId) return;
    while (queue.length) {
      var id = queue.shift();
      var row = document.getElementById(id);
      if (!row || !document.body.contains(row)) continue;
      activeId = id;
      var focused = document.activeElement && row.contains(document.activeElement) ? document.activeElement : null;
      snapshots[id] = { vals: valuesOf(row), focusName: focused ? focused.name : null, failed: false, message: '' };
      setState(row, 'saving', 'Saving…');
      if (!row.checkValidity()) { finishFailed(row, 'Check the highlighted value'); return; }
      row.requestSubmit();
      return;
    }
    idleCheck();
  }

  function idleCheck() {
    if (activeId || queue.length) return;
    if (!idleCallbacks.length) return;
    var failed = hadFailure; hadFailure = false;
    var cbs = idleCallbacks.splice(0, idleCallbacks.length);
    if (failed) return;                // a failed save cancels the waiting action (never silently proceed)
    cbs.forEach(function (cb) { try { cb(); } catch (e) { /* ignore */ } });
  }

  function flushDirty() {
    qsa(ROW).forEach(function (r) { r.__explicit = true; commitRow(r); });
  }

  // Run an action once all edits are saved (saves them first). Returns false if it must wait.
  window.v2CostGridWhenIdle = function (fn) {
    if (!gridBusy()) { fn(); return true; }
    idleCallbacks.push(fn);
    flushDirty();
    idleCheck();
    return false;
  };

  function finishFailed(row, message) {
    var id = row.id;
    var snap = snapshots[id] || { vals: {} };
    Object.keys(snap.vals || {}).forEach(function (name) {   // keep what the user typed
      var inp = row.querySelector('input[name="' + name + '"][data-cost-cell]');
      if (inp) inp.value = snap.vals[name];
    });
    row.setAttribute('data-failed', 'true');
    setState(row, 'failed', 'Failed' + (message ? ': ' + message : ''));
    hadFailure = true;
    // Distinct queued edits are NOT replayed against whatever caused the failure.
    queue.splice(0, queue.length).forEach(function (qid) {
      var q = document.getElementById(qid);
      if (q) setState(q, 'failed', 'Not saved — resolve the earlier error, then press Enter');
    });
    activeId = null;
    delete snapshots[id];
    idleCheck();
  }

  // ── navigation / key handling ─────────────────────────────────────────────────────
  function grid(el) { return el.closest('[data-cost-grid]'); }
  function focusables(g, kind) {
    return qsa(ROW + ' input[data-cost-cell="' + kind + '"]', g).filter(visible);
  }
  function moveFocus(input, delta) {
    var g = grid(input); if (!g) return;
    var list = focusables(g, input.getAttribute('data-cost-cell'));
    var i = list.indexOf(input);
    var t = list[i + delta];
    if (t) t.focus();
  }
  function adjust(input, dir, big) {
    var step = parseFloat(input.getAttribute('data-step') || '1') || 1;
    var cur = parseFloat(normNumber(input.value));
    if (!isFinite(cur)) return;
    var decimals = (String(step).split('.')[1] || '').length;
    var next = cur + dir * step * (big ? 10 : 1);
    input.value = next.toFixed(decimals);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.select();
  }

  // Excel-like: entering a cell selects its value so typing replaces it.  A mouse press on a
  // cell that is not yet focused is taken over (focus + select synchronously) because the
  // browser would otherwise place the caret after focus and collapse the selection.
  document.addEventListener('mousedown', function (e) {
    var t = e.target;
    if (e.button !== 0 || !t || !t.matches || !t.matches('input[data-cost-cell]')) return;
    if (document.activeElement === t) return;
    e.preventDefault();
    t.focus();
    t.select();
  });
  document.addEventListener('focusin', function (e) {
    var t = e.target;
    if (t.matches && t.matches('input[data-cost-cell]')) t.select();
  });

  document.addEventListener('input', function (e) {
    var t = e.target;
    if (!t.matches || !t.matches('input[data-cost-cell]')) return;
    var row = rowOf(t);
    if (!row) return;
    row.removeAttribute('data-failed');
    row.removeAttribute('data-invalid');
    var st = row.getAttribute('data-save-state');
    if (st === 'saving' || st === 'queued') return;
    if (isDirty(row)) setState(row, 'dirty', 'Unsaved'); else setState(row, '', '');
  });

  document.addEventListener('keydown', function (e) {
    var t = e.target;
    if (!t.matches || !t.matches('input[data-cost-cell]')) return;
    var row = rowOf(t);
    if (!row) return;
    if (e.key === 'Enter') {
      e.preventDefault();
      if (e.repeat) return;
      row.__explicit = true;
      commitRow(row);
      moveFocus(t, e.shiftKey ? -1 : 1);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cellsOf(row).forEach(function (i) { i.value = i.getAttribute('data-original') || ''; });
      row.removeAttribute('data-failed'); row.removeAttribute('data-invalid');
      var st = row.getAttribute('data-save-state');
      if (st !== 'saving' && st !== 'queued') setState(row, '', '');
      t.select();
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      var dir = e.key === 'ArrowUp' ? 1 : -1;
      if (isNumeric(t)) { e.preventDefault(); adjust(t, dir, e.shiftKey); }
      else { e.preventDefault(); moveFocus(t, -dir); }
    }
  });

  document.addEventListener('focusout', function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var row = rowOf(t);
    if (!row) return;
    var next = e.relatedTarget;
    if (next && row.contains(next)) return;        // still inside the same row
    commitRow(row);                                // leaving the row commits it (never double-submits)
  });

  // ── htmx lifecycle ───────────────────────────────────────────────────────────────
  document.addEventListener('htmx:beforeSwap', function (e) {
    var d = e.detail || {};
    var target = d.target;
    if (!target) return;
    if (target.matches && target.matches(ROW)) {
      var snap = snapshots[target.id];
      if (snap) {
        snap.live = valuesOf(target);
        var f = document.activeElement && target.contains(document.activeElement) ? document.activeElement : null;
        snap.focusName = f ? f.name : null;
        snap.sel = f && f.selectionStart != null ? [f.selectionStart, f.selectionEnd] : null;
        var text = d.xhr && d.xhr.responseText || '';
        var m = /data-cost-error="true"[^>]*>([^<]*)</.exec(text);
        snap.failed = !!m;
        snap.message = m ? m[1].trim() : '';
      }
    } else if (target.matches && target.matches('[data-cost-grid]')) {
      var openMap = {};
      qsa('details[data-group-code]', target).forEach(function (dd) { openMap[dd.getAttribute('data-group-code')] = dd.open; });
      var f2 = document.activeElement && target.contains(document.activeElement) ? document.activeElement : null;
      target.__view = {
        id: target.id, open: openMap, y: window.scrollY,
        top: target.scrollTop, focusId: f2 && f2.closest(ROW) ? f2.closest(ROW).id : null,
        focusName: f2 ? f2.name : null
      };
      window.__v2CostView = target.__view;
    }
  });

  document.addEventListener('htmx:afterSettle', function (e) {
    var t = e.target;
    if (!t || !t.matches) return;
    if (t.id && t.id.indexOf('v2-cost-authority-') === 0) { syncTokens(t); return; }
    if (t.matches(ROW)) { rowSettled(t); return; }
    if (t.matches('[data-cost-grid]')) {
      syncTokens(t.querySelector('[id^="v2-cost-authority-"]'));
      var v = window.__v2CostView;
      if (v && v.id === t.id) {
        qsa('details[data-group-code]', t).forEach(function (dd) {
          var code = dd.getAttribute('data-group-code');
          if (Object.prototype.hasOwnProperty.call(v.open, code)) dd.open = v.open[code];
        });
        window.scrollTo(0, v.y);
        if (v.focusId) {
          var r = document.getElementById(v.focusId);
          var inp = r && r.querySelector('input[name="' + v.focusName + '"]');
          if (inp) inp.focus({ preventScroll: true });
        }
        window.__v2CostView = null;
      }
    }
  });

  function rowSettled(row) {
    var snap = snapshots[row.id];
    if (!snap) return;
    delete snapshots[row.id];
    if (snap.failed) {
      snapshots[row.id] = snap;
      activeId = row.id;
      finishFailed(row, snap.message);
      return;
    }
    // Saved: the swapped-in row carries the server's values and the new row_version.
    setState(row, 'saved', 'Saved');
    var live = snap.live || {};
    var changed = false;
    cellsOf(row).forEach(function (i) {
      var l = live[i.name];
      var sent = snap.vals[i.name];
      if (l !== undefined && l !== sent) { i.value = l; changed = true; }   // typed while saving
    });
    if (snap.focusName && (!document.activeElement || document.activeElement === document.body)) {
      var f = row.querySelector('input[name="' + snap.focusName + '"][data-cost-cell]');
      if (f) { f.focus({ preventScroll: true }); if (snap.sel && f.setSelectionRange) { try { f.setSelectionRange(snap.sel[0], snap.sel[1]); } catch (_) {} } }
    }
    activeId = null;
    syncTokens(authorityFor(row));
    if (changed) { setState(row, 'dirty', 'Unsaved'); row.__explicit = false; }
    pump();
    idleCheck();
  }

  function authorityFor(row) {
    var g = row.closest('[data-cost-grid]');
    return g ? g.querySelector('[id^="v2-cost-authority-"]') : null;
  }

  function transportFailure(e) {
    var elt = e.detail && e.detail.elt;
    var row = rowOf(elt) || (elt && elt.matches && elt.matches(ROW) ? elt : null);
    if (!row || row.id !== activeId) return;
    finishFailed(row, 'connection problem — nothing was saved');
  }
  document.addEventListener('htmx:sendError', transportFailure);
  document.addEventListener('htmx:responseError', transportFailure);
  document.addEventListener('htmx:timeout', transportFailure);

  // ── Structural actions and Run wait for pending edits ─────────────────────────────
  document.addEventListener('htmx:confirm', function (e) {
    var elt = e.detail && e.detail.elt;
    if (!elt || !elt.matches) return;
    var structural = elt.closest && elt.closest('[data-cost-grid]') && !elt.matches(ROW) && elt.getAttribute('hx-post');
    var isRun = elt.classList && elt.classList.contains('v2-run-form');
    if (!structural && !isRun) return;
    if (!gridBusy()) return;
    e.preventDefault();
    // Saving swaps rows / run controls, so re-locate the control when the grid is idle.
    var rowId = elt.closest && elt.closest(ROW) ? elt.closest(ROW).id : null;
    var testId = elt.getAttribute('data-testid');
    var formEl = elt.tagName === 'FORM' && elt.id ? elt.id : null;
    v2CostGridWhenIdle(function () {
      if (isRun) {
        var rf = document.querySelector('.v2-run-form');
        if (rf) { rf.requestSubmit ? rf.requestSubmit() : htmx.trigger(rf, 'submit'); }
        return;
      }
      var target = elt.isConnected ? elt : null;
      if (!target && rowId && testId) {
        var r = document.getElementById(rowId);
        target = r && r.querySelector('[data-testid="' + testId + '"]');
      }
      if (!target && testId) target = document.querySelector('[data-testid="' + testId + '"]');
      if (!target && formEl) target = document.getElementById(formEl);
      if (!target) return;
      if (target.tagName === 'FORM') target.requestSubmit(); else htmx.trigger(target, 'click');
    });
  });

  window.addEventListener('beforeunload', function (e) {
    if (gridBusy()) { e.preventDefault(); e.returnValue = ''; }
  });

  window.v2CostGrid = { busy: gridBusy, state: function () { return { active: activeId, queued: queue.slice() }; } };
}());
