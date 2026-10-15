"""UX-026: the review counters are computed from the import transaction's proposals only, with one definition of "exact"."""
from app.v2.import_router import EXACT_MAPPING_METHODS


def test_exact_covers_the_field_id_and_the_unique_exact_registry_label_but_not_ambiguous_or_fuzzy_matches():
    assert EXACT_MAPPING_METHODS == {"exact_field_id", "unique_exact_registry_label"}
    methods = ["exact_field_id", "unique_exact_registry_label", "ambiguous_label", "fuzzy_label", "unmapped"]
    assert sum(m in EXACT_MAPPING_METHODS for m in methods) == 2


def test_the_review_template_documents_what_exact_means():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "app/templates/v2/import_review.html").read_text(encoding="utf-8")
    assert "exact registry label" in html and "Exact mappings:" in html
