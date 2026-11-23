"""FABLE-HTTP-02 integration correction (FINCO 34 batch 1).

The original #463 change made every residual ValueError/TypeError of the investor-agreement save an
"unexpected" controlled 500. But ``parse_terms`` (and the P0 contracts it builds) refuse invalid agreements
with AUTHORED, bounded ValueError texts -- e.g. "Legal equity ownership must sum to one". Under #463 alone
those legitimate input refusals became 500 INTERNAL_ERROR, which broke the accepted browser contract
(hosted run 44565047396 / job 135704380031: the React panel waited for its 422 refusal message).

Accepted contract restored and kept:
* authored domain refusals -> 422 with their stable text, nothing persisted;
* interpreter text (JSON / ISO date / library ValueError subclasses) is never echoed;
* non-ValueError faults (TypeError, ...) stay unexpected -> controlled, logged 500 (covered in #463's tests);
* ``InvestorAgreementInputError`` is a ValueError, so internal ``except ValueError`` callers are unchanged.
"""
from __future__ import annotations

import copy
import json
import re

import pytest
from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (reviewed investor harness fixture)


def _post(env, record, agreement):
    from tests.test_investor_f4_workspace import page
    html = page(env, record).text
    return env.client.post("/v2/workbook/investor/agreement", data=dict(
        project=record.project_code, action="save",
        content_hash=re.search(r'name="content_hash" value="([^"]*)"', html).group(1),
        csrf_token=re.search(r'name="csrf_token" value="([^"]*)"', html).group(1),
        agreement=agreement), headers={"HX-Request": "true"})


def _state(env, record):
    from tests.test_investor_f4_workspace import page
    html = page(env, record).text
    return re.search(r'name="content_hash" value="([^"]*)"', html).group(1)


def _mutations():
    def ownership(d):
        d["investors"][0]["ownership_fraction"] = 0.9 * d["investors"][0]["ownership_fraction"]
    def dup_investor(d):
        d["investors"].append(copy.deepcopy(d["investors"][0]))
    def unknown_investor(d):
        d["contributions"][0]["investor_id"] = "NOT-IN-AGREEMENT"
    def schema(d):
        d["schema_version"] = 2
    def extra_field(d):
        d["unexpected"] = 1
    def overcommit(d):
        d["contributions"][0]["amount_keur"] = d["investors"][0]["commitment_keur"] * 10 + 1
    def shl(d):
        d["investors"][0]["investment_class"] = "SHAREHOLDER_LOAN"
    return [
        ("ownership", ownership, "Legal equity ownership must sum to one"),
        ("duplicate", dup_investor, "Duplicate F4 investor identity"),
        ("unknown_investor", unknown_investor, "Contribution investor is not in agreement"),
        ("schema", schema, "Unsupported F4 agreement schema"),
        ("extra_field", extra_field, "F4 agreement has missing or unsupported fields"),
        ("overcommit", overcommit, "Paid-in contributions exceed investor commitment"),
        ("shl", shl, "Only common equity is supported; no SHL lender allocation"),
    ]


@pytest.mark.parametrize("name,mutate,message", _mutations(), ids=[m[0] for m in _mutations()])
def test_authored_domain_refusals_are_422_with_stable_text_and_persist_nothing(env, name, mutate, message):
    from tests.test_investor_f4_workspace import document
    record = env.create()
    before = _state(env, record)
    doc = document()
    mutate(doc)
    r = _post(env, record, json.dumps(doc))
    assert r.status_code == 422, (r.status_code, r.text[:300])
    assert r.json() == {"error": message}
    assert "Traceback" not in r.text and "INTERNAL_ERROR" not in r.text
    assert _state(env, record) == before, "a refused save must not change the working inputs"


def test_ownership_refusal_after_a_valid_save_keeps_the_saved_agreement(env):
    from tests.test_investor_f4_workspace import document, save
    record = env.create()
    assert save(env, record, document()).status_code == 200
    saved = _state(env, record)
    doc = document()
    doc["investors"][0]["ownership_fraction"] = 0.5 * doc["investors"][0]["ownership_fraction"]
    r = _post(env, record, json.dumps(doc))
    assert r.status_code == 422 and r.json() == {"error": "Legal equity ownership must sum to one"}
    assert _state(env, record) == saved


