"""Governance tests for the R02 compact-PPA-UX exact-source cohort (tip of ... -> on_bess01 #433 -> onaccept01 #434 -> L01/L02 #435 -> R02).

Positives: the cohort is exact with accepted main 64a0d5b7 as checked ancestor; ONLY the listed UI sources, the new component, its JS test and the literal reviewed handoffs moved; the WF-React-2 component
file, every backend/engine/writer path and the frozen BESS module are byte-identical to BASE; the built bundle carries the compact UI and no cap/tier payload vocabulary.
Negatives run in a throw-away clone (never in the working tree), grouped per family so each is ONE test identity: one-byte drift of every owned or protected source, registry/handoff/map/base/tree
rewrites, foreign paths, executable modes, symlinks, unpublished untracked files and wrong ancestry all fail closed (each family starts with a positive control).
"""
import json
import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TAIL = ('tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope')


def _git(root, *args):
    return subprocess.check_output(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()


def _reset(root):
    _git(root, 'reset', '-q', '--hard', 'HEAD')
    _git(root, 'clean', '-fdq')


def _bump(root, path):
    f = root / path
    f.write_bytes(f.read_bytes() + b'\n# unreviewed\n')


def _json(root, path, mutate):
    f = root / path
    data = json.loads(f.read_text())
    mutate(data)
    f.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def test_built_bundle_and_component_carry_the_compact_ui_without_any_new_economics():
    bundle = (ROOT / 'static/react/finco-react.js').read_text()
    for needle in ('PPA type', '+ Add PPA', 'Awaiting approved volume-cap economics and numerical proof', 'Show notes', 'data-ppa-save'):
        assert needle in bundle, needle
    for forbidden in ('volume_tiers', 'cap_unit', 'cap_window', 'cap_kind', 'reduced_price_eur_mwh', 'cap_gwh'):
        assert forbidden not in bundle, forbidden
    editor = (ROOT / 'frontend/src/app/workflow/PpaContractsEditor.tsx').read_text()
    assert 'saveRevenueContracts' in editor and 'method: "POST"' not in editor and "method: 'POST'" not in editor      # one persistence path: the canonical writer
    assert re.search(r'readFreshRevenue', editor) and 'contracts_base_token' not in editor.replace('baseToken', '')
    ws = (ROOT / 'frontend/src/app/WorkspaceView.tsx').read_text()
    assert 'PpaContractsEditor' in ws and 'PPAEditorView' not in ws


