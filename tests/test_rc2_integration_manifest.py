"""RC-2 integration manifest: exact ancestry, exact reviewed blobs, router delta and CSRF inventory.

This is an EXACT-CONTENT PROPOSAL awaiting independent (ChatGPT) review - it is not an approval. It adds no
wildcard, no generic allow-list and no descendant rule: any byte change to a listed file, any further router
function change, any new CSRF call site or a different source head fails until a reviewer re-authorises the
new exact content. Historical RC-1 authorities stay enforced by tests/test_trust_readiness_registry.py.
"""
import ast
import copy
import hashlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RC2_BASE_MAIN = "5058c6b4935168241d6923676cb32955cb903185"
RC2_SOURCE_HEADS = (                       # merge order; each the second parent of a normal two-parent merge
    ("275", "73f698705ec5d72af820974873d9be202cd57f7d"),
    ("274", "0fa0ac5e268a37decbae6bc252487aba3e6e31c9"),
    ("277", "1599aa5eb4e82463157fbae430fa227ac71bdead"),
    ("276", "6c704f4e799a9dc1a10eb4f10d4e6b9a14f0ea2f"),
)
RC2_EXACT_BLOBS = {
    "app/api/project_runner.py": "5bc8982875f87d4ee61c6e7740293d52d9acaf2f",
    "app/api/v1/crypto_router.py": "bf168e8f67c54d6cfc674c05d29af15ce028b3b7",
    "app/crypto_terminal/deepstate_composition.py": "eb3f3c71bdb8faf8e69b39c6e01c737d7ef1be11",
    "app/crypto_terminal/tokenized_read.py": "eb2641782877afaf4f499bb0cd83b8151b42f27a",
    "app/export/institutional_workbook.py": "898fc56313038ea477493efaa45ea97502aa8c6a",
    "app/input_adapter.py": "831b5a354e177bbbcff56fabc26d5a7be061b2ae",
    "app/model_v2/developer_evidence.py": "46b8d017e012a679abfc1e48bf8867d029e9ff62",
    "app/persistence/_helpers.py": "e42ebf3d465314cb68775c2f5d3250c3b4f0df70",
    "app/services/sensitivity_matrix.py": "b0dadcda8d7da65562b6ab4562300c1d2da6ab64",
    "app/v2/developer_committed_projection.py": "de61df284830d572dd6cd58870af84d383fa3e47",
    "app/v2/developer_decision_router.py": "dd288a544567151369e629efc69b6eb1db117989",
    "app/v2/sensitivity_matrix_projection.py": "d6aa0d80d4222619053f07f25beaa429481f4ca0",
    "app/v2/sensitivity_matrix_router.py": "15c77bbc84b7443c4f716185ccf9161720d40d68",
    "app/workbook/developer_economics_config.py": "e9a3f1a2eff7821e54d192a4df2ee1332aa09d42",
    "app/workbook/developer_economics_service.py": "2de4d39d85e19b0ab291bb64972eb59d3079365a",
    "app/workbook/registry.py": "4f9c5192e33e4158f8b7e4d1a35115daa94df19d",
    "app/workbook/revenue_multistream.py": "ec3c8c8e12acc049233a57a2b559cbb6e18acca6",
    "domain/revenue/advanced_products.py": "d4ab263422aac5571e52bee4925fe36588e853cc",
    "domain/revenue/multistream_runtime.py": "83beda4eb296b02baf2ebd6659fec243ab196206",
    "finco_core/revenue/generation.py": "35670dc7b5ab4ce01177f9df817a4776c10569ab",
}
RC2_PROTECTED_FINANCIAL_CANDIDATE = frozenset({          # Revenue V3 - release-closed candidate (M2)
    "domain/revenue/multistream_runtime.py", "domain/revenue/advanced_products.py", "finco_core/revenue/generation.py",
})
RC2_ROUTER_MODIFIED_SHA256 = {
    "_build_revenue_contract_editor": "7f39d44027fd59842524e4210e0815c1381ede363d6f4b5acf008d63b1144d11",
    "v2_workbook_run": "19f1389b08e6915654c6adcbe587a28fad6da605cbefaacc68882e64a220439b",
}
RC2_ROUTER_NEW_MODULE_STATEMENTS = (      # M3 hook: the only module-level additions
    "from app.v2.sensitivity_matrix_router import router as sensitivity_matrix_router",
    "router.include_router(sensitivity_matrix_router)",
    "from app.v2.sensitivity_matrix_router import register_template_globals",
    "register_template_globals()",
)
RC2_CSRF_CALL_SITES = frozenset({
    "main_web.py", "app/v2/import_router.py", "app/v2/grid_router.py", "app/crypto_ui.py", "app/v2/router.py",
    "app/v2/investor_f4_router.py", "app/v2/developer_decision_router.py",
})
# Not an RC-2 free path: these are changed vs main but governed elsewhere or free by namespace.
RC2_GOVERNED_ELSEWHERE = frozenset({"app/trust_readiness/registry.py"})
RC2_FREE_PREFIXES = ("tests/", "docs/", "static/", "app/templates/")


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _router_parts(source):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    functions, others = {}, []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            functions[node.name] = "".join(lines[start - 1:node.end_lineno])
        else:
            others.append(ast.unparse(node))
    return functions, others


