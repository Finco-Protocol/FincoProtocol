"""Independent strict successor negatives; no activation/Financial Owner assertion."""
import pytest
from tests import model_mutation_security_successor as S
from tests import rc_sec_csrf_successor as historical

SOURCES={p:(S.ROOT/p).read_text(encoding="utf-8") for p in S.BLOBS}

def test_exact_implementation_source_and_immutable_ancestry():
    assert S.violations(SOURCES)==[]
    assert S.current_mutation_successor_valid()
    assert historical.current_rc_sec_csrf_successor_valid()

@pytest.mark.parametrize("path",list(S.BLOBS))
def test_any_even_nonsemantic_source_drift_requires_new_review(path):
    changed=dict(SOURCES);changed[path]+="\n"
    assert S.violations(changed)

@pytest.mark.parametrize("handler,operation",list(S.ROUTES["app/v2/router.py"].items()))
def test_wrong_operation_or_removed_refusal_fails_without_byte_pins(handler,operation):
    source=SOURCES["app/v2/router.py"]
    # Replace the constant at the unique validator site, not an issuance site.
    needle='(await request.form()).get("csrf_token"), "'+operation+'"'
    assert needle in source
    changed=dict(SOURCES);changed["app/v2/router.py"]=source.replace(needle,'(await request.form()).get("csrf_token"), "wrong-operation"',1)
    assert S.violations(changed,check_pin=False)

def test_missing_history_fails_closed(tmp_path):
    for path,text in SOURCES.items():
        target=tmp_path/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding="utf-8")
    assert not S.current_mutation_successor_valid(repo=tmp_path)
