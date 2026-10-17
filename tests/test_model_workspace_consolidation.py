"""PR B characterization: presentation must preserve the existing authorities."""
from pathlib import Path
import pytest

from app.workbook.runtime_projection import aggregate_to_annual

ROOT = Path(__file__).resolve().parents[1]


def test_annual_authority_preserves_flows_stocks_and_missing():
    rows = [
        {"key": "flow", "label": "Flow", "values": [2, -3, None]},
        {"key": "stock", "label": "Stock", "is_stock": True, "values": [7, 5, None]},
        {"key": "missing", "label": "Missing", "values": [None, None, None]},
    ]
    annual, labels = aggregate_to_annual(rows, ["2026-01", "2026-02", "2027-01"])
    assert labels == ["2026", "2027"]
    assert [r["values"] for r in annual] == [[-1, None], [5, None], [None, None]]


def test_original_tab_and_oob_compatibility_targets_exist():
    page = (ROOT / "app/templates/v2/workbook.html").read_text(encoding="utf-8")
    for tab in ("overview", "project-setup", "inputs", "input-grid", "revenue", "capex", "opex",
                "investor", "debt", "tax", "fs", "returns", "outputs", "scenarios", "compare",
                "sensitivity", "goal-seek", "trust", "run-history"):
        assert f'id="tab-{tab}"' in page
        assert f'id="panel-{tab}"' in page
    legacy = (ROOT / "app/templates/v2/partials/sheet_financial_statements.html").read_text(encoding="utf-8")
    assert 'id="v2-sheet-financial-statements"' in legacy
    assert 'id="fs-runtime-bar"' in legacy


def test_manifest_is_complete_unique_and_shared_by_visible_navigation():
    from app.v2.workspace_destinations import DESTINATIONS, navigation_manifest
    from app.v2.workspace_shell_projection import workspace_nav_groups
    ids = [d.tab_id for d in DESTINATIONS]
    assert len(ids) == len(set(ids)) == 20
    assert {d.tab_id for d in DESTINATIONS if not d.alias_of} == {
        i.tab_id for g in workspace_nav_groups() for i in g.items}
    assert next(d for d in DESTINATIONS if d.tab_id == 'tab-fs').alias_of == 'tab-outputs'
    assert [a['label'] for a in navigation_manifest()['areas']] == ['Inputs', 'Financing', 'Results', 'Scenarios', 'Analysis', 'Model Checks', 'Trust']
    script = (ROOT / 'static/js/inputs_grid_v1.js').read_text(encoding='utf-8')
    assert 'manifest.destinations.forEach' in script
    assert "inputs:    ['tab-" not in script


def test_absent_scalar_never_becomes_an_editable_subtotal():
    from app.v2.input_grid_projection import _row_from_field
    from types import SimpleNamespace
    field = {'field_id': 'capex.C.production_units', 'unit': 'kEUR'}
    pis = SimpleNamespace(get=lambda _: None)
    for total in (3000, 30000):  # Solar and Wind C.01 presentation values
        editable = _row_from_field('C.01', 'Production Units', field, pis, None,
                                  editable=True, reason='', category_total=total)
        assert editable.value == '' and float(editable.category_value.replace(',', '')) == total
        reference = _row_from_field('C.01', 'Production Units', field, pis, None,
                                   editable=False, reason='Read-only', category_total=total)
        assert float(reference.value.replace(',', '')) == total
        assert not reference.editable and 'scalar override absent' in reference.reason
    zero = _row_from_field('C.01', 'Production Units', field, SimpleNamespace(get=lambda _: 0), None,
                           editable=True, reason='', category_total=30000)
    assert zero.value == '0' and zero.category_value == ''


def test_both_statement_consumers_use_one_renderer_and_one_annual_authority():
    legacy = (ROOT / 'app/templates/v2/partials/sheet_financial_statements.html').read_text(encoding='utf-8')
    outputs = (ROOT / 'app/templates/v2/partials/sheet_outputs.html').read_text(encoding='utf-8')
    for source in (legacy, outputs):
        assert 'partials/_statement_table.html' in source
    assert '<table' not in legacy and '<table' not in outputs
    assert 'statements_from_run(runtime_result' in (ROOT / 'app/v2/output_workspace_projection.py').read_text(encoding='utf-8')
    assert 'aggregate_to_annual(' not in (ROOT / 'app/v2/statement_presentation.py').read_text(encoding='utf-8')


