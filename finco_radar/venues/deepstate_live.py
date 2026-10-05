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


ASKS_MATCHED_SIG = "AsksMatched(bytes32,bytes32[])"
BIDS_MATCHED_SIG = "BidsMatched(bytes32,bytes32[])"
ASK_SUBTREE_SIG = "AskSubtreeMatched(bytes32,bytes32,uint160,uint256)"
BID_SUBTREE_SIG = "BidSubtreeMatched(bytes32,bytes32,uint160,uint256)"

SUPPORTED_MATCH_TOPICS = {
    ask_matched_topic0(): "AskMatched",
    bid_matched_topic0(): "BidMatched",
    topic0(ASKS_MATCHED_SIG): "AsksMatched",
    topic0(BIDS_MATCHED_SIG): "BidsMatched",
    topic0(ASK_SUBTREE_SIG): "AskSubtreeMatched",
    topic0(BID_SUBTREE_SIG): "BidSubtreeMatched",
}


def _abi_decode_nodes(data_hex: str):
    """Decode canonical ABI bytes32[] with exact length."""
    raw = bytes.fromhex(data_hex[2:])
    if len(raw) < 96:
        raise ValueError("MALFORMED_BATCH")
    book = raw[:32]
    offset = int.from_bytes(raw[32:64], "big")
    if offset != 0x40:
        raise ValueError("MALFORMED_BATCH_OFFSET")
    length = int.from_bytes(raw[64:96], "big")
    if len(raw) != 96 + 32 * length:
        raise ValueError("MALFORMED_BATCH_LENGTH")
    return book, [raw[96 + i * 32:128 + i * 32] for i in range(length)]

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




