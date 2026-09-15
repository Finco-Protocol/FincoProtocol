/*
 * FINCO Protocol — Live Modelling Layer
 * C2-PR1: LiveModel (infrastructure foundation only — dirty-state
 * tracking, change batching, live edit session state, a stub
 * recalculation scheduler, and an event pipeline for future
 * incremental recalculation; no financial recalculation, no
 * dependency graph, no formula evaluation, no Save/Run integration)
 *
 * Reference: docs/C1_INTERACTION_LAYER_DESIGN.md,
 *            docs/C1_PR1_IMPLEMENTATION_NOTE.md through
 *            docs/C1_PR9_IMPLEMENTATION_NOTE.md,
 *            docs/C2_PR1_IMPLEMENTATION_NOTE.md,
 *            docs/C2_PR2_DIRTY_STATE_UNIFICATION_NOTE.md.
 *
 * C2-PR2 (dirty-state unification) adds clearCellDirty(gridId, addr) /
 * clearSheetDirty(gridId) / clearAllDirty() as idiomatic aliases/
 * extensions of the clearDirty(gridId?) this module already exposed,
 * plus 'sheet-clean' / 'project-clean' pub/sub events emitted on the
 * transition out of dirty, so static/app.js can become a *consumer*
 * of this module's dirty state for the legacy dirty banner / Run
 * gating / Save flow instead of maintaining its own parallel dirty
 * flag for C1-grid-driven edits. No recalculation, dependency graph,
 * or formula work was added in C2-PR2 either.
 *
 * Responsibility in this PR is limited to:
 *   - tracking which cells/sheets/the project are "dirty" (have an
 *     edit that hasn't been accounted for yet)
 *   - batching consecutive edits to the same cell into one net
 *     change ({addr, before (first), after (latest)}) per live edit
 *     session
 *   - tracking a lightweight "live edit session" (started lazily on
 *     the first dirty edit, ended explicitly), summarising what
 *     changed
 *   - a scheduler abstraction that only queues and flushes plain
 *     event objects — it never executes calculation work itself, and
 *     is the seam C2-PR2 (Incremental Recalculation) will consume
 *   - a minimal synchronous pub/sub (on/off/emit) for
 *     'cell-dirty' / 'sheet-dirty' / 'project-dirty' /
 *     'session-started' / 'session-ended' / 'batch-flush'
 *   - observing the one genuinely observable edit path that exists
 *     today: a native `change` event on a real
 *     <input>/<select>/<textarea> living inside a [data-fc-cell].
 *     This is the same event FcClipboardController's `_setCellValue`
 *     (and, via it, paste/undo/redo/fill) already dispatches after
 *     writing a cell, so this module observes every kind of cell
 *     write the C1 interaction layer already performs without
 *     calling into, modifying, or duplicating any of those modules'
 *     state
 *
 * C2-PR3 (Recalculation Scheduler Foundation) adds a deterministic
 * recalc-scheduling layer on top of this module's existing dirty
 * state and pub/sub (Option A: extending FcLiveModel directly, rather
 * than a separate static/modelling/recalc-scheduler.js module, since
 * a scheduler-shaped surface — `scheduler` — already lived on this
 * object since C2-PR1; growing it in place avoids a second module
 * that would just re-subscribe to the same events this file already
 * owns). It adds:
 *
 *   - scheduleRecalc(reason, meta) — called automatically by
 *     markCellDirty() for every dirty edit (no new call site needed
 *     elsewhere); queues the dirty cell/sheet and (re)starts a
 *     debounce timer. Rapid edits within the debounce window collapse
 *     into one pending flush — the timer is reset, not stacked.
 *   - flushScheduledRecalc() — explicit, synchronous flush API (also
 *     what the debounce timer calls automatically). Returns a
 *     deterministic snapshot of what's pending (sorted grids, sorted
 *     addrs per grid, no timestamps in the comparable shape) and
 *     emits 'recalc-flush-start' then 'recalc-flush-complete'. It
 *     performs NO calculation of any kind — it only reads
 *     getDirtySheets()/getDirtyCells() (this module's existing dirty
 *     state) and shapes them into a snapshot. It does not call Save,
 *     Run, or any backend endpoint, and it does NOT clear dirty state
 *     (clearing dirty remains exclusively clearCellDirty/
 *     clearSheetDirty/clearAllDirty's job, per C2-PR2).
 *   - cancelScheduledRecalc(reason) — cancels any pending debounce
 *     timer and clears the scheduler's own pending-flush bookkeeping,
 *     emitting 'recalc-cancelled'. Called automatically by
 *     clearDirty() (and therefore by clearCellDirty/clearSheetDirty/
 *     clearAllDirty, and by the C2-PR2 applyWorkspaceStateMeta ->
 *     clearAllDirty clean-server-meta sync path) so no stale
 *     scheduled-recalc state can ever survive a dirty-clear.
 *   - hasPendingRecalc() / getPendingRecalcSnapshot() — read-only
 *     accessors mirroring the suggested Option A API shape.
 *
 * The scheduler tracks zero dirty state of its own — `_recalcPending`
 * below is just "is a debounce timer currently armed," not a parallel
 * copy of which cells are dirty. The pending snapshot is always
 * derived live from getDirtySheets()/getDirtyCells() at flush time,
 * so FcLiveModel remains the single, sole owner of dirty state exactly
 * as it has been since C2-PR1/C2-PR2.
 *
 * C2-PR8 (First End-to-End Incremental Runtime Slice) makes ONE
 * explicit, documented exception to the "never makes any network/
 * AJAX/htmx call" rule every prior C2 PR enforced: at the very end of
 * flushScheduledRecalc(), after the existing previewPayload has been
 * built (C2-PR6/PR7), this module now makes exactly one real `fetch`
 * call per flush to POST /model/preview via
 * FcRecalcPreview.buildPreviewRequest(), and hands the parsed JSON
 * response to window.FcRuntimeRenderer.render() (a new, separate
 * module, static/modelling/runtime-renderer.js) — never inspecting or
 * acting on the response itself beyond that single call. This is
 * intentional and required by C2-PR8's spec; it is NOT a regression of
 * the "never auto-call fetch" discipline C2-PR3 through C2-PR7
 * documented and tested for — see
 * docs/C2_PR8_FIRST_RUNTIME_SLICE.md for the full justification. It
 * still never calls Save, Run, or any persistence/export endpoint, and
 * the preview call's response can only ever patch one small,
 * non-financial Overview status DOM element via FcRuntimeRenderer.
 *
 * C2-PR9 (Runtime Request Hardening) hardens that exact fetch call,
 * additively, with no new endpoint/behaviour beyond request-lifecycle
 * safety: (1) an AbortController aborts any still-in-flight previous
 * preview request before a new one is issued; (2) a monotonic
 * sequence counter is the authoritative final guard ensuring only the
 * newest request's response ever reaches FcRuntimeRenderer.render().
 * See docs/C2_PR9_RUNTIME_REQUEST_HARDENING.md for the full lifecycle.
 *
 * This module does NOT:
 *   - run any financial recalculation, dependency graph, or formula
 *     evaluation — the scheduler (including the C2-PR3 debounced
 *     flush API added below) only queues/flushes plain event objects
 *     and snapshot data, it never calls a function or computes a
 *     financial value, and (except for the single documented C2-PR8
 *     preview fetch described above) never makes any network/AJAX/htmx
 *   - trigger Save, Run, persistence, or export — those remain
 *     entirely separate, unaffected workflows
 *   - duplicate FcGridRegistry/FcActiveCellManager/
 *     FcSelectionManager/FcUndoManager state — it only reads cell
 *     identity (gridId/addr) from the DOM event target via the same
 *     [data-fc-grid]/[data-fc-cell]/data-fc-addr markup contract
 *     every other C1 module already uses
 *   - fake dirty tracking for a plain-text cell with no real
 *     input/select/textarea descendant — exactly the same
 *     "don't fake what isn't observable" discipline C1-PR8 applied to
 *     cell-edit capture
 */
