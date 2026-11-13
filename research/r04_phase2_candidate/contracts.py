"""Strict annual-quantity syntax, without selecting an annual delivery policy."""
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
import json
import re

SCHEMA = "R04_P2_ANNUAL_QUANTITY_CANDIDATE_V1"
MAX_BYTES = 100_000


class CandidateError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code
        self.annual_semantics_verified = False
        self.production_supported = False


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CandidateError("R04_P2_DUPLICATE_KEY")
        result[key] = value
    return result


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise CandidateError("R04_P2_SCHEMA")


def _text(value):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 200:
        raise CandidateError("R04_P2_TEXT")
    return value


def _date(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (TypeError, ValueError):
        raise CandidateError("R04_P2_DATE") from None


@dataclass(frozen=True)
class AnnualContract:
    contract_id: str
    start: date
    end: date
    annual_quantity_mwh: Fraction
    pricing_reference: str


@dataclass(frozen=True)
class AnnualBook:
    technology: str
    contracts: tuple[AnnualContract, ...]
    canonical_json: str


def parse_annual_document(raw: str) -> AnnualBook:
    """Parse only syntax. Dates/quantity are NOT an approved delivery schedule.

    Decimal amounts travel as explicit strings, with no quantization or chosen
    business tolerance. Legacy share documents remain owned by their old parser.
    A pricing reference is provenance, never a price or approval authority.
    """
    try:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
            raise CandidateError("R04_P2_DOCUMENT_SIZE")
        obj = json.loads(raw, object_pairs_hook=_unique)
        _keys(obj, {"schema", "version", "technology", "contracts"})
        if (obj["schema"] != SCHEMA or type(obj["version"]) is not int or obj["version"] != 1
                or obj["technology"] not in ("solar", "wind")):
            raise CandidateError("R04_P2_SCHEMA")
        rows = obj["contracts"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 24:
            raise CandidateError("R04_P2_CONTRACTS")
        contracts, seen = [], set()
        for row in rows:
            _keys(row, {"id", "start_date", "end_date", "annual_quantity", "pricing_reference"})
            cid = _text(row["id"])
            if cid in seen:
                raise CandidateError("R04_P2_DUPLICATE_CONTRACT")
            seen.add(cid)
            start, end = _date(row["start_date"]), _date(row["end_date"])
            if end <= start:
                raise CandidateError("R04_P2_DATE")
            quantity = row["annual_quantity"]
            _keys(quantity, {"mode", "amount", "unit"})
            if quantity["mode"] != "ABSOLUTE_ANNUAL" or quantity["unit"] not in ("MWh", "GWh"):
                raise CandidateError("R04_P2_QUANTITY_MODE_OR_UNIT")
            amount = quantity["amount"]
            if (not isinstance(amount, str) or len(amount) > 128
                    or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", amount) is None):
                raise CandidateError("R04_P2_QUANTITY")
            mwh = Fraction(amount) * (1000 if quantity["unit"] == "GWh" else 1)
            if mwh <= 0:
                raise CandidateError("R04_P2_QUANTITY")
            contracts.append(AnnualContract(cid, start, end, mwh, _text(row["pricing_reference"])))
        return AnnualBook(obj["technology"], tuple(contracts), json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False))
    except CandidateError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise CandidateError("R04_P2_SCHEMA") from None


def require_production_contract(_book):
    """A syntactically valid candidate cannot promote itself into Save or Run."""
    raise CandidateError("R04_P2_ANNUAL_DELIVERY_POLICY_AND_PRODUCTION_ADMISSION_REQUIRED")
