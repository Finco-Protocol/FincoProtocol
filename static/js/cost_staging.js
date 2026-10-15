// Cost staging module (CAPEX / OPEX direct-cell editing, staged batch Save).
// C-0 extraction from static/js/workbook_v2.js: moved verbatim, NO behaviour change. This file is loaded immediately after
// workbook_v2.js (same position as before), so  workbook_v2.js + cost_staging.js  is byte-identical to the previous single file
// apart from this header. No new financial computation, persistence or transport lives here.
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
  // Batch editing is the default: edits are staged and saved together in ONE atomic request.  The
  // per-row immediate mode stays available as an explicit choice that is remembered for this tab only.
  var MODE_KEY = 'finco.cost.editMode';
  function storedMode() { try { return window.sessionStorage.getItem(MODE_KEY); } catch (_) { return null; } }
  function storeMode(v) { try { window.sessionStorage.setItem(MODE_KEY, v); } catch (_) { /* private mode */ } }
  var stageMode = storedMode() !== 'immediate';
  var batchInFlight = false;
  var pendingStageMsg = '';
  var lastCell = null;         // {rowId, name} of the cell the user last edited (focus is restored there after a Save)

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
    // The CAPEX and OPEX sheets each carry an authority element; only the swapped sheet receives new
    // attributes from the server, so the other one must be brought forward here, or the next batch
    // Save from that sheet would present a stale composite hash (a false 409).
    qsa('[id^="v2-cost-authority-"]').forEach(function (a) {
      a.setAttribute('data-content-hash', hash); a.setAttribute('data-workbook-version', version);
    });
    var shell = document.getElementById('v2-workbook-shell');
    if (shell) { shell.setAttribute('data-content-hash', hash); shell.setAttribute('data-workbook-version', version); }
  }

  // ── queue ─────────────────────────────────────────────────────────────────────────
  function commitRow(row) {
    if (!row || !row.id) return;
    var st = row.getAttribute('data-save-state');
    if (st === 'queued' || st === 'saving') return;          // Enter + blur never double-submit
    if (st === 'failed' && !row.__explicit) return;          // failed values are never auto-resubmitted
    if (!isDirty(row)) { if (st === 'dirty' || st === 'staged') { setState(row, '', ''); updateStagebars(); } return; }
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
    if (stageMode) {                       // staged: nothing is sent until "Save staged"
      setState(row, 'staged', 'Staged');
      updateStagebars();
      return;
    }
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
    if (stageMode && stageHasEdits()) { stageMessage('Save or discard the staged edits first.'); return false; }
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
    if (t.matches && t.matches('input[data-cost-cell]')) {
      t.select();
      t.__entryValue = t.value;            // Esc returns THIS cell to what it held when it was entered
      var r = rowOf(t);
      if (r) lastCell = { rowId: r.id, name: t.name };
    }
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
    if (stageMode) updateStagebars();
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
      var stNow = row.getAttribute('data-save-state');
      if (stNow === 'saving' || stNow === 'queued') return;
      // Discard the CURRENT cell edit only: the cell returns to the value it held when it was
      // entered (its stored value, or the staged value it already carried).  "Discard" in the
      // stage bar drops every staged edit.
      t.value = t.__entryValue !== undefined ? t.__entryValue : (t.getAttribute('data-original') || '');
      row.removeAttribute('data-failed'); row.removeAttribute('data-invalid');
      if (!isDirty(row)) setState(row, '', '');
      else if (stNow !== 'staged') setState(row, 'dirty', 'Unsaved');
      if (stageMode) updateStagebars();
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
    var isScenario = String(elt.getAttribute('hx-post') || '').indexOf('/v2/workbook/scenarios/') === 0;
    if (!structural && !isRun && !isScenario) return;
    if (!gridBusy()) return;
    if (isScenario || (stageMode && stageHasEdits())) {   // never silently save, never silently drop staged edits
      e.preventDefault();
      stageMessage('Save or discard the staged edits first.');
      showGuard(isRun ? 'Run needs your cost edits saved first.' :
        'You have unsaved cost edits. Save or discard them before ' + (isScenario ? 'changing the scenario.' : 'continuing.'));
      return;
    }
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

  // ── Staged mode: ONE atomic Save for several edited cost lines ────────────────────────
  // Nothing is calculated here.  Rows are collected exactly as typed (untouched numbers keep
  // their stored exact value) and posted once to the server transaction, which verifies every
  // row_version + the composite hash and persists all rows or none.  A failure keeps every typed
  // value on screen; there is no automatic retry of an economic write.
  function stagedRows() { return qsa(ROW).filter(function (r) { return r.getAttribute('data-save-state') === 'staged'; }); }
  function stageHasEdits() { return qsa(ROW).some(function (r) { return isDirty(r); }); }
  function stageMessage(text) { qsa('[data-cost-stage-msg]').forEach(function (el) { el.textContent = text || ''; }); }

  function updateStagebars() {
    var n = stagedRows().length;
    var typing = qsa(ROW).filter(function (r) { return r.getAttribute('data-save-state') === 'dirty'; }).length;
    var failed = qsa(ROW).some(function (r) { return r.getAttribute('data-save-state') === 'failed' && isDirty(r); });
    qsa('[data-cost-grid]').forEach(function (g) { if (stageMode) g.setAttribute('data-stage-mode', 'true'); else g.removeAttribute('data-stage-mode'); });
    qsa('[data-cost-stage-toggle]').forEach(function (c) { c.checked = stageMode; });
    qsa('[data-cost-stage-count]').forEach(function (el) {
      el.textContent = (n || typing) ? (n + ' staged') + (typing ? ' · ' + typing + ' editing' : '') : '';
    });
    // While the request is in flight the Save control stays focusable (marked busy, clicks ignored by the
    // in-flight guard): disabling a focused button would drop focus to <body> until the swap restores it.
    qsa('[data-cost-stage-save]').forEach(function (b) {
      b.disabled = !batchInFlight && !(n || typing || failed);
      if (batchInFlight) b.setAttribute('aria-busy', 'true'); else b.removeAttribute('aria-busy');
    });
    qsa('[data-cost-stage-discard]').forEach(function (b) { b.disabled = batchInFlight || !(n || failed || stageHasEdits()); });
    qsa('[data-cost-stagebar]').forEach(function (bar) {
      if (stageMode && (n || typing || failed)) bar.setAttribute('data-has-edits', 'true'); else bar.removeAttribute('data-has-edits');
    });
    qsa('[data-cost-mode-hint]').forEach(function (el) {
      el.textContent = stageMode
        ? 'Enter commits a cell. Nothing is saved until Save (Ctrl+S) — all staged edits go in one request.'
        : 'Immediate mode: each row saves as you leave it.';
    });
    // Tell the user which sheet holds unsaved edits when they are on the other one.
    ['capex', 'opex'].forEach(function (kind) {
      var count = qsa('#v2-sheet-' + kind + ' ' + ROW).filter(function (r) {
        var st = r.getAttribute('data-save-state'); return st === 'staged' || st === 'dirty' || (st === 'failed' && isDirty(r));
      }).length;
      var tab = document.getElementById('tab-' + kind);
      if (tab) { if (count && stageMode) { tab.setAttribute('data-unsaved', String(count)); tab.setAttribute('title', count + ' unsaved cost edit' + (count === 1 ? '' : 's')); }
                 else { tab.removeAttribute('data-unsaved'); tab.removeAttribute('title'); } }
    });
  }

  // A visible, non-modal choice (shown in the panel the user is looking at, which is often NOT the
  // cost sheet when Run or a scenario switch is pressed): Save, Discard or Stay.
  function showGuard(text) {
    var host = document.querySelector('.v2-sheet-panel:not([hidden])') || document.body;
    var box = document.querySelector('[data-cost-guard]');
    if (box) box.remove();
    box = document.createElement('div');
    box.className = 'v2-cost-guard'; box.setAttribute('data-cost-guard', ''); box.setAttribute('role', 'alert');
    box.setAttribute('data-testid', 'cost-guard');
    var msg = document.createElement('span'); msg.textContent = text; box.appendChild(msg);
    [['Save edits', 'save', 'cost-guard-save'], ['Discard edits', 'discard', 'cost-guard-discard'], ['Stay', 'stay', 'cost-guard-stay']]
      .forEach(function (b) {
        var btn = document.createElement('button'); btn.type = 'button'; btn.textContent = b[0];
        btn.setAttribute('data-guard-action', b[1]); btn.setAttribute('data-testid', b[2]); box.appendChild(btn);
      });
    host.insertBefore(box, host.firstChild);
    var first = box.querySelector('button'); if (first) first.focus({ preventScroll: false });
  }
  function discardAll() {
    if (batchInFlight) return;
    qsa(ROW).forEach(function (r) {
      if (!isDirty(r) && r.getAttribute('data-save-state') !== 'staged') return;
      cellsOf(r).forEach(function (i) { i.value = i.getAttribute('data-original') || ''; });
      r.removeAttribute('data-failed'); r.removeAttribute('data-invalid');
      setState(r, '', '');
    });
    stageMessage('Staged edits discarded.');
    updateStagebars();
  }
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('[data-guard-action]') : null;
    if (!b) return;
    var box = b.closest('[data-cost-guard]'), act = b.getAttribute('data-guard-action');
    if (box) box.remove();
    if (act === 'save') saveStaged(); else if (act === 'discard') discardAll();
  });

  function csrfToken() {
    var el = document.querySelector('[data-csrf]');
    return el ? el.getAttribute('data-csrf') : '';
  }
  function liveTokens() {
    // The workbook shell is maintained by syncTokens after every successful cost, scenario or batch
    // write; the per-sheet authority element is only a fallback.  Never guess a token.
    var shell = document.getElementById('v2-workbook-shell');
    var hash = shell && shell.getAttribute('data-content-hash'), version = shell && shell.getAttribute('data-workbook-version');
    if (hash && version) return { hash: hash, version: version };
    var a = document.querySelector('[id^="v2-cost-authority-"]');
    return a ? { hash: a.getAttribute('data-content-hash'), version: a.getAttribute('data-workbook-version') } : null;
  }
  function lineOf(row) {
    var f = function (name) { var i = row.querySelector('[name="' + name + '"]'); return i ? i.value : null; };
    var line = {
      kind: row.getAttribute('data-cost-row'), sub_line_id: row.getAttribute('data-sub-line-id'),
      row_version: f('row_version'), label: String(f('label') || '').trim(), amount_keur: normNumber(f('amount_keur'))
    };
    var infl = row.querySelector('input[name="inflation_pct"]');
    if (infl) line.inflation_pct = normNumber(infl.value);
    return line;
  }
  function setReadonly(on) {
    qsa(ROW + ' input[data-cost-cell]').forEach(function (i) {
      if (on) { i.setAttribute('data-stage-ro', i.readOnly ? '0' : '1'); i.readOnly = true; }
      else if (i.getAttribute('data-stage-ro') === '1') { i.readOnly = false; i.removeAttribute('data-stage-ro'); }
    });
  }

  function saveStaged() {
    if (batchInFlight || !window.htmx) return;
    qsa(ROW).forEach(function (r) {         // an explicit click re-stages typed and previously failed rows
      var st = r.getAttribute('data-save-state');
      if (isDirty(r) && st !== 'staged') { r.__explicit = true; commitRow(r); }
    });
    if (qsa(ROW).some(function (r) { return r.getAttribute('data-save-state') === 'invalid'; })) {
      stageMessage('Fix the highlighted values first — nothing was saved.');
      return;
    }
    var rows = stagedRows();
    var tokens = liveTokens(), csrf = csrfToken();
    if (!rows.length) return;
    if (!tokens || !tokens.hash || !tokens.version || !csrf) {
      stageMessage('Cannot save: page tokens are missing. Reload the page.');
      return;
    }
    restoreFocusAfterSave = true;
    var project = (rows[0].querySelector('input[name="project"]') || {}).value;
    // The response replaces ONE sheet and the other is refreshed afterwards.  Replace the sheet the user is
    // working in with the response itself, so the follow-up refresh only touches the sheet they are NOT in
    // (a swap detaches the focused cell; it is restored, but never needlessly dropped).
    var here = lastCell && document.getElementById(lastCell.rowId);
    var hereKind = here ? here.getAttribute('data-cost-row') : null;
    var sheet = hereKind && rows.some(function (r) { return r.getAttribute('data-cost-row') === hereKind; })
      ? hereKind : rows[0].getAttribute('data-cost-row');
    var others = rows.some(function (r) { return r.getAttribute('data-cost-row') !== sheet; });
    batchInFlight = true;
    stageMessage('Saving ' + rows.length + ' lines…');
    rows.forEach(function (r) { setState(r, 'saving', 'Saving…'); });
    setReadonly(true);          // no keystroke can be lost to the swap that follows
    updateStagebars();
    // The request source must survive the swap (events from a detached element never reach document).
    var source = document.getElementById('v2-workbook-shell') || document.body;
    var payload = JSON.stringify(rows.map(lineOf));
    window.__v2CostBatch = { rows: rows.map(function (r) { return r.id; }), sheet: sheet, others: others, project: project, source: source };
    window.htmx.ajax('POST', '/v2/workbook/grid/cost-lines/save', {
      source: source, target: '#v2-sheet-' + sheet, swap: 'outerHTML',
      values: { project: project, csrf_token: csrf, workbook_version: tokens.version, content_hash: tokens.hash,
                sheet: sheet, payload: payload }
    });
  }

  function finishBatch(ok, detail) {
    var ctx = window.__v2CostBatch;
    if (!ctx) return;
    window.__v2CostBatch = null;
    batchInFlight = false;
    setReadonly(false);
    if (ok) {
      stageMessage('');
      pendingStageMsg = 'Saved ' + ctx.rows.length + ' lines together · Last Run is now STALE — run the model to refresh results.';
      if (ctx.others) {         // the sheet that was NOT swapped carries stale row versions: refresh it too
        var other = ctx.sheet === 'capex' ? 'opex' : 'capex';
        var root = document.getElementById('v2-sheet-' + other);
        if (root) window.htmx.ajax('GET', '/v2/workbook/grid/sheet?project=' + encodeURIComponent(ctx.project) + '&sheet=' + other,
          { source: '#v2-sheet-' + other, target: '#v2-sheet-' + other, swap: 'outerHTML' });
      }
      return;
    }
    var body = {};
    try { body = JSON.parse((detail && detail.xhr && detail.xhr.responseText) || '{}'); } catch (_) { body = {}; }
    var byKey = {};
    (body.lines || []).forEach(function (v) { if (!v.ok) byKey[v.kind + ':' + v.sub_line_id] = v.message || v.code; });
    ctx.rows.forEach(function (id) {
      var r = document.getElementById(id);
      if (!r) return;
      var msg = byKey[r.getAttribute('data-cost-row') + ':' + r.getAttribute('data-sub-line-id')];
      r.setAttribute('data-failed', 'true');
      setState(r, 'failed', msg ? 'Failed: ' + msg : 'Not saved');
    });
    hadFailure = true;
    var status = detail && detail.xhr ? detail.xhr.status : 0;
    stageMessage((body.message || (status ? 'The server rejected the batch.' : 'Connection problem.')) +
      ' Nothing was saved — your typed values are kept.' + (body.reload ? ' Reload the page to continue.' : ''));
    updateStagebars();
  }

  document.addEventListener('htmx:afterRequest', function (e) {
    var d = e.detail || {};
    var ctx = window.__v2CostBatch;
    if (!ctx || d.elt !== ctx.source) return;
    finishBatch(!!d.successful, d);
  });
  ['htmx:sendError', 'htmx:timeout'].forEach(function (name) {
    document.addEventListener(name, function (e) {
      var ctx = window.__v2CostBatch;
      if (ctx && e.detail && e.detail.elt === ctx.source) finishBatch(false, e.detail);
    });
  });

  document.addEventListener('htmx:afterSettle', function (e) {
    var t = e.target;
    if (!t || !t.matches || !t.matches('[data-cost-grid]')) return;
    updateStagebars();
    if (pendingStageMsg) { stageMessage(pendingStageMsg); pendingStageMsg = ''; }
    restoreCellFocus();
    restoreFocusAfterSave = false;
  });

  // Mouse "Save" leaves focus on a button that the swap replaces: put it back on the cell the user was
  // editing so keyboard work continues where it stopped (no scroll jump).  Done as soon as the swapped
  // DOM exists (afterSwap) and again after settle, so focus is not left on <body> while htmx settles.
  function restoreCellFocus() {
    var ae = document.activeElement;
    if (!restoreFocusAfterSave || !lastCell || (ae && ae !== document.body && document.body.contains(ae))) return;
    var r = document.getElementById(lastCell.rowId);
    var inp = r && r.querySelector('input[name="' + lastCell.name + '"]');
    if (inp) inp.focus({ preventScroll: true });
  }
  document.addEventListener('htmx:afterSwap', function (e) {
    var t = e.target;
    if (t && t.matches && t.matches('[data-cost-grid]')) restoreCellFocus();
  });

  var restoreFocusAfterSave = false;
  document.addEventListener('keydown', function (e) {
    if (!(e.ctrlKey || e.metaKey) || String(e.key).toLowerCase() !== 's') return;
    var t = e.target;
    if (!t || !t.closest || !t.closest('[data-cost-grid]')) return;
    e.preventDefault();                 // never the browser's "Save page"
    if (!stageMode) { stageMessage('Immediate mode saves each row when you leave it.'); return; }
    if (!stagedRows().length && !stageHasEdits()) { stageMessage('Nothing to save.'); return; }
    saveStaged();
  });

  document.addEventListener('click', function (e) {
    var t = e.target && e.target.closest ? e.target.closest('[data-cost-stage-save],[data-cost-stage-discard]') : null;
    if (!t) return;
    e.preventDefault();
    if (t.hasAttribute('data-cost-stage-save')) { saveStaged(); return; }
    discardAll();
  });

  document.addEventListener('change', function (e) {
    var t = e.target;
    if (!t || !t.matches || !t.matches('[data-cost-stage-toggle]')) return;
    if (!t.checked && stageMode && (stagedRows().length || stageHasEdits())) {
      t.checked = true;                       // never silently drop or auto-save staged edits
      stageMessage('Save or discard the staged edits before leaving staged mode.');
      return;
    }
    stageMode = t.checked;
    storeMode(stageMode ? 'staged' : 'immediate');
    stageMessage(stageMode ? 'Edits are saved together with “Save staged”.' : 'Immediate mode: each row saves as you leave it.');
    updateStagebars();
  });

  // Contextual entry from the Inputs Grid: open the sheet's category and focus its first amount cell.
  function focusGroup(kind, code) {
    var panel = document.getElementById('v2-sheet-' + kind);
    if (!panel || !code) return false;
    var group = null;
    qsa('details[data-group-code]', panel).forEach(function (d) { if (d.getAttribute('data-group-code') === code) group = d; });
    if (!group) return false;
    group.open = true;
    var cell = group.querySelector('input[data-cost-cell="amount"], input[name="amount_keur"]') ||
      group.querySelector('input[data-cost-cell]');
    group.scrollIntoView({ block: 'start' });
    if (cell) cell.focus({ preventScroll: true });
    return !!cell;
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', updateStagebars); else updateStagebars();

  window.v2CostGrid = { focusGroup: focusGroup, busy: gridBusy, state: function () { return { active: activeId, queued: queue.slice(), staged: stagedRows().map(function (r) { return r.id; }), stageMode: stageMode, batch: batchInFlight }; } };
}());
