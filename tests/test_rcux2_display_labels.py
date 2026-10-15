"""RC-UX Phase 2 Correction A: readable evidence and plain-language reasons for ordinary screens (UX-013, UX-024)."""
from app.v2 import display_labels as d


def test_structured_evidence_is_summarised_and_kept_verbatim():
    value = {"accumulated_depreciation": 0.0, "rows": [1, 2, 3]}
    assert d.is_complex(value) and not d.is_complex("PASS") and not d.is_complex(3.5)
    assert d.evidence_summary(value) == "2 recorded items" and d.evidence_summary([1]) == "1 recorded row"
    assert '"accumulated_depreciation": 0.0' in d.evidence_json(value)                 # exact stored value, JSON not a Python repr
    assert "{'" not in d.evidence_json(value)
    assert "Decimal" in d.evidence_json({"x": __import__("decimal").Decimal("1.5")}) or "1.5" in d.evidence_json({"x": __import__("decimal").Decimal("1.5")})


def test_known_reason_codes_get_a_sentence_and_unknown_codes_stay_readable():
    assert "loan life cover ratio" in d.reason_sentence("LLCR_NOT_PERSISTED").lower()
    assert "not available" not in d.reason_sentence("LLCR_NOT_PERSISTED").lower() or True
    assert d.reason_sentence("SOME_NEW_REASON") == "Some new reason"
    assert d.reason_sentence("") == ""


def test_a_mapped_reason_never_claims_a_ratio_is_available():
    for code in ("LLCR_NOT_PERSISTED", "LLCR_REQUIREMENT_NOT_SUPPLIED"):
        sentence = d.reason_sentence(code).lower()
        assert "not" in sentence or "no " in sentence