def test_csp_filter_removed_without_security_policy_change():
    investor = (ROOT / 'app/templates/v2/partials/sheet_investor.html').read_text(encoding='utf-8')
    assert 'htmx:afterRequest[' not in investor
    script = (ROOT / 'static/js/workbook_v2.js').read_text(encoding='utf-8')
    assert "String(config.verb).toLowerCase() === 'post'" in script
    assert 'presentationGeneration' in script
    assert "source.addEventListener('htmx:beforeOnLoad', beforeLoad)" in script


@pytest.mark.parametrize('template,total', [('generic_solar_reference', 3000), ('generic_wind_reference', 30000)])
def test_real_protected_reference_category_value_and_permission(tmp_path, monkeypatch, template, total):
    from app.persistence import db
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import ensure_reference_models
    from app.v2 import router as presentation
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'prb-reference.db'))
    db.init_db()
    ensure_reference_models()
    record = get_reference_by_template_source(template)
    ws = get_workspace_state(record.user_id, record.project_id)
    pis = presentation._build_pis_with_composite_identity(ws, record, record.user_id)
    grid = presentation._build_input_grid_ctx(record, pis, ws, record.user_id, project_editable=False)['input_grid']
    row = next(category.rows[0] for section in grid.sections if section.section_id == 'capex'
               for category in section.categories if category.code == 'C.01')
    assert not row.editable
    assert float(row.value.replace(',', '')) == total
    assert 'scalar override absent' in row.reason or 'Sum of line items' in row.reason
    assert all(not row.editable for section in grid.sections for category in section.categories for row in category.rows)



# PR #247 Correction C: test the executable accepted browser evidence authority.
# Real checks live in tools.ci_browser_job, no copied YAML inline script.
def _workspace_ci_png(width):
    import struct
    import zlib

    def chunk(kind, data):
        crc = zlib.crc32(kind + data) & 0xffffffff
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    height = 100
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + b"\x20" * (width * 3)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def _workspace_ci_outputs_evidence(folder, *, drop=None, fail=None, exit_code=0):
    """PR #292: the outputs role carries BOTH acceptance modules' results, screenshots and exit records."""
    import hashlib
    import json
    from tools.ci_browser_job import OUTPUTS_ACCEPTANCE
    modules = {}
    for module, spec in OUTPUTS_ACCEPTANCE.items():
        out = folder / spec["folder"]
        out.mkdir(parents=True, exist_ok=True)
        for stale in out.glob("*.png"):          # the generic REQUIRED-pattern placeholder is replaced by the real, listed captures
            stale.unlink()
        shots = {}
        for index in range(max(spec.get("min_screenshots", 1), 1)):
            shot = out / f"shot-{index}.png"
            shot.write_bytes(_workspace_ci_png(1440))
            shots[shot.name] = hashlib.sha256(shot.read_bytes()).hexdigest()
        names = list(spec["required_checks"]) + [f"synthetic check {i}" for i in range(spec["min_total"])]
        checks = [{"check": name, "status": "FAIL" if fail == module and i == 0 else "PASS", "observed": "", "screenshot": ""}
                  for i, name in enumerate(names)]
        if drop == module:
            checks = [c for c in checks if c["check"] not in spec["required_checks"][:1]] if spec["required_checks"] else checks[:-1]
        passed = sum(c["status"] == "PASS" for c in checks)
        (out / "browser-results.json").write_text(json.dumps({
            "schema": spec["schema"], "checks": checks, "passed": passed, "total": len(checks), "all_pass": passed == len(checks),
            "screenshot_sha256": shots}), encoding="utf-8")
        modules[module] = {"exit_code": exit_code if fail == module else 0, "normal_exit": True, "out": f"artifacts/{spec['folder']}"}
    (folder / "outputs-role.json").write_text(json.dumps({"modules": modules}), encoding="utf-8")