def rc2_violations(f) -> list[str]:
    """Pure fail-closed verifier over injected facts; [] means the manifest holds."""
    try:
        problems, previous = [], RC2_BASE_MAIN
        for pr, head in RC2_SOURCE_HEADS:
            merge = f["merges"].get(pr)
            if not f["ancestor"].get(pr) or merge is None:
                problems.append(f"#{pr}: reviewed head is not merged")
                continue
            sha, first, second = merge
            if second != head:
                problems.append(f"#{pr}: second parent is not the reviewed head")
            if first != previous:
                problems.append(f"#{pr}: first parent breaks the normal-merge chain")
            previous = sha
        for path, expected in RC2_EXACT_BLOBS.items():
            if f["blobs"].get(path) != expected:
                problems.append(f"{path}: not the exact reviewed blob")
        changed = {p for status, p in f["status"]}
        for status, path in f["status"]:
            if status not in ("A", "M"):
                problems.append(f"{path}: {status} is not permitted")
            elif not (path in RC2_EXACT_BLOBS or path == "app/v2/router.py" or path in RC2_GOVERNED_ELSEWHERE
                      or path.startswith(RC2_FREE_PREFIXES)):
                problems.append(f"{path}: not part of the reviewed RC-2 content")
        for path in sorted(set(RC2_EXACT_BLOBS) - changed):
            problems.append(f"{path}: reviewed change is missing")
        base_fn, base_other = _router_parts(f["router_base"])
        head_fn, head_other = _router_parts(f["router_head"])
        modified = {n for n in base_fn if n in head_fn and base_fn[n] != head_fn[n]}
        if modified != set(RC2_ROUTER_MODIFIED_SHA256) or set(head_fn) != set(base_fn):
            problems.append(f"router function delta is not the reviewed one: {sorted(modified)}")
        for name, expected in RC2_ROUTER_MODIFIED_SHA256.items():
            if name in head_fn and hashlib.sha256(head_fn[name].encode()).hexdigest() != expected:
                problems.append(f"router function {name} is not the reviewed text")
        added = [s for s in head_other if s not in base_other]
        if added != list(RC2_ROUTER_NEW_MODULE_STATEMENTS) or [s for s in base_other if s not in head_other]:
            problems.append(f"router module-level delta is not the reviewed M3 hook: {added}")
        if frozenset(f["call_sites"]) != RC2_CSRF_CALL_SITES:
            problems.append("CSRF validation call sites differ from the reviewed inventory")
        flags = f["flags"]
        if flags.get("revenue_v3") is not False or flags.get("junior") is not False:
            problems.append("a release-closed activation flag is not False")
        return problems
    except (KeyError, TypeError, ValueError, AttributeError, SyntaxError) as exc:
        return [f"facts incomplete or malformed: {exc!r}"]


