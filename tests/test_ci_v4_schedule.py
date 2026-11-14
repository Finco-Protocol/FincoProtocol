"""CI V4 weighted scheduling: deterministic LPT, no duplicated / lost modules, worker-count choice."""
import json
from pathlib import Path

from tools import ci_v4_schedule as C

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "docs/ci_v4/ci-v4-policy.json").read_text())


def test_lpt_partitions_exactly_once_and_is_deterministic():
    w = {"a": 100.0, "b": 60.0, "c": 50.0, "d": 40.0, "e": 10.0}
    s1, l1 = C.lpt(list(w), w, 2)
    s2, _ = C.lpt(list(reversed(list(w))), w, 2)
    assert s1 == s2
    flat = [m for s in s1 for m in s]
    assert sorted(flat) == sorted(w) and len(flat) == len(set(flat))
    assert max(l1) == 140.0                      # LPT: {a,d} vs {b,c,e}
    assert max(l1) <= sum(w.values()) / 2 + max(w.values())


def test_indivisible_heavy_module_sets_the_floor():
    w = {"heavy": 1500.0, **{"m%d" % i: 10.0 for i in range(20)}}
    sim = C.simulate(list(w), w, "risk", POLICY["workers"]["risk"])
    assert all(r["max_shard_s"] >= 1500.0 for r in sim["rows"]) and sim["projected"] is True


def test_no_empty_workers_are_planned():
    w = {"a": 5.0, "b": 5.0}
    sim = C.simulate(["a", "b"], w, "fast", POLICY["workers"]["fast"])
    assert [r["workers"] for r in sim["rows"]] == [1, 2]
    p = C.plan_shards(["a", "b"], w, "full", POLICY)
    assert all(p["shards"]) and p["workers"] == len(p["shards"])


def test_small_fast_selection_uses_one_worker():
    w = {"a": 30.0, "b": 20.0, "c": 10.0}
    assert C.choose_workers(["a", "b", "c"], w, "fast", POLICY["workers"]["fast"]) == 1


def test_large_selection_scales_but_respects_the_tier_cap():
    w = {"m%03d" % i: 600.0 for i in range(40)}
    assert C.choose_workers(list(w), w, "risk", POLICY["workers"]["risk"]) == POLICY["workers"]["risk"]["max"] == 8
    assert C.choose_workers(list(w), w, "fast", POLICY["workers"]["fast"]) == POLICY["workers"]["fast"]["max"]


def test_unweighted_modules_are_flagged_projected():
    p = C.plan_shards(["tests/test_does_not_have_weight_xyz.py"], {}, "fast", POLICY)
    assert p["unweighted_modules"] == ["tests/test_does_not_have_weight_xyz.py"] and p["projected_weights"]


def test_worker_choice_continues_past_a_subthreshold_step():
    """Correction (2026-11-14): the LPT critical path is NOT monotonic in k - a sub-threshold step may precede a materially better k+1.

    With the risk threshold of 300 s: k=2 saves 800 s (accepted), k=3 saves only 100 s, and k=4 saves exactly 300 s more.
    The scan must reach k=4; stopping at the first sub-threshold step returned 2 and left 300 s of wall time on the table.
    """
    w = {"a": 500.0, "b": 400.0, "c": 400.0, "d": 400.0}
    for k, crit in ((1, 1700.0), (2, 900.0), (3, 800.0), (4, 500.0)):   # the deterministic LPT ladder
        assert max(C.lpt(list(w), w, k)[1]) == crit
    assert C.choose_workers(list(w), w, "risk", POLICY["workers"]["risk"]) == 4


def test_worker_choice_without_break_still_respects_the_threshold_and_cap():
    """No sub-threshold worker is ever taken: gains below the policy minimum never move ``best``, and the cap holds."""
    cfg = POLICY["workers"]["risk"]
    assert C.choose_workers(["a", "b"], {"a": 100.0, "b": 100.0}, "risk", cfg) == 1     # no k saves >= 300 s
    w = {"m%03d" % i: 600.0 for i in range(40)}                                          # every step saves ~600 s
    assert C.choose_workers(list(w), w, "risk", cfg) == cfg["max"] == 8
    w2 = {"heavy": 1500.0, **{"m%d" % i: 10.0 for i in range(20)}}                       # the indivisible floor pins every k
    assert C.choose_workers(list(w2), w2, "risk", cfg) == 1                              # even k=2 saves only 200 s < 300 s


def test_worker_choice_is_deterministic_and_covers_every_module_exactly_once():
    w = {"a": 500.0, "b": 400.0, "c": 400.0, "d": 400.0}
    k = C.choose_workers(list(w), w, "risk", POLICY["workers"]["risk"])
    shards, _ = C.lpt(list(reversed(list(w))), w, k)
    flat = [m for s in shards for m in s]
    assert sorted(flat) == sorted(w) and len(flat) == len(set(flat)) and all(shards)
