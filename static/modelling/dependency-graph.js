/*
 * FINCO Protocol — Live Modelling Layer
 * C2-PR4: Dependency Graph Foundation (infrastructure only — maps
 * dirty C1 cells/sheets to affected coarse-grained model "output
 * groups"; no financial recalculation, no dependency execution, no
 * backend Run call, no Save/dirty-state change)
 *
 * Reference: docs/C2_PR1_IMPLEMENTATION_NOTE.md,
 *            docs/C2_PR2_DIRTY_STATE_UNIFICATION_NOTE.md,
 *            docs/C2_PR3_RECALC_SCHEDULER_FOUNDATION_NOTE.md,
 *            docs/C2_PR4_DEPENDENCY_GRAPH_FOUNDATION_NOTE.md.
 *
 * This module answers exactly one question: "if cell X changes,
 * which coarse-grained model output groups would eventually need
 * recalculation?" It never calculates an output, never walks a
 * formula, never calls a backend endpoint, and never mutates any
 * dirty-state/recalc-scheduler state owned by FcLiveModel.
 *
 * Output groups (coarse, fixed vocabulary):
 *   "overview-kpis", "revenue", "opex", "capex", "senior-debt",
 *   "tax", "scenarios", "export-audit"
 *
 * Mapping philosophy (see the implementation note for full
 * rationale): the bulk of the registry is per-grid wildcard rules
 * grounded in the real `data-fc-grid` ids used across the production
 * sheet templates (capex, opex, inputs, revenue, seniordebt, tax,
 * export, audit, scenarios, scenario-inputs, scenario-summary,
 * scenario-compare) — confirmed via grep against
 * app/templates/partials/*.html, not invented. A small number of
 * finer-grained `inputs!<section>.<field>` rules are layered on top
 * for the handful of top-level scalar inputs (e.g.
 * `input_source_ref`) that plausibly ripple across many
 * groups at once. When uncertain, mappings are conservative (broad)
 * rather than narrow.
 *
 * Unknown/unmapped addresses never throw — they resolve to a
 * conservative broad group set (["overview-kpis", "unknown"]) plus
 * an explanation marking them unmapped, per the "prefer conservative
 * over narrow when uncertain" requirement.
 *
 * All outputs are deterministic: affected groups are always returned
 * sorted; resolveSnapshot()'s input/derived address lists are sorted;
 * no timestamp or session id appears anywhere in any return value.
 */
