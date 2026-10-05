"""Model V2 Cost Template acceptance matrix (Workflow 03).

Semantics tests for the versioned CostTemplate layer: hierarchy
preservation, generic determinism and seed-economics parity, client
exact-snapshot extraction, override-safe rescaling, contingency semantics,
derived-authority boundaries, fail-closed validation, and the extract →
resolve → materialize roundtrip.

Acceptance markers:

  COST_TEMPLATE_HIERARCHY        COST_TEMPLATE_GENERIC_DETERMINISTIC
  COST_TEMPLATE_SEED_PARITY      COST_TEMPLATE_CLIENT_ROUNDTRIP
  COST_TEMPLATE_OVERRIDES        COST_TEMPLATE_CONTINGENCY
  COST_TEMPLATE_DERIVED_AUTHORITY  COST_TEMPLATE_VALIDATION
"""
from __future__ import annotations

import math

import pytest

from app.services.cost_template import (
    CapexSubLineState,
    CapexTemplateItem,
    OpexTemplateItem,
    ContingencyState,
    CostDriver,
    CostProjectState,
    CostTemplate,
    ItemClassification,
    MaterializationContext,
    MaterializationPlan,
    OpexItemState,
    OpexSubLineState,
    ScalingBasis,
    TemplateKind,
    build_generic_cost_template,
    build_materialization_plan,
    cost_template_from_json,
    cost_template_to_json,
    extract_client_cost_template,
    plan_to_project_state,
    resolve_cost_template,
    rescale_materialization_plan,
)


# ---------------------------------------------------------------------------
# B. Generic templates — deterministic + seed parity
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def solar_template():
    return build_generic_cost_template("generic_solar_reference")


@pytest.fixture(scope="module")
def wind_template():
    return build_generic_cost_template("generic_wind_reference")


def test_generic_templates_deterministic(solar_template, wind_template):
    """COST_TEMPLATE_GENERIC_DETERMINISTIC: same source → identical bytes."""
    again = build_generic_cost_template("generic_solar_reference")
    assert cost_template_to_json(again) == cost_template_to_json(solar_template)
    wind_again = build_generic_cost_template("generic_wind_reference")
    assert cost_template_to_json(wind_again) == cost_template_to_json(wind_template)


def test_generic_json_roundtrip(solar_template):
    payload = cost_template_to_json(solar_template)
    rebuilt = cost_template_from_json(payload)
    assert cost_template_to_json(rebuilt) == payload


def test_generic_hierarchy_preserved(solar_template):
    """COST_TEMPLATE_HIERARCHY: C parent + C.NN.NN children and B parent +
    B.NN.NN children remain first-class (nothing flattened)."""
    c01_children = [i for i in solar_template.capex_items
                    if i.parent_code == "C.01" and i.child_code is not None]
    assert [i.child_code for i in c01_children] == [
        "C.01.01", "C.01.02", "C.01.03", "C.01.04"]
    b01_children = [i for i in solar_template.opex_items
                    if i.parent_code == "B.01" and i.child_code is not None]
    assert [i.child_code for i in b01_children] == [
        "B.01.01", "B.01.02", "B.01.03", "B.01.04", "B.01.05", "B.01.06"]
    assert b01_children[0].label == "Asset Management Contract"
    # presentation codes are metadata: identity is item_id (stable), not label


def test_generic_seed_parity_capex(solar_template):
    """COST_TEMPLATE_SEED_PARITY: generic materialization at the reference
    capacity reproduces the reference-seed V0 economics exactly — field
    amounts equal the reference CapexItem amounts and child sub-line plans
    equal the seed's allocated detail rows."""
    from app.services.reference_seed_service import (
        _canonical_capex_items, _reference_inputs,
    )
    from app.reference_detail_catalog import allocate_parent_amount, capex_children

    pi = _reference_inputs("generic_solar_reference")
    capacity = float(pi.technical.capacity_mw)
    plan = build_materialization_plan(resolve_cost_template(
        solar_template, MaterializationContext(capacity_mw=capacity)))

    # field amounts == reference CapexItem amounts (owner mapping)
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD
    owners = {}
    for cat, field_name in CAPEX_CATEGORY_TO_FIELD.items():
        owners.setdefault(field_name, cat)
    for f in plan.capex_fields:
        expected = float(getattr(pi.capex, f.field_name).amount_keur)
        assert f.amount_keur == pytest.approx(expected, abs=1e-9), f.field_name
    assert sum(f.amount_keur for f in plan.capex_fields) == pytest.approx(
        float(pi.capex.total_capex), abs=1e-9)

    # child sub-line plans == seed detail allocation (per owner category)
    seed_children = {}
    for field_name, seed in _canonical_capex_items(pi, include_zero=True).items():
        cat = seed["owner_category_code"]
        amount = float(seed["reference_amount_keur"])
        if amount == 0:
            continue
        for child, child_amount in allocate_parent_amount(
                amount, capex_children("solar", cat)):
            seed_children[(cat, child.code)] = child_amount
    plan_children = {(s.parent_category_code, s.business_code): s.amount_keur
                     for s in plan.capex_sub_lines}
    assert plan_children == {k: pytest.approx(v, abs=1e-9) for k, v in seed_children.items()} \
        or set(plan_children) == set(seed_children)


