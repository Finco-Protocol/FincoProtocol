"""One-shot on-chain verification of Stock Token oracle candidates (PR #190/#191).

Read-only on Robinhood Chain mainnet (chain_id 4663). Pins ONE block for the whole run; every contract read
(``eth_getCode``, ``description()``, ``decimals()``, ``latestRoundData()``, ``oraclePaused()``) uses that exact tag. No
transactions, no signing, no credentials in output.

Results are typed on-chain verification outcomes ONLY — this tool never decides promotion. Promotion additionally needs
official heartbeat authority and a final provenance review outside this tool. It verifies candidate identity/contract
behaviour; it never produces an AVAILABLE oracle value.

Input contract: ``stock_token_oracle_candidates.json`` with ``active_candidates`` / ``rejected_candidates`` /
``unresolved``. The default run verifies ``active_candidates`` ONLY (an empty list is valid). ``--include-rejected`` is an
explicit opt-in that additionally re-verifies the historical ``rejected_candidates``.

Failure semantics (stdout is always one JSON document; nothing but typed codes is emitted for failures):
  exit 0  run completed on a pinned block that stayed canonical
  exit 2  CHAIN_ID_MISMATCH / CANDIDATES_SCHEMA_INVALID
  exit 3  VERIFICATION_BLOCK_REORG — the pinned block hash changed; the run is INVALID and NO results are emitted
  exit 4  RPC_UNAVAILABLE / PINNED_BLOCK_INVALID
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DEFAULT_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
CHAIN_ID = 4663
MAX_FUTURE_SECONDS = 120
MAX_DECIMALS = 77

SEL_DESCRIPTION = "0x7284e416"
SEL_DECIMALS = "0x313ce567"
SEL_LATEST_ROUND = "0xfeaf968c"
SEL_ORACLE_PAUSED = "0x7706ba52"

CANDIDATES_PATH = REPO / "app" / "radar_rwa" / "data" / "stock_token_oracle_candidates.json"

# Typed on-chain verification results (NOT promotion decisions)
RESULT_NOT_DEPLOYED = "NOT_DEPLOYED_ON_4663"
RESULT_ONCHAIN_VERIFIED = "ONCHAIN_VERIFIED"
RESULT_DESCRIPTION_MISMATCH = "DESCRIPTION_MISMATCH"
RESULT_DECIMALS_INVALID = "DECIMALS_INVALID"
RESULT_ROUND_INVALID = "ROUND_INVALID"
RESULT_ORACLE_PAUSED_UNREADABLE = "ORACLE_PAUSED_UNREADABLE"

# Typed run-level failures
ERROR_CHAIN_ID_MISMATCH = "CHAIN_ID_MISMATCH"
ERROR_SCHEMA_INVALID = "CANDIDATES_SCHEMA_INVALID"
ERROR_BLOCK_REORG = "VERIFICATION_BLOCK_REORG"
ERROR_RPC_UNAVAILABLE = "RPC_UNAVAILABLE"
ERROR_PINNED_BLOCK_INVALID = "PINNED_BLOCK_INVALID"

EXIT_OK, EXIT_INVALID_INPUT, EXIT_REORG, EXIT_RPC = 0, 2, 3, 4


class RpcError(Exception):
    """Any transport/JSON-RPC failure. The message is never emitted (it could carry a URL)."""


def safe_rpc_label(url: str) -> str:
    """Hostname only: no scheme credentials, path or query token ever reaches an artifact."""
    try:
        return urlparse(url).hostname or "unknown"
    except ValueError:
        return "unknown"


class HttpRpc:
    """Minimal JSON-RPC over HTTPS. Tests inject any object exposing ``call(method, params)``."""

    def __init__(self, url: str, client: httpx.Client | None = None) -> None:
        self._url = url
        self._client = client or httpx.Client(timeout=15.0)

    def __repr__(self) -> str:
        return "HttpRpc(<redacted>)"

    def close(self) -> None:
        self._client.close()

    def call(self, method: str, params: list) -> Any:
        try:
            response = self._client.post(
                self._url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            response.raise_for_status()
            body = response.json()
        except Exception:
            raise RpcError("RPC_TRANSPORT") from None      # drop the original: httpx errors embed the request URL
        if not isinstance(body, dict) or body.get("error"):
            raise RpcError("RPC_ERROR")
        return body.get("result")


def _hex_to_int(raw: Any) -> int | None:
    if not isinstance(raw, str) or raw in ("", "0x"):
        return None
    try:
        return int(raw.removeprefix("0x"), 16)
    except ValueError:
        return None


def _decode_abi_string(raw_hex: str) -> str:
    try:
        clean = raw_hex.removeprefix("0x")
        if len(clean) < 128:
            return ""
        length = int(clean[64:128], 16)
        if length == 0 or length > 256:
            return ""
        return bytes.fromhex(clean[128:128 + length * 2]).decode("utf-8", errors="replace")
    except ValueError:
        return ""


def _decode_int256(hex_word: str) -> int:
    """Two's-complement signed int256 decoding (``2**256 - 1`` is -1, never a huge positive price)."""
    value = int(hex_word, 16)
    if value >= 2 ** 255:
        value -= 2 ** 256
    return value


