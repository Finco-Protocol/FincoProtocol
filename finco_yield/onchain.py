from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Any

import httpx

from .identity import canonical_address
from .registry import CanonicalExecutionBinding

SELECTOR_ASSET="38d52e0f"
SELECTOR_TOTAL_ASSETS="01e1d114"
SELECTOR_TOTAL_SUPPLY="18160ddd"
SELECTOR_DECIMALS="313ce567"
SELECTOR_CONVERT_TO_ASSETS="07a2d13a"
SELECTOR_CONVERT_TO_SHARES="c6e6f592"
SELECTOR_PREVIEW_DEPOSIT="ef8b30f7"
SELECTOR_PREVIEW_REDEEM="4cdad506"
SELECTOR_BALANCE_OF="70a08231"
SELECTOR_ALLOWANCE="dd62ed3e"


class OnchainReadError(RuntimeError):
    pass


def _word(value: int) -> str:
    if value < 0:
        raise ValueError("uint256 must be non-negative")
    return f"{value:064x}"


def _address_word(address: str) -> str:
    return canonical_address(address)[2:].rjust(64,"0")


def _uint(value: str | None) -> int:
    if not value or value == "0x":
        raise OnchainReadError("empty uint result")
    try:
        return int(value,16)
    except ValueError as exc:
        raise OnchainReadError("invalid uint result") from exc


def _address(value: str | None) -> str:
    if not value or len(value.removeprefix("0x")) < 40:
        raise OnchainReadError("empty address result")
    return canonical_address("0x"+value.removeprefix("0x")[-40:])


def rpc_url_for_chain(chain_id: int) -> str | None:
    value=os.getenv(f"FINCO_YIELD_RPC_{chain_id}","").strip()
    return value or None


async def _rpc(client: Any, rpc_url: str, method: str, params: list[Any]) -> Any:
    try:
        response=await client.post(
            rpc_url,
            json={"jsonrpc":"2.0","id":1,"method":method,"params":params},
            timeout=10.0,
        )
        response.raise_for_status()
        payload=response.json()
    except Exception as exc:
        raise OnchainReadError("RPC unavailable") from exc
    if not isinstance(payload,dict) or payload.get("error") is not None or "result" not in payload:
        raise OnchainReadError("RPC returned an error")
    return payload["result"]


async def _call(client: Any,rpc_url: str,contract: str,data: str,block_tag: str) -> str:
    return await _rpc(
        client,
        rpc_url,
        "eth_call",
        [{"to":canonical_address(contract),"data":"0x"+data.removeprefix("0x")},block_tag],
    )


@dataclass(frozen=True)
class Erc4626DirectObservation:
    chain_id:int
    block_number:int
    block_timestamp:datetime
    contract_address:str
    asset_address:str
    share_token:str
    share_decimals:int
    total_assets:int
    total_supply:int
    one_share_assets:int
    one_asset_shares:int
    preview_deposit_assets:int|None
    preview_deposit_shares:int|None
    preview_redeem_shares:int|None
    preview_redeem_assets:int|None
    adapter_version:str="erc4626-rpc-y1.0"
    code_verified:bool=False