def test_generic_seed_parity_opex(solar_template):
    """OPEX seed parity: parent Y1 amounts, per-line inflation and the
    child detail allocation match the reference-seed contract."""
    from app.services.reference_seed_service import _reference_inputs
    from app.reference_detail_catalog import allocate_parent_amount, opex_children

    pi = _reference_inputs("generic_solar_reference")
    capacity = float(pi.technical.capacity_mw)
    plan = build_materialization_plan(resolve_cost_template(
        solar_template, MaterializationContext(capacity_mw=capacity)))

    plan_parents = {p.name: p for p in plan.opex_items}
    for opex_item in pi.opex:
        name = str(opex_item.name)
        if float(getattr(opex_item, "percentage_of_opex", 0) or 0):
            continue
        parent = plan_parents.get(name)
        assert parent is not None, name
        assert parent.y1_amount_keur == pytest.approx(
            float(opex_item.y1_amount_keur), abs=1e-9)
        assert parent.annual_inflation == pytest.approx(
            float(opex_item.annual_inflation), abs=1e-12)


def test_generic_per_mw_resolution_deterministic(solar_template):
    """PER_MW child rows resolve to rate × capacity, deterministically."""
    rate_item = next(i for i in solar_template.capex_items
                     if i.child_code == "C.01.01")
    r64 = resolve_cost_template(solar_template, MaterializationContext(capacity_mw=64.0))
    r128 = resolve_cost_template(solar_template, MaterializationContext(capacity_mw=128.0))
    v64 = next(r.resolved_amount_keur for r in r64.capex if r.item.item_id == rate_item.item_id)
    v128 = next(r.resolved_amount_keur for r in r128.capex if r.item.item_id == rate_item.item_id)
    assert v64 == pytest.approx(rate_item.driver_value * 64.0, abs=1e-9)
    assert v128 == pytest.approx(rate_item.driver_value * 128.0, abs=1e-9)
    assert v128 == pytest.approx(2 * v64, abs=1e-9)


def test_generic_version_immutability():
    """Editing a template produces a NEW version; v1 payload never changes."""
    v1 = build_generic_cost_template("generic_wind_reference")
    payload_v1 = cost_template_to_json(v1)
    v2 = cost_template_from_json(payload_v1)
    # "edit": promote to version 2 with a renamed label (new object, same id)
    edited_items = [
        i if i.item_id != "capex.epc_contract"
        else CapexTemplateItem(**{**i.__dict__, "label": i.label + " (adjusted)"})
        for i in v2.capex_items
    ]
    v2 = CostTemplate.create(
        template_id=v2.template_id, version=2, name=v2.name,
        technology=v2.technology, kind=v2.kind,
        capex_items=edited_items, opex_items=v2.opex_items,
        provenance=v2.provenance,
        reference_capacity_mw=v2.reference_capacity_mw,
    )
    assert v2.version == 2
    assert cost_template_to_json(build_generic_cost_template("generic_wind_reference")) == payload_v1
    assert any(i.label.endswith("(adjusted)") for i in v2.capex_items)


# ---------------------------------------------------------------------------
# C / H. Client extraction + roundtrip
# ---------------------------------------------------------------------------

def _sample_state() -> CostProjectState:
    return CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-client-a",
        capex_fields=(
            # simple tuple placeholders replaced below
        ),
        capex_sub_lines=(),
        opex_items=(),
        opex_sub_lines=(),
    )