def _normalise_description(text: str) -> str:
    """Whitespace-only normalisation. Case is NOT folded: the runtime oracle compares descriptions exactly."""
    return " ".join(text.split())


def _call_at(rpc, to: str, data: str, tag: str) -> str | None:
    """eth_call at the pinned tag. None when the call reverts/returns nothing (a contract-level answer).

    A JSON-RPC error body (``RPC_ERROR``, e.g. a revert) is a contract-level answer; a transport failure is NOT — it
    propagates and aborts the run as RPC_UNAVAILABLE rather than being misread as a failed oracle."""
    try:
        raw = rpc.call("eth_call", [{"to": to, "data": data}, tag])
    except RpcError as exc:
        if str(exc) == "RPC_ERROR":
            return None
        raise
    return raw if isinstance(raw, str) and raw not in ("", "0x") else None


def _words(raw: str) -> list[str]:
    clean = raw.removeprefix("0x")
    return [clean[i:i + 64] for i in range(0, len(clean) - len(clean) % 64, 64)]


def _normalise_candidate(candidate: Mapping[str, Any]) -> dict[str, str] | None:
    proxy = candidate.get("candidate_feed_proxy") or candidate.get("rejected_proxy")
    pair = candidate.get("candidate_pair") or candidate.get("expected_pair")
    fields = (candidate.get("symbol"), candidate.get("canonical_id"), candidate.get("token_contract"), proxy, pair)
    if not all(isinstance(f, str) and f for f in fields):
        return None
    return {"symbol": fields[0], "canonical_id": fields[1], "token_contract": fields[2],
            "candidate_feed_proxy": fields[3], "expected_pair": fields[4]}


def select_candidates(document: Any, *, include_rejected: bool) -> list[dict[str, str]] | None:
    """``active_candidates`` by default; ``rejected_candidates`` only on explicit request. None = schema invalid."""
    if not isinstance(document, dict) or not isinstance(document.get("active_candidates"), list):
        return None
    rows = list(document["active_candidates"])
    if include_rejected:
        rejected = document.get("rejected_candidates")
        if not isinstance(rejected, list):
            return None
        rows += rejected
    normalised = [_normalise_candidate(row) if isinstance(row, dict) else None for row in rows]
    return None if any(row is None for row in normalised) else normalised  # type: ignore[return-value]


def _verify_candidate(rpc, candidate: dict[str, str], tag: str, block_number: int, block_ts: int) -> dict[str, Any]:
    proxy, token, expected = candidate["candidate_feed_proxy"], candidate["token_contract"], candidate["expected_pair"]
    row: dict[str, Any] = {**candidate, "pinned_block": block_number}

    code = rpc.call("eth_getCode", [proxy, tag])           # an RpcError here aborts the run: absence is never assumed
    row["proxy_deployed"] = isinstance(code, str) and code not in ("", "0x")
    if not row["proxy_deployed"]:
        row["verification_result"] = RESULT_NOT_DEPLOYED
        return row

    raw = _call_at(rpc, proxy, SEL_DESCRIPTION, tag)
    description = _decode_abi_string(raw) if raw else ""
    row["description"] = description                        # the exact returned text is always preserved
    row["description_readable"] = bool(description)
    if _normalise_description(description) != _normalise_description(expected):
        row["verification_result"] = RESULT_DESCRIPTION_MISMATCH
        row["expected_pair_matches_description"] = False
        return row

    decimals_raw = _call_at(rpc, proxy, SEL_DECIMALS, tag)
    decimals = int(_words(decimals_raw)[0], 16) if decimals_raw and _words(decimals_raw) else None
    row["decimals"] = decimals
    if decimals is None or not 0 <= decimals <= MAX_DECIMALS:
        row["verification_result"] = RESULT_DECIMALS_INVALID
        return row

    round_raw = _call_at(rpc, proxy, SEL_LATEST_ROUND, tag)
    words = _words(round_raw) if round_raw else []
    if len(words) < 5:
        row["verification_result"] = RESULT_ROUND_INVALID
        row["round_issue"] = "ROUND_DATA_MALFORMED"
        return row
    round_id, started_at, updated_at, answered_in = (int(words[0], 16), int(words[2], 16),
                                                      int(words[3], 16), int(words[4], 16))
    answer = _decode_int256(words[1])
    row["latest_round"] = {"roundId": round_id, "answer_signed": answer, "startedAt": started_at,
                           "updatedAt": updated_at, "answeredInRound": answered_in}
    issue = None
    if round_id <= 0:
        issue = "ROUND_ID_NOT_POSITIVE"
    elif answer <= 0:
        issue = "ANSWER_NOT_POSITIVE"
    elif updated_at <= 0:
        issue = "UPDATED_AT_NOT_POSITIVE"
    elif answered_in < round_id:
        issue = "ANSWERED_IN_ROUND_LT_ROUND_ID"
    elif updated_at > block_ts + MAX_FUTURE_SECONDS:        # chain time of the pinned block, never the local wall clock
        issue = "UPDATED_AT_IN_FUTURE"
    if issue:
        row["verification_result"] = RESULT_ROUND_INVALID
        row["round_issue"] = issue
        return row

    paused_raw = _call_at(rpc, token, SEL_ORACLE_PAUSED, tag)
    paused_words = _words(paused_raw) if paused_raw else []
    paused = int(paused_words[0], 16) if paused_words else None
    if paused not in (0, 1):
        row["verification_result"] = RESULT_ORACLE_PAUSED_UNREADABLE
        return row
    row["oracle_paused"] = bool(paused)                      # recorded as a fact; never turned into a runtime value

    row["verification_result"] = RESULT_ONCHAIN_VERIFIED
    return row