def _collect():
    import re
    rows = [r.split() for r in _git("rev-list", "--merges", "--parents", f"{RC2_BASE_MAIN}..HEAD").splitlines()]
    merges, ancestor = {}, {}
    for pr, head in RC2_SOURCE_HEADS:
        found = [r for r in rows if len(r) == 3 and r[2] == head]
        merges[pr] = tuple(found[0]) if len(found) == 1 else None
        ancestor[pr] = subprocess.run(["git", "merge-base", "--is-ancestor", head, "HEAD"], cwd=ROOT).returncode == 0
    status = [tuple(l.split("\t", 1)) for l in _git("diff", "--name-status", "--no-renames", RC2_BASE_MAIN).splitlines()]
    sites = set()
    for path in list((ROOT / "app").rglob("*.py")) + [ROOT / "main_web.py"]:
        rel = path.relative_to(ROOT).as_posix()
        if not rel.startswith("app/trust_readiness/") and re.search(r"(?<!def )validate_csrf_token\(", path.read_text(encoding="utf-8", errors="ignore")):
            sites.add(rel)
    flag = lambda p, n: bool(re.search(rf"^{n}\s*=\s*True", (ROOT / p).read_text(encoding="utf-8"), re.M))  # noqa: E731
    return {
        "merges": merges, "ancestor": ancestor, "status": status, "call_sites": sites,
        "blobs": {p: _git("hash-object", p) for p in RC2_EXACT_BLOBS if (ROOT / p).exists()},
        "router_base": _git("show", f"{RC2_BASE_MAIN}:app/v2/router.py"),
        "router_head": (ROOT / "app/v2/router.py").read_text(encoding="utf-8"),
        "flags": {"revenue_v3": flag("domain/revenue/advanced_products.py", "ACTIVATION_ENABLED"),
                  "junior": flag("app/workbook/junior_debt_config.py", "ACTIVATION_ENABLED")},
    }


@pytest.fixture(scope="module")
def facts():
    try:
        merged = _collect()
    except subprocess.CalledProcessError:
        pytest.skip("RC-2 integration history is unavailable in this checkout")
    if not any(merged["ancestor"].values()):
        pytest.skip("not the RC-2 integration branch")
    return merged


def _flags_closed(f):
    f = copy.deepcopy(f)
    f["flags"] = {"revenue_v3": False, "junior": False}
    return f


def test_manifest_holds_for_the_integrated_candidate(facts):
    assert rc2_violations(_flags_closed(facts)) == []
    assert RC2_PROTECTED_FINANCIAL_CANDIDATE <= set(RC2_EXACT_BLOBS)


def test_every_mutation_is_rejected(facts):
    base = _flags_closed(facts)
    def bad(**changes):
        f = copy.deepcopy(base)
        f.update(changes)
        assert rc2_violations(f), changes
    for pr, head in RC2_SOURCE_HEADS:
        sha, first, second = base["merges"][pr]
        bad(merges={**base["merges"], pr: (sha, first, "2" * 40)})          # replaced source head
        bad(merges={**base["merges"], pr: (sha, "3" * 40, second)})         # wrong first parent
        bad(merges={**base["merges"], pr: None})
        bad(ancestor={**base["ancestor"], pr: False})
    for path in RC2_EXACT_BLOBS:                                              # incl. every financial-candidate blob
        bad(blobs={**base["blobs"], path: "1" * 40})
        bad(blobs={k: v for k, v in base["blobs"].items() if k != path})
    for status, path in (("A", "financial_engine/new.py"), ("M", "app/persistence/run_history_repository.py"),
                         ("A", "finco_radar/venues/new.py"), ("D", "tests/test_ci_acceptance.py"),
                         ("M", "app/auth.py"), ("A", "app/v2/unreviewed_save.py"), ("A", ".github/workflows/x.yml")):
        bad(status=[*base["status"], (status, path)])
    router = base["router_head"]
    bad(router_head=router + "\n\n@router.post('/rogue')\nasync def v2_rogue():\n    return None\n")
    bad(router_head=router.replace("validate_csrf_token(form.get(\"csrf_token\"))", "True", 1))
    bad(router_head=router.replace("register_template_globals()\n", "", 1))
    bad(router_head=router + "\nimport rogue_unreviewed_module\n")
    bad(call_sites=set(base["call_sites"]) | {"app/v2/sensitivity_matrix_router.py"})   # silently adding CSRF is also a change
    bad(call_sites=set(base["call_sites"]) - {"app/v2/developer_decision_router.py"})
    bad(flags={"revenue_v3": True, "junior": False})
    bad(flags={"revenue_v3": False, "junior": True})
    assert rc2_violations({})                                                 # missing facts never authorise


def test_missing_git_history_is_not_an_authorisation(monkeypatch):
    import sys
    def unavailable(*args):
        raise subprocess.CalledProcessError(1, ["git", *args])
    monkeypatch.setattr(sys.modules[__name__], "_git", unavailable)
    with pytest.raises(subprocess.CalledProcessError):
        _collect()