def test_parse_terms_types_authored_refusals_and_never_echoes_library_text(monkeypatch):
    from app.model_v2 import investor_f4 as f4
    from tests.test_investor_f4_workspace import document
    doc = document()
    doc["investors"][0]["ownership_fraction"] = 0.25
    with pytest.raises(f4.InvestorAgreementInputError) as exc:
        f4.parse_terms(json.dumps(doc))
    assert str(exc.value) == "Legal equity ownership must sum to one"
    assert isinstance(exc.value, ValueError)  # internal ``except ValueError`` callers keep working

    def library_fault(value, required):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "private library detail")

    monkeypatch.setattr(f4, "_keys", library_fault)
    with pytest.raises(f4.InvestorAgreementInputError) as exc:
        f4.parse_terms(json.dumps(document()))
    assert str(exc.value) == "F4 agreement payload is invalid"
    assert "private library detail" not in str(exc.value)


def test_parse_terms_does_not_convert_non_value_errors(monkeypatch):
    from app.model_v2 import investor_f4 as f4
    from tests.test_investor_f4_workspace import document

    def bug(value, required):
        raise TypeError("internal contract violation")

    monkeypatch.setattr(f4, "_keys", bug)
    with pytest.raises(TypeError):
        f4.parse_terms(json.dumps(document()))


def test_a_valid_agreement_still_parses_and_saves(env):
    from app.model_v2 import investor_f4 as f4
    from tests.test_investor_f4_workspace import document, save
    assert f4.parse_terms(json.dumps(document())) is not None
    assert f4.parse_terms("") is None and f4.parse_terms(None) is None
    record = env.create()
    assert save(env, record, document()).status_code == 200


@pytest.mark.parametrize("payload_kind", ["int_digit_limit", "deep_nesting", "duplicate_key"])
def test_decoder_level_failures_are_generic_422_text_never_interpreter_text(payload_kind):
    """Independent review finding: json.loads raises a PLAIN ValueError for an integer literal over the
    interpreter's digit limit, and RecursionError for pathological nesting; neither text may reach a client."""
    from app.model_v2 import investor_f4 as f4
    raw = {"int_digit_limit": '{"schema_version": 1' + "0" * 5000 + "}",
           "deep_nesting": "[" * 200000 + "]" * 200000,
           "duplicate_key": '{"a": 1, "a": 2}'}[payload_kind]
    with pytest.raises(f4.InvestorAgreementInputError) as exc:
        f4.parse_terms(raw)
    text = str(exc.value)
    expected = ("F4 duplicate JSON keys are not permitted" if payload_kind == "duplicate_key"
                else "F4 agreement payload is not valid JSON")
    assert text == expected
    for leak in ("digits", "set_int_max_str_digits", "recursion", "maximum"):
        assert leak not in text.lower()


def test_digit_limit_payload_over_http_is_a_generic_422(env):
    record = env.create()
    before = _state(env, record)
    r = _post(env, record, '{"schema_version": 1' + "0" * 5000 + "}")
    assert r.status_code == 422 and r.json() == {"error": "F4 agreement payload is not valid JSON"}
    assert "digits" not in r.text
    assert _state(env, record) == before


def test_arithmetic_overflow_on_absurd_amounts_is_a_generic_refusal():
    from app.model_v2 import investor_f4 as f4
    from tests.test_investor_f4_workspace import document
    doc = document()
    for inv in doc["investors"]:
        inv["commitment_keur"] = 1.7e308
    for c in doc["contributions"]:
        c["amount_keur"] = 1.7e308
    doc["contributions"] = doc["contributions"] * 3
    try:
        f4.parse_terms(json.dumps(doc))
    except f4.InvestorAgreementInputError as exc:
        assert "overflow" not in str(exc).lower() and "fsum" not in str(exc)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"non-typed refusal escaped parse_terms: {type(exc).__name__}")