# ── Exact TickMath32 integer port (deepstate-contracts@37aa0d2e) ──────────
# Direct port of TickMath32.sol: getPriceFactorAtTick / _fractionFactor /
# _quoteAtFactor — pure integer arithmetic, no floats, no Decimal authority.
_TICKMATH_FACTOR0 = {0: 0x100000000000000000000000000000000, 1: 0xffffff4e8de845adac77243cd0914b37, 10: 0xfffff9118b28579a1d5c6790c7f175ab, 11: 0xfffff86019156b3d676efe25eda498b3, 12: 0xfffff7aea702f9dfa5d5d3bb9279d256, 13: 0xfffff6fd34f10380d83ba739d8f75046, 14: 0xfffff64bc2df8820fe4b37891ebb409f, 2: 0xfffffe9d1bd1065a50971275792f1c83, 3: 0xfffffdeba9ba4205ec0a898fcd6f94e9, 4: 0xfffffd3a37a3f8b07e7c4871dc00d76e, 5: 0xfffffc88c58e2a5a07970e01eea908e4, 6: 0xfffffbd75378d702870599268a464fcf, 7: 0xfffffb25e163fea9fc72a8c66eced432, 8: 0xfffffa746f4fa1506788fbc89750bf71, 9: 0xfffff9c2fd3bbef5c7f3511439f23c11, 15: 0xfffff59a50ce87c017af4391fc7bd1b4}
_TICKMATH_FACTOR1 = {1: 0xfffff4e8debe025e24128a3d460731f1, 10: 0xffff9118c90ae5d5e1aae8556956bbce, 11: 0xffff8601ac96dcbee28dc84499b8b8dd, 12: 0xffff7aea909dd26544c77f0bdc9ee440, 13: 0xffff6fd3751fc6c3b4490bedc4d9b6af, 14: 0xffff64bc5a1cb9d4dd03a944c8d06bfb, 2: 0xffffe9d1bdf703aef21ea4dcfb0682d8, 3: 0xffffdeba9dab03ed16130032411d9852, 4: 0xffffd3a37dda03133bde87a8379c8932, 5: 0xffffc88c5e84011c0f7061c1f8747ebb, 6: 0xffffbd753fa8fe023cb7f01a95a85617, 7: 0xffffb25e2148f9c06fa4cf6516bd41ca, 8: 0xffffa7470363f4515426d76c762b6b61, 9: 0xffff9c2fe5f9edaf962e1b139ece9519, 15: 0xffff59a53f94ab936ae8cc833ff1a560}
_TICKMATH_FACTOR2 = {1: 0xffff4e8e25879bfa09ea263360240c1a, 10: 0xfff911a315e6bcd6539048f8bac58ea3, 11: 0xfff860360951b7ecba3dc0ba9b0a7c4d, 12: 0xfff7aec977b80143043f6d3dd6d17cca, 13: 0xfff6fd5d6119439abe99c1a5c03bd998, 14: 0xfff64bf1c57529b5b16747e59b571acc, 2: 0xfffe9d1cc60ddab126de1aec4a87e7b8, 3: 0xfffdebabe19266e494faa08bf06f95d2, 4: 0xfffd3a3b7814eb53cd7629d70fea116a, 5: 0xfffc88cb899512be849eb1004af9a6da, 6: 0xfffbd75c161287e4a9d98eb29b205e4e, 7: 0xfffb25ed1d8cf58667a3511be150639f, 8: 0xfffa747ea0040664238f92f792405805, 9: 0xfff9c3109d77653e7e48d2997f2379d1, 15: 0xfff59a86a4cb5e55dfd877cc112a9619}
_TICKMATH_FACTOR3 = {1: 0xfff4e91bff1b8c3d88338e0ebf284a4d, 10: 0xff9130b359dbce534e76903b39de605f, 11: 0xff861e9c29c4178cc9272e1140473f0b, 12: 0xff7b0cffbe1596751b6382200cc3b5d9, 13: 0xff6ffbde117ee04e90c901f772e3d464, 14: 0xff64eb371eaec554c6d000c306ca5e48, 2: 0xffe9d2b2f7db2755ddf1d28a378a438c, 3: 0xffdebcc4e4eb184180b1fe46ef229c17, 4: 0xffd3a751c0f7e10bd3b9f8ae012fbe06, 5: 0xffc8925986ae3ed08f06593fe67ac1bf, 6: 0xffbd7ddc30bb29b9304ec1b3093eeb72, 7: 0xffb269d9b9cbd4fa6c269773746a69d9, 8: 0xffa756521c8daed19f3a1b48fb94c589, 9: 0xff9c434553ae60823fa7dde946a88ebf, 15: 0xff59db0ae05450ba1ecf379840cb103d}
_TICKMATH_FACTOR4 = {1: 0xff4ecb59511ec8a5301ba217ef18dd7c, 10: 0xf92959bb5dd4ba7434b7e1b1c86a6355, 11: 0xf87ce0e5b2094d9bbff35cfc575603f6, 12: 0xf7d0df730ad13bb8fe90d496d60fb6ea, 13: 0xf7255510c4288238d1b490ead1a26390, 14: 0xf67a416c733f846d81897dca4e77a30e, 2: 0xfe9e115c7b8f884badd25995e79d2f09, 3: 0xfdedd1b496a89f34c46757b38a53619a, 4: 0xfd3e0c0cf486c174853f3a5931e0ee03, 5: 0xfc8ec01121e447bb455d621825da76cd, 6: 0xfbdfed6ce5f09c489da5ff395ecae2e6, 7: 0xfb3193cc4227c3f46f66a72687c5c9a8, 8: 0xfa83b2db722a033a7c25bb14315d7fcc, 9: 0xf9d64a46eb939f352d2e093e4110a050, 15: 0xf5cfa433e653729065e4527c9e33781c}
_TICKMATH_FACTOR5 = {1: 0xf5257d152486cc2c7b9d0c7aed980fc3, 10: 0xa5fed6a9b15138ea1cbd7f621710701a, 11: 0x9ef5326091a111ada0911f09ebb9fdcf, 12: 0x9837f0518db8a96f46ad23182e42f6f6, 13: 0x91c3d373ab11c3360fd6d8e0ae5ac9d6, 14: 0x8b95c1e3ea8bd6e6fbe4628758a53c8f, 2: 0xeac0c6e7dd24392ed02d75b3706e54fa, 3: 0xe0ccdeec2a94e111065895048dd333c8, 4: 0xd744fccad69d6af439a68bb9902d3fde, 5: 0xce248c151f8480e3e235838f95f2c6ec, 6: 0xc5672a115506dadd3e2ad0c964dd9f36, 7: 0xbd08a39f580c36bea8811fb66d0faf78, 8: 0xb504f333f9de6484597d89b3754abe9f, 9: 0xad583eea42a14ac64980a8c8f59a2ec4, 15: 0x85aac367cc487b14c5c95b8c2154c1b0}
_TICKMATH_RESIDUAL = {1: 0xffffffd3a37a05e383e14c90273c94f5, 2: 0xffffffa746f41376f74124cd483186d4, 3: 0xffffff7aea6e28ba5a1e33b2f9234215}


