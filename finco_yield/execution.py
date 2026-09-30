"""Unsigned execution planning only. No private keys, signing or broadcasting."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
from .identity import canonical_address
from .verify import sha256_canonical

@dataclass(frozen=True)
class ExecutionIntent:
    chain_id: int
    opportunity_uid: str
    destination_contract: str
    input_token: str
    output_token: str
    amount: int
    receiver: str

@dataclass(frozen=True)
class Approval:
    token: str
    spender: str
    amount: int
    unlimited: bool = False

@dataclass(frozen=True)
class TransactionPayload:
    to: str
    data: str
    value: int = 0

@dataclass(frozen=True)
class ExecutionQuote:
    quote_id: str
    created_at: datetime
    expires_at: datetime
    input_fingerprint: str
    destination_contract: str
    receiver: str
    expected_output: str | None
    provider: str
    route_hash: str
    chain_id: int
    amount: int
    input_token: str

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

class ExecutionValidationError(ValueError): pass

def input_fingerprint(intent: ExecutionIntent) -> str:
    return sha256_canonical({"chain_id":intent.chain_id,"opportunity_uid":intent.opportunity_uid,"destination_contract":canonical_address(intent.destination_contract),"input_token":canonical_address(intent.input_token),"output_token":canonical_address(intent.output_token),"amount":intent.amount,"receiver":canonical_address(intent.receiver)})

def route_hash(route: tuple[str,...], destination_contract: str, receiver: str) -> str:
    return sha256_canonical({"route":list(route),"destination_contract":canonical_address(destination_contract),"receiver":canonical_address(receiver)})

def build_direct_erc4626_deposit(intent: ExecutionIntent, ttl_seconds: int = 30) -> TransactionPlan:
    selector="6e553f65"
    amount_word=f"{intent.amount:064x}"
    receiver_word=canonical_address(intent.receiver)[2:].rjust(64,"0")
    data="0x"+selector+amount_word+receiver_word
    route=("DIRECT_ERC4626_DEPOSIT",)
    now=datetime.now(timezone.utc)
    quote=ExecutionQuote("direct_"+uuid.uuid4().hex,now,now+timedelta(seconds=ttl_seconds),input_fingerprint(intent),intent.destination_contract,intent.receiver,None,"DIRECT",route_hash(route,intent.destination_contract,intent.receiver),intent.chain_id,intent.amount,intent.input_token)
    return TransactionPlan(quote,route,transactions=(TransactionPayload(canonical_address(intent.destination_contract),data,0),),provider_attribution="Direct protocol execution")

def validate_quote(intent: ExecutionIntent, plan: TransactionPlan, now: datetime|None=None) -> None:
    now=now or datetime.now(timezone.utc); q=plan.quote
    checks=((q.chain_id==intent.chain_id,"wrong chain"),(canonical_address(q.destination_contract)==canonical_address(intent.destination_contract),"wrong contract"),(canonical_address(q.receiver)==canonical_address(intent.receiver),"wrong receiver"),(q.amount==intent.amount,"modified amount"),(canonical_address(q.input_token)==canonical_address(intent.input_token),"modified input token"),(q.input_fingerprint==input_fingerprint(intent),"modified intent"),(q.route_hash==route_hash(plan.route,intent.destination_contract,intent.receiver),"modified route"),(q.expires_at>now,"expired quote"))
    for ok,msg in checks:
        if not ok: raise ExecutionValidationError(msg)
    if any(a.unlimited for a in plan.approvals):
        raise ExecutionValidationError("unlimited approval requires explicit separate disclosure")

def assert_connected_receiver(intent: ExecutionIntent, connected_wallet: str) -> None:
    if canonical_address(intent.receiver)!=canonical_address(connected_wallet):
        raise ExecutionValidationError("receiver must equal connected wallet")

@dataclass(frozen=True)
class PreTradeEvidenceRecord:
    underwriting_snapshot_hash: str
    quote_id: str
    route_hash: str
    destination_contract: str
    receiver: str
    evidence_hashes: tuple[str,...]
    assumptions: object
    @property
    def record_hash(self)->str: return sha256_canonical(self)
