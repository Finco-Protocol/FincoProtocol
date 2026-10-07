"""PR #191 Correction B: behavioural tests for tools/verify_stock_token_oracles.py.

The verifier is executed against a deterministic fake RPC (no network). Fixtures use clearly synthetic addresses; nothing here
is evidence about the real chain — the real 8-row result lives in the committed historical artifact.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("verify_stock_token_oracles", REPO / "tools" / "verify_stock_token_oracles.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)

CANDIDATES = REPO / "app" / "radar_rwa" / "data" / "stock_token_oracle_candidates.json"
HISTORICAL = REPO / "docs" / "radar" / "stock_token_oracle_candidate_verification_2026-10-04.json"

PROXY = "0x" + "bb" * 20
TOKEN = "0x" + "aa" * 20
BLOCK_NUMBER = 80165854
BLOCK_TS = 4_102_444_800            # year 2100: chain time is deliberately unrelated to the local wall clock
_UNSET = object()
SECRET_URL = "https://user:SECRETPASS" + chr(64) + "rpc.example.test/v1/path?token=SECRET123&key=SECRETKEY"


def word(value: int) -> str:
    return f"{value % (1 << 256):064x}"


def abi_string(text: str) -> str:
    raw = text.encode()
    return "0x" + word(32) + word(len(raw)) + raw.hex().ljust(((len(raw) + 31) // 32) * 64, "0")


def round_data(*, round_id=5, answer=190_00000000, started=BLOCK_TS - 90, updated=BLOCK_TS - 60, answered=5) -> str:
    return "0x" + word(round_id) + word(answer) + word(started) + word(updated) + word(answered)


def block_hash(number: int, altered: bool = False) -> str:
    return "0x" + f"{number + (10**6 if altered else 0):064x}"


class FakeRpc:
    """Deterministic JSON-RPC double. Records every call with its block tag."""

    def __init__(self, *, chain_id=4663, deployed=(PROXY,), description="AAPL / USD", decimals=8, round_=None, paused=0,
                 reorg=False, advance=False, block_ts=BLOCK_TS, head_override=_UNSET, fail_transport=None,
                 fail_revert=(), raise_with_text=None):
        self.chain_id, self.deployed = chain_id, {a.lower() for a in deployed}
        self.description, self.decimals_value = description, decimals
        self.round_ = round_ if round_ is not None else round_data()
        self.paused, self.reorg, self.advance, self.block_ts = paused, reorg, advance, block_ts
        self.head_override, self.fail_transport, self.fail_revert = head_override, fail_transport, set(fail_revert)
        self.raise_with_text = raise_with_text
        self.log: list[tuple] = []                       # (method, to_or_None, selector_or_None, tag)
        self.latest_calls = 0
        self.closed = False

    def close(self):
        self.closed = True

    def _block(self, number, altered=False):
        return {"number": hex(number), "timestamp": hex(self.block_ts), "hash": block_hash(number, altered)}

    def call(self, method, params):
        if self.raise_with_text:
            raise RuntimeError(self.raise_with_text)
        if self.fail_transport == method:
            raise V.RpcError("RPC_TRANSPORT")
        if method == "eth_chainId":
            self.log.append((method, None, None, None))
            return hex(self.chain_id)
        if method == "eth_getBlockByNumber":
            tag = params[0]
            self.log.append((method, None, None, tag))
            if tag == "latest":
                self.latest_calls += 1
                if self.head_override is not _UNSET:
                    return self.head_override
                return self._block(BLOCK_NUMBER + (self.latest_calls - 1 if self.advance else 0))
            return self._block(int(tag, 16), altered=self.reorg)
        if method == "eth_getCode":
            self.log.append((method, params[0].lower(), None, params[1]))
            return "0x6080" if params[0].lower() in self.deployed else "0x"
        assert method == "eth_call", method
        to, data, tag = params[0]["to"].lower(), params[0]["data"], params[1]
        self.log.append((method, to, data, tag))
        if (to, data) in self.fail_revert:
            raise V.RpcError("RPC_ERROR")
        if data == V.SEL_DESCRIPTION:
            return abi_string(self.description)
        if data == V.SEL_DECIMALS:
            return "0x" + word(self.decimals_value)
        if data == V.SEL_LATEST_ROUND:
            return self.round_
        if data == V.SEL_ORACLE_PAUSED:
            return "0x" + word(self.paused) if self.paused is not None else "0x"
        raise AssertionError(f"unexpected selector {data}")


def doc(*, active=True, rejected=()):
    row = {"symbol": "AAPL", "canonical_id": "4663:" + TOKEN, "token_contract": TOKEN,
           "candidate_feed_proxy": PROXY, "candidate_pair": "AAPL / USD"}
    return {"active_candidates": [row] if active else [], "rejected_candidates": list(rejected), "unresolved": []}


def run(rpc=None, document=_UNSET, **kw):
    rpc = rpc or FakeRpc()
    return V.run_verification(rpc, doc() if document is _UNSET else document, rpc_label="rpc.example.test", **kw)


def result(rpc=None, document=_UNSET):
    code, out = run(rpc, document)
    assert code == 0, out
    return out["results"][0]


# ── A. current schema, zero active candidates ────────────────────────────────────────────────────
def test_zero_active_candidates_runs_cleanly_with_the_shipped_schema():
    code, out = run(document=json.loads(CANDIDATES.read_text(encoding="utf-8")))
    assert code == 0 and out["total"] == 0 and out["results"] == []
    assert out["onchain_verified"] == 0 and out["not_deployed"] == 0
    assert out["candidate_source"] == "active_candidates"


def test_main_cli_path_works_against_the_shipped_candidates_file(capsys):
    rpc = FakeRpc()
    code = V.main([], {"FINCO_ROBINHOOD_RPC_URL": "https://rpc.example.test"}, rpc_factory=lambda url: rpc)
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["total"] == 0 and rpc.closed
    assert [m for m, *_ in rpc.log if m in ("eth_getCode", "eth_call")] == []        # nothing to verify, no contract reads


def test_default_run_never_touches_rejected_candidates():
    shipped = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    assert len(shipped["rejected_candidates"]) == 8
    rpc = FakeRpc()
    code, out = run(rpc, shipped)
    assert code == 0 and out["total"] == 0
    assert not any(m == "eth_getCode" for m, *_ in rpc.log)


def test_legacy_candidates_key_is_not_silently_accepted():
    code, out = run(document={"candidates": [doc()["active_candidates"][0]]})
    assert code == 2 and out == {"error": "CANDIDATES_SCHEMA_INVALID"}


@pytest.mark.parametrize("bad", [None, [], {"active_candidates": "x"}, {"active_candidates": [{"symbol": "AAPL"}]}])
def test_malformed_candidate_documents_fail_closed_without_a_traceback(bad):
    code, out = run(document=bad)
    assert code == 2 and out["error"] == "CANDIDATES_SCHEMA_INVALID"


def test_include_rejected_is_an_explicit_opt_in_that_reproduces_the_historical_set():
    shipped = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    rpc = FakeRpc(deployed=())           # fixture: nothing deployed — exercises the code path, is not chain evidence
    code, out = V.run_verification(rpc, shipped, include_rejected=True, rpc_label="x")
    assert code == 0 and out["total"] == 8 and out["not_deployed"] == 8
    assert out["candidate_source"] == "active_candidates+rejected_candidates"
    historical = json.loads(HISTORICAL.read_text(encoding="utf-8"))
    expected = {(r["symbol"], r["candidate_proxy"], r["verification_result"]) for r in historical["results"]}
    actual = {(r["symbol"], r["candidate_feed_proxy"], r["verification_result"]) for r in out["results"]}
    assert actual == expected


# ── B / C. deployment and chain identity ─────────────────────────────────────────────────────────
def test_empty_getcode_is_not_deployed_on_4663():
    row = result(FakeRpc(deployed=()))
    assert row["verification_result"] == "NOT_DEPLOYED_ON_4663" and row["proxy_deployed"] is False
    assert "description" not in row                                    # nothing else was read from an absent contract


def test_wrong_chain_fails_with_chain_id_mismatch_and_a_nonzero_exit(capsys):
    rpc = FakeRpc(chain_id=1)
    code = V.main([], {}, rpc_factory=lambda url: rpc, candidates_path=_write_candidates(None))
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["error"] == "CHAIN_ID_MISMATCH" and out["got"] == 1 and out["expected"] == 4663
    assert not any(m in ("eth_getCode", "eth_call", "eth_getBlockByNumber") for m, *_ in rpc.log)


def _write_candidates(tmp, document=_UNSET):
    import tempfile
    path = Path(tempfile.mkdtemp()) / "candidates.json"
    path.write_text(json.dumps(doc() if document is _UNSET else document), encoding="utf-8")
    return path


# ── D. one pinned block for every read ───────────────────────────────────────────────────────────
def test_pinned_block_n_is_used_for_every_contract_read():
    rpc = FakeRpc(advance=True)           # a second ``latest`` read would return N+1
    code, out = run(rpc)
    assert code == 0 and out["results"][0]["verification_result"] == "ONCHAIN_VERIFIED"
    tag = hex(BLOCK_NUMBER)
    assert rpc.latest_calls == 1
    reads = [(m, data) for m, to, data, t in rpc.log if m in ("eth_getCode", "eth_call")]
    assert [d for _, d in reads] == [None, V.SEL_DESCRIPTION, V.SEL_DECIMALS, V.SEL_LATEST_ROUND, V.SEL_ORACLE_PAUSED]
    assert {t for m, to, data, t in rpc.log if m in ("eth_getCode", "eth_call")} == {tag}
    assert [t for m, _, _, t in rpc.log if m == "eth_getBlockByNumber"] == ["latest", tag]     # final check: exact tag


def test_oracle_paused_is_read_from_the_stock_token_not_the_feed():
    rpc = FakeRpc()
    run(rpc)
    paused_reads = [to for m, to, data, t in rpc.log if data == V.SEL_ORACLE_PAUSED]
    assert paused_reads == [TOKEN] and PROXY not in paused_reads


def test_full_pinned_block_audit_fields_are_recorded():
    code, out = run()
    assert out["pinned_block_number"] == BLOCK_NUMBER
    assert out["pinned_block_hash"] == block_hash(BLOCK_NUMBER) and len(out["pinned_block_hash"]) == 66
    assert out["pinned_block_timestamp"] == BLOCK_TS and out["reorg_detected"] is False
    assert out["chain_id"] == 4663 and out["rpc_authority"] == "rpc.example.test"


def test_invalid_pinned_block_fails_closed():
    for head in (None, {"number": "0x1"}, {"number": "0x1", "hash": "0xab"}, {"hash": "0xab", "timestamp": "0x1"}):
        code, out = run(FakeRpc(head_override=head))
        assert code == 4 and out == {"error": "PINNED_BLOCK_INVALID"}


# ── E. reorg invalidates the entire run ──────────────────────────────────────────────────────────
def test_reorg_is_a_typed_nonzero_failure_and_no_result_survives(capsys):
    rpc = FakeRpc(reorg=True)
    code = V.main([], {}, rpc_factory=lambda url: rpc, candidates_path=_write_candidates(None))
    text = capsys.readouterr().out
    out = json.loads(text)
    assert code == 3 and out["error"] == "VERIFICATION_BLOCK_REORG" and out["reorg_detected"] is True
    assert "results" not in out and "ONCHAIN_VERIFIED" not in text and out.get("onchain_verified") is None
    assert out["pinned_block_hash"] != out["recheck_block_hash"] and len(out["pinned_block_hash"]) == 66


def test_reorg_run_invalidates_even_not_deployed_findings():
    code, out = run(FakeRpc(reorg=True, deployed=()))
    assert code == 3 and "results" not in out and "not_deployed" not in out


# ── F-I. latestRoundData validity ────────────────────────────────────────────────────────────────
def test_negative_int256_answer_is_round_invalid_never_a_huge_positive_price(capsys):
    negative_one = 2 ** 256 - 1
    rpc = FakeRpc(round_=round_data(answer=negative_one))
    row = result(rpc)
    assert row["verification_result"] == "ROUND_INVALID" and row["round_issue"] == "ANSWER_NOT_POSITIVE"
    assert row["latest_round"]["answer_signed"] == -1
    assert str(negative_one) not in json.dumps(row)


def test_signed_decoder_is_twos_complement():
    assert V._decode_int256("f" * 64) == -1
    assert V._decode_int256(word(2 ** 255)) == -(2 ** 255)
    assert V._decode_int256(word(190)) == 190 and V._decode_int256(word(0)) == 0


@pytest.mark.parametrize("kwargs,issue", [
    ({"updated": 0}, "UPDATED_AT_NOT_POSITIVE"),
    ({"round_id": 0, "answered": 0}, "ROUND_ID_NOT_POSITIVE"),
    ({"answer": 0}, "ANSWER_NOT_POSITIVE"),
    ({"round_id": 9, "answered": 8}, "ANSWERED_IN_ROUND_LT_ROUND_ID"),
    ({"updated": BLOCK_TS + V.MAX_FUTURE_SECONDS + 1}, "UPDATED_AT_IN_FUTURE"),
])
def test_invalid_rounds_are_round_invalid_with_a_typed_issue(kwargs, issue):
    row = result(FakeRpc(round_=round_data(**kwargs)))
    assert row["verification_result"] == "ROUND_INVALID" and row["round_issue"] == issue


def test_future_updated_at_is_judged_against_the_pinned_block_time_with_tolerance():
    ok = result(FakeRpc(round_=round_data(updated=BLOCK_TS + V.MAX_FUTURE_SECONDS)))
    assert ok["verification_result"] == "ONCHAIN_VERIFIED"                       # exactly at the tolerance
    late = result(FakeRpc(round_=round_data(updated=BLOCK_TS + V.MAX_FUTURE_SECONDS + 1)))
    assert late["round_issue"] == "UPDATED_AT_IN_FUTURE"


def test_future_check_does_not_use_the_local_wall_clock():
    # The pinned block is in the year 2100 and updatedAt is 10s before it: far in the LOCAL clock's future, yet valid
    # relative to chain time. A wall-clock comparison would wrongly reject it.
    assert result(FakeRpc(round_=round_data(updated=BLOCK_TS - 10)))["verification_result"] == "ONCHAIN_VERIFIED"
    # And an old block timestamp (year 2001) with a modern updatedAt is rejected on chain time, not accepted by wall clock.
    old_ts = 1_000_000_000
    row = result(FakeRpc(block_ts=old_ts, round_=round_data(updated=1_790_000_000)))
    assert row["round_issue"] == "UPDATED_AT_IN_FUTURE"


def test_malformed_round_data_is_round_invalid():
    for raw in ("0x", "0x1234", "0x" + word(1) * 3):
        class Short(FakeRpc):
            pass
        row = result(Short(round_=raw))
        assert row["verification_result"] == "ROUND_INVALID"


# ── J. description must match exactly ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("returned", ["FAKE AAPL / USD", "AAPL / USD TEST", "OTHER AAPL / USD SOURCE",
                                      "AAPL / USDC", "xAAPL / USD", "aapl / usd", "AAPL/USD", ""])
def test_description_must_match_exactly_not_by_substring(returned):
    row = result(FakeRpc(description=returned))
    assert row["verification_result"] == "DESCRIPTION_MISMATCH"
    assert row["description"] == returned                                       # exact returned text preserved


@pytest.mark.parametrize("returned", ["AAPL / USD", "  AAPL / USD  ", "AAPL  /  USD"])
def test_only_whitespace_normalisation_is_allowed(returned):
    row = result(FakeRpc(description=returned))
    assert row["verification_result"] == "ONCHAIN_VERIFIED" and row["description"] == returned


# ── decimals / oraclePaused ──────────────────────────────────────────────────────────────────────
def test_invalid_decimals_are_typed():
    assert result(FakeRpc(decimals=V.MAX_DECIMALS + 1))["verification_result"] == "DECIMALS_INVALID"


def test_decimals_are_read_from_the_proxy_not_assumed():
    row = result(FakeRpc(decimals=6))
    assert row["verification_result"] == "ONCHAIN_VERIFIED" and row["decimals"] == 6


@pytest.mark.parametrize("paused", [None, 2])
def test_unreadable_or_non_boolean_oracle_paused_is_unreadable(paused):
    assert result(FakeRpc(paused=paused))["verification_result"] == "ORACLE_PAUSED_UNREADABLE"


def test_reverting_oracle_paused_is_unreadable():
    rpc = FakeRpc(fail_revert={(TOKEN, V.SEL_ORACLE_PAUSED)})
    assert result(rpc)["verification_result"] == "ORACLE_PAUSED_UNREADABLE"


def test_paused_true_is_recorded_as_a_fact_and_is_not_a_runtime_value():
    row = result(FakeRpc(paused=1))
    assert row["verification_result"] == "ONCHAIN_VERIFIED" and row["oracle_paused"] is True
    assert "value" not in row and "price" not in json.dumps(row).lower()


# ── transport failures abort the run (never misread as an oracle verdict) ────────────────────────
@pytest.mark.parametrize("method", ["eth_chainId", "eth_getBlockByNumber", "eth_getCode"])
def test_transport_failure_aborts_the_run(method):
    code, out = run(FakeRpc(fail_transport=method))
    assert code == 4 and out == {"error": "RPC_UNAVAILABLE"}


def test_transport_failure_during_a_contract_read_is_not_recorded_as_round_invalid():
    class Flaky(FakeRpc):
        def call(self, method, params):
            if method == "eth_call" and params[0]["data"] == V.SEL_LATEST_ROUND:
                raise V.RpcError("RPC_TRANSPORT")
            return super().call(method, params)
    code, out = run(Flaky())
    assert code == 4 and out == {"error": "RPC_UNAVAILABLE"}


# ── L. secrets never appear in emitted output ────────────────────────────────────────────────────
SECRETS = ("SECRETPASS", "SECRET123", "SECRETKEY", "user:", "/v1/path")


def _assert_no_secrets(text):
    for secret in SECRETS:
        assert secret not in text, secret


def _main_output(capsys, rpc, *, env_url=SECRET_URL, candidates=None, args=()):
    code = V.main(list(args), {"FINCO_ROBINHOOD_RPC_URL": env_url}, rpc_factory=lambda url: rpc,
                  candidates_path=_write_candidates(None, candidates if candidates is not None else _UNSET))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_rpc_credentials_and_query_tokens_never_appear_on_success(capsys):
    code, text = _main_output(capsys, FakeRpc())
    assert code == 0 and "rpc.example.test" in text
    _assert_no_secrets(text)


@pytest.mark.parametrize("rpc,expected", [
    (FakeRpc(reorg=True), 3), (FakeRpc(chain_id=7), 2), (FakeRpc(fail_transport="eth_chainId"), 4),
    (FakeRpc(raise_with_text=f"connect failed {SECRET_URL}"), 4),
])
def test_rpc_credentials_never_appear_on_any_failure_path(capsys, rpc, expected):
    code, text = _main_output(capsys, rpc)
    assert code == expected
    _assert_no_secrets(text)


def test_schema_failure_does_not_echo_the_url(capsys):
    code, text = _main_output(capsys, FakeRpc(), candidates={"candidates": []})
    assert code == 2
    _assert_no_secrets(text)


def test_safe_label_and_repr_redact(capsys):
    assert V.safe_rpc_label(SECRET_URL) == "rpc.example.test"
    assert V.safe_rpc_label("not a url") == "unknown"
    _assert_no_secrets(repr(V.HttpRpc(SECRET_URL)))


def test_http_transport_errors_do_not_carry_the_url():
    import httpx

    def handler(request):
        raise httpx.ConnectError("boom " + str(request.url), request=request)
    rpc = V.HttpRpc(SECRET_URL, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(V.RpcError) as caught:
        rpc.call("eth_chainId", [])
    _assert_no_secrets(str(caught.value) + repr(caught.value) + str(caught.value.__cause__))


# ── M. never a promotion verdict; read-only; no mutation ─────────────────────────────────────────
def test_tool_never_emits_promotion_eligible_or_a_promotion_verdict(capsys):
    for rpc in (FakeRpc(), FakeRpc(deployed=()), FakeRpc(paused=1)):
        _, text = _main_output(capsys, rpc)
        assert "PROMOTION_ELIGIBLE" not in text and "promotion" not in text.lower()
    assert "PROMOTION_ELIGIBLE" not in (REPO / "tools" / "verify_stock_token_oracles.py").read_text(encoding="utf-8")


def test_only_read_only_rpc_methods_are_used():
    rpc = FakeRpc()
    run(rpc)
    assert {m for m, *_ in rpc.log} <= {"eth_chainId", "eth_getBlockByNumber", "eth_getCode", "eth_call"}


def test_verification_never_modifies_the_candidates_file_or_the_registry():
    registry = REPO / "app" / "radar_rwa" / "data" / "stock_token_oracle_feeds.json"
    before = (hashlib.sha256(CANDIDATES.read_bytes()).hexdigest(), hashlib.sha256(registry.read_bytes()).hexdigest())
    V.main(["--include-rejected"], {}, rpc_factory=lambda url: FakeRpc(deployed=()))
    after = (hashlib.sha256(CANDIDATES.read_bytes()).hexdigest(), hashlib.sha256(registry.read_bytes()).hexdigest())
    assert before == after


def test_tool_source_has_no_execution_signing_or_custody_path():
    source = (REPO / "tools" / "verify_stock_token_oracles.py").read_text(encoding="utf-8")
    for banned in ("eth_sendTransaction", "eth_sendRawTransaction", "eth_sign", "personal_sign", "sign_transaction",
                   "private_key", "broadcast", "execute_trade", "custody", "PERSISTENCE_PROBABILITY"):
        assert banned not in source, banned