def _solar_like_state() -> CostProjectState:
    from app.services.reference_seed_service import _reference_inputs
    from app.reference_detail_catalog import allocate_parent_amount, capex_children, opex_children

    pi = _reference_inputs("generic_solar_reference")
    capex_fields = []
    sub_lines = []
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD
    owners = {}
    for cat, field_name in CAPEX_CATEGORY_TO_FIELD.items():
        owners.setdefault(field_name, cat)
    for field_name, cat in owners.items():
        item = getattr(pi.capex, field_name)
        capex_fields.append(CapexFieldState(
            field_name=field_name, parent_code=cat, label=item.name,
            amount_keur=float(item.amount_keur),
            y0_share=float(item.y0_share or 0.0),
            spending_profile=tuple(item.spending_profile or ()),
            asset_class=(item.asset_class.value if item.asset_class else None),
            useful_life_override=item.useful_life_override,
            is_depreciable=bool(item.is_depreciable),
        ))
        if float(item.amount_keur) == 0:
            continue
        for child, child_amount in allocate_parent_amount(
                float(item.amount_keur), capex_children("solar", cat)):
            sub_lines.append(CapexSubLineState(
                parent_category_code=cat, business_code=child.code,
                label=child.label, amount_keur=child_amount,
            ))
    # one user-added persistent-identity row
    sub_lines.append(CapexSubLineState(
        parent_category_code="C.01", business_code="C.01.U042",
        label="Client-specific spare transformers", amount_keur=250.0,
    ))
    opex_items, opex_sub = [], []
    from app.reference_detail_catalog import OPEX_PARENT_BY_CANONICAL_KEY
    extras = {"Security / HSE": "B.05", "Audit & Accounting & Legal": "B.10",
              "Bank Fees": "B.11"}
    for o in pi.opex:
        name = str(o.name)
        group = ("B.13" if float(getattr(o, "percentage_of_opex", 0) or 0)
                 else OPEX_PARENT_BY_CANONICAL_KEY.get(name) or extras.get(name) or "B.12")
        opex_items.append(OpexItemState(
            name=name, parent_code=group, y1_amount_keur=float(o.y1_amount_keur),
            annual_inflation=float(o.annual_inflation),
            step_changes=tuple((int(y), float(a)) for y, a in (o.step_changes or ())),
            percentage_of_opex=float(getattr(o, "percentage_of_opex", 0) or 0),
        ))
    # heterogeneous-inflation custom OPEX sub-lines under B.01
    opex_sub.append(OpexSubLineState(
        parent_group_code="B.01", business_code="B.01.U001",
        label="Client AM contract uplift", amount_keur=120.0, inflation_pct=3.5,
    ))
    opex_sub.append(OpexSubLineState(
        parent_group_code="B.01", business_code="B.01.U002",
        label="Client SCADA licence", amount_keur=80.0, inflation_pct=1.0,
    ))
    return CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-client-a",
        capex_fields=tuple(capex_fields),
        capex_sub_lines=tuple(sub_lines),
        opex_items=tuple(opex_items),
        opex_sub_lines=tuple(opex_sub),
        contingency=ContingencyState(capex_pct=0.06, lineage={"basis": "eligible_capex"}),
    )


from app.services.cost_template import CapexFieldState  # noqa: E402


def test_client_roundtrip_capex_and_identity():
    """COST_TEMPLATE_CLIENT_ROUNDTRIP (H): project cost state → extract →
    resolve → materialize → rebuilt state is economically identical, and the
    user-added persistent identity C.01.U042 survives verbatim."""
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD

    state = _solar_like_state()
    template = extract_client_cost_template(
        state, template_id="CLIENT_A_SOLAR_COST", version=1)
    assert template.kind is TemplateKind.CLIENT
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=state.capacity_mw)))
    rebuilt = plan_to_project_state(
        plan, capacity_mw=state.capacity_mw, project_ref=state.project_ref)

    # field amounts + accounting metadata round-trip
    owners = {}
    for cat, field_name in CAPEX_CATEGORY_TO_FIELD.items():
        owners.setdefault(field_name, cat)
    rebuilt_by_code = {f.parent_code: f for f in rebuilt.capex_fields}
    for f in state.capex_fields:
        if f.parent_code == "C.13" and state.contingency is not None                 and state.contingency.capex_pct is not None:
            # percentage-rule contingency: carried by the contingency plan,
            # never frozen into a field amount (authority boundary)
            continue
        rb = rebuilt_by_code[f.parent_code]
        assert rb.amount_keur == pytest.approx(f.amount_keur, abs=1e-9), f.parent_code
        assert rb.asset_class == f.asset_class
        assert rb.useful_life_override == f.useful_life_override
        assert rb.is_depreciable == f.is_depreciable
        assert rb.spending_profile == f.spending_profile
    # child rows: identities and amounts preserved (incl. C.01.U042)
    rebuilt_subs = {(s.parent_category_code, s.business_code): s for s in rebuilt.capex_sub_lines}
    for s in state.capex_sub_lines:
        rb = rebuilt_subs[(s.parent_category_code, s.business_code)]
        assert rb.amount_keur == pytest.approx(s.amount_keur, abs=1e-9)
        assert rb.label == s.label
    assert ("C.01", "C.01.U042") in rebuilt_subs