(function () {
  'use strict';

  // _dirtyCells[gridId] = Set of addr strings
  var _dirtyCells = {};
  // _dirtySheets = Set of gridId strings
  var _dirtySheets = {};
  var _projectDirty = false;

  // _pendingBatch[gridId][addr] = { gridId, addr, before, after }
  var _pendingBatch = {};

  var _session = null; // { id, startedAt } | null
  var _nextSessionId = 1;

  var _listeners = {}; // eventName -> [handler, ...]

  var _schedulerQueue = [];

  // C2-PR9: Runtime Request Hardening. The previous (C2-PR8) fetch
  // call had no abort/sequencing protection — a slow earlier preview
  // response could, in principle, resolve after a newer one and patch
  // the DOM with stale data. This module now tracks the single
  // in-flight preview request's AbortController (`_previewAbortController`,
  // aborted-and-replaced on every new flush that issues a fetch) and a
  // monotonic sequence counter (`_previewRequestSeq`/`_previewLatestSeq`)
  // used as the authoritative final guard against rendering a stale
  // response, even in the edge case where an aborted fetch's promise
  // still resolves. See docs/C2_PR9_RUNTIME_REQUEST_HARDENING.md.
  var _previewAbortController = null;
  var _previewRequestSeq = 0;
  var _previewLatestSeq = 0;

  function on(eventName, handler) {
    if (!eventName || typeof handler !== 'function') return;
    if (!_listeners[eventName]) _listeners[eventName] = [];
    _listeners[eventName].push(handler);
  }

  function off(eventName, handler) {
    if (!_listeners[eventName]) return;
    var idx = _listeners[eventName].indexOf(handler);
    if (idx !== -1) _listeners[eventName].splice(idx, 1);
  }

  function _emit(eventName, detail) {
    var handlers = _listeners[eventName];
    if (!handlers || !handlers.length) return;
    // Snapshot so a handler removing itself mid-emit is safe.
    handlers.slice().forEach(function (handler) {
      handler(detail);
    });
  }

  function isSessionActive() {
    return !!_session;
  }

  function getSession() {
    if (!_session) return null;
    return { id: _session.id, startedAt: _session.startedAt };
  }

  function startSession() {
    if (_session) return _session.id;
    _session = { id: _nextSessionId++, startedAt: Date.now() };
    _emit('session-started', { id: _session.id });
    return _session.id;
  }

  /**
   * Ends the current live edit session (if any), returning a summary
   * of everything that changed during it. Does not clear dirty state
   * or the pending batch by itself — dirty state intentionally
   * outlives a session until something else (e.g. a future Save
   * integration in a later PR) explicitly clears it.
   */
  function endSession() {
    if (!_session) return null;
    var summary = {
      id: _session.id,
      dirtyCells: getDirtyCells(),
      dirtySheets: getDirtySheets(),
      projectDirty: _projectDirty,
      batch: getBatch()
    };
    _session = null;
    _emit('session-ended', summary);
    return summary;
  }

  function getDirtyCells(gridId) {
    if (gridId) {
      return _dirtyCells[gridId] ? Object.keys(_dirtyCells[gridId]) : [];
    }
    var all = [];
    Object.keys(_dirtyCells).forEach(function (g) {
      Object.keys(_dirtyCells[g]).forEach(function (addr) {
        all.push({ gridId: g, addr: addr });
      });
    });
    return all;
  }

  function getDirtySheets() {
    return Object.keys(_dirtySheets);
  }

  function isCellDirty(gridId, addr) {
    return !!(_dirtyCells[gridId] && _dirtyCells[gridId][addr]);
  }

  function isSheetDirty(gridId) {
    return !!_dirtySheets[gridId];
  }

  function isProjectDirty() {
    return _projectDirty;
  }

  function clearDirty(gridId) {
    if (gridId) {
      delete _dirtyCells[gridId];
      delete _dirtySheets[gridId];
      delete _pendingBatch[gridId];
      _projectDirty = Object.keys(_dirtySheets).length > 0;
      _emit('sheet-clean', { gridId: gridId });
      if (!_projectDirty) _emit('project-clean', {});
      cancelScheduledRecalc('dirty-cleared');
      return;
    }
    _dirtyCells = {};
    _dirtySheets = {};
    _pendingBatch = {};
    _projectDirty = false;
    _emit('project-clean', {});
    cancelScheduledRecalc('dirty-cleared');
  }

  /**
   * Clears the dirty flag for a single cell. If that cell was the
   * only dirty cell in its sheet, the sheet (and, transitively, the
   * project if no other sheet is dirty) is cleared too. C2-PR2:
   * canonical per-cell clear API used by the dirty-state unification
   * layer (e.g. a future Save integration could call this per
   * successfully-persisted cell instead of clearing a whole sheet).
   */
  function clearCellDirty(gridId, addr) {
    if (!gridId || !addr || !_dirtyCells[gridId]) return;
    delete _dirtyCells[gridId][addr];
    if (_pendingBatch[gridId]) delete _pendingBatch[gridId][addr];
    if (Object.keys(_dirtyCells[gridId]).length === 0) {
      clearDirty(gridId);
    }
  }

  // C2-PR2: idiomatic aliases matching the canonical dirty-state API
  // surface (markCellDirty/clearCellDirty/clearSheetDirty/clearAllDirty)
  // used by app.js's dirty-state unification. clearSheetDirty/
  // clearAllDirty are aliases of the pre-existing clearDirty(gridId)/
  // clearDirty() — no behaviour change, just a name that reads clearly
  // at every call site that clears a whole sheet or the whole project.
  function clearSheetDirty(gridId) {
    clearDirty(gridId);
  }

  function clearAllDirty() {
    clearDirty();
  }

  /**
   * Marks a single cell (and transitively its sheet/the project)
   * dirty, accumulates it into the pending batch (coalescing
   * consecutive edits to the same cell into one net before/after
   * pair), queues a plain "cell-changed" event onto the scheduler,
   * and emits the dirty pub/sub events. Never throws; missing
   * gridId/addr is a no-op.
   */
  function markCellDirty(gridId, addr, before, after) {
    if (!gridId || !addr) return;

    startSession();

    if (!_dirtyCells[gridId]) _dirtyCells[gridId] = {};
    _dirtyCells[gridId][addr] = true;

    var sheetWasDirty = !!_dirtySheets[gridId];
    _dirtySheets[gridId] = true;
    _projectDirty = true;

    if (!_pendingBatch[gridId]) _pendingBatch[gridId] = {};
    var existing = _pendingBatch[gridId][addr];
    _pendingBatch[gridId][addr] = {
      gridId: gridId,
      addr: addr,
      before: existing ? existing.before : before,
      after: after
    };

    var event = { type: 'cell-changed', gridId: gridId, addr: addr, before: before, after: after };
    _schedulerQueue.push(event);

    _emit('cell-dirty', { gridId: gridId, addr: addr, before: before, after: after });
    if (!sheetWasDirty) _emit('sheet-dirty', { gridId: gridId });
    _emit('project-dirty', { gridId: gridId });

    scheduleRecalc('cell-changed', { gridId: gridId, addr: addr });
  }

  function getBatch(gridId) {
    if (gridId) {
      return _pendingBatch[gridId] ? Object.keys(_pendingBatch[gridId]).map(function (addr) {
        return _pendingBatch[gridId][addr];
      }) : [];
    }
    var all = [];
    Object.keys(_pendingBatch).forEach(function (g) {
      Object.keys(_pendingBatch[g]).forEach(function (addr) {
        all.push(_pendingBatch[g][addr]);
      });
    });
    return all;
  }

  /**
   * Returns the pending batch (coalesced net changes since the last
   * flush) and clears it. Does not clear dirty-state flags or the
   * scheduler queue — those are independent, separately-cleared
   * concepts.
   */
  function flushBatch(gridId) {
    var batch = getBatch(gridId);
    if (gridId) {
      delete _pendingBatch[gridId];
    } else {
      _pendingBatch = {};
    }
    _emit('batch-flush', { gridId: gridId || null, batch: batch });
    return batch;
  }

  // --- Scheduler: queues/flushes plain event objects only. No
  // function is ever called, no calculation is ever performed here —
  // this is purely the seam C2-PR2 will consume.
  function schedulerQueueLength() {
    return _schedulerQueue.length;
  }

  function schedulerQueueEvent(event) {
    if (!event) return;
    _schedulerQueue.push(event);
  }

  function schedulerFlush() {
    var drained = _schedulerQueue;
    _schedulerQueue = [];
    return drained;
  }

  function schedulerPeek() {
    return _schedulerQueue.slice();
  }

  var scheduler = {
    queueLength: schedulerQueueLength,
    queueEvent: schedulerQueueEvent,
    flush: schedulerFlush,
    peek: schedulerPeek
  };

  // --- C2-PR3: deterministic recalculation scheduler foundation.
  // No financial calculation is ever performed here — see the module
  // header comment. This block only debounces/batches/snapshots the
  // dirty state this module already owns; it never makes any network
  // or AJAX call of any kind, and never invokes Save or Run.
  var RECALC_DEBOUNCE_MS = 250;

  var _recalcTimer = null; // setTimeout handle, or null if nothing scheduled
  var _recalcReason = null; // the reason string of the most recent schedule call

  function hasPendingRecalc() {
    return _recalcTimer !== null;
  }

  /**
   * Builds a deterministic snapshot of currently-dirty sheets/cells.
   * Grids are sorted alphabetically by gridId; cell addresses are
   * sorted alphabetically within each grid. No timestamp or other
   * non-reproducible field is included, so two snapshots of the same
   * logical dirty state are deep-equal regardless of edit order or
   * wall-clock time. This performs zero calculation — it is purely a
   * read+reshape of getDirtySheets()/getDirtyCells().
   */
  function getPendingRecalcSnapshot() {
    var gridIds = getDirtySheets().slice().sort();
    var grids = gridIds.map(function (gridId) {
      var addrs = getDirtyCells(gridId).slice().sort();
      return { gridId: gridId, addrs: addrs };
    });
    return { grids: grids, projectDirty: isProjectDirty() };
  }

  /**
   * Schedules (or reschedules) a debounced recalculation flush.
   * Called automatically by markCellDirty() for every dirty edit, and
   * safe to call manually (e.g. from a test, or a future caller).
   * Rapid calls within RECALC_DEBOUNCE_MS collapse into a single
   * eventual flush — each call resets the timer rather than stacking
   * another one. Performs no calculation; only arms a timer and emits
   * 'recalc-scheduled'.
   */
  function scheduleRecalc(reason, meta) {
    _recalcReason = reason || 'cell-changed';
    if (_recalcTimer !== null) {
      clearTimeout(_recalcTimer);
    }
    _recalcTimer = setTimeout(function () {
      _recalcTimer = null;
      flushScheduledRecalc();
    }, RECALC_DEBOUNCE_MS);
    _emit('recalc-scheduled', { reason: _recalcReason, meta: meta || null });
  }

  /**
   * Cancels any pending debounced recalc flush without flushing it.
   * Called automatically whenever dirty state is cleared (clearDirty/
   * clearCellDirty/clearSheetDirty/clearAllDirty), so a scheduled
   * recalc can never survive past the dirty state it was scheduled
   * for. Safe to call when nothing is pending (no-op, no event).
   */
  function cancelScheduledRecalc(reason) {
    if (_recalcTimer === null) return false;
    clearTimeout(_recalcTimer);
    _recalcTimer = null;
    _emit('recalc-cancelled', { reason: reason || 'cancelled' });
    return true;
  }

  /**
   * Explicit, synchronous flush API — the same function the debounce
   * timer calls automatically, also callable manually (tests, or a
   * future caller that wants to flush immediately rather than wait
   * out the debounce window). Returns a deterministic pending-recalc
   * snapshot (see getPendingRecalcSnapshot) and emits
   * 'recalc-flush-start' then 'recalc-flush-complete' around it.
   *
   * Critically, this performs NO calculation: it never evaluates a
   * formula, never walks a dependency graph (none exists), and never
   * calls Save, Run, fetch, or any backend endpoint. It also does NOT
   * clear dirty state — clearing dirty remains exclusively the job of
   * clearCellDirty/clearSheetDirty/clearAllDirty (C2-PR2's contract),
   * so a flushed-but-unsaved edit still correctly reports dirty.
   */
  function flushScheduledRecalc() {
    if (_recalcTimer !== null) {
      clearTimeout(_recalcTimer);
      _recalcTimer = null;
    }
    var reason = _recalcReason;
    _emit('recalc-flush-start', { reason: reason });
    var snapshot = getPendingRecalcSnapshot();
    // C2-PR4: additive only. If window.FcDependencyGraph is present
    // (static/modelling/dependency-graph.js, loaded after this file),
    // annotate the snapshot with the coarse-grained output groups its
    // dirty cells/sheets would eventually affect. This module never
    // computes that mapping itself — it only calls into
    // FcDependencyGraph.resolveSnapshot(), a read-only function that
    // performs no calculation and makes no network call. If the
    // dependency-graph module isn't loaded (e.g. an older page, or a
    // test fixture that doesn't include it), this is a no-op and the
    // snapshot shape is byte-for-byte identical to C2-PR3's.
    if (window.FcDependencyGraph && typeof window.FcDependencyGraph.resolveSnapshot === 'function') {
      snapshot.affectedGroups = window.FcDependencyGraph.resolveSnapshot(snapshot);
    }
    // C2-PR5: additive only. If window.FcRecalcExecutor is present
    // (static/modelling/recalc-executor.js, loaded after this file),
    // hand the snapshot (already annotated with affectedGroups above)
    // to the deterministic no-op execution stub and attach its result
    // under snapshot.execution. This module never performs or
    // duplicates that logic itself — FcRecalcExecutor.execute() is a
    // pure, non-throwing function that performs no calculation, no
    // network call, and no dirty-state mutation. If the executor
    // module isn't loaded, this is a no-op and the snapshot shape is
    // byte-for-byte identical to C2-PR4's.
    if (window.FcRecalcExecutor && typeof window.FcRecalcExecutor.execute === 'function') {
      snapshot.execution = window.FcRecalcExecutor.execute(snapshot, { reason: reason });
    }
    _emit('recalc-flush-complete', { reason: reason, snapshot: snapshot });

    // C2-PR8: First End-to-End Incremental Runtime Slice. This is the
    // FIRST and ONLY place in the entire C2 chain (PR1 through PR7
    // explicitly never did this) where a real network call is made
    // automatically as part of the edit -> dirty -> schedule -> flush
    // path. This is an intentional, explicit, documented exception to
    // every prior PR's "never auto-call fetch" guardrail — see
    // docs/C2_PR8_FIRST_RUNTIME_SLICE.md for the full justification.
    // It fires at most once per flush (never per keystroke, thanks to
    // the existing 250ms debounce this block sits after), only when a
    // previewPayload was actually built above, and only when a real
    // `fetch` function exists (so this is a safe no-op in any
    // non-browser/test harness that doesn't define one). The response
    // is handed, verbatim, to FcRuntimeRenderer.render() — this module
    // never inspects or acts on the response itself beyond that single
    // call, and never calls Save, Run, or any persistence/export path.
    if (
      window.FcRecalcPreview &&
      typeof window.FcRecalcPreview.buildPreviewRequest === 'function' &&
      snapshot.execution &&
      snapshot.execution.previewPrepared &&
      snapshot.execution.previewPayload &&
      typeof fetch === 'function'
    ) {
      var req = window.FcRecalcPreview.buildPreviewRequest(snapshot.execution.previewPayload);

      // C2-PR9: abort any previous in-flight preview request before
      // issuing a new one — at most one preview fetch is ever allowed
      // to be in flight at a time. Then capture this request's own
      // sequence number before calling fetch(), so the response
      // handler below can authoritatively detect staleness.
      if (_previewAbortController) {
        try {
          _previewAbortController.abort();
        } catch (e) {
          // Defensive: abort() should never throw, but a non-standard
          // AbortController polyfill must never break the flush path.
        }
      }
      var controller = (typeof AbortController === 'function') ? new AbortController() : null;
      _previewAbortController = controller;

      _previewRequestSeq += 1;
      var seq = _previewRequestSeq;
      _previewLatestSeq = seq;

      // C2-PR11: a preview fetch is genuinely about to be issued for
      // this flush -> "Preview updating…". This is the one and only
      // place setUpdating() is called, mirroring how this is the one
      // and only place a preview fetch is issued.
      if (window.FcRuntimeRenderer && typeof window.FcRuntimeRenderer.setUpdating === 'function') {
        window.FcRuntimeRenderer.setUpdating();
      }

      try {
        fetch(req.url, {
          method: req.method,
          headers: req.headers,
          body: JSON.stringify(req.body),
          signal: controller ? controller.signal : undefined
        }).then(function (res) {
          // C2-PR11: a non-2xx HTTP status is a failure for state-
          // machine purposes even though `fetch()` itself resolves
          // (rather than rejects) for those responses. The sequence
          // check still gates whether this is even allowed to react at
          // all, exactly as it already does for the success path.
          if (!res.ok) {
            if (seq === _previewLatestSeq && window.FcRuntimeRenderer && typeof window.FcRuntimeRenderer.setFailed === 'function') {
              window.FcRuntimeRenderer.setFailed();
            }
            return null;
          }
          return res.json();
        }).then(function (json) {
          if (json === null) return; // already handled by the !res.ok branch above
          // C2-PR9: sequence check is the authoritative, final guard
          // against rendering a stale response — defense in depth on
          // top of AbortController, since an aborted request's
          // promise could in principle still resolve in some edge
          // case. Only the newest request's response is ever allowed
          // to reach FcRuntimeRenderer.render().
          if (seq !== _previewLatestSeq) return;
          if (window.FcRuntimeRenderer && typeof window.FcRuntimeRenderer.render === 'function') {
            window.FcRuntimeRenderer.render(json);
          }
        }).catch(function () {
          // Network/parse/AbortError: never throws, never breaks the
          // page. C2-PR9's invariant (an aborted/superseded request
          // never patches a preview VALUE) is unchanged — but C2-PR11
          // additionally surfaces a genuine (non-aborted, still-newest)
          // failure as the "Preview failed" STATE label, without ever
          // touching the previously-rendered preview VALUE text. A
          // request that was itself superseded (seq !== _previewLatestSeq
          // by the time it lands here) is silently discarded exactly as
          // before — only the newest request's failure is ever shown.
          if (seq === _previewLatestSeq && window.FcRuntimeRenderer && typeof window.FcRuntimeRenderer.setFailed === 'function') {
            window.FcRuntimeRenderer.setFailed();
          }
        });
      } catch (e) {
        // Defensive: fetch() itself throwing synchronously (e.g. an
        // unusual test/polyfill environment) must never break the
        // flush path or any caller of flushScheduledRecalc().
        if (window.FcRuntimeRenderer && typeof window.FcRuntimeRenderer.setFailed === 'function') {
          window.FcRuntimeRenderer.setFailed();
        }
      }
    } else if (window.FcRuntimeRenderer && typeof window.FcRuntimeRenderer.setUnavailable === 'function') {
      // C2-PR11: this flush had nothing preview-able to send (no
      // previewPayload was built, no fetch global, etc.) — no request
      // is issued at all, so the state machine reflects that
      // explicitly as "Preview unavailable" rather than silently
      // leaving a stale "Preview updating…"/previous state displayed
      // forever. Only reached when the `if` above's guard fails, i.e.
      // exactly the existing no-op condition this block already had
      // before C2-PR11 — no new no-op path was introduced.
      window.FcRuntimeRenderer.setUnavailable();
    }

    return snapshot;
  }

  // --- DOM wiring: the one genuinely observable edit path.
  function _isFormField(el) {
    return !!(el && el.matches && el.matches('input, select, textarea'));
  }

  function _findCell(el) {
    var cellEl = el.closest ? el.closest('[data-fc-cell]') : null;
    if (!cellEl) return null;
    var gridEl = cellEl.closest ? cellEl.closest('[data-fc-grid]') : null;
    if (!gridEl) return null;
    var gridId = gridEl.getAttribute('data-fc-grid');
    var addr = cellEl.getAttribute('data-fc-addr');
    if (!gridId || !addr) return null;
    var editable = cellEl.getAttribute('data-fc-editable');
    if (editable === 'false') return null;
    return { gridId: gridId, addr: addr };
  }

  var _editBefore = null; // { el, gridId, addr, value }

  function _onFocusIn(evt) {
    var el = evt.target;
    if (!_isFormField(el)) return;
    var resolved = _findCell(el);
    if (!resolved) return;
    _editBefore = {
      el: el,
      gridId: resolved.gridId,
      addr: resolved.addr,
      value: el.value != null ? String(el.value) : ''
    };
  }

  function _onChange(evt) {
    var el = evt.target;
    if (!_editBefore || _editBefore.el !== el) return;

    var before = _editBefore.value;
    var after = el.value != null ? String(el.value) : '';
    var gridId = _editBefore.gridId;
    var addr = _editBefore.addr;
    // Advance the snapshot rather than clearing it, so a second
    // `change` on the same still-focused field (no refocus in
    // between) is tracked as a further incremental edit instead of
    // being silently dropped.
    _editBefore.value = after;

    if (before === after) return;
    markCellDirty(gridId, addr, before, after);
  }

  var _initialized = false;

  function init() {
    if (_initialized) return false;
    _initialized = true;

    document.addEventListener('focusin', _onFocusIn);
    document.addEventListener('change', _onChange);

    return true;
  }

  window.FcLiveModel = {
    init: init,

    markCellDirty: markCellDirty,
    isCellDirty: isCellDirty,
    isSheetDirty: isSheetDirty,
    isProjectDirty: isProjectDirty,
    getDirtyCells: getDirtyCells,
    getDirtySheets: getDirtySheets,
    clearDirty: clearDirty,
    clearCellDirty: clearCellDirty,
    clearSheetDirty: clearSheetDirty,
    clearAllDirty: clearAllDirty,

    getBatch: getBatch,
    flushBatch: flushBatch,

    startSession: startSession,
    endSession: endSession,
    isSessionActive: isSessionActive,
    getSession: getSession,

    scheduler: scheduler,

    // C2-PR3: deterministic recalculation scheduler foundation.
    scheduleRecalc: scheduleRecalc,
    flushScheduledRecalc: flushScheduledRecalc,
    cancelScheduledRecalc: cancelScheduledRecalc,
    hasPendingRecalc: hasPendingRecalc,
    getPendingRecalcSnapshot: getPendingRecalcSnapshot,

    on: on,
    off: off
  };

  init();
})();
