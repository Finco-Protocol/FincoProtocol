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


def _crit(w, k):
    return max(C.lpt(list(w), w, k)[1])


def _break_rule(w, cfg):
    """The accepted pre-correction rule (stop at the first sub-threshold step), kept here only as the reference the corrected scan is compared with."""
    best, best_crit = 1, _crit(w, 1)
    for k in range(2, min(int(cfg["max"]), len(w)) + 1):
        if best_crit - _crit(w, k) >= float(cfg["min_module_seconds_per_extra_worker"]):
            best, best_crit = k, _crit(w, k)
        else:
            break
    return best


def test_worker_choice_continues_past_a_subthreshold_step_when_every_added_worker_is_paid_for():
    """Correction (2026-11-14): the LPT critical path is NOT monotonic in k - a sub-threshold step may precede a materially better k+2.

    Risk threshold 300 s per extra worker. LPT ladder 3000, 1500, 1400, 800: k=2 saves 1500 (accepted), k=3 saves only 100 (refused), and k=4
    saves 700 over k=2 for TWO added workers (350 s each >= 300 s): accepted. The accepted pre-correction rule stopped at 2 and left 700 s on the table.
    """
    cfg = POLICY["workers"]["risk"]
    w = {"m0": 100.0, "m1": 800.0, "m2": 700.0, "m3": 700.0, "m4": 700.0}
    assert [_crit(w, k) for k in (1, 2, 3, 4)] == [3000.0, 1500.0, 1400.0, 800.0]
    assert _break_rule(w, cfg) == 2
    assert C.choose_workers(list(w), w, "risk", cfg) == 4


def test_one_threshold_never_pays_for_two_added_workers():
    """The policy buys a runner only for a saving of min_module_seconds_per_extra_worker EACH. LPT ladder 1700, 900, 800, 500: k=2 saves 800
    (accepted); k=4 would save only 400 for two added workers (200 s each < 300 s) and must be refused - accepting it overspends runners."""
    cfg = POLICY["workers"]["risk"]
    w = {"a": 500.0, "b": 400.0, "c": 400.0, "d": 400.0}
    assert [_crit(w, k) for k in (1, 2, 3, 4)] == [1700.0, 900.0, 800.0, 500.0]
    assert C.choose_workers(list(w), w, "risk", cfg) == 2 == _break_rule(w, cfg)


def test_worker_choice_still_respects_the_threshold_and_cap():
    """No worker is ever taken without its own saving: gains below the policy minimum never move ``best``, and the cap holds."""
    cfg = POLICY["workers"]["risk"]
    assert C.choose_workers(["a", "b"], {"a": 100.0, "b": 100.0}, "risk", cfg) == 1     # no k saves >= 300 s
    w = {"m%03d" % i: 600.0 for i in range(40)}                                          # every step saves ~600 s
    assert C.choose_workers(list(w), w, "risk", cfg) == cfg["max"] == 8
    w2 = {"heavy": 1500.0, **{"m%d" % i: 10.0 for i in range(20)}}                       # the indivisible floor pins every k
    assert C.choose_workers(list(w2), w2, "risk", cfg) == 1                              # even k=2 saves only 200 s < 300 s
    fast = POLICY["workers"]["fast"]                                                      # the FAST tier cap (2) is never exceeded either
    assert C.choose_workers(list(w), w, "fast", fast) == fast["max"] == 2


def test_worker_choice_is_deterministic_and_covers_every_module_exactly_once():
    w = {"a": 500.0, "b": 400.0, "c": 400.0, "d": 400.0}
    k = C.choose_workers(list(w), w, "risk", POLICY["workers"]["risk"])
    shards, _ = C.lpt(list(reversed(list(w))), w, k)
    flat = [m for s in shards for m in s]
    assert sorted(flat) == sorted(w) and len(flat) == len(set(flat)) and all(shards)
    assert C.choose_workers(list(reversed(list(w))), w, "risk", POLICY["workers"]["risk"]) == k      # input order never matters


def test_seeded_property_every_accepted_worker_is_priced_and_the_plan_is_a_partition():
    """500 seeded weight sets (stdlib RNG, fixed seed): the chosen count is within [1, min(cap, modules)], saves at least the threshold for each
    added worker over one worker, is never above the pre-correction count by more than the priced rule allows, and the plan is an exact partition."""
    import random
    rng = random.Random(448)
    for tier in ("fast", "risk", "full"):
        cfg = POLICY["workers"][tier]
        gain = float(cfg["min_module_seconds_per_extra_worker"])
        for _ in range(170):
            n = rng.randint(1, 14)
            w = {"m%02d" % i: float(rng.choice((20, 90, 150, 300, 450, 600, 900, 1500))) for i in range(n)}
            k = C.choose_workers(list(w), w, tier, cfg)
            assert 1 <= k <= min(int(cfg["max"]), n)
            assert _crit(w, 1) - _crit(w, k) >= gain * (k - 1)                  # cumulative: each added worker earned the threshold
            assert k >= _break_rule(w, cfg)                                       # the corrected scan can only find MORE justified workers than stopping early
            plan = C.plan_shards(list(w), w, tier, POLICY)
            flat = [m for s in plan["shards"] for m in s]
            assert sorted(flat) == sorted(w) and len(flat) == len(set(flat)) and all(plan["shards"]) and plan["workers"] == len(plan["shards"])


def test_unit_scan_of_the_node_split_prices_every_added_worker_too():
    """apply_node_split scans named units with the same rule; the counterexamples above hold for ``_lpt_units`` as well."""
    cfg = POLICY["workers"]["risk"]
    gain = float(cfg["min_module_seconds_per_extra_worker"])
    for units, expected in (({"a": 500.0, "b": 400.0, "c": 400.0, "d": 400.0}, 2),
                            ({"m0": 100.0, "m1": 800.0, "m2": 700.0, "m3": 700.0, "m4": 700.0}, 4)):
        best, (bs, bl) = 1, C._lpt_units(units, 1)
        for k in range(2, min(cfg["max"], len(units)) + 1):
            shards, loads = C._lpt_units(units, k)
            if max(bl) - max(loads) >= gain * (k - best):
                best, bs, bl = k, shards, loads
        assert best == expected and sorted(u for s in bs for u in s) == sorted(units)