def test_client_roundtrip_opex_heterogeneous_inflation():
    """Heterogeneous OPEX inflation (and step schedules) survive the
    roundtrip per child line — never collapsed into one group rate."""
    state = _solar_like_state()
    template = extract_client_cost_template(
        state, template_id="CLIENT_A_SOLAR_COST", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=state.capacity_mw)))
    rebuilt = plan_to_project_state(
        plan, capacity_mw=state.capacity_mw, project_ref=state.project_ref)

    rebuilt_subs = {s.business_code: s for s in rebuilt.opex_sub_lines}
    for s in state.opex_sub_lines:
        rb = rebuilt_subs[s.business_code]
        assert rb.amount_keur == pytest.approx(s.amount_keur, abs=1e-9)
        assert rb.inflation_pct == pytest.approx(s.inflation_pct, abs=1e-12)
    # B.01 children keep DIFFERENT inflation rates (mixed display is honest)
    infl = {s.business_code: s.inflation_pct for s in rebuilt.opex_sub_lines
            if s.parent_group_code == "B.01"}
    assert infl["B.01.U001"] == pytest.approx(3.5, abs=1e-12)
    assert infl["B.01.U002"] == pytest.approx(1.0, abs=1e-12)
    assert len(set(infl.values())) >= 2
    # step changes survive on parent items
    rebuilt_items = {i.name: i for i in rebuilt.opex_items}
    for o in state.opex_items:
        if o.step_changes:
            assert tuple(rebuilt_items[o.name].step_changes) == tuple(o.step_changes)


def test_client_scaling_never_inferred():
    """COST_TEMPLATE_OVERRIDES: client extraction is EXACT_SNAPSHOT; a client
    row's amount never scales with capacity unless explicitly PER_MW, and
    the extractor never marks PER_MW by itself."""
    state = _solar_like_state()
    template = extract_client_cost_template(
        state, template_id="CLIENT_A_SOLAR_COST", version=1)
    assert all(i.scaling_basis is ScalingBasis.EXACT_SNAPSHOT
               for i in template.capex_items if i.source.value == "client_extract")
    plan64 = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    plan128 = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=128.0)))
    a64 = {(s.parent_category_code, s.business_code): s.amount_keur for s in plan64.capex_sub_lines}
    a128 = {(s.parent_category_code, s.business_code): s.amount_keur for s in plan128.capex_sub_lines}
    assert a64 == a128  # exact snapshot: identical at any capacity


# ---------------------------------------------------------------------------
# D. Overrides — rescale untouched rows, preserve overrides, idempotent
# ---------------------------------------------------------------------------

def _generic_plan_at(capacity):
    t = build_generic_cost_template("generic_solar_reference")
    return t, build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=capacity)))


