"""Indivisible reviewed groups, current measurements and explicit fallback provenance."""
from copy import deepcopy

import pytest

from tests.ci_v3_synthetic_evidence import bundle, reseal
from tools.ci_v3_partition_plan import plan_partitions
from tools.ci_v3_runtime_weights import build_weights
from tools.ci_v3_schema import ContractError, seal


def test_group_is_scheduled_first_and_keeps_three_workers_nonempty():
    d = bundle(); names = sorted(d['inventory']['modules'])
    weights = seal({'schema': 1, 'kind': 'ci-v3-weights', 'source': d['inventory']['source'],
        'inventory_digest': d['inventory']['digest'], 'modules_ms': dict(zip(names, [9000, 8000, 6000, 7000]))})
    group = {'reviewed-session': names[:2]}
    p = plan_partitions(d['inventory'], d['policy'], weights, groups=group)
    assert p['module_workers'] == {names[0]: 'worker-0', names[1]: 'worker-0', names[2]: 'worker-2', names[3]: 'worker-1'}
    assert p == plan_partitions(d['inventory'], d['policy'], reseal({**weights, 'modules_ms': dict(reversed(list(weights['modules_ms'].items())))}), groups=group)
    assert set(p['module_workers']) == set(names)


@pytest.mark.parametrize('groups', [{'g': ['unknown.py']}, {'g': ['tests/test_alpha.py'] * 2},
    {'g': ['tests/test_alpha.py'], 'h': ['tests/test_alpha.py']}, {'g': []}])
def test_foreign_or_overlapping_groups_fail_closed(groups):
    d = bundle(); w = build_weights(d['inventory'], 'e' * 64)
    with pytest.raises(ContractError): plan_partitions(d['inventory'], d['policy'], w, groups=groups)


def measurement(d, **changes):
    return seal({'schema': 1, 'kind': 'ci-v3-duration-measurements', 'source': d['inventory']['source'],
        'inventory_digest': d['inventory']['digest'], 'environment_digest': 'e' * 64,
        'reference': 'original fixture process/JUnit hashes', 'modules_ms': {'tests/test_beta.py': 12345}, **changes})


def test_current_measurement_and_fallback_are_distinct_and_complete():
    d = bundle(); m = measurement(d)
    result = build_weights(d['inventory'], 'e' * 64, [m])
    assert result['modules_ms']['tests/test_beta.py'] == 12345
    assert result['modules_ms']['tests/test_alpha.py'] == 2000
    assert result['provenance']['tests/test_beta.py']['basis'] == 'measured'
    assert result['provenance']['tests/test_alpha.py']['basis'] == 'node-count-fallback'
    assert set(result['modules_ms']) == set(d['inventory']['modules'])


@pytest.mark.parametrize('field,value', [('source', {}), ('inventory_digest', 'f' * 64), ('environment_digest', 'f' * 64)])
def test_stale_measurement_is_preserved_as_excluded_and_uses_explicit_fallback(field, value):
    d = bundle(); result = build_weights(d['inventory'], 'e' * 64, [measurement(d, **{field: value})])
    assert result['modules_ms']['tests/test_beta.py'] == 1000 and len(result['excluded_measurements']) == 1
    assert all(p['basis'] == 'node-count-fallback' for p in result['provenance'].values())


def test_duplicate_or_tampered_measurements_rejected():
    d = bundle(); m = measurement(d)
    with pytest.raises(ContractError, match='duplicate'): build_weights(d['inventory'], 'e' * 64, [m, m])
    m['modules_ms']['tests/test_beta.py'] = 1
    with pytest.raises(ContractError, match='digest'): build_weights(d['inventory'], 'e' * 64, [m])