(function () {
  'use strict';

  var ALL_GROUPS = [
    'overview-kpis',
    'revenue',
    'opex',
    'capex',
    'senior-debt',
    'tax',
    'scenarios',
    'export-audit'
  ];

  // Conservative fallback for any address that cannot be resolved by
  // a more specific rule below. "overview-kpis" is included because
  // any unmapped edit could plausibly move a headline KPI; "unknown"
  // flags that this is a fallback, not a confirmed mapping.
  var UNKNOWN_GROUPS = ['overview-kpis', 'unknown'];

  // --- Per-grid wildcard rules: "any addr in this grid affects these
  // groups." Grounded in the real data-fc-grid ids confirmed via grep
  // across app/templates/partials/*.html (sheet_capex.html,
  // sheet_opex_detail.html, sheet_inputs.html, sheet_revenue.html,
  // sheet_senior_debt.html, sheet_tax.html, workspace_shell.html,
  // _audit_governance_relocated.html, scenario_matrix.html,
  // scenario_tab.html, _scenario_unified_entry.html,
  // scenario_compare.html).
  //
  // Rationale per grid:
  //  - capex: a CAPEX line item amount feeds total CAPEX, which feeds
  //    financing/sizing (senior-debt) and the headline KPIs. It does
  //    not plausibly affect revenue, opex, tax, or scenarios/export
  //    directly, so it is scoped to those three groups rather than
  //    everything.
  //  - opex: an OPEX line item (budget/inflation/wht/subtotal) feeds
  //    opex itself, the tax calculation (opex is deductible), and
  //    headline KPIs (e.g. equity IRR/DSCR depend on opex).
  //  - inputs: the generic top-level scalar Inputs grid is
  //    deliberately the broadest wildcard — these are the seed
  //    assumptions (technical/financial/debt/tax/schedule) that the
  //    whole model is built from, so any inputs! edit conservatively
  //    affects every primary financial group. A handful of more
  //    precise per-field rules are layered on top below and take
  //    precedence when they match.
  //  - revenue: a revenue line item affects revenue and headline
  //    KPIs (revenue feeds DSCR/IRR), and tax (revenue is taxable).
  //  - seniordebt: a senior-debt facility/gearing/rate/tenor change
  //    affects senior-debt itself and headline KPIs (DSCR/IRR/sizing);
  //    it does not directly affect revenue/opex/tax line items.
  //  - tax: a tax assumption (cit_rate, convention, g20_status, etc.)
  //    affects tax and headline KPIs (post-tax equity IRR).
  //  - export / audit: these are read-mostly presentation surfaces
  //    over already-computed model state (current_context, governance
  //    posture, workbook downloads) — they don't feed back into any
  //    other model output, so they map onto a single, separate
  //    "export-audit" group and nothing else.
  //  - scenarios / scenario-inputs / scenario-summary /
  //    scenario-compare: all four scenario-related grids map to the
  //    "scenarios" group. scenario-inputs additionally affects
  //    overview-kpis conservatively, since editing a scenario's
  //    underlying inputs plausibly changes that scenario's computed
  //    KPIs too.
  var GRID_RULES = {
    capex: ['capex', 'senior-debt', 'overview-kpis'],
    opex: ['opex', 'tax', 'overview-kpis'],
    inputs: ['overview-kpis', 'revenue', 'opex', 'capex', 'senior-debt', 'tax'],
    revenue: ['revenue', 'tax', 'overview-kpis'],
    seniordebt: ['senior-debt', 'overview-kpis'],
    tax: ['tax', 'overview-kpis'],
    export: ['export-audit'],
    audit: ['export-audit'],
    scenarios: ['scenarios'],
    'scenario-inputs': ['scenarios', 'overview-kpis'],
    'scenario-summary': ['scenarios'],
    'scenario-compare': ['scenarios']
  };

  // --- Finer-grained rules for specific `inputs!<section>.<field>`
  // addresses, layered on top of the inputs grid's broad wildcard.
  // These are deliberately narrower than the inputs wildcard only
  // where the field's real-world effect is obviously scoped — e.g. a
  // tax-section field should not need to claim it affects capex.
  // Sections confirmed via grep of field_row(... section="...") calls
  // across app/templates/partials/sheet_inputs.html: identity,
  // technical, capex, opex, revenue, debt, tax, schedule.
  var INPUTS_SECTION_RULES = {
    // capacity_mw-style technical/capacity inputs ripple into
    // revenue (production), capex (sizing), senior-debt (debt
    // sizing/DSCR), and headline KPIs. Conservative — does not
    // include opex/tax since those are less directly load-bearing on
    // capacity changes.
    technical: ['overview-kpis', 'revenue', 'capex', 'senior-debt'],
    capex: ['capex', 'senior-debt', 'overview-kpis'],
    opex: ['opex', 'tax', 'overview-kpis'],
    revenue: ['revenue', 'tax', 'overview-kpis'],
    debt: ['senior-debt', 'overview-kpis'],
    tax: ['tax', 'overview-kpis'],
    // identity/schedule sections (project name, COD date, etc.) are
    // largely presentational/timing — conservatively scoped to
    // headline KPIs and scenarios (schedule affects construction
    // timing, which can move scenario comparisons) only.
    identity: ['overview-kpis'],
    schedule: ['overview-kpis', 'scenarios']
  };

  function _uniqueSorted(arr) {
    var seen = {};
    var out = [];
    arr.forEach(function (g) {
      if (!seen[g]) {
        seen[g] = true;
        out.push(g);
      }
    });
    out.sort();
    return out;
  }

  function _parseAddr(addr) {
    if (typeof addr !== 'string' || addr.indexOf('!') === -1) return null;
    var bangIdx = addr.indexOf('!');
    var gridId = addr.slice(0, bangIdx);
    var key = addr.slice(bangIdx + 1);
    if (!gridId || !key) return null;
    return { gridId: gridId, key: key };
  }

  /**
   * Resolves a single cell address to the set of coarse output
   * groups it plausibly affects. Never throws. Unknown/unmapped
   * addresses (malformed, or a gridId with no registered rule)
   * conservatively resolve to UNKNOWN_GROUPS.
   */
  function resolveCell(addr) {
    var parsed = _parseAddr(addr);
    if (!parsed) return _uniqueSorted(UNKNOWN_GROUPS.slice());

    var gridId = parsed.gridId;
    var key = parsed.key;

    if (gridId === 'inputs') {
      var section = key.split('.')[0];
      var sectionRule = INPUTS_SECTION_RULES[section];
      if (sectionRule) return _uniqueSorted(sectionRule.slice());
      // Unrecognised inputs section: fall through to the broad
      // inputs-grid wildcard rather than UNKNOWN, since "inputs" is
      // itself a known, registered grid — just not this section.
      return _uniqueSorted(GRID_RULES.inputs.slice());
    }

    var gridRule = GRID_RULES[gridId];
    if (gridRule) return _uniqueSorted(gridRule.slice());

    return _uniqueSorted(UNKNOWN_GROUPS.slice());
  }

  /**
   * Resolves a flat list of addresses to the union of all affected
   * groups, sorted and de-duplicated.
   */
  function getAffectedGroups(addrs) {
    var groups = [];
    (addrs || []).forEach(function (addr) {
      groups = groups.concat(resolveCell(addr));
    });
    return _uniqueSorted(groups);
  }

  /**
   * Resolves a FcLiveModel.getPendingRecalcSnapshot()-shaped snapshot
   * ({ grids: [{gridId, addrs}], projectDirty }) to its union of
   * affected groups. Reads only the addrs already present in the
   * snapshot — never queries the DOM, FcLiveModel, or any other
   * module. Deterministic: same logical snapshot always produces the
   * same sorted affectedGroups array, regardless of input grid/addr
   * ordering.
   */
  function resolveSnapshot(snapshot) {
    var addrs = [];
    if (snapshot && Array.isArray(snapshot.grids)) {
      snapshot.grids.forEach(function (grid) {
        if (grid && Array.isArray(grid.addrs)) {
          addrs = addrs.concat(grid.addrs);
        }
      });
    }
    return getAffectedGroups(addrs);
  }

  /**
   * Human/diagnostic-readable explanation of how a single address
   * resolved. Never throws. For an unmapped address, explicitly
   * states that it is unmapped and that the conservative fallback
   * was used.
   */
  function explain(addr) {
    var parsed = _parseAddr(addr);
    var groups = resolveCell(addr);

    if (!parsed) {
      return {
        addr: addr,
        matched: false,
        rule: null,
        affectedGroups: groups,
        reason: 'Address is malformed or unmapped (expected "gridId!key" shape); conservative fallback group set returned.'
      };
    }

    var gridId = parsed.gridId;
    var key = parsed.key;

    if (gridId === 'inputs') {
      var section = key.split('.')[0];
      if (INPUTS_SECTION_RULES[section]) {
        return {
          addr: addr,
          matched: true,
          rule: 'inputs-section:' + section,
          affectedGroups: groups,
          reason: 'Matched inputs section "' + section + '" fine-grained rule.'
        };
      }
      return {
        addr: addr,
        matched: true,
        rule: 'grid-wildcard:inputs',
        affectedGroups: groups,
        reason: 'No fine-grained rule for inputs section "' + section + '"; fell back to the broad inputs-grid wildcard.'
      };
    }

    if (GRID_RULES[gridId]) {
      return {
        addr: addr,
        matched: true,
        rule: 'grid-wildcard:' + gridId,
        affectedGroups: groups,
        reason: 'Matched grid-level wildcard rule for grid "' + gridId + '".'
      };
    }

    return {
      addr: addr,
      matched: false,
      rule: null,
      affectedGroups: groups,
      reason: 'Grid id "' + gridId + '" is not registered in the dependency graph; conservative fallback group set returned.'
    };
  }

  window.FcDependencyGraph = {
    ALL_GROUPS: ALL_GROUPS.slice(),
    UNKNOWN_GROUPS: UNKNOWN_GROUPS.slice(),

    resolveCell: resolveCell,
    resolveSnapshot: resolveSnapshot,
    getAffectedGroups: getAffectedGroups,
    explain: explain
  };
})();
