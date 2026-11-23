"""Unreleased financial candidates stay inactive (replaces the retired blob-pinned candidate-authority guards).

Every module-level ``*_ENABLED`` activation/UI switch under app/ and domain/ must be a literal ``False`` unless it
is listed in ``RELEASED`` below. Turning a candidate on (or adding a new switch as ``True``) therefore requires
editing this file, which is a protected CI path (CODEOWNERS) and is visible in review. Values are read with the
AST, so a switch computed at import time (env var, function call) is rejected as well.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCAN = ("app", "domain")
SWITCH_SUFFIXES = ("ACTIVATION_ENABLED", "CANDIDATE_UI_ENABLED")

# path -> switch name for switches that an owner has released (literal True expected).
RELEASED = {
    ("app/workbook/multisenior_config.py", "ACTIVATION_ENABLED"),
}

# switches that existed when the retired guards were replaced: they must keep existing (a deletion would silently
# drop the control rather than close it).
KNOWN_CLOSED = {
    ("app/bess_commercial_candidate/contracts.py", "ACTIVATION_ENABLED"),
    ("app/services/m7_bess_authority.py", "ACTIVATION_ENABLED"),
    ("app/revenue_v4_candidate/contracts.py", "ACTIVATION_ENABLED"),
    ("app/model_v2/acquisition/economics.py", "ACTIVATION_ENABLED"),
    ("app/model_v2/costing_wf09b_candidate/contracts.py", "ACTIVATION_ENABLED"),
    ("app/model_v2/financing_wf07_candidate/contracts.py", "ACTIVATION_ENABLED"),
    ("app/model_v2/credit_wf06_candidate/__init__.py", "ACTIVATION_ENABLED"),
    ("app/model_v2/tax_wf10_candidate/contracts.py", "ACTIVATION_ENABLED"),
    ("app/generation_v2_candidate/contracts.py", "ACTIVATION_ENABLED"),
    ("app/v2/bess_candidate_router.py", "CANDIDATE_UI_ENABLED"),
    ("app/workbook/quarterly_frequency_config.py", "ACTIVATION_ENABLED"),
    ("app/workbook/junior_debt_config.py", "ACTIVATION_ENABLED"),
    ("app/workbook/bess_config.py", "ACTIVATION_ENABLED"),
    ("domain/revenue/advanced_products.py", "ACTIVATION_ENABLED"),
}


def switches(root: Path = ROOT) -> dict[tuple[str, str], ast.AST]:
    found = {}
    for top in SCAN:
        for path in sorted((root / top).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in tree.body:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
                for t in targets:
                    if isinstance(t, ast.Name) and t.id.endswith(SWITCH_SUFFIXES) and getattr(node, "value", None) is not None:
                        found[(path.relative_to(root).as_posix(), t.id)] = node.value
    return found


def problems(root: Path = ROOT) -> list[str]:
    found = switches(root)
    bad = []
    for key, value in sorted(found.items()):
        literal = value.value if isinstance(value, ast.Constant) and isinstance(value.value, bool) else None
        expected = key in RELEASED
        if literal is not expected:
            bad.append("%s:%s must be the literal %s" % (key[0], key[1], expected))
    for key in sorted((KNOWN_CLOSED | RELEASED) - set(found)):
        bad.append("%s:%s disappeared (close it explicitly instead of deleting the switch)" % key)
    return bad


def test_every_unreleased_financial_candidate_is_literally_inactive():
    assert problems() == []


@pytest.mark.parametrize("text", ["ACTIVATION_ENABLED = True\n", "import os\nACTIVATION_ENABLED = bool(os.environ.get('X'))\n"])
def test_an_opened_or_computed_switch_is_rejected(tmp_path, text):
    for rel, _ in KNOWN_CLOSED | RELEASED:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text((ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "app/workbook/bess_config.py").write_text(text, encoding="utf-8")
    assert any("bess_config.py:ACTIVATION_ENABLED" in p for p in problems(tmp_path))


def test_a_deleted_switch_is_rejected(tmp_path):
    for rel, _ in KNOWN_CLOSED | RELEASED:
        if rel != "app/workbook/junior_debt_config.py":
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text((ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")
    assert any("junior_debt_config.py:ACTIVATION_ENABLED disappeared" in p for p in problems(tmp_path))