async def read_erc4626(
    binding:CanonicalExecutionBinding,
    *,
    rpc_url:str,
    block_number:int|None=None,
    preview_deposit_assets:int|None=None,
    client:Any|None=None,
)->Erc4626DirectObservation:
    owns=client is None
    client=client or httpx.AsyncClient()
    try:
        chain=int(await _rpc(client,rpc_url,"eth_chainId",[]),16)
        if chain!=binding.chain_id:
            raise OnchainReadError("chain id mismatch")
        if block_number is None:
            block_number=int(await _rpc(client,rpc_url,"eth_blockNumber",[]),16)
        if block_number <= 0:
            raise OnchainReadError("invalid block number")
        tag=hex(block_number)
        block=await _rpc(client,rpc_url,"eth_getBlockByNumber",[tag,False])
        if not isinstance(block,dict) or not block.get("timestamp"):
            raise OnchainReadError("block timestamp unavailable")
        block_ts=datetime.fromtimestamp(int(block["timestamp"],16),tz=timezone.utc)
        code=await _rpc(client,rpc_url,"eth_getCode",[binding.contract_address,tag])
        if code in {None,"0x","0x0","0x00"}:
            raise OnchainReadError("vault bytecode unavailable")
        asset=_address(await _call(client,rpc_url,binding.contract_address,SELECTOR_ASSET,tag))
        if asset!=canonical_address(binding.underlying_asset):
            raise OnchainReadError("direct underlying mismatch")
        if canonical_address(binding.share_token)!=canonical_address(binding.contract_address):
            raise OnchainReadError("direct share-token binding mismatch")
        total_assets=_uint(await _call(client,rpc_url,binding.contract_address,SELECTOR_TOTAL_ASSETS,tag))
        total_supply=_uint(await _call(client,rpc_url,binding.contract_address,SELECTOR_TOTAL_SUPPLY,tag))
        decimals=_uint(await _call(client,rpc_url,binding.contract_address,SELECTOR_DECIMALS,tag))
        if decimals>77:
            raise OnchainReadError("share decimals out of range")
        one_share=10**decimals
        one_share_assets=_uint(
            await _call(
                client,
                rpc_url,
                binding.contract_address,
                SELECTOR_CONVERT_TO_ASSETS+_word(one_share),
                tag,
            )
        )
        one_asset_shares=_uint(
            await _call(
                client,
                rpc_url,
                binding.contract_address,
                SELECTOR_CONVERT_TO_SHARES+_word(1),
                tag,
            )
        )
        preview_shares=preview_redeem_assets=None
        if preview_deposit_assets is not None:
            preview_shares=_uint(
                await _call(
                    client,
                    rpc_url,
                    binding.contract_address,
                    SELECTOR_PREVIEW_DEPOSIT+_word(preview_deposit_assets),
                    tag,
                )
            )
            preview_redeem_assets=_uint(
                await _call(
                    client,
                    rpc_url,
                    binding.contract_address,
                    SELECTOR_PREVIEW_REDEEM+_word(preview_shares),
                    tag,
                )
            )
        return Erc4626DirectObservation(
            chain_id=chain,
            block_number=block_number,
            block_timestamp=block_ts,
            contract_address=canonical_address(binding.contract_address),
            asset_address=asset,
            share_token=canonical_address(binding.share_token),
            share_decimals=decimals,
            total_assets=total_assets,
            total_supply=total_supply,
            one_share_assets=one_share_assets,
            one_asset_shares=one_asset_shares,
            preview_deposit_assets=preview_deposit_assets,
            preview_deposit_shares=preview_shares,
            preview_redeem_shares=preview_shares,
            preview_redeem_assets=preview_redeem_assets,
            code_verified=True,
        )
    finally:
        if owns:
            await client.aclose()


async def read_allowance(
    *,
    chain_id:int,
    token_address:str,
    owner:str,
    spender:str,
    rpc_url:str,
    client:Any|None=None,
)->tuple[int,int]:
    owns=client is None
    client=client or httpx.AsyncClient()
    try:
        chain=int(await _rpc(client,rpc_url,"eth_chainId",[]),16)
        if chain!=chain_id:
            raise OnchainReadError("chain id mismatch")
        block=int(await _rpc(client,rpc_url,"eth_blockNumber",[]),16)
        data=SELECTOR_ALLOWANCE+_address_word(owner)+_address_word(spender)
        return _uint(await _call(client,rpc_url,token_address,data,hex(block))),block
    finally:
        if owns:
            await client.aclose()


async def read_share_balance(
    *,
    chain_id:int,
    token_address:str,
    wallet_address:str,
    rpc_url:str,
    client:Any|None=None,
)->tuple[int,int,int]:
    owns=client is None
    client=client or httpx.AsyncClient()
    try:
        chain=int(await _rpc(client,rpc_url,"eth_chainId",[]),16)
        if chain!=chain_id:
            raise OnchainReadError("chain id mismatch")
        block=int(await _rpc(client,rpc_url,"eth_blockNumber",[]),16)
        tag=hex(block)
        decimals=_uint(await _call(client,rpc_url,token_address,SELECTOR_DECIMALS,tag))
        balance=_uint(
            await _call(
                client,
                rpc_url,
                token_address,
                SELECTOR_BALANCE_OF+_address_word(wallet_address),
                tag,
            )
        )
        return balance,decimals,block
    finally:
        if owns:
            await client.aclose()
