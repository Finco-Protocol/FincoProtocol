"""V11 Stage 3 safety: default OFF, separate identity, loader/provenance fail-closed, admission declines.

* Default OFF: a Run without ``stage3_run`` never imports the Stage 3 module and the hook is canonical.
* Separate capability: own ABI 30001, own artifact / build manifest / sealed approved-source manifest; the
  V10 Stage 1/Stage 2 artifacts and approved manifests are untouched by Stage 3.
* Loader: every artifact, manifest, seal, build-ID, runtime or canonical-source deviation declines before
  any native call and never raises.
* Admission: every configuration outside the admitted space declines with its reason, and the canonical
  evaluation (which then runs) gives the identical result or raises the identical exception.
"""
from __future__ import annotations

import dataclasses
import json
import pickle
import shutil
import subprocess
import sys

import pytest

from financial_engine.native_v11 import config as s3config
from tests.native_v11_support import ARTIFACT, HERE, MANIFEST, S3, approved_fields, committed_manifest

ROOT = HERE.parents[1]


# ------------------------------------------------------------------ default OFF and separation

def test_default_config_is_off_and_validated():
    assert s3config.current_config() == s3config.Stage3Config() and s3config.Stage3Config().mode == "off"
    with pytest.raises(ValueError):
        s3config.Stage3Config(mode="on")
    with pytest.raises(ValueError):
        s3config.Stage3Config(mode="candidate", require_build_id=1)
    with s3config.stage3_run(S3):
        with pytest.raises(RuntimeError, match="IMMUTABLE"):
            with s3config.stage3_run(s3config.Stage3Config()):
                pass


def test_default_run_never_imports_stage3():
    code = ("import sys; sys.path[:0]=['.']\n"
            "from app.api.project_runner import run_project\n"
            "run_project('Solar', 'Base')\n"
            "print('stage3' if 'financial_engine.native_v11.stage3' in sys.modules else 'clean')\n")
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip().splitlines()[-1] == "clean"


def test_hook_is_canonical_when_off():
    import financial_engine.financing.project as proj
    assert proj._native_v11_stage3() is None
    with s3config.stage3_run(S3):
        assert proj._native_v11_stage3() is not None


def test_stage3_is_a_separate_versioned_capability():
    m = committed_manifest()
    assert m["abi_version"] == 30001 and m["artifact"] == ARTIFACT and m["variant"] == "release"
    assert m["approved_blobs_sha256"] == __import__("hashlib").sha256(
        (HERE / "approved_canonical_blobs_stage3.json").read_bytes()).hexdigest()
    v10 = json.loads((ROOT / "financial_engine" / "native_v10" / "fk_v10_manifest.json").read_text())
    v10s2 = json.loads((ROOT / "financial_engine" / "native_v10" / "fk_v10_stage2_manifest.json").read_text())
    assert m["build_id"] not in (v10["build_id"], v10s2["build_id"])
    assert v10["build_id"] == "ced5b63a77b5467ba312181cda5ea158af14aa894ab6ec67f3f00a5144fa8434"
    assert v10s2["artifact_sha256"] and v10["artifact_sha256"] == \
        "da763e0e8895359b81c6197b7252c349be9201c380aeee051dea60e5077e1307"
    tracked = subprocess.run(["git", "ls-files", "financial_engine/native_v11/"], cwd=str(ROOT), capture_output=True,
                             text=True, check=True).stdout.split()
    assert not [p for p in tracked if p.endswith(".so")]


def test_committed_stage3_approved_manifest_matches_the_working_tree():
    from financial_engine.native_v10 import provenance
    from financial_engine.native_v11 import stage3
    assert json.loads((HERE / "approved_canonical_blobs_stage3.json").read_text()) == provenance.build_manifest(
        stage3.STAGE3_REGION_FUNCTIONS, stage3.STAGE3_EXTRA_SOURCES)


def test_v10_approved_manifests_are_unchanged_by_stage3():
    from financial_engine.native_v10 import provenance
    assert json.loads(provenance.APPROVED_MANIFEST.read_text()) == provenance.build_manifest()
    assert json.loads(provenance.STAGE2_APPROVED_MANIFEST.read_text()) == provenance.build_manifest(
        provenance.STAGE2_REGION_FUNCTIONS, provenance.STAGE2_EXTRA_SOURCES)


# ------------------------------------------------------------------ loader

def _release_dir(tmp_path, name, with_binary=True):
    d = tmp_path / name
    d.mkdir()
    for f in (MANIFEST, "approved_canonical_blobs_stage3.json"):
        shutil.copy(HERE / f, d / f)
    if with_binary:
        shutil.copy(HERE / ARTIFACT, d / ARTIFACT)
    return d


