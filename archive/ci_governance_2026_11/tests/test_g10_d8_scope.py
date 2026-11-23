"""G10/D8 cohort governance: the closed cohort is exact, registered, and fails closed on any drift."""
from __future__ import annotations

import pytest

import tests.fin_v2_cohorts as C
from tests import g10_d8_scope as G


def test_cohort_is_registered_and_exact():
    assert G.__name__ in C.COHORT_MODULES and G in C.cohorts()
    assert G.exact_blobs_ok() is True
    assert G.manifest()["schema_version"] == G.SCHEMA


def test_every_owned_path_is_admitted_and_no_stream_path_is():
    for path in sorted(G.OWNED_PATHS | {G.MANIFEST}):
        assert G.allowed_path(path), path
    for path in sorted(G.OTHER_STREAM_PATHS):
        assert not G.allowed_path(path), path
    assert not any(p.startswith(G.FORBIDDEN_PREFIXES) for p in G.OWNED_PATHS)


def test_one_altered_byte_in_any_owned_file_fails_closed(tmp_path):
    import shutil, subprocess
    for path in sorted(G.OWNED_PATHS - {'tests/g10_d8_scope.py', 'tests/fin_v2_cohorts.py'}):
        original = (G.ROOT / path).read_bytes()
        mutated = original + b"\n# drift\n" if path.endswith(('.py', '.tsx', '.md')) else original + b"\n"
        (G.ROOT / path).write_bytes(mutated)
        try:
            assert G.exact_blobs_ok() is False, path
            assert G.matches(path, original) is False, path
        finally:
            (G.ROOT / path).write_bytes(original)
        assert G.exact_blobs_ok() is True, path


def test_new_financial_or_stream_paths_are_never_admitted():
    for path in ('app/v2/save_all_commands.py', '.github/workflows/ci_v4_pr.yml', 'tests/ci_v4_scope.py',
                 'financial_engine/orchestrator.py', 'main_web.py'):
        assert not G.allowed_path(path), path
