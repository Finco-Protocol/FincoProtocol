"""Small, explicit local source/tamper proof; not automatically collected."""
import json
from pathlib import Path

from tests import on_bess01_scope as S


def test_exact_local_source_ancestry_modes_and_registration():
    from tests.fin_v2_cohorts import COHORT_MODULES
    assert S.__name__ in COHORT_MODULES
    assert S.exact_blobs_ok()
    assert not S.exact_blobs_ok(ref=S.BASE)
    assert S.protected_blobs() == {}
    assert not S.allowed_path('financial_engine/inputs.py')
    assert not S.allowed_path('app/v2/bess_setup_router.py.bak')


def test_one_unsigned_byte_in_every_owned_source_is_refused():
    for path in sorted(S.OWNED_PATHS):
        target = S.ROOT / path
        original = target.read_bytes()
        try:
            target.write_bytes(original + b'\n')
            assert not S.exact_blobs_ok(), path
        finally:
            target.write_bytes(original)
    assert S.exact_blobs_ok()


def test_forged_pin_base_tree_schema_and_extra_path_fail_closed():
    target = S.ROOT / S.MANIFEST
    original = target.read_bytes()
    for key in ('base', 'base_tree', 'schema_version', 'source_blobs', 'base_blobs'):
        try:
            data = json.loads(original)
            if key in ('source_blobs', 'base_blobs'):
                data[key][next(iter(data[key]))] = 'f' * 40
            else:
                data[key] = 'f' * 40
            target.write_text(json.dumps(data))
            assert not S.exact_blobs_ok(), key
        finally:
            target.write_bytes(original)
    unknown = S.ROOT / 'app/v2/on_bess01_unsigned.py'
    try:
        unknown.write_text('unsigned = True\n')
        assert not S.exact_blobs_ok()
    finally:
        unknown.unlink()
    assert S.exact_blobs_ok()


def test_foreign_modes_and_cross_path_pins_fail_closed():
    target = S.ROOT / 'app/v2/bess_setup_router.py'
    mode = target.stat().st_mode
    try:
        target.chmod(0o755)
        assert not S.exact_blobs_ok()
    finally:
        target.chmod(mode)
    pins = S.manifest()['source_blobs']
    assert not S.supersedes('static/react/finco-react.js', pins['static/react/finco-react.css'])
