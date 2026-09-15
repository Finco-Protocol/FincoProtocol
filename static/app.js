/* FINCO Protocol workspace interactions */

var activeTab = 'overview';
var draftPersistTimer = null;

function showNewProjectPanel() {
  // Hide all panels, show the new project panel in main workspace
  document.querySelectorAll('.tab-panel').forEach(function(p) {
    p.classList.remove('active');
    if (p.id !== 'panel-new-project') p.style.display = 'none';
  });
  var np = document.getElementById('panel-new-project');
  if (np) {
    np.style.display = 'block';
    np.classList.add('active');
  }
  document.querySelectorAll('.ws-tab').forEach(function(t) { t.classList.remove('active'); });
  var workspace = document.getElementById('workspace-content');
  if (workspace) workspace.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeNewProjectPanel() {
  var np = document.getElementById('panel-new-project');
  if (np) {
    np.style.display = 'none';
    np.classList.remove('active');
  }
  // Restore overview tab
  switchTab('overview');
}

function duplicateCurrentScenario() {
  var currentId = document.getElementById('current_saved_scenario_id');
  if (!currentId || !currentId.value) {
    alert('Load a saved scenario first.');
    return;
  }
  if (window.htmx) {
    window.htmx.ajax('POST', '/scenarios/' + currentId.value + '/duplicate', {
      target: '#saved-scenario-panel',
      swap: 'outerHTML'
    });
  }
}

function setButtonDisabledState(id, disabled) {
  var btn = document.getElementById(id);
  if (!btn) return;
  btn.disabled = !!disabled;
  btn.setAttribute('aria-disabled', disabled ? 'true' : 'false');
}

function setActionReason(id, reason) {
  var btn = document.getElementById(id);
  if (!btn) return;
  if (reason) {
    btn.setAttribute('title', reason);
    btn.setAttribute('data-disabled-reason', reason);
  } else {
    btn.removeAttribute('title');
    btn.removeAttribute('data-disabled-reason');
  }
}

function updateReviewerActionHelp(meta) {
  var helper = document.getElementById('reviewer-action-help');
  if (!helper) return;
  var dirtyMessage = helper.getAttribute('data-dirty-message') || '';
  var cleanMessage = helper.getAttribute('data-clean-message') || '';
  helper.textContent = meta && meta.dirty ? dirtyMessage : cleanMessage;
}

function updateExportLineageGuidance(meta) {
  var helper = document.getElementById('reviewer-export-lineage-help');
  if (helper) {
    var dirtyMessage = helper.getAttribute('data-dirty-message') || '';
    var cleanMessage = helper.getAttribute('data-clean-message') || '';
    helper.textContent = meta && meta.dirty ? dirtyMessage : cleanMessage;
  }

  var lineageNote = document.getElementById('export-lineage-guidance');
  if (lineageNote) {
    lineageNote.textContent = meta && meta.dirty
      ? 'Unsaved draft edits are active. Runtime-backed exports remain tied to the last clean backend snapshot until you save and run again.'
      : 'Draft and saved state are aligned. Runtime-backed exports reflect the last clean backend runtime boundary shown in the workspace.';
  }

  var lineageChip = document.getElementById('export-lineage-dirty-chip');
  if (lineageChip && meta && meta.dirty_label) {
    lineageChip.textContent = meta.dirty_label;
  }
}

function switchTab(tabId) {
  if (!tabId) return;
  // UX-1A: don't switch into a panel that doesn't exist in the current
  // render (e.g. a stale hash from a previous project). Leave the
  // current tab showing rather than silently falling through.
  if (!document.getElementById('panel-' + tabId)) return;
  activeTab = tabId;

  // UX-2: keep hidden form field in sync so POST /run knows the active tab.
  var _atInput = document.getElementById('hidden-active-tab');
  if (_atInput) _atInput.value = tabId;

  // UX-1A: an unrelated htmx swap elsewhere in the workspace (Save,
  // Run, scenario actions) can leave the New Project panel forced
  // visible (see the htmx:afterSwap handlers below). Any real tab
  // switch should always close it.
  var newProjectPanel = document.getElementById('panel-new-project');
  if (newProjectPanel) {
    newProjectPanel.style.display = 'none';
    newProjectPanel.classList.remove('active');
  }

  document.querySelectorAll('.ws-tab').forEach(function(btn) {
    btn.classList.remove('active');
  });
  var activeBtn = document.getElementById('tab-' + tabId);
  if (activeBtn) activeBtn.classList.add('active');

  document.querySelectorAll('.tab-panel').forEach(function(panel) {
    panel.classList.remove('active');
  });
  var activePanel = document.getElementById('panel-' + tabId);
  if (activePanel) activePanel.classList.add('active');

  if (history.pushState) {
    history.pushState(null, '', '#' + tabId);
  }

  var workspace = document.getElementById('workspace-content');
  if (workspace) workspace.scrollIntoView({ behavior: 'smooth', block: 'start' });
  if (activeBtn) activeBtn.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });

  // STAB-4: sync five-area nav active state
  var RESULTS_TABS = ['construction','production','revenue','opex','capex',
    'senior-debt','shl','tax','pl','cashflow','balance','distributions','sponsor'];
  var NAV_AREA_MAP = {
    'overview': 'dashboard',
    'inputs': 'inputs',
    'scenario': 'scenarios',
    'audit': 'export-audit',
    'downloads': 'export-audit',
    'help': 'help'
  };
  document.querySelectorAll('.nav-compression-tab').forEach(function(btn) {
    btn.classList.remove('active');
  });
  var navArea = RESULTS_TABS.indexOf(tabId) !== -1 ? 'results' : (NAV_AREA_MAP[tabId] || null);
  if (navArea) {
    var navBtn = document.querySelector('.nav-compression-tab[data-p2fix4-area="' + navArea + '"]');
    if (navBtn) navBtn.classList.add('active');
  }

  // STAB-4: sync results sub-nav active state and wrapper visibility
  document.querySelectorAll('.results-subnav-tab').forEach(function(btn) {
    btn.classList.remove('active');
  });
  var subnavWrapper = document.getElementById('results-subnav-wrapper');
  if (RESULTS_TABS.indexOf(tabId) !== -1) {
    var subnavBtn = document.getElementById('results-subnav-tab-' + tabId);
    if (subnavBtn) subnavBtn.classList.add('active');
    if (subnavWrapper) subnavWrapper.classList.remove('results-subnav-wrapper--hidden');
  } else {
    if (subnavWrapper) subnavWrapper.classList.add('results-subnav-wrapper--hidden');
  }

  document.dispatchEvent(new CustomEvent('tabChanged', { detail: { tab: tabId } }));
}

