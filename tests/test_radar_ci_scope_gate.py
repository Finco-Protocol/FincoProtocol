"""End-to-end fixtures for PR-base Radar milestone scope governance."""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "radar_ci_scope_gate.py"
FORBIDDEN_MODEL_CORE_ROOTS = frozenset(
    {"financial_engine", "finco_core", "domain", "tax_reference_registry"}
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def test_r3_only_pr_still_triggers_both_regression_workflows() -> None:
    for name in ("radar_r5_signals_history.yml", "radar_r6_terminal.yml"):
        workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert '      - "finco_radar/**"' in workflow
        assert "- name: Focused" in workflow


def test_invalid_commit_identity_fails_closed(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(GATE), "r5", "--base", "not-a-sha", "--head", "not-a-sha"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2


def _extract_constant_import_target(call: ast.Call) -> str | None:
    """Return a literal string module name from positional arg 0 or keyword 'name'."""
    target_node: ast.AST | None = None
    if call.args:
        target_node = call.args[0]
    else:
        for keyword in call.keywords:
            if keyword.arg == "name":
                target_node = keyword.value
                break
    if isinstance(target_node, ast.Constant) and isinstance(target_node.value, str):
        return target_node.value
    return None


def _is_dynamic_import_call(
    call: ast.Call,
    importlib_aliases: set[str],
    import_module_aliases: set[str],
    builtins_aliases: set[str],
) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == "__import__" or func.id in import_module_aliases
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.attr == "import_module" and func.value.id in importlib_aliases:
            return True
        if func.attr == "__import__" and func.value.id in builtins_aliases:
            return True
    return False


def scan_forbidden_model_core_imports(
    package_root: Path,
    forbidden_roots: frozenset[str] = FORBIDDEN_MODEL_CORE_ROOTS,
) -> tuple[int, list[str]]:
    """Fail-closed static AST scan for forbidden Model-core imports under package_root.

    Checks ``import ...``, ``from ... import ...``, and constant-string calls to
    ``importlib.import_module(...)`` / ``__import__(...)``. Arbitrary runtime-computed
    dynamic import strings are an explicit limitation of static AST inspection.
    """
    if not package_root.is_dir():
        return 0, [f"{package_root}: package root directory does not exist"]

    py_files = sorted(package_root.rglob("*.py"))
    if not py_files:
        return 0, [f"{package_root}: no Python files found to scan"]

    violations: list[str] = []
    for path in py_files:
        rel = path.relative_to(package_root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(f"{rel}: unreadable file ({type(exc).__name__}: {exc})")
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            violations.append(f"{rel}:{exc.lineno}: syntax error ({exc.msg})")
            continue

        importlib_aliases: set[str] = {"importlib"}
        import_module_aliases: set[str] = set()
        builtins_aliases: set[str] = {"builtins"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", 1)[0]
                    if alias.name == "importlib":
                        importlib_aliases.add(alias.asname or "importlib")
                    elif alias.name == "builtins":
                        builtins_aliases.add(alias.asname or "builtins")
                    if root_name in forbidden_roots:
                        violations.append(f"{rel}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    root_name = node.module.split(".", 1)[0]
                    if node.module == "importlib":
                        for alias in node.names:
                            if alias.name == "import_module":
                                import_module_aliases.add(alias.asname or "import_module")
                    if root_name in forbidden_roots:
                        violations.append(f"{rel}:{node.lineno}: from {node.module} import ...")

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_dynamic_import_call(
                node, importlib_aliases, import_module_aliases, builtins_aliases,
            ):
                target = _extract_constant_import_target(node)
                if target and not target.startswith("."):
                    root_name = target.split(".", 1)[0]
                    if root_name in forbidden_roots:
                        violations.append(f"{rel}:{node.lineno}: dynamic import {target!r}")

    return len(py_files), violations


def _strip_yaml_scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value.split("#", 1)[0].strip()


def _extract_workflow_pr_paths_and_events(workflow_path: Path) -> tuple[set[str], list[str]]:
    """Targeted stdlib extractor for top-level ``on:`` events and ``on.pull_request.paths``."""
    lines = workflow_path.read_text(encoding="utf-8").splitlines()
    in_on = False
    on_indent: int | None = None
    events: set[str] = set()
    in_pr = False
    pr_indent: int | None = None
    in_paths = False
    paths_indent: int | None = None
    paths: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))

        if not in_on:
            if indent == 0 and stripped == "on:":
                in_on = True
            continue

        if indent == 0:
            break

        if on_indent is None:
            on_indent = indent

        if indent == on_indent and ":" in stripped:
            event_name = stripped.split(":", 1)[0].strip()
            events.add(event_name)
            in_pr = event_name == "pull_request"
            pr_indent = None
            in_paths = False
            paths_indent = None
            continue

        if in_pr:
            if pr_indent is None:
                pr_indent = indent
            if indent == pr_indent and ":" in stripped:
                key_name = stripped.split(":", 1)[0].strip()
                in_paths = key_name == "paths"
                paths_indent = None
                continue
            if in_paths:
                if indent <= pr_indent:
                    in_paths = False
                    continue
                if paths_indent is None:
                    paths_indent = indent
                if indent == paths_indent and stripped.startswith("- "):
                    paths.append(_strip_yaml_scalar(stripped[2:]))

    assert events, f"{workflow_path}: missing 'on:' events"
    assert paths, f"{workflow_path}: missing 'on.pull_request.paths' entries"
    return events, paths


def test_finco_radar_has_zero_model_core_imports() -> None:
    radar_root = ROOT / "finco_radar"
    scanned_count, violations = scan_forbidden_model_core_imports(radar_root)
    assert scanned_count > 0
    assert violations == [], f"Forbidden Model-core imports found in finco_radar: {violations}"


@pytest.mark.parametrize(
    ("case", "snippet", "expected_fragment"),
    [
        ("import_financial_engine", "import financial_engine.foo\n", "financial_engine.foo"),
        ("import_financial_engine_root", "import financial_engine\n", "financial_engine"),
        ("from_finco_core", "from finco_core.bar import X\n", "finco_core.bar"),
        ("from_domain", "from domain import x\n", "domain"),
        ("from_tax_reference_registry", "from tax_reference_registry.x import y\n", "tax_reference_registry.x"),
        (
            "importlib_import_module",
            "import importlib\nmod = importlib.import_module('financial_engine.foo')\n",
            "financial_engine.foo",
        ),
        (
            "from_importlib_import_module",
            "from importlib import import_module\nmod = import_module('finco_core.bar')\n",
            "finco_core.bar",
        ),
        (
            "aliased_import_module_kwarg",
            "from importlib import import_module as load_mod\nload_mod(name='domain.baz')\n",
            "domain.baz",
        ),
        (
            "dunder_import",
            "mod = __import__('tax_reference_registry.rules')\n",
            "tax_reference_registry.rules",
        ),
        (
            "builtins_dunder_import",
            "import builtins\nmod = builtins.__import__('financial_engine.calc')\n",
            "financial_engine.calc",
        ),
    ],
)
def test_ast_boundary_guard_rejects_forbidden_import_mutants(
    tmp_path: Path, case: str, snippet: str, expected_fragment: str,
) -> None:
    synthetic_pkg = tmp_path / "synthetic_radar"
    (synthetic_pkg / "sub").mkdir(parents=True)
    (synthetic_pkg / "sub" / "mutant.py").write_text(snippet, encoding="utf-8")

    scanned_count, violations = scan_forbidden_model_core_imports(synthetic_pkg)
    assert scanned_count == 1, f"Case {case}: expected 1 scanned file"
    assert len(violations) == 1, f"Case {case}: expected 1 violation, got {violations}"
    assert expected_fragment in violations[0], f"Case {case}: {violations}"


def test_ast_boundary_guard_fails_closed_on_syntax_unreadable_and_empty(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty_pkg"
    empty_dir.mkdir()
    scanned_empty, empty_violations = scan_forbidden_model_core_imports(empty_dir)
    assert scanned_empty == 0
    assert empty_violations and "no Python files found" in empty_violations[0]

    broken_pkg = tmp_path / "broken_pkg"
    broken_pkg.mkdir()
    (broken_pkg / "bad_syntax.py").write_text("def broken(:\n", encoding="utf-8")
    (broken_pkg / "bad_utf8.py").write_bytes(b"\xff\xfe\x00\x00")
    scanned_broken, broken_violations = scan_forbidden_model_core_imports(broken_pkg)
    assert scanned_broken == 2
    assert len(broken_violations) == 2
    assert any("syntax error" in v for v in broken_violations)
    assert any("unreadable file" in v for v in broken_violations)


def test_ast_boundary_guard_allows_clean_radar_module(tmp_path: Path) -> None:
    clean_pkg = tmp_path / "clean_radar"
    clean_pkg.mkdir()
    (clean_pkg / "clean.py").write_text(
        "from __future__ import annotations\n"
        "import json\n"
        "from pathlib import Path\n"
        "from finco_radar.signals import engine\n"
        "from . import helper\n",
        encoding="utf-8",
    )
    scanned_count, violations = scan_forbidden_model_core_imports(clean_pkg)
    assert scanned_count == 1
    assert violations == []


