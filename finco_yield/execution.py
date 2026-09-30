"""Canonical unsigned execution planning. No private keys, signing or broadcasting."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from .evidence_v1 import YieldEvidenceV1, YieldPreTradeEvidenceV1, canonical_hash
from .identity import canonical_address
from .onchain import Erc4626DirectObservation
from .providers import NormalizedProviderQuote
from .registry import CanonicalExecutionBinding, YieldRegistry

SELECTOR_DEPOSIT = "6e553f65"
SELECTOR_APPROVE = "095ea7b3"
MAX_UINT256 = (1 << 256) - 1
DIRECT_AUTHORITY_MAX_AGE_SECONDS = 120
DIRECT_AUTHORITY_MAX_FUTURE_SKEW_SECONDS = 30


class ExecutionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionIntent:
    opportunity_uid: str
    amount: int
    connected_wallet: str
    funding_token: str | None = None
    execution_method: str = "DIRECT_ERC4626"


@dataclass(frozen=True)
class Approval:
    token: str
    spender: str
    amount: int
    current_allowance: int = 0
    observed_block_number: int | None = None
    exact: bool = True
    unlimited: bool = False


@dataclass(frozen=True)
class TransactionPayload:
    to: str
    data: str
    value: int = 0
    purpose: str = ""


@dataclass(frozen=True)
class ExecutionQuote:
    quote_id: str
    created_at: datetime
    expires_at: datetime
    opportunity_uid: str
    opportunity_snapshot_version: str
    chain_id: int
    input_token: str
    amount: int
    receiver: str
    destination_contract: str
    expected_output_token: str
    expected_output: int | None
    expected_output_guaranteed: bool
    provider: str
    route_hash: str
    approval_hash: str
    fee_slippage_hash: str
    authority_block_number: int | None = None
    authority_block_timestamp: datetime | None = None


@dataclass(frozen=True)
class TransactionPlan:
    quote: ExecutionQuote
    route: tuple[str, ...]
    approvals: tuple[Approval, ...] = ()
    transactions: tuple[TransactionPayload, ...] = ()
    slippage_bps: Decimal | None = None
    fees: tuple[str, ...] = ()
    gas_estimate: int | None = None
    provider_attribution: str | None = None
    user_signable: bool = False
    protection_state: str = "REVIEW_ONLY"
    warning: str | None = None

    @property
    def plan_hash(self) -> str:
        return canonical_hash(self)


def _word(value: int) -> str:
    if value < 0 or value > MAX_UINT256:
        raise ExecutionValidationError("uint256 out of range")
    return f"{value:064x}"


def _address_word(address: str) -> str:
    return canonical_address(address)[2:].rjust(64, "0")


def _binding(
    intent: ExecutionIntent,
    registry: YieldRegistry,
    *,
    direct_revalidation: bool,
) -> tuple[CanonicalExecutionBinding, str, str, str]:
    method = intent.execution_method.upper()
    binding = (
        registry.canonical_binding(intent.opportunity_uid)
        if direct_revalidation
        else registry.execution_binding(intent.opportunity_uid)
    )
    if intent.amount <= 0:
        raise ExecutionValidationError("amount must be positive")
    receiver = canonical_address(intent.connected_wallet)
    funding = (
        canonical_address(intent.funding_token)
        if intent.funding_token
        else binding.underlying_asset
    )
    if method not in binding.allowed_execution_methods:
        raise ExecutionValidationError(
            "execution method not allowed for canonical opportunity"
        )
    return binding, receiver, funding, method


def _approval_hash(approvals) -> str:
    return canonical_hash(approvals)


def _fee_hash(fees, slippage) -> str:
    return canonical_hash({"fees": fees, "slippage_bps": slippage})


def _route_hash(
    route,
    transactions,
    binding,
    receiver,
    output_token,
    expected_output,
    provider,
) -> str:
    return canonical_hash(
        {
            "route": route,
            "transactions": transactions,
            "opportunity_uid": binding.opportunity_uid,
            "snapshot_version": binding.snapshot_version,
            "chain_id": binding.chain_id,
            "destination": binding.contract_address,
            "underlying": binding.underlying_asset,
            "share_token": binding.share_token,
            "receiver": receiver,
            "expected_output_token": output_token,
            "expected_output": expected_output,
            "provider": provider,
        }
    )


def _validate_direct_authority(
    observation: Erc4626DirectObservation,
    *,
    now: datetime | None = None,
    max_age_seconds: int = DIRECT_AUTHORITY_MAX_AGE_SECONDS,
) -> None:
    now = now or datetime.now(timezone.utc)
    if observation.block_number <= 0:
        raise ExecutionValidationError("direct authority block is invalid")
    if observation.block_timestamp.tzinfo is None:
        raise ExecutionValidationError("direct authority timestamp must be timezone-aware")
    if observation.code_verified is not True:
        raise ExecutionValidationError("direct authority bytecode was not verified")
    age = (
        now - observation.block_timestamp.astimezone(timezone.utc)
    ).total_seconds()
    if age > max_age_seconds:
        raise ExecutionValidationError("direct authority observation is stale")
    if age < -DIRECT_AUTHORITY_MAX_FUTURE_SKEW_SECONDS:
        raise ExecutionValidationError("direct authority observation is future-dated")
    if observation.preview_deposit_assets is None:
        raise ExecutionValidationError("previewDeposit authority is required")
    if observation.preview_deposit_shares is None:
        raise ExecutionValidationError("previewDeposit result is unavailable")


def build_direct_erc4626_deposit(
    intent: ExecutionIntent,
    *,
    registry: YieldRegistry,
    direct_observation: Erc4626DirectObservation,
    current_allowance: int,
    allowance_block_number: int | None = None,
    ttl_seconds: int = 30,
    now: datetime | None = None,
) -> TransactionPlan:
    binding, receiver, funding, method = _binding(
        intent, registry, direct_revalidation=True
    )
    if method != "DIRECT_ERC4626":
        raise ExecutionValidationError("direct builder requires DIRECT_ERC4626")
    _validate_direct_authority(direct_observation, now=now)
    if funding != binding.underlying_asset:
        raise ExecutionValidationError(
            "direct deposit funding token must equal canonical underlying"
        )
    if (
        direct_observation.chain_id != binding.chain_id
        or canonical_address(direct_observation.contract_address)
        != binding.contract_address
    ):
        raise ExecutionValidationError("direct chain/contract mismatch")
    if canonical_address(direct_observation.asset_address) != binding.underlying_asset:
        raise ExecutionValidationError("direct underlying mismatch")
    if canonical_address(direct_observation.share_token) != binding.share_token:
        raise ExecutionValidationError("direct share-token mismatch")
    if direct_observation.preview_deposit_assets != intent.amount:
        raise ExecutionValidationError("previewDeposit must bind exact amount")
    if current_allowance < 0:
        raise ExecutionValidationError("allowance cannot be negative")

    approvals = []
    txs = []
    if current_allowance < intent.amount:
        approval = Approval(
            binding.underlying_asset,
            binding.contract_address,
            intent.amount,
            current_allowance,
            allowance_block_number,
            True,
            False,
        )
        approvals.append(approval)
        txs.append(
            TransactionPayload(
                binding.underlying_asset,
                "0x"
                + SELECTOR_APPROVE
                + _address_word(binding.contract_address)
                + _word(intent.amount),
                0,
                "EXACT_ERC20_APPROVAL",
            )
        )

    txs.append(
        TransactionPayload(
            binding.contract_address,
            "0x"
            + SELECTOR_DEPOSIT
            + _word(intent.amount)
            + _address_word(receiver),
            0,
            "ERC4626_DEPOSIT",
        )
    )
    route = ("DIRECT_ERC4626", "EXACT_APPROVAL_IF_NEEDED", "DEPOSIT")
    approvals_t = tuple(approvals)
    txs_t = tuple(txs)
    quote_now = now or datetime.now(timezone.utc)
    expected = direct_observation.preview_deposit_shares
    rh = _route_hash(
        route,
        txs_t,
        binding,
        receiver,
        binding.share_token,
        expected,
        "DIRECT",
    )
    quote = ExecutionQuote(
        "direct_" + uuid.uuid4().hex,
        quote_now,
        quote_now + timedelta(seconds=ttl_seconds),
        binding.opportunity_uid,
        binding.snapshot_version,
        binding.chain_id,
        binding.underlying_asset,
        intent.amount,
        receiver,
        binding.contract_address,
        binding.share_token,
        expected,
        False,
        "DIRECT",
        rh,
        _approval_hash(approvals_t),
        _fee_hash((), None),
        direct_observation.block_number,
        direct_observation.block_timestamp,
    )
    return TransactionPlan(
        quote,
        route,
        approvals_t,
        txs_t,
        provider_attribution="Direct ERC-4626 protocol call",
        user_signable=False,
        protection_state="UNPROTECTED_PREVIEW_ONLY",
        warning=(
            "previewDeposit is an estimate, not a guaranteed min-shares output. "
            "Direct signing remains disabled until vault-specific protection is approved."
        ),
    )


def build_routed_plan(
    intent: ExecutionIntent,
    *,
    registry: YieldRegistry,
    provider_quote: NormalizedProviderQuote,
    ttl_seconds: int = 30,
) -> TransactionPlan:
    binding, receiver, funding, method = _binding(
        intent, registry, direct_revalidation=False
    )
    if (
        provider_quote.chain_id != binding.chain_id
        or canonical_address(provider_quote.receiver) != receiver
        or canonical_address(provider_quote.input_token) != funding
        or provider_quote.input_amount != intent.amount
    ):
        raise ExecutionValidationError(
            "provider quote identity/receiver/amount mismatch"
        )
    if provider_quote.expires_at <= datetime.now(timezone.utc):
        raise ExecutionValidationError("provider quote expired")

    if method == "ZERO_X_THEN_DIRECT":
        if (
            provider_quote.provider != "0X_V2"
            or canonical_address(provider_quote.output_token)
            != binding.underlying_asset
        ):
            raise ExecutionValidationError(
                "0x route must end in canonical vault underlying"
            )
        protection = "SWAP_ONLY_REQUIRES_FRESH_DIRECT_DEPOSIT_QUOTE"
    elif method == "ENSO":
        if (
            provider_quote.provider != "ENSO"
            or canonical_address(provider_quote.output_token)
            != binding.share_token
        ):
            raise ExecutionValidationError(
                "Enso route must end in canonical share token"
            )
        protection = "PROVIDER_ROUTE_REVIEW_ONLY"
    else:
        raise ExecutionValidationError("unsupported routed method")

    tx = TransactionPayload(
        provider_quote.transaction.to,
        provider_quote.transaction.data,
        provider_quote.transaction.value,
        f"{provider_quote.provider}_ROUTE",
    )
    approvals = (
        ()
        if not provider_quote.approval_target
        else (
            Approval(
                funding,
                provider_quote.approval_target,
                intent.amount,
                0,
                None,
                True,
                False,
            ),
        )
    )
    route = (method, provider_quote.provider)
    now = datetime.now(timezone.utc)
    rh = _route_hash(
        route,
        (tx,),
        binding,
        receiver,
        provider_quote.output_token,
        provider_quote.expected_output,
        provider_quote.provider,
    )
    q = ExecutionQuote(
        provider_quote.provider.lower() + "_" + uuid.uuid4().hex,
        now,
        min(provider_quote.expires_at, now + timedelta(seconds=ttl_seconds)),
        binding.opportunity_uid,
        binding.snapshot_version,
        binding.chain_id,
        funding,
        intent.amount,
        receiver,
        binding.contract_address,
        provider_quote.output_token,
        provider_quote.expected_output,
        False,
        provider_quote.provider,
        rh,
        _approval_hash(approvals),
        _fee_hash(provider_quote.fee_summary, None),
    )
    return TransactionPlan(
        q,
        route,
        approvals,
        (tx,),
        fees=provider_quote.fee_summary,
        gas_estimate=provider_quote.transaction.gas,
        provider_attribution=provider_quote.provider,
        user_signable=False,
        protection_state=protection,
        warning=(
            "Provider route is normalized and validated but production "
            "mainnet signing is not activated."
        ),
    )


def validate_quote(
    intent: ExecutionIntent,
    plan: TransactionPlan,
    *,
    registry: YieldRegistry,
    now: datetime | None = None,
) -> None:
    q = plan.quote
    binding, receiver, funding, _ = _binding(
        intent,
        registry,
        direct_revalidation=q.provider == "DIRECT",
    )
    now = now or datetime.now(timezone.utc)

    if (
        q.provider == "DIRECT"
        and canonical_address(q.expected_output_token) != binding.share_token
    ):
        raise ExecutionValidationError("share-token substitution")
    if (
        q.provider == "0X_V2"
        and canonical_address(q.expected_output_token) != binding.underlying_asset
    ):
        raise ExecutionValidationError("0x output-token substitution")
    if (
        q.provider == "ENSO"
        and canonical_address(q.expected_output_token) != binding.share_token
    ):
        raise ExecutionValidationError("Enso output-token substitution")
    if q.provider not in {"DIRECT", "0X_V2", "ENSO"}:
        raise ExecutionValidationError("unexpected provider")

    checks = (
        (q.opportunity_uid == binding.opportunity_uid, "opportunity substitution"),
        (
            q.opportunity_snapshot_version == binding.snapshot_version,
            "snapshot mutation",
        ),
        (q.chain_id == binding.chain_id, "chain mutation"),
        (q.amount == intent.amount, "amount mutation"),
        (canonical_address(q.receiver) == receiver, "receiver substitution"),
        (
            canonical_address(q.destination_contract) == binding.contract_address,
            "destination substitution",
        ),
        (canonical_address(q.input_token) == funding, "input token substitution"),
        (q.expires_at > now, "quote expired"),
        (
            q.approval_hash == _approval_hash(plan.approvals),
            "approval mutation",
        ),
        (
            q.fee_slippage_hash == _fee_hash(plan.fees, plan.slippage_bps),
            "fee/slippage mutation",
        ),
        (
            q.route_hash
            == _route_hash(
                plan.route,
                plan.transactions,
                binding,
                receiver,
                q.expected_output_token,
                q.expected_output,
                q.provider,
            ),
            "route/calldata mutation",
        ),
    )
    for ok, msg in checks:
        if not ok:
            raise ExecutionValidationError(msg)

    if q.expected_output_guaranteed:
        raise ExecutionValidationError("unsupported guaranteed-output claim")
    for approval in plan.approvals:
        if (
            approval.unlimited
            or approval.amount == MAX_UINT256
            or not approval.exact
            or approval.amount > intent.amount
        ):
            raise ExecutionValidationError(
                "approval must be exact/minimal and non-unlimited"
            )

    if q.provider == "DIRECT":
        if q.authority_block_number is None or q.authority_block_timestamp is None:
            raise ExecutionValidationError("direct authority identity missing")
        deposits = [
            tx for tx in plan.transactions if tx.purpose == "ERC4626_DEPOSIT"
        ]
        if (
            len(deposits) != 1
            or canonical_address(deposits[0].to) != binding.contract_address
        ):
            raise ExecutionValidationError("wrong direct calldata target")


def build_pre_trade_evidence(
    underwriting: YieldEvidenceV1,
    plan: TransactionPlan,
) -> YieldPreTradeEvidenceV1:
    q = plan.quote
    return YieldPreTradeEvidenceV1(
        q.opportunity_uid,
        q.opportunity_snapshot_version,
        underwriting.canonical_input_hash,
        underwriting.canonical_output_hash,
        q.quote_id,
        q.created_at,
        q.expires_at,
        q.chain_id,
        q.input_token,
        q.amount,
        q.receiver,
        q.destination_contract,
        q.expected_output,
        q.provider,
        q.route_hash,
        q.approval_hash,
        q.fee_slippage_hash,
    )
