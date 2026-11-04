"""PR-U2a (owner D14): the browser's Import % check must agree with the canonical contract on every case.

Independent oracle: the server's own ``app.capex_profiles.contract.build_weights`` (exact Fraction arithmetic) decides each synthetic case; the
browser module (``frontend/src/app/capex/profileImport.ts``) is bundled with esbuild and evaluated on the same inputs. A disagreement in either
direction fails: the client must never accept what the server refuses, nor block what the server accepts.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.capex_profiles.contract import ProfileError, ProfileShape, ProfileSpec, build_weights

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

CASES = [
    (["100"], 1), (["50", "50"], 2), (["50", "49.99"], 2), (["50", "50.01"], 2), (["33.33", "33.33", "33.34"], 3), (["33.33", "33.33", "33.33"], 3),
    (["33.33333333", "33.33333333", "33.33333334"], 3), (["8.333333333333333333"] * 12, 12), (["8.3333333"] * 12, 12), (["0", "100", "0"], 3),
    (["0"] * 23 + ["100"], 24), (["2.7777777777777777777778"] * 36, 36), (["50", "50"], 3), (["25"] * 4, 3), (["100.0000001"], 1), (["99.99999999"], 1),
    (["0"], 1), (["60", "40.0000000"], 2),
]


def _server_accepts(values, months):
    try:
        build_weights(ProfileSpec(item_key="C.01.01", shape=ProfileShape.EXPLICIT, explicit_percent=tuple(values)), months)
        return True
    except ProfileError:
        return False


def _client(cases):
    script = """
import { build } from 'esbuild';
import { mkdtemp, rm, symlink } from 'node:fs/promises'; import { tmpdir } from 'node:os'; import { join } from 'node:path'; import { pathToFileURL } from 'node:url';
const out = await mkdtemp(join(tmpdir(), 'u2-oracle-'));
await build({ entryPoints: [process.argv[1]], bundle: true, outfile: join(out, 'm.mjs'), format: 'esm', platform: 'node', packages: 'external' });
await symlink(process.argv[2], join(out, 'node_modules'));
const P = await import(pathToFileURL(join(out, 'm.mjs')));
const cases = JSON.parse(process.argv[3]);
console.log(JSON.stringify(cases.map(([v, n]) => P.checkExplicit(v, n).ok)));
await rm(out, { recursive: true, force: true });
"""
    proc = subprocess.run(["node", "--input-type=module", "-e", script, "--", str(FRONTEND / "src/app/capex/profileImport.ts"),
                           str(FRONTEND / "node_modules"), json.dumps(cases)], cwd=FRONTEND, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def node_ready():
    # The CI V3 Python workers do not install the frontend toolchain (no `npm ci`; workflows are not changed by this PR). The oracle runs wherever
    # frontend/node_modules exists (local, compile job); the acceptance matrix reports it as LOCAL_PASS, never as a CI result.
    if shutil.which("node") is None or not (FRONTEND / "node_modules" / "esbuild").exists():
        pytest.skip("frontend toolchain not installed in this environment (npm ci in frontend/)")


def test_client_check_agrees_with_the_canonical_contract_on_every_case(node_ready):
    client = _client(CASES)
    server = [_server_accepts(v, n) for v, n in CASES]
    assert client == server, [(c, a, b) for c, a, b in zip(CASES, client, server) if a != b]
    assert server.count(True) >= 8 and server.count(False) >= 6          # the cases cover both outcomes


def test_import_parser_unit_suite(node_ready):
    proc = subprocess.run(["node", "--test", str(FRONTEND / "src/app/capex/__tests__/profileImport.test.mjs")], cwd=ROOT,
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]