def price_factor_at_tick(tick: int) -> tuple[int, int]:
    """Exact port of TickMath32.getPriceFactorAtTick (integer semantics).

    Returns (factor, shift): the dimensionless quote/base raw price is
    ``factor * 2**-shift`` (i.e. factor >> shift in engine integer math).
    """
    scaled = tick * 3
    integer_exponent = scaled >> 26
    fraction = scaled - (integer_exponent << 26)
    if fraction <= 0x2000000:
        inverse = _fraction_factor(fraction)
        factor = ((2**256 - 1) // inverse) + 1
    else:
        integer_exponent += 1
        factor = _fraction_factor(0x4000000 - fraction)
    return factor, 128 - integer_exponent


def _fraction_factor(fraction: int) -> int:
    """Exact port of TickMath32._fractionFactor (nibble tables + residual)."""
    residual = fraction & 0x03
    fraction >>= 2
    factor = _TICKMATH_FACTOR0[fraction & 0x0F]
    nibble = (fraction >> 4) & 0x0F
    if nibble:
        factor = (factor * _TICKMATH_FACTOR1[nibble]) >> 128
    nibble = (fraction >> 8) & 0x0F
    if nibble:
        factor = (factor * _TICKMATH_FACTOR2[nibble]) >> 128
    nibble = (fraction >> 12) & 0x0F
    if nibble:
        factor = (factor * _TICKMATH_FACTOR3[nibble]) >> 128
    nibble = (fraction >> 16) & 0x0F
    if nibble:
        factor = (factor * _TICKMATH_FACTOR4[nibble]) >> 128
    nibble = fraction >> 20
    if nibble:
        factor = (factor * _TICKMATH_FACTOR5[nibble]) >> 128
    if residual:
        factor = (factor * _TICKMATH_RESIDUAL[residual]) >> 128
    return factor


def quote_at_factor(factor: int, shift: int, quantity: int, round_up: bool) -> int:
    """Exact port of DeepstateV1._quoteAtFactor (uint muldiv floor/ceil)."""
    product = quantity * factor
    quote = product >> shift
    if round_up and (product & ((1 << shift) - 1)):
        quote += 1
    return quote


def match_gross_base_raw(node: RestingNode, event_type: str) -> int:
    """Canonical gross base (NVDA raw) per the pinned match semantics.

    AskMatched: delta = correction - 1; gross = floor(q * price) - delta
    BidMatched: delta = correction - 1; gross =  ceil(q * price) + delta
    """
    factor, shift = price_factor_at_tick(node.tick)
    if event_type == "AskMatched":
        return quote_at_factor(factor, shift, node.quantity, False) - (node.correction - 1)
    if event_type == "BidMatched":
        return quote_at_factor(factor, shift, node.quantity, True) + (node.correction - 1)
    raise ValueError(f"UNSUPPORTED_EVENT {event_type}")


def decode_match_log(log: dict) -> dict | None:
    """Decode one canonical Deepstate match event, fail-closed on malformed ABI."""
    if log.get("address", "").lower() != DEEPSTATE_ROUTER.lower():
        return None
    topics = log.get("topics") or []
    if len(topics) != 1:
        return None
    event_type = SUPPORTED_MATCH_TOPICS.get(str(topics[0]).lower())
    if event_type is None:
        return None
    data = log.get("data", "0x")
    if not isinstance(data, str) or not data.startswith("0x") or (len(data) - 2) % 64:
        return None
    try:
        raw = bytes.fromhex(data[2:])
        if event_type in ("AskMatched", "BidMatched"):
            if len(raw) != 64:
                return None
        elif event_type in ("AsksMatched", "BidsMatched"):
            if len(raw) < 96:
                return None
        elif len(raw) != 128:
            return None

        book_id = "0x" + raw[:32].hex()
        if book_id.lower() != DEEPSTATE_BOOK_ID.lower():
            return None

        matches: list[dict] = []
        if event_type in ("AskMatched", "BidMatched"):
            matches.append({"match_index": 0,
                            "node": decode_resting_node("0x" + raw[32:64].hex()),
                            "side": event_type})
        elif event_type in ("AsksMatched", "BidsMatched"):
            _, nodes = _abi_decode_nodes(data)
            for match_index, node_bytes in enumerate(nodes):
                matches.append({"match_index": match_index,
                                "node": decode_resting_node("0x" + node_bytes.hex()),
                                "side": "AskMatched" if event_type == "AsksMatched" else "BidMatched"})
        else:
            quantity_word = raw[64:96]
            if any(quantity_word[:12]):
                return None
            matches.append({
                "match_index": 0,
                "subtree_root": "0x" + raw[32:64].hex(),
                "quantity_token0_raw": int.from_bytes(quantity_word, "big"),
                "quote_amount_token1_raw": int.from_bytes(raw[96:128], "big"),
                "side": event_type,
            })
    except (ValueError, OverflowError, KeyError):
        return None

    try:
        return {
            "event_type": event_type,
            "book_id": book_id,
            "matches": matches,
            "log_index": int(log["logIndex"], 16),
            "block_number": int(log["blockNumber"], 16),
            "block_hash": log["blockHash"],
            "transaction_hash": log["transactionHash"],
            "address": log["address"],
        }
    except (KeyError, TypeError, ValueError):
        return None

def _fill_evidence(match: dict, event_type: str) -> tuple[int, int]:
    """Gross (base_raw, quote_raw) for one canonical fill entry.

    Single/batch nodes: gross USDG raw is the node quantity and gross NVDA
    raw follows the exact contract match math (Ask floor-delta / Bid
    ceil+delta).  Subtree forms carry the exact emitted aggregates.
    """
    if "node" in match:
        gross_quote_raw = match["node"].quantity
        gross_base_raw = match_gross_base_raw(match["node"], match["side"])
        return gross_base_raw, gross_quote_raw
    # Deepstate subtree: token0 quantity = USDG; token1 quoteAmount = NVDA.
    # FINCO presentation is NVDA base / USDG quote.
    return match["quote_amount_token1_raw"], match["quantity_token0_raw"]


def match_to_observations(decoded: dict, *, collected_at: datetime,
                          block_timestamp: int | None = None,
                          usdg_usd: tuple[Decimal, datetime] | None = None,
                          freshness_state=None) -> list:  # noqa: F821
    """Map one decoded canonical match log to MARKET MarketObservations.

    One observation per canonical economic fill.  Batch events produce one
    observation per node in execution-priority order; the deterministic
    identity adds ``match_index``.  Freshness is fail-closed: until a
    Deepstate freshness ceiling is approved, observations are persisted
    with FreshnessState.UNAVAILABLE (canonical historical evidence stays
    intact in the payload — it is just never presented as current).
    """
    from finco_radar.venues.observations import FreshnessState, ObservationStatus
    from finco_radar.venues.observations import MarketObservation

    if freshness_state is None:
        freshness_state = FreshnessState.UNAVAILABLE  # fail-closed (see F)
    collected_iso = (collected_at.isoformat() if isinstance(collected_at, datetime)
                     else str(collected_at))
    ts = None
    if block_timestamp is not None:
        ts = datetime.fromtimestamp(block_timestamp, timezone.utc).isoformat()
    observations = []
    for match in decoded["matches"]:
        gross_base_raw, gross_quote_raw = _fill_evidence(match, decoded["event_type"])
        execution_price = (Decimal(gross_quote_raw) * Decimal(10**12)
                           / Decimal(gross_base_raw))     # USDG/NVDA human
        payload = {
            "chain_id": DEEPSTATE_CHAIN_ID,
            "venue": DEEPSTATE_VENUE,
            "venue_market_id": DEEPSTATE_POOL_ID,
            "router": DEEPSTATE_ROUTER.lower(),
            "pool_id": DEEPSTATE_POOL_ID,
            "book_id": decoded["book_id"].lower(),
            "event_type": decoded["event_type"],
            "match_index": match["match_index"],
            "transaction_hash": decoded["transaction_hash"],
            "log_index": decoded["log_index"],
            "block_number": decoded["block_number"],
            "block_hash": decoded["block_hash"],
            "gross_base_amount_nvda": str(int(gross_base_raw)),
            "gross_quote_amount_usdg": gross_quote_raw,
            "deepstate_execution_timestamp": ts,
            "deepstate_freshness_policy": "NOT_YET_APPROVED",
        }
        if usdg_usd is not None and ts is not None:
            normalized, effective = normalize_to_usd(
                execution_price, datetime.fromisoformat(ts),
                usdg_usd[0], usdg_usd[1])
            payload["normalized_usd_price"] = str(normalized)
            payload["usdg_usd_value"] = str(usdg_usd[0])
            payload["usdg_usd_timestamp"] = usdg_usd[1].isoformat()
            payload["effective_evidence_timestamp"] = effective.isoformat()
        observations.append(MarketObservation(
            ts=ts,
            collected_at=collected_iso,
            canonical_asset_id="NVDA",
            venue_id=DEEPSTATE_VENUE,
            instrument_id=DEEPSTATE_POOL_ID,
            instrument_type="tokenized_stock_book",
            price=str(execution_price),
            source="DEEPSTATE_PROTOCOL_ROUTER_V1",
            freshness_state=freshness_state,
            observation_status=ObservationStatus.OK,
            payload=payload,
        ))
    return observations


def fetch_match_logs(rpc_url: str, from_block: int, to_block: int,
                     *, timeout: int = 25) -> list[dict]:
    """Read-only eth_getLogs for canonical Deepstate matches on the Router."""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "eth_getLogs",
        "params": [{
            "address": DEEPSTATE_ROUTER,
            "topics": [list(SUPPORTED_MATCH_TOPICS)],
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
    """Pure optional normalization arithmetic.

    V1 collector intentionally does not acquire USDG/USD here; normalized
    fields remain absent unless reviewed evidence is explicitly supplied.
    """
    normalized = Decimal(usdg_per_nvda) * Decimal(usdg_usd)
    effective = min(deepstate_executed_at, usdg_usd_observed_at)
    return normalized, effective