def _workspace_ci_role_evidence(root, prefix, role, head, tree, case="pass"):
    import hashlib
    import json
    import xml.etree.ElementTree as ET
    from tools.ci_browser_job import REQUIRED, SELECTIONS, CONSOLIDATION_TEMPLATES

    folder = root / f"{prefix}-{role}"
    folder.mkdir(parents=True)
    if role == "consolidation":
        shots = folder / "workspace-consolidation"
        shots.mkdir()
        for template in CONSOLIDATION_TEMPLATES:
            for width, scheme in ((1440, "light"), (390, "dark")):
                (shots / f"prb-{template}-{width}-{scheme}.png").write_bytes(_workspace_ci_png(width))
        if case == "artifact-missing":
            (shots / f"prb-{CONSOLIDATION_TEMPLATES[0]}-1440-light.png").unlink()
        if case == "artifact-corrupt":
            target = shots / f"prb-{CONSOLIDATION_TEMPLATES[0]}-1440-light.png"
            image = bytearray(target.read_bytes())
            image[40] ^= 0x01  # Invalid IDAT CRC, while artifact manifest is regenerated correctly.
            target.write_bytes(image)
    else:
        for pattern in REQUIRED[role]:
            target = folder / pattern.removeprefix("artifacts/").replace("*", "synthetic")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.suffix == ".png":
                target.write_bytes(_workspace_ci_png(1440))
            else:
                target.write_text("{}", encoding="utf-8")

    process = {"head": head, "tree": tree, "label": role, "exit_code": 0,
               "normal_exit": True, "junit_failures": 0}
    if role == "outputs":
        _workspace_ci_outputs_evidence(folder)
    if role == "import":
        # PR #266: the import role runs BOTH suites; the V2 captures carry their real viewport widths.
        from tools.ci_browser_job import IMPORT_V2_SCREENSHOTS, IMPORT_V3_SCREENSHOTS
        shots = folder / "model-import-v2"
        shots.mkdir(exist_ok=True)
        for name, width in IMPORT_V2_SCREENSHOTS + IMPORT_V3_SCREENSHOTS:
            (shots / name).write_bytes(_workspace_ci_png(width))
    if role in SELECTIONS:
        if role == "consolidation":
            cases = [("test_model_workspace_consolidation_browser", f"test_synthetic_{index}") for index in range(17)]
        elif role == "import":
            from tools.ci_browser_job import IMPORT_V2_NODES, IMPORT_V3_NODES
            cases = [("test_model_ai_import_browser_c", "test_synthetic")] + [
                (node.split("::")[0].removeprefix("tests/").removesuffix(".py"), node.split("::", 1)[1])
                for node in IMPORT_V2_NODES + IMPORT_V3_NODES]
        else:
            cases = [("test_ci_synthetic", "test_synthetic")]
        nodes = [f"tests/{module}.py::{name}" for module, name in cases]
        names = [name for _, name in cases]
        inventory = {"head": head, "tree": tree, "pytest_exit": 0,
                     "collected": nodes[:-1] if role == "consolidation" and case == "collection-missing" else nodes,
                     "selected": nodes, "deselected": [], "collection_skips": [],
                     "collection_errors": [],
                     "outcomes": {node: {"status": "passed", "reason": ""} for node in nodes}}
        (folder / "inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
        executed = (cases[:-1] if role == "consolidation" and case == "execution-missing" else cases)
        suite = ET.Element("testsuite", tests=str(len(executed)), failures="0", errors="0", skipped="0")
        for index, (module, name) in enumerate(executed):
            element = ET.SubElement(suite, "testcase", classname=f"tests.{module}", name=name)
            if role == "consolidation" and index == 0 and case in ("skip", "failure", "error"):
                ET.SubElement(element, "skipped" if case == "skip" else case)
        ET.ElementTree(suite).write(folder / "results.xml", encoding="utf-8")
        process["junit_sha256"] = hashlib.sha256((folder / "results.xml").read_bytes()).hexdigest()
    (folder / "process.json").write_text(json.dumps(process), encoding="utf-8")
    manifest = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in folder.rglob("*") if p.is_file()}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def _workspace_ci_matrix(tmp_path, prefix, head, tree, case="pass"):
    from tools.ci_browser_job import REQUIRED
    for role in REQUIRED:
        _workspace_ci_role_evidence(tmp_path, prefix, role, head, tree,
                                    case=case if role == "consolidation" else "pass")
    return tmp_path / f"{prefix}-consolidation"


