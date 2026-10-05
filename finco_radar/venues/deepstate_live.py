"""Deepstate NVDA/USDG canonical execution-market source (V1 vertical slice).

READ-ONLY derived market source over the reviewed Deepstate authority:

    venue        = DEEPSTATE
    chain_id     = 4663 (Robinhood Chain)
    router       = 0x6cf19308C22FC82ea620Fa0B3E94948d20f27B96
    pool id      = keccak256(abi.encode(USDG, NVDA))
                 = 0x42819cadfbb25aab80543236e280fba4e61aa61e0b5b777541de54ae69da35e4
    book (V1)    = keccak256(abi.encode(USDG, NVDA, epoch=0))
                 = 0xdf941c235503a5d2e67aee5dea00f2965f99421c0d034bd77f924c05c66bf399
    base (NVDA)  = 0xd0601CE157Db5bdC3162BbaC2a2C8af5320D9EEC (18 decimals)
    quote (USDG) = 0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168 (6 decimals)

Only canonical executed Deepstate matches (AskMatched / BidMatched on the
production Router for the reviewed book) become MARKET observations.
Order-book midpoints, best bid/ask, router quotes, frontend quotes and
Transfer-log reconstruction are never persisted as executions.

Node layout (deepstate-contracts@37aa0d2e, DeepstateV1.sol header):

    bits 224-255: signed 32-bit logarithmic tick
    bits  64-223: 160-bit filled quantity (quote raw units for the NVDA/USDG book)
    bits  32- 63: 32-bit same-tick branch correction code
    bits   0- 31: 32-bit nonce/path suffix

Tick ``t`` prices one quote raw unit in ``2 ** (96 * t / 2**31)`` base raw
units (TickMath32).  The gross base amount is ``floor(quantity * price)``;
the correction code reconciles the resting tick notional rounding
(``delta = correction - 1``) exactly as the engine settles.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, getcontext
import json
import urllib.request

getcontext().prec = 60

DEEPSTATE_VENUE = "DEEPSTATE"
DEEPSTATE_CHAIN_ID = 4663
DEEPSTATE_ROUTER = "0x6cf19308C22FC82ea620Fa0B3E94948d20f27B96"
DEEPSTATE_POOL_ID = "0x42819cadfbb25aab80543236e280fba4e61aa61e0b5b777541de54ae69da35e4"
DEEPSTATE_BOOK_ID = "0xdf941c235503a5d2e67aee5dea00f2965f99421c0d034bd77f924c05c66bf399"
DEEPSTATE_NVDA = "0xd0601CE157Db5bdC3162BbaC2a2C8af5320D9EEC"
DEEPSTATE_USDG = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"
NVDA_DECIMALS = 18
USDG_DECIMALS = 6

ASK_MATCHED_SIG = "AskMatched(bytes32,bytes32)"
BID_MATCHED_SIG = "BidMatched(bytes32,bytes32)"


def topic0(signature: str) -> str:
    """keccak256 of one canonical event signature (never a hard-coded hash)."""
    from eth_utils import keccak as _keccak
    return "0x" + _keccak(text=signature).hex()


def ask_matched_topic0() -> str:
    return topic0(ASK_MATCHED_SIG)


def bid_matched_topic0() -> str:
    return topic0(BID_MATCHED_SIG)


@dataclass(frozen=True)
class RestingNode:
    """Decoded Deepstate packed fill node (verified layout)."""

    tick: int
    quantity: int
    correction: int
    nonce: int


def decode_resting_node(node: int | str) -> RestingNode:
    """Decode one packed Deepstate node word into its four fields."""
    value = int(node, 16) if isinstance(node, str) else int(node)
    if value < 0 or value >= 2**256:
        raise ValueError("MALFORMED_NODE")
    tick = value >> 224
    if tick >= 2**31:
        tick -= 2**32
    quantity = (value >> 64) & ((1 << 160) - 1)
    correction = (value >> 32) & 0xFFFFFFFF
    nonce = value & 0xFFFFFFFF
    return RestingNode(tick=tick, quantity=quantity, correction=correction, nonce=nonce)


def tick_price(tick: int) -> Decimal:
    """TickMath32 semantics as an exact-ish Decimal: 2 ** (96 * tick / 2**31)."""
    return Decimal(2) ** (Decimal(96) * Decimal(tick) / Decimal(2**31))


def gross_base_raw(node: RestingNode) -> int:
    """Gross base (NVDA) raw amount: floor(quantity * tick_price)."""
    if node.quantity < 0:
        raise ValueError("NEGATIVE_QUANTITY")
    return int(Decimal(node.quantity) * tick_price(node.tick))


def decode_match_log(log: dict) -> dict | None:
    """Decode one canonical Deepstate match log, or return ``None``.

    Accepts only: production Router address + canonical AskMatched /
    BidMatched topic0 + the reviewed NVDA/USDG book.  Everything else
    (wrong router, unknown book, foreign event) is rejected as ``None``.
    """
    if log.get("address", "").lower() != DEEPSTATE_ROUTER.lower():
        return None
    topics = log.get("topics") or []
    if len(topics) != 1:
        return None
    topic = topics[0].lower()
    if topic == ask_matched_topic0():
        event_type = "AskMatched"
    elif topic == bid_matched_topic0():
        event_type = "BidMatched"
    else:
        return None
    data = log.get("data", "0x")
    if not isinstance(data, str) or len(data) != 2 + 128:
        return None
    book_id = "0x" + data[2:66]
    if book_id.lower() != DEEPSTATE_BOOK_ID.lower():
        return None
    try:
        node = decode_resting_node("0x" + data[66:130])
    except ValueError:
        return None
    return {
        "event_type": event_type,
        "book_id": book_id,
        "node": node,
        "log_index": int(log["logIndex"], 16),
        "block_number": int(log["blockNumber"], 16),
        "block_hash": log["blockHash"],
        "transaction_hash": log["transactionHash"],
        "address": log["address"],
    }


def match_to_observation(decoded: dict, *, collected_at: datetime,
                         block_timestamp: int | None = None) -> "MarketObservation":  # noqa: F821
    """Map one decoded canonical match to a MARKET MarketObservation."""
    from finco_radar.venues.observations import FreshnessState, ObservationStatus
    from finco_radar.venues.observations import MarketObservation

    node: RestingNode = decoded["node"]
    gross_quote_raw = node.quantity                      # USDG raw (6 decimals)
    gross_quote = Decimal(gross_quote_raw) / Decimal(10**USDG_DECIMALS)
    price = tick_price(node.tick)                        # NVDA raw per USDG raw
    gross_base_raw = gross_quote_raw * price             # NVDA raw (exact)
    execution_price = (Decimal(gross_quote_raw) * Decimal(10**12)
                       / gross_base_raw)                 # USDG/NVDA human
    ts = None
    if block_timestamp is not None:
        ts = datetime.fromtimestamp(block_timestamp, timezone.utc).isoformat()
    collected_iso = (collected_at.isoformat() if isinstance(collected_at, datetime)
                     else str(collected_at))
    payload = {
        "chain_id": DEEPSTATE_CHAIN_ID,
        "venue": DEEPSTATE_VENUE,
        "venue_market_id": DEEPSTATE_POOL_ID,
        "router": DEEPSTATE_ROUTER.lower(),
        "pool_id": DEEPSTATE_POOL_ID,
        "book_id": decoded["book_id"].lower(),
        "event_type": decoded["event_type"],
        "transaction_hash": decoded["transaction_hash"],
        "log_index": decoded["log_index"],
        "block_number": decoded["block_number"],
        "block_hash": decoded["block_hash"],
        "gross_base_amount_nvda": str(int(gross_base_raw)),
        "gross_quote_amount_usdg": gross_quote_raw,
        "node": {"tick": node.tick, "quantity": node.quantity,
                 "correction": node.correction, "nonce": node.nonce},
    }
    return MarketObservation(
        ts=ts,
        collected_at=collected_iso,
        canonical_asset_id="NVDA",
        venue_id=DEEPSTATE_VENUE,
        instrument_id=DEEPSTATE_POOL_ID,
        instrument_type="tokenized_stock_book",
        price=str(execution_price),
        source="DEEPSTATE_PROTOCOL_ROUTER_V1",
        freshness_state=FreshnessState.AVAILABLE,
        observation_status=ObservationStatus.OK,
        payload=payload,
    )


def fetch_match_logs(rpc_url: str, from_block: int, to_block: int,
                     *, timeout: int = 25) -> list[dict]:
    """Read-only eth_getLogs for canonical Deepstate matches on the Router."""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "eth_getLogs",
        "params": [{
            "address": DEEPSTATE_ROUTER,
            "topics": [[ask_matched_topic0(), bid_matched_topic0()]],
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
        }],
    }).encode()
    request = urllib.request.Request(
        rpc_url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    if body.get("error"):
        raise RuntimeError(f"RPC_ERROR {body['error']}")
    return body.get("result") or []


def fetch_block_timestamp(rpc_url: str, block_number: int,
                          *, timeout: int = 25) -> int | None:
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "eth_getBlockByNumber",
        "params": [hex(block_number), False],
    }).encode()
    request = urllib.request.Request(
        rpc_url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    block = body.get("result") or {}
    return int(block["timestamp"], 16) if block.get("timestamp") else None


def normalize_to_usd(usdg_per_nvda: Decimal, deepstate_executed_at: datetime,
                     usdg_usd: Decimal, usdg_usd_observed_at: datetime):
    """USD normalization through the EXISTING reviewed USDG/USD authority.

    normalized = Deepstate NVDA/USDG gross execution x USDG/USD.
    The effective evidence timestamp is min(deepstate, usdg_usd) so a fresh
    USDG quote can never refresh an older Deepstate execution.
    """
    normalized = Decimal(usdg_per_nvda) * Decimal(usdg_usd)
    effective = min(deepstate_executed_at, usdg_usd_observed_at)
    return normalized, effective
