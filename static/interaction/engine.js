/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * C1-PR1: InteractionEngine bootstrap (foundation only — no behaviour)
 *
 * Reference: docs/C1_INTERACTION_LAYER_DESIGN.md, sections 4 and 9.
 *
 * Responsibility in this PR is limited to:
 *   - booting exactly once
 *   - calling FcGridRegistry.scanAll() on initial load
 *   - calling FcGridRegistry.scan(target) once per htmx swap, scoped
 *     to the swapped subtree (mirrors the existing scoping pattern
 *     already used by bindDraftPersistenceFields/bindEditableGridInputs
 *     in static/app.js)
 *   - dispatching two lifecycle events other modules can extend
 *     later (fc:engineReady, fc:gridsScanned)
 *
 * This module does NOT:
 *   - track an active cell, selection, or edit mode
 *   - move focus or restore scroll position
 *   - handle any keyboard, mouse, or clipboard events
 *   - replace or modify the existing htmx:afterSwap listener in
 *     static/app.js — it attaches its own, independent listener
 *     (additive, per design doc §9), so existing behaviour for
 *     New Project panel reshow / Compare tab activation / draft
 *     persistence is completely unaffected by this file.
 */
(function () {
  'use strict';

  var _booted = false;

  function _dispatch(name, detail) {
    document.dispatchEvent(new CustomEvent(name, { detail: detail || {} }));
  }

  function _onInitialLoad() {
    var registered = window.FcGridRegistry.scanAll();
    _dispatch('fc:engineReady', { grids: registered });
  }

  function _onAfterSwap(evt) {
    var target = evt && evt.target ? evt.target : document;
    var registered = window.FcGridRegistry.scan(target);
    _dispatch('fc:gridsScanned', { grids: registered });
  }

  /**
   * Boot the engine. Idempotent — calling this more than once (or
   * loading this script twice) is a no-op after the first call, so
   * the htmx:afterSwap lifecycle hook is attached exactly once.
   */
  function boot() {
    if (_booted) return false;
    _booted = true;

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', _onInitialLoad);
    } else {
      _onInitialLoad();
    }

    document.addEventListener('htmx:afterSwap', _onAfterSwap);
    return true;
  }

  function isBooted() {
    return _booted;
  }

  window.FcInteractionEngine = {
    boot: boot,
    isBooted: isBooted
  };

  // Auto-boot on script load. base.html loads this script with
  // `defer`, after grid-registry.js, so window.FcGridRegistry is
  // guaranteed to exist by the time this line runs.
  boot();
})();