@pytest.mark.parametrize('case', ['pass', 'collection-missing', 'execution-missing', 'skip',
                                  'failure', 'error', 'artifact-missing', 'artifact-corrupt'])
def test_workspace_browser_ci_evidence_is_fail_closed(tmp_path, case):
    """The eight accepted scenarios execute the real validator and mandatory aggregate."""
    import json
    from tools.ci_acceptance import EvidenceError
    from tools.ci_browser_job import validate_consolidation, validate_browser_records, REQUIRED

    head, tree = "a" * 40, "b" * 40
    merge_head, merge_tree = "c" * 40, "d" * 40
    exact = _workspace_ci_matrix(tmp_path, "browser", head, tree, case)
    _workspace_ci_matrix(tmp_path, "merge-browser", merge_head, merge_tree)
    inventory = json.loads((exact / "inventory.json").read_text(encoding="utf-8"))
    process = json.loads((exact / "process.json").read_text(encoding="utf-8"))

    # Independent accepted synthetic-merge evidence remains valid for every case.
    merge_proof = validate_browser_records(tmp_path, merge_head, merge_tree, "success", "merge-browser")
    assert set(merge_proof["mandatory_roles"]) == set(REQUIRED)
    if case == "pass":
        validate_consolidation(exact, inventory, process)
        proof = validate_browser_records(tmp_path, head, tree, "success")
        assert set(proof["mandatory_roles"]) == set(REQUIRED)
        assert len(inventory["collected"]) == len(inventory["selected"]) == 17
        assert len(inventory["outcomes"]) == 17
    else:
        with pytest.raises(EvidenceError):
            validate_consolidation(exact, inventory, process)
        with pytest.raises(EvidenceError):
            validate_browser_records(tmp_path, head, tree, "success")


def test_workspace_browser_ci_parallel_source_and_validator_are_required():
    """CI V2: the consolidation role stays mandatory, isolated and validator-gated.

    (The #247 form asserted two six-role matrices; V2 runs the same six roles as isolated supervised
    processes on one runner and proves exact HEAD / synthetic-merge tree equality instead.)
    """
    import inspect
    from tools.ci_browser_job import SELECTIONS, REQUIRED, validate_browser_records

    workflow = (ROOT / ".github/workflows/protocol_ui_browser.yml").read_text(encoding="utf-8")
    assert "for role in protocol import grid q4 outputs consolidation; do" in workflow
    assert workflow.count("mandatory-browser-evidence:") == 1
    assert 'python -m tools.ci_browser_job "$role" --expected "$HEAD_SHA"' in workflow
    assert "python -m tools.ci_browser_job aggregate" in workflow and "--job-result success" in workflow
    assert "tools.ci_merge_tree_guard" in workflow
    assert "if-no-files-found: error" in workflow                           # mandatory evidence upload
    assert "name: model-workspace-consolidation-browser" in workflow         # screenshot alias preserved
    assert set(REQUIRED) == {"protocol", "import", "grid", "q4", "outputs", "consolidation"}
    assert SELECTIONS["consolidation"] == ["tests/test_model_workspace_consolidation_browser.py"]
    assert REQUIRED["consolidation"] == ["artifacts/workspace-consolidation/prb-*.png"]
    assert "validate_consolidation(folder, inventory, process)" in inspect.getsource(validate_browser_records)