function activateTab(tabId) {
  switchTab(tabId);
}

function switchProject(projectId) {
  document.querySelectorAll('.ps-card').forEach(function(card) {
    card.classList.remove('active');
    var statusDot = card.querySelector('.ps-card-status');
    if (statusDot) {
      statusDot.textContent = '';
      statusDot.classList.remove('ps-card-status--active');
    }
  });

  var activeCard = document.getElementById('ps-' + projectId);
  if (activeCard) {
    activeCard.classList.add('active');
    var statusDot = activeCard.querySelector('.ps-card-status');
    if (statusDot) {
      statusDot.textContent = '●';
      statusDot.classList.add('ps-card-status--active');
    }
  }

  document.dispatchEvent(new CustomEvent('projectChanged', { detail: { project: projectId } }));
}

window.applyScenarioSnapshot = function(snapshot, scenarioId) {
  if (!snapshot) return;
  Object.keys(snapshot).forEach(function(key) {
    var field = document.getElementById(key) || document.querySelector('[name="' + key + '"]');
    if (field) field.value = snapshot[key];
  });
  var currentId = document.getElementById('current_saved_scenario_id');
  if (currentId) currentId.value = scenarioId || '';
  if (window.syncEditableGridMirrors) {
    window.syncEditableGridMirrors();
  }
};

window.syncEditableGridMirrors = function() {
  document.querySelectorAll('[data-grid-source]').forEach(function(input) {
    var sourceId = input.getAttribute('data-grid-source');
    if (!sourceId) return;
    var source = document.getElementById(sourceId);
    if (!source) return;
    if (document.activeElement !== input) {
      input.value = source.value || '';
    }
  });
};

