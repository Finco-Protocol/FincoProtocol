"""Cold-process exact legacy comparison against an immutable Git base checkout.

No baseline is refreshed. The comparison retains every deterministic field.
Invoke with --base-checkout pointing at a detached authorized base worktree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

BASE_SHA = "2e199bc3fb8e7a5971e26d1a1a48e9875a63045d"
ROOT = Path(__file__).resolve().parents[1]
CODE = r'''
import json, sys, math
from dataclasses import asdict, replace
from app import project_factories
from app.services.production_financial_authority import run_clean_production
from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
from finco_core.inputs import project_inputs_to_dict, hash_inputs_for_cache
from app.api.project_runner import run_project
from app.services.run_certificate_service import build_certificate_payload, canonical_certificate_signing_bytes
from types import SimpleNamespace
from datetime import datetime, timezone
import hashlib
kind=sys.argv[1]
pi=getattr(project_factories, 'create_generic_'+kind+'_reference')()
run=run_clean_production(pi)
evidence=build_run_integrity_evidence(run)
payload={'inputs':project_inputs_to_dict(pi),'input_hash':hash_inputs_for_cache(pi),
         'run':asdict(run),'integrity_evidence':evidence,
         'integrity':run_integrity_checks(evidence).to_dict()}
project_type = {'solar':'Solar', 'wind':'Wind', 'data_center':'Data Center', 'ev_charging':'EV Charging'}[kind]
api = run_project(project_type, 'Base', project_inputs_override=pi)
payload['runtime_export_payload'] = api
# Identical immutable historical identity, not today's code-branch provenance.
stamp = datetime(2026, 10, 9, tzinfo=timezone.utc)
fixture_hash = hashlib.sha256(json.dumps(payload['inputs'],sort_keys=True,default=str).encode()).hexdigest()
ws = SimpleNamespace(any_run_committed=True, project_id='synthetic-legacy-'+kind,
    project_code='synthetic-legacy-'+kind, last_runtime_snapshot_id='synthetic-run-'+kind,
    last_runtime_composite_hash=fixture_hash, last_runtime_origin='v2_workbook_run',
    last_runtime_at=stamp, last_runtime_scenario_id=None, last_runtime_summary=api['kpis'],
    last_runtime_snapshot={'project_type':project_type},
    last_runtime_identity={'engine_version':'historical-engine', 'workbook_version':'historical-workbook',
        'composite_hash':fixture_hash, 'git_sha':'2e199bc3fb8e7a5971e26d1a1a48e9875a63045d',
        'git_branch':'main', 'scenario_name':'Base'})
payload['historical_certificate_bytes_sha256'] = hashlib.sha256(
    canonical_certificate_signing_bytes(build_certificate_payload(ws, issued_at=stamp))).hexdigest()
# Real writer, same historical provenance: compare every cell, formula and style.
# ZIP/container creation times are not financial evidence and are not compared.
from app.export.institutional_workbook import _build_export_bundle, export_institutional_workbook_from_bundle
from openpyxl import load_workbook
from io import BytesIO
bundle = _build_export_bundle('generic_'+kind+'_reference', project_inputs=pi)
time_keys = ('generated_at','export_generated_at','runtime_timestamp','runtime_generated_at')
for row in bundle.runtime_rows:
    for key in time_keys:
        row[key] = stamp.isoformat()
    for key in ('source_branch','branch_name'):
        row[key] = 'historical-main'
    row['commit_sha'] = '2e199bc3fb8e7a5971e26d1a1a48e9875a63045d'
bundle = replace(bundle, generated_at=stamp.isoformat(), runtime_timestamp=stamp.isoformat(),
    branch='historical-main', commit_sha='2e199bc3fb8e7a5971e26d1a1a48e9875a63045d')
wb = load_workbook(BytesIO(export_institutional_workbook_from_bundle(bundle)))
for row in wb['Export_Metadata']:
    if row[0].value == 'Export generated at':
        row[1].value = stamp.isoformat()  # documented nondeterministic export clock only
payload['institutional_export_cells'] = {
    sheet.title:[(cell.coordinate,cell.value,cell.number_format,str(cell._style))
                 for row in sheet for cell in row if cell.value is not None]
    for sheet in wb.worksheets}
def encode(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {'non_finite_float': repr(value)}
    if isinstance(value, dict):
        return {key:encode(item) for key,item in value.items()}
    if isinstance(value, (list,tuple)):
        return [encode(item) for item in value]
    return value
print('F3_EXACT_JSON='+json.dumps(encode(payload),sort_keys=True,default=str,allow_nan=False))
'''


def capture(checkout, kind):
    process = subprocess.run([sys.executable, "-c", CODE, kind], cwd=checkout,
        capture_output=True, text=True, encoding="utf-8", timeout=300)
    if process.returncode:
        raise RuntimeError(process.stderr)
    line = next(line for line in process.stdout.splitlines() if line.startswith("F3_EXACT_JSON="))
    return json.loads(line.split("=", 1)[1])


def differences(before, after, path=""):
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        return [p for key in sorted(before.keys() | after.keys()) for p in
            ([path + "/" + key] if key not in before or key not in after else differences(before[key], after[key], path + "/" + key))]
    if isinstance(before, list):
        if len(before) != len(after):
            return [path]
        return [p for index, pair in enumerate(zip(before, after)) for p in differences(*pair, path + f"/{index}")]
    return [] if before == after else [path]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/f3/legacy-equivalence.json")
    args = parser.parse_args()
    actual = subprocess.run(["git", "rev-parse", "HEAD"], cwd=args.base_checkout,
        check=True, capture_output=True, text=True).stdout.strip()
    if actual != BASE_SHA:
        raise RuntimeError("The baseline checkout is not the approved immutable base.")
    report = {"base_sha": BASE_SHA, "cold_process": True, "cases": []}
    for kind in ("solar", "wind", "data_center", "ev_charging"):
        before, after = capture(args.base_checkout, kind), capture(ROOT, kind)
        delta = differences(before, after)
        digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        report["cases"].append(dict(project=kind, differences=delta, base_digest=digest(before), candidate_digest=digest(after)))
        print(kind, "EXACT" if not delta else delta)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if any(case["differences"] for case in report["cases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