@pytest.mark.parametrize("missing_role", ["protocol", "import", "grid", "q4", "outputs", "consolidation"])
def test_workspace_browser_ci_aggregate_rejects_any_omitted_mandatory_role(tmp_path, missing_role):
    """A successful job badge cannot hide an omitted role: the evidence directory of each role is required."""
    import shutil
    from tools.ci_acceptance import EvidenceError
    from tools.ci_browser_job import validate_browser_records, REQUIRED

    head, tree = "a" * 40, "b" * 40
    _workspace_ci_matrix(tmp_path, "browser", head, tree)
    assert set(validate_browser_records(tmp_path, head, tree, "success")["mandatory_roles"]) == set(REQUIRED)
    shutil.rmtree(tmp_path / f"browser-{missing_role}")
    with pytest.raises((EvidenceError, OSError)):
        validate_browser_records(tmp_path, head, tree, "success")


def test_workspace_browser_ci_aggregate_rejects_a_missing_screenshot_and_a_missing_junit(tmp_path):
    from tools.ci_acceptance import EvidenceError
    from tools.ci_browser_job import validate_browser_records

    head, tree = "a" * 40, "b" * 40
    folder = _workspace_ci_matrix(tmp_path, "browser", head, tree)
    junit = folder / "results.xml"
    saved = junit.read_bytes()
    junit.unlink()
    with pytest.raises((EvidenceError, OSError)):
        validate_browser_records(tmp_path, head, tree, "success")
    junit.write_bytes(saved)
    validate_browser_records(tmp_path, head, tree, "success")
    for png in folder.glob("**/prb-*.png"):
        png.unlink()
    with pytest.raises(EvidenceError):
        validate_browser_records(tmp_path, head, tree, "success")


@pytest.mark.parametrize("job_result", ["failure", "cancelled", "skipped", "", None])
def test_workspace_browser_ci_aggregate_rejects_absent_or_failed_jobs(tmp_path, job_result):
    from tools.ci_acceptance import EvidenceError
    from tools.ci_browser_job import validate_browser_records
    with pytest.raises(EvidenceError, match="matrix"):
        validate_browser_records(tmp_path, "a" * 40, "b" * 40, job_result)


@pytest.mark.parametrize("source", ["head", "tree"])
def test_workspace_browser_ci_aggregate_rejects_wrong_source(tmp_path, source):
    from tools.ci_acceptance import EvidenceError
    from tools.ci_browser_job import validate_browser_records
    head, tree = "a" * 40, "b" * 40
    _workspace_ci_matrix(tmp_path, "browser", head, tree)
    with pytest.raises(EvidenceError, match="source"):
        validate_browser_records(tmp_path, "x" * 40 if source == "head" else head,
                                 "y" * 40 if source == "tree" else tree, "success")


@pytest.mark.parametrize("field,value", [("exit_code", 1), ("normal_exit", False),
                                        ("junit_sha256", "0" * 64)])
def test_workspace_browser_ci_process_and_junit_proof_required(tmp_path, field, value):
    import hashlib
    import json
    from tools.ci_acceptance import EvidenceError
    from tools.ci_browser_job import validate_browser_records
    head, tree = "a" * 40, "b" * 40
    folder = _workspace_ci_matrix(tmp_path, "browser", head, tree)
    process = json.loads((folder / "process.json").read_text())
    process[field] = value
    (folder / "process.json").write_text(json.dumps(process))
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["process.json"] = hashlib.sha256((folder / "process.json").read_bytes()).hexdigest()
    (folder / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(EvidenceError):
        validate_browser_records(tmp_path, head, tree, "success")


# PR #266 Correction B: Import V2 Chromium evidence is mandatory inside the existing `import` role.
def _rewrite_workspace_manifest(folder):
    import hashlib
    import json
    manifest = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in folder.rglob("*") if p.is_file() and p.name != "manifest.json"}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _import_matrix(tmp_path, head="a" * 40, tree="b" * 40):
    from tools.ci_browser_job import REQUIRED
    for role in REQUIRED:
        _workspace_ci_role_evidence(tmp_path, "browser", role, head, tree)
    return tmp_path / "browser-import", head, tree


def test_import_role_runs_both_suites_and_accepts_complete_evidence(tmp_path):
    from tools.ci_browser_job import IMPORT_V2_NODES, validate_browser_records
    folder, head, tree = _import_matrix(tmp_path)
    assert len(IMPORT_V2_NODES) == 6 and "import" in validate_browser_records(tmp_path, head, tree, "success")["mandatory_roles"]


