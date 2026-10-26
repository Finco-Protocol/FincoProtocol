"""Independent strict successor negatives; no activation/Financial Owner assertion."""
import pytest
import ast
import subprocess
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


def test_browser_layer_preserves_all_original_pins_and_historical_contract():
    original=subprocess.check_output(["git","show","6b779fb52f918ec079995924df3198269d09786e:tests/model_mutation_security_successor.py"],cwd=S.ROOT).decode("utf-8")
    tree=ast.parse(original)
    old={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body
         if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ("SOURCE_HEAD","BLOBS")}
    assert S.SOURCE_HEAD==old["SOURCE_HEAD"]=="1800bf6092af650f18aa6ae70e9df221797090fd"
    assert S.BLOBS==old["BLOBS"] and len(S.BLOBS)==112
    historical_sources=dict(SOURCES)
    assert set(S._browser_layers())=={"tests/model_mutation_cookie_policy_acceptance.py","tests/model_react_wf2_browser_acceptance.py"}
    for path in S._browser_layers():
        historical_sources[path]=subprocess.check_output(
            ["git","show",S.SOURCE_HEAD+":"+path],cwd=S.ROOT).decode("utf-8")
    assert S.violations(historical_sources)==[]


@pytest.mark.parametrize("attribute",["BROWSER_CORRECTION_SOURCE_HEAD","BROWSER_CORRECTION_PARENT","BROWSER_CORRECTION_BLOB",
                                      "PPA_CORRECTION_SOURCE_HEAD","PPA_CORRECTION_PARENT","PPA_CORRECTION_BLOB"])
def test_browser_layer_wrong_source_parent_or_blob_fails_closed(monkeypatch,attribute):
    monkeypatch.setattr(S,attribute,"0"*40)
    assert not S.current_mutation_successor_valid()


def test_finval_b2c1_successor_is_exactly_six_additive_paths_and_keeps_every_original_pin():
    assert len(S.BLOBS)==112 and S.SOURCE_HEAD=="1800bf6092af650f18aa6ae70e9df221797090fd"
    assert set(S.FINVAL_B2C1_SUCCESSORS)=={"app/templates/v2/partials/sheet_opex.html","app/v2/react_workspace_router.py",
        "app/v2/router.py","frontend/src/app/WorkspaceView.tsx","frontend/src/app/types.ts","static/react/finco-react.js"}
    for path,blob in S.FINVAL_B2C1_SUCCESSORS.items():
        assert path in S.BLOBS and len(blob)==40 and blob!=S.BLOBS[path]
        assert S.git_blob(SOURCES[path])==blob                      # the current reviewed source is the admitted successor
    assert S.TOKEN_MODULE not in S.FINVAL_B2C1_SUCCESSORS

@pytest.mark.parametrize("path",["app/templates/v2/partials/sheet_opex.html","app/v2/react_workspace_router.py","app/v2/router.py",
    "frontend/src/app/WorkspaceView.tsx","frontend/src/app/types.ts","static/react/finco-react.js"])
def test_finval_b2c1_one_byte_of_drift_in_any_successor_path_fails_closed(path):
    changed=dict(SOURCES);changed[path]+="\n"
    assert S.violations(changed)

def test_finval_b2c1_historical_pins_still_validate_the_historical_sources():
    historical=dict(SOURCES)
    for path in S.FINVAL_B2C1_SUCCESSORS:
        historical[path]=subprocess.check_output(["git","show",S.SOURCE_HEAD+":"+path],cwd=S.ROOT).decode("utf-8")
    assert S.violations(historical)==[]                                # old pin values remain individually accepted

def test_finval_b2c1_unreviewed_seventh_path_and_token_module_drift_are_refused():
    for path in ("app/v2/grid_router.py","app/workbook/mutation_csrf.py"):
        changed=dict(SOURCES);changed[path]+="\n"
        assert S.violations(changed)

def test_finval_b2c1_successor_does_not_weaken_the_operation_bound_csrf_gate():
    source=SOURCES["app/v2/router.py"]
    needle='(await request.form()).get("csrf_token"), "workbook-update"'
    assert needle in source
    changed=dict(SOURCES);changed["app/v2/router.py"]=source.replace(needle,'(await request.form()).get("csrf_token"), "wrong-operation"',1)
    assert S.violations(changed)                       # the byte pin refuses it ...
    assert S.violations(changed,check_pin=False)       # ... and so does the structural gate, independent of any pin

def test_finval_b2c1_successor_does_not_weaken_the_protected_reference_guard():
    source=SOURCES["app/v2/router.py"]
    assert "is_protected_reference(" in source
    changed=dict(SOURCES);changed["app/v2/router.py"]=source.replace("is_protected_reference(","is_protected_reference_removed(")
    assert S.violations(changed,check_pin=False)
