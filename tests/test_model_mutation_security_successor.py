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
        assert S.git_blob(SOURCES[path]) in {blob,S.D029_RUN_INTENT_SUCCESSORS.get(path)}   # current source = an admitted reviewed successor
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


# ── D-029 (PR #384): additive Run-intent successor layer ─────────────────────────────────────────────────────
D029_PATHS={"app/v2/router.py","static/react/finco-react.js"}


def _blob_source(blob):
    return subprocess.check_output(["git","cat-file","blob",blob],cwd=S.ROOT).decode("utf-8")


def test_d029_layer_is_exactly_two_additive_paths_and_keeps_every_original_and_finval_pin():
    assert set(S.D029_RUN_INTENT_SUCCESSORS)==D029_PATHS
    assert len(S.BLOBS)==112 and S.SOURCE_HEAD=="1800bf6092af650f18aa6ae70e9df221797090fd"
    for path,blob in S.D029_RUN_INTENT_SUCCESSORS.items():
        assert path in S.BLOBS and len(blob)==40
        assert blob not in (S.BLOBS[path],S.FINVAL_B2C1_SUCCESSORS[path])        # a NEW reviewed state, never a repin
        assert S.git_blob(SOURCES[path])==blob
    assert S.TOKEN_MODULE not in S.D029_RUN_INTENT_SUCCESSORS


@pytest.mark.parametrize("path",sorted(D029_PATHS))
def test_d029_one_byte_of_drift_in_a_successor_path_fails_closed(path):
    changed=dict(SOURCES);changed[path]+="\n"
    assert S.violations(changed)


@pytest.mark.parametrize("path",sorted(D029_PATHS))
def test_d029_original_and_finval_blobs_remain_individually_admitted(path):
    for blob in (S.BLOBS[path],S.FINVAL_B2C1_SUCCESSORS[path]):
        changed=dict(SOURCES);changed[path]=_blob_source(blob)
        assert not [e for e in S.violations(changed) if e.startswith(path+": unreviewed")]


def _decide_before_csrf(s):
    start=s.index("    # ── D-029: optional Run intent");end=s.index("    ws = get_workspace_state(user_id=workspace_owner",start)
    block=s[start:end];rest=s[:start]+s[end:]
    anchor="    # Authorization precedes CSRF so inaccessible"
    return rest.replace(anchor,block+anchor,1)


def test_d029_run_route_invariants_hold_and_each_negative_is_detected_without_byte_pins():
    source=SOURCES["app/v2/router.py"]
    assert S.d029_run_order_violations(source)==[]
    mutations={
        "decide before the CSRF gate":_decide_before_csrf,
        "reconcile by today's hash":lambda s:s.replace("workbook_version=workbook_version, content_hash=content_hash,\n            protected_reference","workbook_version=workbook_version, content_hash=current_identity.composite_hash,\n            protected_reference",1),
        "protected refusal dropped":lambda s:s.replace("protected_reference=is_protected_reference(project_record),","protected_reference=False,",1),
        "actor is the session user":lambda s:s.replace("actor_id=workspace_owner, project_id=project_record.project_id, run_intent_id","actor_id=user.user_id, project_id=project_record.project_id, run_intent_id",1),
        "commit without the reservation":lambda s:s.replace("            run_intent=_ri_reservation,\n",""),
        "second finalizer":lambda s:s.replace("    _ri_committed = _ri.committed_decision(","    _ri.finalize(_ri_decision)\n    _ri_committed = _ri.committed_decision(",1),
    }
    for name,mutate in mutations.items():
        changed=mutate(source)
        assert changed!=source,name
        assert S.d029_run_order_violations(changed),name
        broken=dict(SOURCES);broken["app/v2/router.py"]=changed
        assert S.violations(broken,check_pin=False),name


def test_d029_security_gates_are_unchanged_by_the_successor():
    source=SOURCES["app/v2/router.py"]
    for needle,replacement in (('(await request.form()).get("csrf_token"), "workbook-update"','(await request.form()).get("csrf_token"), "wrong-operation"'),
                               ("is_protected_reference(","is_protected_reference_removed(")):
        assert needle in source
        changed=dict(SOURCES);changed["app/v2/router.py"]=source.replace(needle,replacement,1 if "csrf" in needle else -1)
        assert S.violations(changed,check_pin=False)


def test_d029_register_is_an_additive_layer_in_the_validator_not_a_rewrite_of_history():
    import re
    original=subprocess.check_output(["git","show","6b779fb52f918ec079995924df3198269d09786e:tests/model_mutation_security_successor.py"],cwd=S.ROOT).decode("utf-8")
    current=(S.ROOT/"tests/model_mutation_security_successor.py").read_text(encoding="utf-8")
    pins=re.findall(r'^\s*"([^"]+)"\s*:\s*"([0-9a-f]{40})"',original,flags=re.M)
    assert len(pins)>=112
    for path,blob in pins:                                       # every historical pin line is still present verbatim
        assert '"%s": "%s"'%(path,blob) in current or '"%s":"%s"'%(path,blob) in current,(path,blob)