def test_loader_declines_every_artifact_manifest_and_seal_deviation(tmp_path, stage3_artifacts):
    from financial_engine.native_v11 import stage3

    def verify(directory):
        return stage3._verify(directory, MANIFEST)

    assert verify(_release_dir(tmp_path, "ok"))[1] is None
    assert verify(_release_dir(tmp_path, "missing", with_binary=False))[1].startswith("LOADER3_ARTIFACT_UNAVAILABLE")
    corrupt = _release_dir(tmp_path, "corrupt")
    data = bytearray((corrupt / ARTIFACT).read_bytes())
    data[3000] ^= 0xFF
    (corrupt / ARTIFACT).write_bytes(bytes(data))
    assert verify(corrupt) == (None, "LOADER3_ARTIFACT_SHA256_MISMATCH")
    unsealed = _release_dir(tmp_path, "unsealed")
    approved = json.loads((unsealed / "approved_canonical_blobs_stage3.json").read_text())
    approved["blobs"]["financial_engine/orchestrator.py"] = "0" * 40
    (unsealed / "approved_canonical_blobs_stage3.json").write_text(json.dumps(approved))
    assert verify(unsealed) == (None, "LOADER3_APPROVED_MANIFEST_NOT_SEALED")
    for field, value, reason in (("abi_version", 10001, "LOADER3_ABI_VERSION_MANIFEST"),
                                 ("build_id", "0" * 64, "LOADER3_BUILD_ID")):
        d = _release_dir(tmp_path, field)
        manifest = json.loads((d / MANIFEST).read_text())
        manifest[field] = value
        (d / MANIFEST).write_text(json.dumps(manifest))
        assert verify(d) == (None, reason)
    # an unexpected loader error is a decline, never an exception, and is cached per directory
    stage3._reset_for_tests()
    assert stage3.get_stage3(tmp_path / "does-not-exist")[0] is None
    stage3._reset_for_tests()


def test_canonical_source_tamper_fails_authentication(tmp_path):
    from financial_engine.native_v10 import eligibility, provenance
    from financial_engine.native_v11 import stage3
    if eligibility.check_runtime():
        pytest.skip("source authentication is reached only on validated runtimes")
    for path in ("financial_engine/financing/project.py", "financial_engine/native_v11/stage3.py",
                 "financial_engine/tax/atad.py", "financial_engine/native_v11/kernel_v11_stage3.c"):
        m = json.loads((HERE / "approved_canonical_blobs_stage3.json").read_text())
        m["blobs"][path] = "0" * 40
        (tmp_path / "m.json").write_text(json.dumps(m))
        auth, reason = provenance.authenticate(tmp_path / "m.json", functions=stage3.STAGE3_REGION_FUNCTIONS,
                                               attributes=stage3.STAGE3_REGION_ATTRIBUTES,
                                               aliases=stage3.STAGE3_ALIASES,
                                               extra_sources=stage3.STAGE3_EXTRA_SOURCES)
        assert auth is None and reason == f"PROVENANCE_BLOB_MISMATCH:{path}"


@pytest.mark.parametrize("key", [("Linux", "x86_64", "cpython", (3, 10)), ("Windows", "AMD64", "cpython", (3, 12))])
def test_unvalidated_runtime_declines_at_the_loader(monkeypatch, key, stage3_artifacts):
    from financial_engine.native_v10 import eligibility
    from financial_engine.native_v11 import stage3
    monkeypatch.setattr(eligibility, "runtime_key", lambda: key)
    stage3._reset_for_tests()
    try:
        lib, reason = stage3.get_stage3()
        assert lib is None and reason.startswith("RUNTIME_NOT_VALIDATED")
    finally:
        stage3._reset_for_tests()


# ------------------------------------------------------------------ admission declines (model level)

@pytest.fixture(scope="module")
def model_inputs():
    from app.api.project_runner import run_project
    from app.services import production_financial_authority as pfa
    import financial_engine.financing.project as proj
    real, out = proj._senior_debt_model, {}

    def spy(model_input, *, shl_maturity_context=None):
        out.setdefault("shl" if model_input.shareholder_loan is not None else "plain", model_input)
        return real(model_input, shl_maturity_context=shl_maturity_context)

    proj._senior_debt_model = spy
    try:
        pfa._POLICY_RUN_CACHE.clear()
        run_project("Solar", "Base")
    finally:
        proj._senior_debt_model = real
        pfa._POLICY_RUN_CACHE.clear()
    return out


def _both(inputs, ctx=None, config=S3):
    from financial_engine.native_v11 import stage3
    from financial_engine.orchestrator import run_senior_debt_model
    from financial_engine.run_scope import engine_run_scope
    with engine_run_scope():
        try:
            ref = ("ok", pickle.dumps(run_senior_debt_model(inputs, shl_maturity_context=ctx)))
        except Exception as exc:  # noqa: BLE001
            ref = ("raise", f"{type(exc).__name__}: {exc}")
    with engine_run_scope(), s3config.stage3_run(config) as st:
        got = stage3.run_senior_debt_model(inputs, shl_maturity_context=ctx)
    return ref, got, st.as_dict()


def _tax(inputs, **policy):
    return dataclasses.replace(inputs, tax=dataclasses.replace(inputs.tax, policy=dataclasses.replace(inputs.tax.policy,
                                                                                                    **policy)))


def test_admitted_inputs_are_served_exactly(model_inputs, stage3_artifacts):
    for inputs in model_inputs.values():
        ref, got, st = _both(inputs)
        assert ref[0] == "ok" and got is not None and pickle.dumps(got) == ref[1], st
        assert st["native_models"] == 1 and not st["declines"]