/*
 * C2-PR2: Dirty-state unification.
 *
 * Previously, the legacy dirty banner / Run-gating / Save flow above
 * was driven exclusively by server-computed `meta.dirty` (a snapshot
 * diff of `#main-form` against the saved scenario, recomputed by
 * POST /scenarios/state/draft on a 350ms debounce after any
 * `#main-form` field change — see queueWorkspaceDraftPersist below).
 * Separately, FcLiveModel (static/modelling/live-model.js, C2-PR1)
 * tracked its own, entirely independent, client-side dirty state for
 * edits made through the C1 spreadsheet interaction layer (typing,
 * undo/redo, fill, paste — anything that flows through
 * FcCellIO.writeValue, which all of those already do). Nothing ever
 * read FcLiveModel's dirty state, and — because C1 grid cells live
 * outside `#main-form` — a C1 grid edit was invisible to the legacy
 * mechanism entirely. Two parallel, non-communicating notions of
 * "dirty" existed for the same workspace.
 *
 * FcLiveModel is now the canonical client-side dirty-state source.
 * `_lastServerMeta` below caches the most recent genuine server-provided
 * meta (so a client-only FcLiveModel dirty signal can be overlaid onto
 * it without discarding the other fields — active scenario name,
 * runtime snapshot id, labels — that only the server knows about).
 * `_syncDirtyFromLiveModel()` re-applies the dirty banner / Run gating
 * / lineage guidance whenever FcLiveModel transitions into or out of
 * a dirty state, via FcLiveModel's existing pub/sub ('project-dirty' /
 * 'project-clean') rather than polling. The legacy server-driven path
 * (queueWorkspaceDraftPersist -> applyWorkspaceStateMeta) is left
 * completely intact for `#main-form` fields (the top-level Inputs
 * fields it has always covered) — this is strictly additive overlay
 * logic, not a replacement of the server round trip for those fields.
 */
// The most recent meta actually received from the server (never
// mutated by the FcLiveModel overlay below) — the genuine source of
// truth for every #main-form-driven field (active scenario name,
// runtime snapshot id, last_runtime_origin_label, and #main-form's
// own dirty bit). Kept distinct from what gets painted to the DOM so
// the overlay in _syncDirtyFromLiveModel always starts from the real
// last server answer, not from a previously-overlaid value.
var _lastServerMeta = null;
var _applyingFromLiveModelSync = false;

function _syncDirtyFromLiveModel() {
  if (!window.FcLiveModel || _applyingFromLiveModelSync) return;
  var liveDirty = window.FcLiveModel.isProjectDirty();
  var base = _lastServerMeta || {};
  // Once FcLiveModel reports dirty, the workspace is dirty even if the
  // server-side #main-form snapshot diff says otherwise — a C1 grid
  // edit is a real unsaved change. Once FcLiveModel reports clean
  // again (e.g. after clearAllDirty() on Save), defer to whatever the
  // last genuine server meta said (it may still be dirty for
  // #main-form reasons FcLiveModel knows nothing about).
  var effectiveDirty = liveDirty || !!base.dirty;
  var merged = {};
  Object.keys(base).forEach(function(k) { merged[k] = base[k]; });
  merged.dirty = effectiveDirty;
  if (liveDirty && !base.dirty) {
    merged.dirty_label = 'Unsaved edits';
  } else if (!effectiveDirty) {
    // C2-PR12: dirty-strip-lag fix. Previously this branch was missing,
    // so `merged.dirty_label` fell through to whatever `_lastServerMeta`
    // last said (still "Unsaved edits" immediately after a successful
    // Save, since /scenarios/save's HTMX response never refreshes
    // `_lastServerMeta` — see the btn-save htmx:afterRequest handler
    // below). `meta.dirty` itself was always correct (so the banner,
    // gated on `!meta.dirty`, hid immediately) but the strip TEXT
    // (`#workspace-strip-dirty`, gated on the now-stale `dirty_label`)
    // lagged until a later Run's response overwrote `_lastServerMeta`.
    // Explicitly clamping the label to "Clean saved state" (the same
    // clean-state wording app/services/scenario_state_service.py and
    // app/services/run_service.py already use server-side) whenever the
    // merged state is genuinely clean keeps the strip text and the
    // banner in sync on the same tick, with no dependency on a
    // subsequent Run.
    merged.dirty_label = 'Clean saved state';
  }
  _applyingFromLiveModelSync = true;
  try {
    window.applyWorkspaceStateMeta(merged);
  } finally {
    _applyingFromLiveModelSync = false;
  }
}