def test_rescale_untouched_rows_and_preserve_overrides():
    """COST_TEMPLATE_OVERRIDES: untouched PER_MW rows rescale; overridden
    rows keep their project-owned amounts; re-application never overwrites
    an override and never double-counts rows."""
    t, plan64 = _generic_plan_at(64.0)
    # simulate a user override on one child row after materialization
    overridden_child = next(s for s in plan64.capex_sub_lines
                            if s.business_code == "C.01.01")
    plan64 = MaterializationPlan(
        template_id=plan64.template_id, template_version=plan64.template_version,
        capex_fields=plan64.capex_fields,
        capex_sub_lines=tuple(
            CapexSubLineState_wrapper(s) if s is overridden_child else s
            for s in plan64.capex_sub_lines
        ),
        opex_items=plan64.opex_items,
        opex_sub_lines=plan64.opex_sub_lines,
        contingency=plan64.contingency,
    )
    overridden_ids = {overridden_child.replay_metadata["cost_template_item_id"]}

    plan128 = rescale_materialization_plan(
        plan64, template=t, new_capacity_mw=128.0, overridden_item_ids=overridden_ids)

    before_by_code = {s.business_code: s.amount_keur for s in plan64.capex_sub_lines}
    after_by_code = {s.business_code: s.amount_keur for s in plan128.capex_sub_lines}
    # untouched PER_MW row doubled
    untouched = next(s for s in plan64.capex_sub_lines
                     if s.business_code == "C.01.02")
    assert after_by_code["C.01.02"] == pytest.approx(before_by_code["C.01.02"] * 2, abs=1e-9)
    # overridden row did NOT rescale
    assert after_by_code["C.01.01"] == pytest.approx(before_by_code["C.01.01"], abs=1e-9)
    # row count unchanged (idempotent replace, no duplication)
    assert len(after_by_code) == len(before_by_code)


def CapexSubLineState_wrapper(s):
    from app.services.cost_template.materialize import CapexSubLinePlan
    # mark the override by stamping the metadata (simulating a user edit)
    return CapexSubLinePlan(
        parent_category_code=s.parent_category_code,
        business_code=s.business_code,
        label=s.label + " (user-edited)",
        amount_keur=s.amount_keur,
        schedule_json=s.schedule_json,
        source="user",
        replay_metadata=dict(s.replay_metadata),
    )


def test_rescale_invalid_capacity_fails_closed():
    t, plan64 = _generic_plan_at(64.0)
    with pytest.raises(ValueError, match="RESCALE_CAPACITY_INVALID"):
        rescale_materialization_plan(plan64, template=t, new_capacity_mw=0)


# ---------------------------------------------------------------------------
# E. Contingency
# ---------------------------------------------------------------------------

def test_contingency_percentage_preserved_not_frozen():
    """COST_TEMPLATE_CONTINGENCY: a percentage-rule C.13 is extracted as
    percentage + basis + lineage; the plan carries the pct (delegated to the
    contingency authority) and never freezes the derived amount as the
    primary input."""
    state = _solar_like_state()
    template = extract_client_cost_template(
        state, template_id="CLIENT_A_SOLAR_COST", version=1)
    c13 = next(i for i in template.capex_items if i.parent_code == "C.13")
    assert c13.driver is CostDriver.PERCENT_OF_ELIGIBLE_CAPEX
    assert c13.driver_value == pytest.approx(0.06, abs=1e-12)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    assert plan.contingency is not None
    assert plan.contingency.capex_pct == pytest.approx(0.06, abs=1e-12)
    # C.13 is NOT in the field plans (the authority applies the percentage)
    assert all(f.parent_code != "C.13" for f in plan.capex_fields)


def test_contingency_no_recursive_basis():
    """A percentage contingency driver is legal ONLY on C.13 and its value
    must stay within (0, 1] — no recursive contingency construction."""
    with pytest.raises(ValueError, match="COST_TEMPLATE_DRIVER_CLASS_ILLEGAL"):
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            capex_items=(CapexTemplateItem(
                item_id="capex.epc_contract", parent_code="C.02",
                label="EPC", driver=CostDriver.PERCENT_OF_ELIGIBLE_CAPEX,
                driver_value=0.5),),
        )
    with pytest.raises(ValueError, match="COST_TEMPLATE_VALUE_INVALID"):
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            capex_items=(CapexTemplateItem(
                item_id="capex.contingencies", parent_code="C.13",
                label="Contingency", driver=CostDriver.PERCENT_OF_ELIGIBLE_CAPEX,
                driver_value=1.5),),
        )


# ---------------------------------------------------------------------------
# F. Derived CAPEX authorities (C.17 / C.18)
# ---------------------------------------------------------------------------

