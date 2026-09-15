"""Phase PR1 — Form Timing Fields Enrichment (helper).

The Generic Solar / Generic Wind create form
in ``app/templates/partials/new_project_form.html``
already ships the four timing fields
(``cod_date``, ``construction_months``,
``horizon_years``, ``ppa_term_years``) as
``<input>`` controls. The form posts them to
``/projects/create`` and the route stores them
in the baseline snapshot via
``_apply_new_project_required_inputs``.

However, the legacy ``_build_schema_from_form``
helper in ``main_web.py`` (used by
``compare_service``, ``download_service``, and
``run_service`` for Path B schema builds) does
NOT carry the four timing fields into the
``ProjectInputsSchema``. This means Path B
runs silently fall back to factory defaults
for these four fields, while Path A (snapshot)
runs use the user-supplied values.

Claude's delta review flagged this as
"silent template-default drift" — the form
and the saved scenario can produce different
``ProjectInputs`` even when the user typed
identical values into identical form fields.

This module is the **enrichment sidecar** for
Path B callers. It is callable from any
service that needs to upgrade an existing
``ProjectInputsSchema`` to carry the four
timing fields. It is also the reference
implementation that any future fix in
``main_web.py`` should mirror (i.e. the four
timing fields must be carried with the same
field names, types, and conversion rules).

Hard no-go (locked by tests):

- no financial formula changes
- no model / factory / frozen-schedule
  changes
- no debt-sizing / tax / IDC / depreciation
  changes
- no construction / C10 / R-PAR changes
- no manual_gearing / no min(gearing, sculpt)
- no persistence schema migration
- no static/app.js changes
- no app.js financial calc
- no Tailwind / Alpine / React / Vue / Svelte
- no R99 / R102 / G20 promotion
- use_construction_schedule_engine remains
  False
- rc1 SHA preserved

The helper is read-only — it does not write
to any persistence layer, mutate any state,
or perform any I/O. It only constructs and
returns a new ``ProjectInputsSchema`` with
the timing fields populated.
"""

from __future__ import annotations

from typing import Optional

from app.input_schema import ProjectInputsSchema


# The four timing fields that the create form
# ships but Path B schema-build loses. These
# names MUST match the form field names in
# ``app/templates/partials/new_project_form.html``
# and the snapshot keys in
# ``_apply_new_project_required_inputs``.
FORM_TIMING_FIELDS = (
    "cod_date",
    "construction_months",
    "horizon_years",
    "ppa_term_years",
)


def enrich_schema_with_timing_fields(
    base: ProjectInputsSchema,
    *,
    cod_date: Optional[str] = None,
    construction_months: Optional[int] = None,
    horizon_years: Optional[int] = None,
    ppa_term_years: Optional[int] = None,
) -> ProjectInputsSchema:
    """Return a new ``ProjectInputsSchema`` with the
    four timing fields populated on top of an
    existing schema.

    The base schema's other fields (project_type,
    project_name, scenario, capacity_mw, revenue,
    capex, opex, debt) are preserved verbatim. Only
    the four timing fields are touched.

    Note: ``ppa_term_years`` is stored on the
    nested ``revenue`` Pydantic model (where the
    S1 schema places it). The other three timing
    fields are stored at the top level. The
    helper handles both placements correctly.

    Behaviour:

    - ``None`` value (the default) means "do not
      touch this field" — the base schema's
      existing value is preserved.
    - Empty string ``""`` is also treated as
      "no value" and the base schema's value is
      preserved (this is what the create form
      sends for an optional field the user did
      not fill in).
    - Any other string / int is assigned to the
      corresponding field, overwriting the base
      schema's value.

    The helper is a pure function: it does not
    mutate the base schema. It returns a new
    ``ProjectInputsSchema`` instance.

    Pinned by tests.
    """
    def _coerce_str(v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    def _coerce_int(v):
        v = _coerce_str(v)
        if v is None:
            return None
        return int(v)

    new_cod = _coerce_str(cod_date)
    new_cm = _coerce_int(construction_months)
    new_hy = _coerce_int(horizon_years)
    new_ppa = _coerce_int(ppa_term_years)

    # First apply the three top-level fields.
    out = base.model_copy(
        update={
            "cod_date": new_cod,
            "construction_months": new_cm,
            "horizon_years": new_hy,
        }
    )
    # Then apply ppa_term_years to the nested
    # revenue model. If a revenue sub-model does
    # not exist, create one with just the
    # ppa_term_years field set.
    if new_ppa is not None:
        from app.input_schema import RevenueInput
        if out.revenue is None:
            out = out.model_copy(
                update={"revenue": RevenueInput(ppa_term_years=new_ppa)}
            )
        else:
            out = out.model_copy(
                update={
                    "revenue": out.revenue.model_copy(
                        update={"ppa_term_years": new_ppa}
                    )
                }
            )
    return out


def timing_fields_from_form_dict(form_data: dict) -> dict:
    """Extract the four timing fields from a
    FastAPI ``Form(...)`` flat dict (the kind
    ``/projects/create`` receives).

    Returns a dict with the four timing keys
    (``cod_date``, ``construction_months``,
    ``horizon_years``, ``ppa_term_years``). The
    values are the raw form strings (or empty
    string if the user left the field blank).

    This is a thin adapter so callers do not
    have to re-derive the four field names.
    Pinned by tests.
    """
    return {
        "cod_date": form_data.get("cod_date", ""),
        "construction_months": form_data.get("construction_months", ""),
        "horizon_years": form_data.get("horizon_years", ""),
        "ppa_term_years": form_data.get("ppa_term_years", ""),
    }


def apply_timing_to_schema(
    base: ProjectInputsSchema,
    form_data: dict,
) -> ProjectInputsSchema:
    """Convenience: extract the four timing
    fields from ``form_data`` (a FastAPI Form
    flat dict) and return a new schema with
    them applied.

    This is the one-shot entry point for Path B
    callers that receive a form submission and
    want to build a schema that does NOT lose
    the four timing fields.

    Usage in a service:

        schema = deps.build_schema_from_form(
            project_type=project_type,
            scenario=scenario,
            capacity_mw=capacity_mw,
            ...  # legacy fields
        )
        # PR1 enrichment: carry timing fields
        # forward.
        schema = apply_timing_to_schema(schema, form_data)

    Pinned by tests.
    """
    timing = timing_fields_from_form_dict(form_data)
    return enrich_schema_with_timing_fields(
        base,
        cod_date=timing["cod_date"],
        construction_months=timing["construction_months"],
        horizon_years=timing["horizon_years"],
        ppa_term_years=timing["ppa_term_years"],
    )