window.applyWorkspaceStateMeta = function(meta) {
  if (!meta) return;
  if (!_applyingFromLiveModelSync) {
    // Only a genuine server-driven call updates the cached "real"
    // meta; a call made by _syncDirtyFromLiveModel's own overlay (the
    // _applyingFromLiveModelSync === true branch) must not poison it,
    // otherwise the next sync would treat its own previous overlay as
    // the server's answer.
    _lastServerMeta = meta;
  }
  // C2-PR2: when a fresh server meta reports a clean workspace (e.g.
  // right after Save or Discard succeeds), bring FcLiveModel's
  // canonical dirty state back into sync too — otherwise a C1 grid
  // edit made before Save would keep FcLiveModel (and therefore the
  // banner, via _syncDirtyFromLiveModel above) reporting dirty forever,
  // since FcLiveModel dirty state is only ever cleared explicitly.
  // Guarded by _applyingFromLiveModelSync so this can never re-trigger
  // _syncDirtyFromLiveModel -> applyWorkspaceStateMeta in a loop.
  if (!_applyingFromLiveModelSync && meta.dirty === false && window.FcLiveModel && window.FcLiveModel.clearAllDirty) {
    window.FcLiveModel.clearAllDirty();
  }
  var currentId = document.getElementById('current_saved_scenario_id');
  if (currentId && typeof meta.active_scenario_id !== 'undefined') currentId.value = meta.active_scenario_id || '';
  var dirty = document.getElementById('workspace_dirty_state');
  if (dirty && typeof meta.dirty !== 'undefined') dirty.value = meta.dirty ? '1' : '0';
  var runtimeId = document.getElementById('last_runtime_snapshot_id');
  if (runtimeId && typeof meta.last_runtime_snapshot_id !== 'undefined') runtimeId.value = meta.last_runtime_snapshot_id || '';

  var activeName = document.getElementById('workspace-active-scenario-name');
  if (activeName && typeof meta.active_scenario_name !== 'undefined') {
    activeName.textContent = meta.active_scenario_name || 'Workspace Base';
  }
  var dirtyLabel = document.getElementById('workspace-dirty-label');
  if (dirtyLabel && meta.dirty_label) dirtyLabel.textContent = meta.dirty_label;
  var runtimeLabel = document.getElementById('workspace-runtime-origin-label');
  if (runtimeLabel && meta.last_runtime_origin_label) runtimeLabel.textContent = meta.last_runtime_origin_label;
  var runtimeChip = document.getElementById('workspace-runtime-snapshot-id');
  if (runtimeChip) runtimeChip.textContent = meta.last_runtime_snapshot_id || 'No runtime snapshot';
  var stripActive = document.getElementById('workspace-strip-active-scenario');
  if (stripActive && typeof meta.active_scenario_name !== 'undefined') stripActive.textContent = meta.active_scenario_name || 'Workspace Base';
  var stripDirty = document.getElementById('workspace-strip-dirty');
  if (stripDirty && meta.dirty_label) stripDirty.textContent = meta.dirty_label;
  var stripOrigin = document.getElementById('workspace-strip-runtime-origin');
  if (stripOrigin && meta.last_runtime_origin_label) stripOrigin.textContent = meta.last_runtime_origin_label;
  var stripSnap = document.getElementById('workspace-strip-runtime-snapshot');
  if (stripSnap) stripSnap.textContent = meta.last_runtime_snapshot_id || 'Not yet run';
  var banner = document.getElementById('workspace-unsaved-banner');
  if (banner) banner.classList.toggle('is-hidden', !meta.dirty);
  var bannerActive = document.getElementById('workspace-banner-active-scenario');
  if (bannerActive && typeof meta.active_scenario_name !== 'undefined') bannerActive.textContent = meta.active_scenario_name || 'Workspace Base';
  var bannerOrigin = document.getElementById('workspace-banner-runtime-origin');
  if (bannerOrigin && meta.last_runtime_origin_label) bannerOrigin.textContent = meta.last_runtime_origin_label;

  var dirtyReason = 'Disabled because unsaved draft edits exist. Save or revert first.';
  ['btn-run-model-sidebar', 'btn-compare-draft', 'btn-save-run'].forEach(function(id) {
    setButtonDisabledState(id, !!meta.dirty);
    setActionReason(id, meta.dirty ? dirtyReason : '');
  });
  updateReviewerActionHelp(meta);
  updateExportLineageGuidance(meta);
};

window.refreshScenarioWorkspace = function(projectId) {
  if (!projectId || !window.htmx) return;
  window.htmx.ajax('GET', '/scenarios?project=' + encodeURIComponent(projectId), {
    target: '#saved-scenario-panel',
    swap: 'outerHTML'
  });
};

function queueWorkspaceDraftPersist() {
  var form = document.getElementById('main-form');
  if (!form) return;
  if (draftPersistTimer) window.clearTimeout(draftPersistTimer);
  draftPersistTimer = window.setTimeout(function() {
    var payload = new URLSearchParams(new FormData(form));
    fetch('/scenarios/state/draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
      body: payload.toString(),
      credentials: 'same-origin'
    })
      .then(function(resp) { return resp.ok ? resp.json() : null; })
      .then(function(data) {
        if (data && window.applyWorkspaceStateMeta) {
          window.applyWorkspaceStateMeta(data);
        }
        if (window.syncEditableGridMirrors) {
          window.syncEditableGridMirrors();
        }
      })
      .catch(function() {
        // Best-effort draft persistence only; keep the workspace usable if this fails.
      });
  }, 350);
}

