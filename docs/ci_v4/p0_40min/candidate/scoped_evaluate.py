"""Opt-in per-OUTER-CALL experiment; never a per-test or session cache.

This has no import-time hook and does not replace any historical function. A
reviewed successor would place this boundary around the specific read-only
entry points measured below. Mutations must happen between outer evaluations.
"""
from tests import fin_v2_cohorts as C


def evaluate(function, *args, **kwargs):
    if C._CALL:
        raise RuntimeError("experiment requires a fresh outer call; nested mutable tests are unsupported")
    with C.call_scope():
        return function(*args, **kwargs)