@pytest.mark.parametrize("mutation", [
    "v2-node-not-collected", "v2-node-skipped", "v2-node-not-in-junit", "v2-junit-failure",
    "screenshot-missing", "screenshot-wrong-width", "screenshot-corrupt", "c-suite-absent", "c-suite-failed",
])
def test_import_v2_evidence_is_fail_closed(tmp_path, mutation):
    import json
    import xml.etree.ElementTree as ET
    import hashlib
    from tools.ci_acceptance import EvidenceError
    from tools.ci_browser_job import IMPORT_V2_NODES, validate_browser_records
    folder, head, tree = _import_matrix(tmp_path)
    inventory = json.loads((folder / "inventory.json").read_text())
    victim = IMPORT_V2_NODES[0]
    if mutation == "v2-node-not-collected":
        inventory["collected"].remove(victim)
        inventory["selected"].remove(victim)
        inventory["outcomes"].pop(victim)
    elif mutation == "v2-node-skipped":
        inventory["outcomes"][victim] = {"status": "skipped", "reason": "playwright missing"}
    elif mutation == "c-suite-absent":
        gone = [n for n in inventory["selected"] if n.startswith("tests/test_model_ai_import_browser_c.py::")]
        for node in gone:
            inventory["selected"].remove(node); inventory["collected"].remove(node); inventory["outcomes"].pop(node)
    elif mutation == "c-suite-failed":
        node = next(n for n in inventory["selected"] if n.startswith("tests/test_model_ai_import_browser_c.py::"))
        inventory["outcomes"][node] = {"status": "failed", "reason": ""}
    (folder / "inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    process = json.loads((folder / "process.json").read_text())
    if mutation in ("v2-node-not-in-junit", "v2-junit-failure"):
        tree_xml = ET.parse(folder / "results.xml")
        suite = tree_xml.getroot()
        module = victim.split("::")[0].removesuffix(".py").replace("/", ".")
        for case in list(suite):
            if case.get("classname") == module and case.get("name") == victim.split("::", 1)[1]:
                if mutation == "v2-node-not-in-junit":
                    suite.remove(case)
                else:
                    ET.SubElement(case, "failure")
        tree_xml.write(folder / "results.xml", encoding="utf-8")
        process["junit_sha256"] = hashlib.sha256((folder / "results.xml").read_bytes()).hexdigest()
        (folder / "process.json").write_text(json.dumps(process), encoding="utf-8")
    shots = folder / "model-import-v2"
    if mutation == "screenshot-missing":
        (shots / "solar-04-review-mobile.png").unlink()
    elif mutation == "screenshot-wrong-width":
        (shots / "solar-04-review-mobile.png").write_bytes(_workspace_ci_png(1440))
    elif mutation == "screenshot-corrupt":
        target = shots / "wind-02-confirm.png"
        raw = bytearray(target.read_bytes()); raw[40] ^= 0x01; target.write_bytes(raw)
    _rewrite_workspace_manifest(folder)
    with pytest.raises(EvidenceError):
        validate_browser_records(tmp_path, head, tree, "success")


def test_import_role_without_any_v2_screenshot_directory_cannot_pass(tmp_path):
    import shutil
    from tools.ci_acceptance import EvidenceError
    from tools.ci_browser_job import validate_browser_records
    folder, head, tree = _import_matrix(tmp_path)
    shutil.rmtree(folder / "model-import-v2")
    _rewrite_workspace_manifest(folder)
    with pytest.raises(EvidenceError):
        validate_browser_records(tmp_path, head, tree, "success")


@pytest.mark.parametrize("mutation", [
    "v3-node-not-collected", "v3-node-skipped", "v3-node-failed", "v3-node-not-in-junit", "v3-junit-failure",
    "v3-screenshot-missing", "v3-screenshot-wrong-width", "v3-screenshot-corrupt",
])
def test_import_v3_evidence_is_fail_closed(tmp_path, mutation):
    """PR #296: a missing, skipped, failed or uncaptured Excel-migration browser node cannot be reported as success."""
    import json
    import xml.etree.ElementTree as ET
    import hashlib
    from tools.ci_acceptance import EvidenceError
    from tools.ci_browser_job import IMPORT_V3_NODES, validate_browser_records
    folder, head, tree = _import_matrix(tmp_path)
    victim = IMPORT_V3_NODES[0]
    inventory = json.loads((folder / "inventory.json").read_text())
    if mutation == "v3-node-not-collected":
        for key in ("collected", "selected"):
            inventory[key].remove(victim)
        inventory["outcomes"].pop(victim)
    elif mutation == "v3-node-skipped":
        inventory["outcomes"][victim] = {"status": "skipped", "reason": "playwright missing"}
    elif mutation == "v3-node-failed":
        inventory["outcomes"][victim] = {"status": "failed", "reason": ""}
    (folder / "inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    if mutation in ("v3-node-not-in-junit", "v3-junit-failure"):
        tree_xml = ET.parse(folder / "results.xml")
        suite = tree_xml.getroot()
        module = victim.split("::")[0].removesuffix(".py").replace("/", ".")
        for case in list(suite):
            if case.get("classname") == module and case.get("name") == victim.split("::", 1)[1]:
                if mutation == "v3-node-not-in-junit":
                    suite.remove(case)
                else:
                    ET.SubElement(case, "failure")
        tree_xml.write(folder / "results.xml", encoding="utf-8")
        process = json.loads((folder / "process.json").read_text())
        process["junit_sha256"] = hashlib.sha256((folder / "results.xml").read_bytes()).hexdigest()
        (folder / "process.json").write_text(json.dumps(process), encoding="utf-8")
    shots = folder / "model-import-v2"
    if mutation == "v3-screenshot-missing":
        (shots / "migration-06-reconciliation.png").unlink()
    elif mutation == "v3-screenshot-wrong-width":
        (shots / "migration-05-manifest-mobile.png").write_bytes(_workspace_ci_png(1440))
    elif mutation == "v3-screenshot-corrupt":
        target = shots / "migration-01-assess-desktop.png"
        raw = bytearray(target.read_bytes()); raw[40] ^= 0x01; target.write_bytes(raw)
    _rewrite_workspace_manifest(folder)
    with pytest.raises(EvidenceError):
        validate_browser_records(tmp_path, head, tree, "success")


def test_import_v3_nodes_match_the_real_browser_module():
    """The mandatory node list must name tests that really exist in the V3 module (a rename cannot silently drop coverage)."""
    import re
    from pathlib import Path
    from tools.ci_browser_job import IMPORT_V3_MODULE, IMPORT_V3_NODES
    source = Path(IMPORT_V3_MODULE).read_text(encoding="utf-8")
    defined = set(re.findall(r"^def (test_\w+)\(", source, re.M))
    assert {node.split("::", 1)[1] for node in IMPORT_V3_NODES} == defined
    for name in ("migration-01-assess-desktop.png", "migration-06-reconciliation.png", "migration-05-manifest-mobile.png"):
        assert name in source


def test_defusedxml_is_a_declared_runtime_dependency_in_every_install_manifest():
    """app/model_import/workbook_inspect.py imports defusedxml at runtime: every CI/deploy install path must provide it."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert re.search(r"^defusedxml>=0\.7\.1,<0\.8\s*$", (root / "requirements.txt").read_text(), re.M)
    assert re.search(r"^defusedxml==0\.7\.1\s*$", (root / "constraints.txt").read_text(), re.M)
    assert '"defusedxml"' in (root / "pyproject.toml").read_text()
    assert "defusedxml" not in (root / "requirements-ci-tests.txt").read_text()       # not a CI-only helper
    module = (root / "app/model_import/workbook_inspect.py").read_text()
    assert "from defusedxml import ElementTree as SafeET" in module and "from defusedxml.common import DefusedXmlException" in module
    assert "xml.etree" not in module and "lxml" not in module                          # no unrestricted parser fallback
    for workflow in ("ci_public_job.yml", "ci_browser_job.yml", "pr_compile_and_safety.yml", "model_ai_import_c0_gate.yml",
                     "dependency_security_audit.yml"):
        assert "-r requirements.txt" in (root / ".github/workflows" / workflow).read_text(), workflow