function bindDraftPersistenceFields(root) {
  var scope = root || document;
  var mainForm = document.getElementById('main-form');
  if (!mainForm || !mainForm.contains(scope) && scope !== document) return;
  mainForm.querySelectorAll('input, select, textarea').forEach(function(field) {
    if (field.type === 'hidden' || field.dataset.draftBound === '1') return;
    field.dataset.draftBound = '1';
    field.addEventListener('input', queueWorkspaceDraftPersist);
    field.addEventListener('change', queueWorkspaceDraftPersist);
  });
}

function bindEditableGridInputs(root) {
  var scope = root || document;
  scope.querySelectorAll('[data-grid-source]').forEach(function(input) {
    if (input.dataset.gridBound === '1') return;
    input.dataset.gridBound = '1';
    input.addEventListener('input', function() {
      var source = document.getElementById(input.getAttribute('data-grid-source'));
      if (!source) return;
      source.value = input.value;
      source.dispatchEvent(new Event('input', { bubbles: true }));
    });
    input.addEventListener('change', function() {
      var source = document.getElementById(input.getAttribute('data-grid-source'));
      if (!source) return;
      source.value = input.value;
      source.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
}

// C2-PR2: subscribe to FcLiveModel's existing pub/sub once, rather
// than polling or adding a redundant DOM listener of our own — every
// C1-grid-driven write (type, undo/redo, fill, paste) already flows
// through FcCellIO.writeValue -> a native `change` event -> FcLiveModel
// markCellDirty(), so this is the single seam needed to make the
// legacy dirty banner/Run-gating reflect C1 grid edits too.
if (window.FcLiveModel && window.FcLiveModel.on) {
  window.FcLiveModel.on('project-dirty', _syncDirtyFromLiveModel);
  window.FcLiveModel.on('project-clean', _syncDirtyFromLiveModel);
}

document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.ws-tab[data-tab]').forEach(function(tabBtn) {
    tabBtn.addEventListener('click', function() {
      var tabId = tabBtn.getAttribute('data-tab');
      if (tabId) switchTab(tabId);
    });
  });

  var hash = window.location.hash.replace('#', '');
  if (hash) {
    // Support both legacy .ws-tab and new UI-3 .fo-sheet DOM tabs
    var hashTab = document.querySelector('.ws-tab[data-tab="' + hash + '"]') ||
                  document.querySelector('.fo-sheet[data-fo-sheet-kind="dom"][data-fo-sheet-id="' + hash + '"]');
    if (hashTab) setTimeout(function() { switchTab(hash); }, 0);
  } else {
    var defaultTab = document.querySelector('.ws-tab[data-tab="overview"]');
    var defaultPanel = document.getElementById('panel-overview');
    if (defaultTab) defaultTab.classList.add('active');
    if (defaultPanel) defaultPanel.classList.add('active');
    document.querySelectorAll('.tab-panel').forEach(function(panel) {
      if (panel.id !== 'panel-overview') panel.classList.remove('active');
    });
  }

  window.addEventListener('hashchange', function() {
    var currentHash = window.location.hash.replace('#', '');
    if (currentHash && currentHash !== activeTab) switchTab(currentHash);
  });

  document.querySelectorAll('.sidebar-nav-link').forEach(function(link) {
    link.addEventListener('click', function() {
      var href = link.getAttribute('href');
      if (!href || !href.startsWith('#')) return;
      var id = href.substring(1);
      if (!id || id === 'dashboard' || id === 'audit') return;

      document.querySelectorAll('.sidebar-nav-link').forEach(function(other) {
        other.classList.remove('active');
      });
      link.classList.add('active');

      var target = document.getElementById(id);
      if (target && target.tagName === 'DETAILS' && !target.hasAttribute('open')) {
        target.setAttribute('open', '');
      }
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  var sidebarRunBtn = document.getElementById('btn-run-model-sidebar');
  if (sidebarRunBtn) {
    sidebarRunBtn.addEventListener('click', function() {
      var realRunBtn = document.getElementById('btn-run-model');
      if (realRunBtn) realRunBtn.click();
    });
  }

  var saveBtn = document.getElementById('btn-save');
  if (saveBtn) {
    saveBtn.addEventListener('click', function() {
      var form = document.getElementById('main-form');
      if (form) form.dispatchEvent(new CustomEvent('saveRequested', { bubbles: true }));
    });
    // C2-PR2: /scenarios/save's htmx response only swaps
    // #saved-scenario-panel (the saved-scenario summary cards); unlike
    // /scenarios/{id}/load or /scenarios/state/discard, it never calls
    // applyWorkspaceStateMeta itself (the legacy banner/Run-gating was
    // never live-updated by a Save click before this change either —
    // that swap target doesn't include the banner element). What a
    // successful Save click does mean, unambiguously, is "the user's
    // current edits have just been persisted" — so this clears
    // FcLiveModel's canonical dirty state on a successful response,
    // bringing the C1-grid-driven dirty signal back in sync with the
    // save the user just performed, without touching the legacy
    // #main-form snapshot-diff mechanism or the /scenarios/save
    // request/response contract itself.
    saveBtn.addEventListener('htmx:afterRequest', function(evt) {
      if (evt && evt.detail && evt.detail.successful && window.FcLiveModel && window.FcLiveModel.clearAllDirty) {
        window.FcLiveModel.clearAllDirty();
      }
    });
  }

  if (window.syncEditableGridMirrors) {
    window.syncEditableGridMirrors();
  }

  var discardBtn = document.getElementById('btn-discard-edits');
  if (discardBtn) {
    discardBtn.addEventListener('click', function() {
      var form = document.getElementById('main-form');
      if (!form) return;
      var payload = new URLSearchParams(new FormData(form));
      fetch('/scenarios/state/discard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
        body: payload.toString(),
        credentials: 'same-origin'
      })
        .then(function(resp) { return resp.ok ? resp.json() : null; })
        .then(function(data) {
          if (!data) return;
          if (data.snapshot && window.applyScenarioSnapshot) {
            window.applyScenarioSnapshot(data.snapshot, data.active_scenario_id || '');
          }
          if (window.applyWorkspaceStateMeta) {
            window.applyWorkspaceStateMeta(data);
          }
          var activeProject = document.getElementById('active_project');
          if (activeProject && window.refreshScenarioWorkspace) {
            window.refreshScenarioWorkspace(activeProject.value);
          }
        })
        .catch(function() {
          alert('Could not discard edits right now.');
        });
    });
  }

  // duplicateCurrentScenario() is called via onclick on the button (defined at top of file)

  bindDraftPersistenceFields(document);
  bindEditableGridInputs(document);
  bindCapexAddLineUx(document);

  document.querySelectorAll('.input-group-summary').forEach(function(summary) {
    summary.addEventListener('click', function() {
      var group = summary.parentElement;
      if (group.hasAttribute('open')) {
        group.removeAttribute('open');
      } else {
        group.setAttribute('open', '');
      }
    });
  });
});

document.addEventListener('htmx:afterSwap', function(evt) {
  var target = evt && evt.target ? evt.target : document;
  bindDraftPersistenceFields(target);
  bindEditableGridInputs(target);
  bindCapexAddLineUx(target);
  if (window.syncEditableGridMirrors) {
    window.syncEditableGridMirrors();
  }
  // UX-1A: only re-show the New Project panel when the swap actually
  // landed inside it (e.g. submitting the create-project form posts
  // its result into #new-project-result). Previously this checked a
  // static condition (panel hidden + contains a form) that is true
  // after almost any unrelated swap in the workspace, which forced
  // the New Project panel open whenever a user ran the model, saved,
  // or created a scenario while viewing a different tab.
  var panel = document.getElementById('panel-new-project');
  if (panel && panel.style.display === 'none' && panel.contains(target) && panel.querySelector('form')) {
    panel.style.display = 'block';
    panel.classList.add('active');
  }

  // UX-2I: activate the Compare tab once the swap that populated
  // #panel-compare-mount has actually landed. Listening for the swap
  // itself (rather than relying on the triggering link's own
  // hx-on::after-request, which can fire before/without a successful
  // target resolution) guarantees the tab only switches once the
  // comparison table is really in the DOM.
  if (target && target.id === 'panel-compare-mount') {
    switchTab('compare');
  }
});

/* ─────────────────────────────────────────────────────────────────────
 *  Phase 57A-8: CAPEX Add-Line UX (in-memory preview)
 * ─────────────────────────────────────────────────────────────────────
 *
 *  Pure-UI affordance. When the user clicks a `+ Add line`
 *  button in `#capex-add-line-toolbar`, this module inserts
 *  a temporary row into the rendered CAPEX grid. The
 *  temporary row:
 *
 *    * has `data-capex-tmp="true"` on the <tr>
 *    * has a generated temporary business code
 *      (e.g. C.03.TMP-1) shown in the Code cell
 *    * has an editable label and editable amount
 *    * has an Unsaved / not persisted badge
 *    * has a Remove / cancel button
 *
 *  CRITICAL INVARIANTS:
 *
 *    1. The amount <input> for a temporary row has NO
 *       `name` attribute. So the temporary row is
 *       NEVER included in the form payload that is
 *       submitted to the backend.
 *    2. Temporary rows do NOT create any new backend
 *       CAPEX input. The backend CAPEX structure is
 *       untouched.
 *    3. The authoritative CAPEX totals (Hard CAPEX,
 *       Financing, Total) are NOT modified. A small
 *       preview-only total is rendered in the toolbar
 *       (clearly labelled "Preview only — not used by
 *       Run until persistence is implemented").
 *    4. When temporary rows exist, a warning block
 *       is shown to make the in-memory-only behaviour
 *       explicit.
 *    5. The module makes NO API calls. No fetch, no
 *       XHR, no htmx request, no form submission.
 *
 *  This is a runtime UI prototype only. Persistence is
 *  explicitly out of scope (see 57A-6 design doc).
 */
(function () {
  'use strict';

  // Per-category counter for generated temporary codes.
  // Reset on full page reload.
  var _tmpCounter = {};

  function _nextTmpIndex(catCode) {
    _tmpCounter[catCode] = (_tmpCounter[catCode] || 0) + 1;
    return _tmpCounter[catCode];
  }

  function _generateTmpCode(catCode) {
    return catCode + '.TMP-' + _nextTmpIndex(catCode);
  }

  // Find the rendered grid wrapper for CAPEX.
  function _gridRoot(root) {
    return (root || document).querySelector(
      '#capex-single-sheet-grid'
    );
  }

  // Find the tbody of the grid.
  function _gridTbody(root) {
    var t = _gridRoot(root);
    if (!t) return null;
    return t.tBodies && t.tBodies[0] ? t.tBodies[0] : null;
  }

  // Find the section_band <tr> for a given category code.
  // This is the <tr data-capex-add-line="C.01"> element.
  function _findCategoryRow(catCode, root) {
    var sel = 'tr[data-capex-category="' + catCode + '"]';
    var rows = (root || document).querySelectorAll(sel);
    if (!rows || !rows.length) return null;
    return rows[0];
  }

  // Find the last sub-line row of a given category, i.e.
  // the row before the cat-subtotal row.
  function _findCategorySubtotalRow(catCode, root) {
    var sel = 'tr[data-capex-row="cat-subtotal-' + catCode + '"]';
    var rows = (root || document).querySelectorAll(sel);
    if (!rows || !rows.length) return null;
    return rows[0];
  }

  // Build a temporary row element.
  function _buildTmpRow(catCode, catName, tmpCode) {
    var tr = document.createElement('tr');
    tr.className = 'lig-row--data lig-row--data-tmp';
    tr.setAttribute('data-capex-tmp', 'true');
    tr.setAttribute('data-capex-tmp-category', catCode);
    tr.setAttribute('data-capex-tmp-code', tmpCode);
    tr.setAttribute('data-capex-tmp-not-persisted', 'true');

    // Label cell
    var labelTd = document.createElement('td');
    labelTd.className = 'lig-cell fc-grid-col-label fc-cell fc-cell--indented';
    var labelSpan = document.createElement('span');
    labelSpan.className = 'lig-cell-runtime';
    labelSpan.setAttribute('data-capex-tmp-label', 'true');
    labelSpan.textContent = 'New line — ' + catCode;
    labelTd.appendChild(labelSpan);
    // "Unsaved" badge
    var badge = document.createElement('span');
    badge.className = 'badge badge-warning capex-tmp-unsaved-badge';
    badge.setAttribute('data-capex-tmp-unsaved-badge', 'true');
    badge.textContent = 'Unsaved / not persisted';
    labelTd.appendChild(document.createTextNode(' '));
    labelTd.appendChild(badge);
    tr.appendChild(labelTd);

    // Code cell
    var codeTd = document.createElement('td');
    codeTd.className = 'lig-cell fc-cell fc-cell--code';
    codeTd.setAttribute('data-capex-tmp-code-cell', 'true');
    codeTd.textContent = tmpCode;
    tr.appendChild(codeTd);

    // Amount cell
    var amountTd = document.createElement('td');
    amountTd.className = 'lig-cell fc-cell fc-cell--amount fc-cell--indented';
    var amountInput = document.createElement('input');
    amountInput.type = 'number';
    amountInput.step = 'any';
    amountInput.min = '0';
    amountInput.value = '0.00';
    // CRITICAL: no name attribute => the row is not
    // included in any form submit.
    amountInput.setAttribute('data-capex-tmp-amount', 'true');
    amountInput.setAttribute(
      'aria-label',
      'Temporary CAPEX amount for ' + tmpCode + ' (not persisted)'
    );
    amountInput.className = 'lig-input fc-input-native';
    amountInput.addEventListener('input', function () {
      _updatePreviewTotals();
    });
    amountTd.appendChild(amountInput);
    // Remove button cell
    var removeTd = document.createElement('td');
    removeTd.className = 'lig-cell fc-cell fc-cell--tmp-remove';
    var removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'capex-tmp-remove-btn';
    removeBtn.setAttribute('data-capex-tmp-remove', 'true');
    removeBtn.setAttribute('aria-label', 'Remove temporary line ' + tmpCode);
    removeBtn.textContent = '\u2715 Remove';
    removeBtn.addEventListener('click', function () {
      _removeTmpRow(tr);
    });
    removeTd.appendChild(removeBtn);
    tr.appendChild(amountTd);
    tr.appendChild(removeTd);

    return tr;
  }

  // Recompute the preview-only total.
  function _updatePreviewTotals() {
    var tmpRows = document.querySelectorAll(
      'tr[data-capex-tmp="true"]'
    );
    var total = 0.0;
    var n = 0;
    for (var i = 0; i < tmpRows.length; i++) {
      var input = tmpRows[i].querySelector(
        'input[data-capex-tmp-amount="true"]'
      );
      var amt = input ? parseFloat(input.value) : 0.0;
      if (!isNaN(amt)) total += amt;
      n++;
    }
    var totalsEl = document.querySelector(
      '[data-capex-add-line-preview-totals="true"]'
    );
    var detailEl = document.querySelector(
      '[data-capex-add-line-preview-detail="true"]'
    );
    if (totalsEl && detailEl) {
      if (n > 0) {
        totalsEl.removeAttribute('hidden');
        detailEl.textContent =
          ' ' + n + ' temporary line' + (n === 1 ? '' : 's') +
          ' totalling ' + total.toFixed(2) + ' kEUR ' +
          '(preview, not included in authoritative CAPEX total).';
      } else {
        totalsEl.setAttribute('hidden', '');
        detailEl.textContent = '';
      }
    }
    // Show / hide the run/save warning.
    var warn = document.getElementById('capex-tmp-run-warning');
    if (warn) {
      if (n > 0) warn.removeAttribute('hidden');
      else warn.setAttribute('hidden', '');
    }
  }

  // Remove a temporary row.
  function _removeTmpRow(tr) {
    if (tr && tr.parentNode) tr.parentNode.removeChild(tr);
    _updatePreviewTotals();
  }

  // Wire a single add-line button.
  function _bindAddLineButton(btn) {
    if (!btn || btn.__capexBound) return;
    btn.__capexBound = true;
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      var catCode = btn.getAttribute('data-capex-add-line-btn');
      var catName = btn.getAttribute('data-capex-cat-name') || catCode;
      if (!catCode) return;
      var tbody = _gridTbody(document);
      if (!tbody) {
        // Grid is not on this page (e.g. factory reference
        // or another tab). Silently no-op.
        return;
      }
      // Decide where to insert: just BEFORE the
      // category subtotal row (or at end of category
      // block if subtotal not found).
      var subtotal = _findCategorySubtotalRow(catCode, document);
      var tmpCode = _generateTmpCode(catCode);
      var tr = _buildTmpRow(catCode, catName, tmpCode);
      if (subtotal && subtotal.parentNode === tbody) {
        tbody.insertBefore(tr, subtotal);
      } else {
        // Fall back: insert at end of tbody.
        tbody.appendChild(tr);
      }
      _updatePreviewTotals();
    });
  }

  // Public binding entry point. Idempotent.
  function bindCapexAddLineUx(root) {
    var scope = root || document;
    var btns = scope.querySelectorAll(
      '[data-capex-add-line-btn]'
    );
    for (var i = 0; i < btns.length; i++) {
      _bindAddLineButton(btns[i]);
    }
  }

  // Expose for tests / external callers.
  window.bindCapexAddLineUx = bindCapexAddLineUx;
  window._capexTmpCount = function () {
    return document.querySelectorAll(
      'tr[data-capex-tmp="true"]'
    ).length;
  };
  window._capexTmpPurge = function () {
    var rows = document.querySelectorAll(
      'tr[data-capex-tmp="true"]'
    );
    for (var i = 0; i < rows.length; i++) {
      rows[i].parentNode.removeChild(rows[i]);
    }
    _tmpCounter = {};
    _updatePreviewTotals();
  };
})();