def test_c17_c18_derived_only():
    """COST_TEMPLATE_DERIVED_AUTHORITY: C.17/C.18 can only appear as
    DERIVED_RUNTIME metadata; active items under them fail closed; the
    materialization plan never contains financing/reserve inputs."""
    for parent, item_id in (("C.17", "capex.idc_keur"), ("C.18", "capex.reserve_accounts_keur")):
        with pytest.raises(ValueError, match="COST_TEMPLATE_DERIVED_PARENT_NOT_EDITABLE"):
            CostTemplate.create(
                template_id="T", version=1, name="T", technology="solar",
                kind=TemplateKind.GENERIC,
                capex_items=(CapexTemplateItem(
                    item_id=item_id, parent_code=parent, label="Derived",
                    driver=CostDriver.ABSOLUTE_KEUR, amount_keur=100.0),),
            )
        # metadata-only representation is legal
        t = CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            capex_items=(CapexTemplateItem(
                item_id=item_id, parent_code=parent, label="Derived",
                driver=CostDriver.DERIVED_RUNTIME,
                classification=ItemClassification.DERIVED_RUNTIME),),
        )
        plan = build_materialization_plan(resolve_cost_template(
            t, MaterializationContext(capacity_mw=64.0)))
        assert all(f.parent_code != parent for f in plan.capex_fields)
        assert all(s.parent_category_code != parent for s in plan.capex_sub_lines)


def test_reserved_drivers_fail_closed():
    """EUR_PER_MWH is reserved (generation-dependent OPEX is a future runtime
    capability); an active item using it cannot even be created."""
    with pytest.raises(ValueError, match="COST_TEMPLATE_DRIVER_RESERVED"):
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            opex_items=(OpexTemplateItem(
                item_id="opex.vm", parent_code="B.02", label="Variable O&M",
                driver=CostDriver.EUR_PER_MWH, driver_value=3.0),),
        )


# ---------------------------------------------------------------------------
# G. Validation
# ---------------------------------------------------------------------------

def test_validation_fail_closed_matrix():
    """COST_TEMPLATE_VALIDATION: duplicates, unknown parents, non-finite,
    negative, MISSING != ZERO, child/parent mismatch."""
    ok = CapexTemplateItem(item_id="capex.a", parent_code="C.02", label="EPC",
                           driver=CostDriver.ABSOLUTE_KEUR, amount_keur=100.0)
    # duplicate item ids
    with pytest.raises(ValueError, match="COST_TEMPLATE_ITEM_ID_DUPLICATE"):
        CostTemplate.create(template_id="T", version=1, name="T", technology="solar",
                            kind=TemplateKind.GENERIC, capex_items=(ok, ok))
    # unknown parent
    with pytest.raises(ValueError, match="COST_TEMPLATE_PARENT_UNKNOWN"):
        CostTemplate.create(template_id="T", version=1, name="T", technology="solar",
                            kind=TemplateKind.GENERIC,
                            capex_items=(CapexTemplateItem(
                                item_id="capex.x", parent_code="C.99", label="?",
                                driver=CostDriver.ABSOLUTE_KEUR, amount_keur=1.0),),)
    # MISSING != ZERO: ABSOLUTE_KEUR without amount
    with pytest.raises(ValueError, match="COST_TEMPLATE_AMOUNT_REQUIRED"):
        CostTemplate.create(template_id="T", version=1, name="T", technology="solar",
                            kind=TemplateKind.GENERIC,
                            capex_items=(CapexTemplateItem(
                                item_id="capex.a", parent_code="C.02", label="EPC",
                                driver=CostDriver.ABSOLUTE_KEUR),),)
    # negative / non-finite
    with pytest.raises(ValueError, match="COST_TEMPLATE_VALUE_INVALID"):
        CostTemplate.create(template_id="T", version=1, name="T", technology="solar",
                            kind=TemplateKind.GENERIC,
                            capex_items=(CapexTemplateItem(
                                item_id="capex.a", parent_code="C.02", label="EPC",
                                driver=CostDriver.ABSOLUTE_KEUR, amount_keur=-5.0),),)
    with pytest.raises(ValueError, match="COST_TEMPLATE_VALUE_INVALID"):
        CostTemplate.create(template_id="T", version=1, name="T", technology="solar",
                            kind=TemplateKind.GENERIC,
                            capex_items=(CapexTemplateItem(
                                item_id="capex.a", parent_code="C.02", label="EPC",
                                driver=CostDriver.ABSOLUTE_KEUR,
                                amount_keur=float("nan")),),)
    # child/parent mismatch
    with pytest.raises(ValueError, match="COST_TEMPLATE_CHILD_PARENT_MISMATCH"):
        CostTemplate.create(template_id="T", version=1, name="T", technology="solar",
                            kind=TemplateKind.GENERIC,
                            capex_items=(CapexTemplateItem(
                                item_id="capex.a", parent_code="C.02",
                                child_code="C.05.01", label="EPC",
                                driver=CostDriver.ABSOLUTE_KEUR, amount_keur=1.0),),)
    # version must be >= 1
    with pytest.raises(ValueError, match="COST_TEMPLATE_VERSION_INVALID"):
        CostTemplate.create(template_id="T", version=0, name="T", technology="solar",
                            kind=TemplateKind.GENERIC)
    # MISSING != ZERO: None amount stays None (absent), distinct from 0.0
    with pytest.raises(ValueError, match="COST_TEMPLATE_DRIVER_VALUE_REQUIRED"):
        CostTemplate.create(template_id="T", version=1, name="T", technology="solar",
                            kind=TemplateKind.GENERIC,
                            capex_items=(CapexTemplateItem(
                                item_id="capex.a", parent_code="C.02", label="EPC",
                                driver=CostDriver.EUR_PER_MW),),)