def run_verification(rpc, document: Any, *, include_rejected: bool = False, rpc_label: str = "unknown",
                     now: datetime | None = None) -> tuple[int, dict[str, Any]]:
    """Execute one verification run. Returns (exit_code, document). No mutation of any input or file."""
    candidates = select_candidates(document, include_rejected=include_rejected)
    if candidates is None:
        return EXIT_INVALID_INPUT, {"error": ERROR_SCHEMA_INVALID}
    try:
        chain_id = _hex_to_int(rpc.call("eth_chainId", []))
        if chain_id != CHAIN_ID:
            return EXIT_INVALID_INPUT, {"error": ERROR_CHAIN_ID_MISMATCH, "got": chain_id, "expected": CHAIN_ID}

        head = rpc.call("eth_getBlockByNumber", ["latest", False])
        number = _hex_to_int(head.get("number")) if isinstance(head, dict) else None
        block_hash = head.get("hash") if isinstance(head, dict) else None
        block_ts = _hex_to_int(head.get("timestamp")) if isinstance(head, dict) else None
        if number is None or not isinstance(block_hash, str) or not block_hash or block_ts is None:
            return EXIT_RPC, {"error": ERROR_PINNED_BLOCK_INVALID}
        tag = hex(number)

        results = [_verify_candidate(rpc, candidate, tag, number, block_ts) for candidate in candidates]

        recheck = rpc.call("eth_getBlockByNumber", [tag, False])         # exact tag, never "latest"
        recheck_hash = recheck.get("hash") if isinstance(recheck, dict) else None
    except RpcError:
        return EXIT_RPC, {"error": ERROR_RPC_UNAVAILABLE}

    if recheck_hash != block_hash:
        # The run observed a block that is no longer canonical: EVERYTHING it saw is invalid. No result survives.
        return EXIT_REORG, {"error": ERROR_BLOCK_REORG, "chain_id": CHAIN_ID, "pinned_block_number": number,
                            "pinned_block_hash": block_hash, "recheck_block_hash": recheck_hash,
                            "reorg_detected": True}
    return EXIT_OK, {
        "rpc_authority": rpc_label,
        "chain_id": CHAIN_ID,
        "verified_at": (now or datetime.now(timezone.utc)).isoformat(),
        "candidate_source": "active_candidates+rejected_candidates" if include_rejected else "active_candidates",
        "pinned_block_number": number,
        "pinned_block_hash": block_hash,
        "pinned_block_timestamp": block_ts,
        "reorg_detected": False,
        "total": len(results),
        "onchain_verified": sum(1 for r in results if r["verification_result"] == RESULT_ONCHAIN_VERIFIED),
        "not_deployed": sum(1 for r in results if r["verification_result"] == RESULT_NOT_DEPLOYED),
        "results": results,
    }


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None,
         rpc_factory: Callable[[str], Any] | None = None, candidates_path: Path | None = None,
         now: datetime | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if env is None else env
    include_rejected = "--include-rejected" in args
    url = environ.get("FINCO_ROBINHOOD_RPC_URL", DEFAULT_RPC_URL)
    try:
        document = json.loads((candidates_path or CANDIDATES_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(json.dumps({"error": ERROR_SCHEMA_INVALID}))
        return EXIT_INVALID_INPUT
    rpc = (rpc_factory or HttpRpc)(url)
    try:
        code, output = run_verification(rpc, document, include_rejected=include_rejected,
                                        rpc_label=safe_rpc_label(url), now=now)
    except Exception:                                   # never let an exception text (it may embed the URL) escape
        code, output = EXIT_RPC, {"error": ERROR_RPC_UNAVAILABLE}
    finally:
        close = getattr(rpc, "close", None)
        if callable(close):
            close()
    print(json.dumps(output, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