def test_unsupported_configurations_decline(model_inputs, stage3_artifacts):
    from financial_engine.policies.tax import CashTaxTiming, TaxBasisPeriodisation
    from financial_engine.senior_debt.policy import SeniorDebtSizingMode
    shl, plain = model_inputs["shl"], model_inputs["plain"]
    cases = [
        (_tax(plain, cash_tax_timing=CashTaxTiming.SAME_PERIOD), "CASH_TAX_TIMING"),
        (_tax(shl, tax_basis_periodisation=TaxBasisPeriodisation.MODEL_YEAR_PAIRING), "TAX_PATH_MODEL_YEAR_PAIRING"),
        (dataclasses.replace(plain, senior_debt_policy=dataclasses.replace(
            plain.senior_debt_policy, sizing_mode=SeniorDebtSizingMode.GEARING_CAP, maximum_gearing=0.7)), "SIZING_MODE"),
        (dataclasses.replace(shl, debt_sizing_case=dataclasses.replace(
            shl.debt_sizing_case, tax_periodisation_mode_override="calendar_tax_year")), "BANK_TAX_PERIODISATION_OVERRIDE"),
    ]
    for inputs, reason in cases:
        ref, got, st = _both(inputs)
        assert got is None and st["declines"] == {reason: 1}, (reason, st)
    from financial_engine.shl.maturity_authority import ShlMaturityContext
    ref, got, st = _both(plain, ctx=ShlMaturityContext.provisional_pass())
    assert ref[0] == "raise" and got is None and st["declines"] == {"SHL_MATURITY_CONTEXT_WITHOUT_SHL": 1}


def test_canonical_rejections_decline_without_effect(model_inputs, stage3_artifacts):
    from financial_engine.shl.maturity_authority import ShlMaturityContext
    shl, plain = model_inputs["shl"], model_inputs["plain"]
    no_convergence = dataclasses.replace(plain, senior_debt_policy=dataclasses.replace(
        plain.senior_debt_policy, maximum_iterations=1))
    shl_no_convergence = dataclasses.replace(shl, shareholder_loan=dataclasses.replace(
        shl.shareholder_loan, maximum_iterations=1))
    for inputs, reason in ((no_convergence, "PLAIN_KERNEL_STATUS_2"), (shl_no_convergence, "SHL_KERNEL_STATUS_7")):
        ctx = ShlMaturityContext.provisional_pass() if inputs.shareholder_loan else None
        ref, got, st = _both(inputs, ctx=ctx)
        assert ref[0] == "raise" and got is None and st["declines"] == {reason: 1}, (ref, st)
        assert ctx is None or ctx.ledger.shortfalls == ()


def test_replaced_canonical_function_declines(model_inputs, stage3_artifacts, monkeypatch):
    import financial_engine.orchestrator as orch
    real = orch._merge_financing_tax_input
    monkeypatch.setattr(orch, "_merge_financing_tax_input", lambda *a, **k: real(*a, **k))
    ref, got, st = _both(model_inputs["shl"])
    assert got is None and st["declines"] == {"CANONICAL_REGION_REPLACED": 1}


def test_build_id_pin_mismatch_declines(model_inputs, stage3_artifacts):
    pinned = s3config.Stage3Config(mode="candidate", require_build_id="0" * 64)
    ref, got, st = _both(model_inputs["plain"], config=pinned)
    assert got is None and st["declines"] == {"BUILD_ID_PIN_MISMATCH": 1}
    exact = s3config.Stage3Config(mode="candidate", require_build_id=committed_manifest()["build_id"])
    ref, got, st = _both(model_inputs["plain"], config=exact)
    assert got is not None and pickle.dumps(got) == ref[1]


def test_reproducible_out_of_tree_build(tmp_path):
    from tests.native_v10_support import compiler_or_skip
    compiler_or_skip()
    outs = []
    for root in (tmp_path / "a", tmp_path / "b" / "deeper" / "checkout"):
        pkg = root / "financial_engine" / "native_v11"
        pkg.mkdir(parents=True)
        (root / "financial_engine" / "__init__.py").write_text("")
        for name in ("__init__.py", "build_stage3.py", "kernel_v11_stage3.c", "approved_canonical_blobs_stage3.json"):
            shutil.copy(HERE / name, pkg / name)
        out = root / "out"
        proc = subprocess.run([sys.executable, "-m", "financial_engine.native_v11.build_stage3", "--out", str(out)],
                              cwd=str(root), env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, proc.stderr[-2000:]
        outs.append(out)
    a, b = outs
    assert (a / ARTIFACT).read_bytes() == (b / ARTIFACT).read_bytes()
    ma, mb = (json.loads((x / MANIFEST).read_text()) for x in outs)
    assert approved_fields(ma) == approved_fields(mb)
    expected = committed_manifest()
    if ma["compiler"] != expected["compiler"]:
        pytest.skip("not the approved build toolchain")
    assert approved_fields(ma) == approved_fields(expected)