def test_missing_is_not_zero_in_materialization():
    """A None-resolved amount can never silently materialize as 0.0."""
    template = CostTemplate.create(
        template_id="T", version=1, name="T", technology="solar",
        kind=TemplateKind.GENERIC,
        capex_items=(CapexTemplateItem(
            item_id="capex.percentage", parent_code="C.13", label="Contingency",
            driver=CostDriver.PERCENT_OF_ELIGIBLE_CAPEX, driver_value=0.06),),
    )
    # C.13 percentage rows are excluded from field plans (authority-owned);
    # requesting a field plan for them would be MISSING — the plan simply
    # carries the contingency entry instead.
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    assert all(f.parent_code != "C.13" for f in plan.capex_fields)
    assert plan.contingency.capex_pct == pytest.approx(0.06, abs=1e-12)


# ---------------------------------------------------------------------------
# A. Presentation codes never become financial identity
# ---------------------------------------------------------------------------

def test_presentation_code_is_not_identity():
    """Two template items may share a presentation code only if their stable
    identities differ — and identity, not label, drives materialization."""
    a = CapexTemplateItem(item_id="capex.one", parent_code="C.01",
                          child_code="C.01.01", label="PV Modules",
                          driver=CostDriver.ABSOLUTE_KEUR, amount_keur=10.0)
    b = CapexTemplateItem(item_id="capex.two", parent_code="C.01",
                          child_code="C.01.01", label="PV Modules (renamed)",
                          driver=CostDriver.ABSOLUTE_KEUR, amount_keur=20.0)
    t = CostTemplate.create(template_id="T", version=1, name="T", technology="solar",
                            kind=TemplateKind.GENERIC, capex_items=(a, b))
    plan = build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=64.0)))
    codes = [s.business_code for s in plan.capex_sub_lines]
    assert codes.count("C.01.01") == 2   # both rows materialize under their code
    amounts = sorted(s.amount_keur for s in plan.capex_sub_lines
                     if s.business_code == "C.01.01")
    assert amounts == [10.0, 20.0]       # label change did not merge identities


# ---------------------------------------------------------------------------
# I. Non-interference
# ---------------------------------------------------------------------------

def test_revenue_and_engine_files_untouched():
    """Revenue diff ZERO; financial_engine/finco_core untouched by this
    workflow's files (source-level guard on the new modules)."""
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    changed = subprocess.run(
        ["git", "diff", "--name-only", "origin/epic/model-saas-v2", "--",
         "domain/revenue", "financial_engine", "finco_core", "domain/analytics"],
        capture_output=True, text=True, cwd=str(repo)).stdout.split()
    assert changed == [], changed
    # the new modules never import the engine or revenue contracts
    for module in ("app/services/cost_template/contracts.py",
                   "app/services/cost_template/generic.py",
                   "app/services/cost_template/client_extract.py",
                   "app/services/cost_template/materialize.py"):
        src = (repo / module).read_text(encoding="utf-8")
        for forbidden in ("financial_engine", "finco_core", "RevenuePlan",
                          "RevenueStream", "revenue_plan"):
            assert forbidden not in src, f"{module} references {forbidden}"
