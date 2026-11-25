"""Behavioural validator for the stale-draft Bankability refusal (moved verbatim from the retired
tests/on_bess01_reviewed_successors.py so the browser acceptance keeps its full state assertions)."""
import json

APPROVED_WARNINGS = frozenset((
    'The project changed after this view loaded. Nothing was saved — reload to see the current values.',
    'Saved configuration changed. Your draft is retained; review the refreshed values before saving.',
))


def bankability_refusal_valid(*, status, event, tone, warning, before, after, posts, local_day_count):
    """No selector-only acceptance: typed canonical refusal + all state invariants."""
    expected = {'field_id': 'debt.bankability.configuration', 'message':
        'Draft changed since page loaded, so your edit was not saved. Reload the page to see the current value, then enter it again.',
        'error_class': None, 'conflict': True}
    try:
        return (status == 409 and event == {'workbook-field-error': expected}
                and tone == 'conflict' and warning in APPROVED_WARNINGS
                and before == after and posts == [] and local_day_count == 'act_365'
                and json.loads(after[0]['bankability_config_json']) == {'version': 1, 'day_count': 'act_360'})
    except (ValueError, TypeError, KeyError, IndexError):
        return False
