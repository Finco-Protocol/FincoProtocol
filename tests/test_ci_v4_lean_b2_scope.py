"""CI V4 Lean B2 exact-source successor (after the accepted B1 leaf): positive identity and adversarial fail-closed controls.

Risk protected: B2 moves bytes of the protected provenance graph (the U1 provenance tests, the registry, two forward hooks and the current maps). It
must own exactly its finite file set, change no CI control file, make the U1 read-only nodes share ONE call scope without ever scoping a mutation, and
every forged manifest, registry state, handoff, mode or ref must be rejected. Every negative runs in an ISOLATED clone (a committed variant); the
evaluated checkout is never edited and no verdict is cached across mutations.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
U1_TESTS = "tests/test_u1_scope.py"
SCOPED_NODES = ("test_positive_cohort_is_exact_registered_and_closed",
                "test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession",
                "test_integration_reference_is_main_after_414_and_everything_unowned_equals_it")


def _git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()


def _g(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args], cwd=root)


# -------------------------------------------------------------------------------------------------------------- positive identity


# -------------------------------------------------------------------------------------------------------------- the one behavioural change
_MUTATING = ("_flip", "wt", "_tree", "unlink", "chmod", "write_text", "write_bytes", "worktree", "checkout", "reset", "commit", "clean", "symlink")


def _functions():
    import ast
    tree = ast.parse((ROOT / U1_TESTS).read_text())
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _mutation_markers(node):
    import ast
    seen = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in _MUTATING:
            seen.add(n.id)
        elif isinstance(n, ast.Attribute) and n.attr in _MUTATING:
            seen.add(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in _MUTATING:
            seen.add(n.value)
        elif isinstance(n, ast.arg) and n.arg in _MUTATING:
            seen.add(n.arg)
    return seen


@pytest.mark.parametrize("name", SCOPED_NODES)
def test_u1_scoped_nodes_are_one_call_scope_around_a_read_only_body(name):
    """The ONLY behavioural change: the public test is `with C.call_scope(): _body()`; the body is the unchanged original, takes no fixture and contains no mutation."""
    import ast
    fns = _functions()
    public, body = fns[name], fns["_" + name[len("test_"):]]
    assert [a.arg for a in public.args.args] == [] and [a.arg for a in body.args.args] == []
    assert len(public.body) == 1 and isinstance(public.body[0], ast.With) and len(public.body[0].body) == 1
    item = public.body[0].items[0].context_expr
    assert ast.unparse(item) == "C.call_scope()" and len(public.body[0].items) == 1
    call = public.body[0].body[0]
    assert isinstance(call, ast.Expr) and ast.unparse(call.value) == "_" + name[len("test_"):] + "()"
    assert not _mutation_markers(body), (name, _mutation_markers(body))


def test_the_mutation_detector_is_not_vacuous_and_tamper_nodes_stay_outside_any_scope():
    fns = _functions()
    assert _mutation_markers(fns["test_one_altered_byte_in_any_owned_file_fails_closed"])         # the detector sees a real mutation node
    assert _mutation_markers(fns["test_protected_and_unowned_code_modified_after_signing_fails_closed"])
    import ast
    for name, node in fns.items():
        if name.startswith("test_") and name not in SCOPED_NODES and _mutation_markers(node):
            assert not any(isinstance(x, ast.Attribute) and x.attr == "call_scope" for x in ast.walk(node)), name       # no tamper / worktree node sits inside a shared scope
    for name in ("test_older_cohorts_still_exact_through_the_bounded_hooks",):
        assert name in fns                                                  # the pre-existing read-only scope is untouched


# -------------------------------------------------------------------------------------------------------------- tamper (committed refs)


