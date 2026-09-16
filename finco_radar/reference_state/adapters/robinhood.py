"""R4-owned read-only adapter for the official Robinhood Stock Token
``/corporate-actions`` endpoint.

Wire shape (verified live 2026-09-16, payload top-level key ``corpActions``)::

    {"id": "0x<32-byte hex>",                       # the canonical asset UID
     "type": "CORPORATE_ACTION_TYPE_CASH_DIVIDEND",
     "status": "CORPORATE_ACTION_STATUS_IN_PROGRESS",
     "processDate": {"year": 2026, "month": 10, "day": 14},
     "tokenSymbol": "LRCX",
     "deployments": [{"contractAddress": "0x…", "chainId": 4663,
                      "networkName": "Robinhood Chain"}],
     "details": {"cashDividend": {"underlyingSymbol": "LRCX", "rate": "0.33"}}}

Known types currently include cash/stock dividends and forward/reverse splits;
the API is forward-compatible with additional types and statuses. Unknown
material is preserved verbatim and classified conservatively — never silently
treated as NONE and never borrowed semantics from another action type.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping

import httpx

from finco_radar.assets.contracts import (
    AssetKey,
    RegistrySourceError,
    normalize_symbol,
)

from ..contracts import CorporateActionEvidenceError, CorporateActionRow
from ..contracts import ReferenceStateStatus

_KNOWN_TYPES: frozenset[str] = frozenset(
    {
        "CORPORATE_ACTION_TYPE_FORWARD_SPLIT",
        "CORPORATE_ACTION_TYPE_REVERSE_SPLIT",
        "CORPORATE_ACTION_TYPE_CASH_DIVIDEND",
        "CORPORATE_ACTION_TYPE_STOCK_DIVIDEND",
    }
)
_KNOWN_STATUSES: frozenset[str] = frozenset(
    {
        "CORPORATE_ACTION_STATUS_IN_PROGRESS",
        "CORPORATE_ACTION_STATUS_COMPLETED",
    }
)
_TYPE_VARIANTS: dict[str, str] = {
    "CORPORATE_ACTION_TYPE_FORWARD_SPLIT": "forwardSplit",
    "CORPORATE_ACTION_TYPE_REVERSE_SPLIT": "reverseSplit",
    "CORPORATE_ACTION_TYPE_CASH_DIVIDEND": "cashDividend",
    "CORPORATE_ACTION_TYPE_STOCK_DIVIDEND": "stockDividend",
}
_KNOWN_VARIANTS: frozenset[str] = frozenset(_TYPE_VARIANTS.values())


def _invalid(message: str) -> CorporateActionEvidenceError:
    return CorporateActionEvidenceError(
        message,
        ReferenceStateStatus.CORPORATE_ACTION_EVIDENCE_INVALID,
    )


def _parse_action_uid(value: Any) -> str:
    if not isinstance(value, str):
        raise _invalid("corporate action id must be a string")
    uid = value.strip().lower()
    if not (uid.startswith("0x") and len(uid) == 66):
        raise _invalid("corporate action id must be a 32-byte 0x-prefixed hex value")
    try:
        int(uid[2:], 16)
    except ValueError as exc:
        raise _invalid("corporate action id must be hex") from exc
    return uid


def _parse_process_date(value: Any) -> date | None:
    """processDate is an official calendar date with no time-of-day or zone."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _invalid("processDate must be an object")
    try:
        year = int(value["year"])
        month = int(value["month"])
        day = int(value["day"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid("processDate must contain integer year/month/day") from exc
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise _invalid(f"processDate is not a valid calendar date: {value}") from exc


def _parse_deployments(value: Any) -> tuple[AssetKey, ...]:
    if not isinstance(value, list) or not value:
        raise _invalid("corporate action deployments must be a non-empty list")
    keys: list[AssetKey] = []
    for deployment in value:
        if not isinstance(deployment, Mapping):
            raise _invalid("corporate action deployment must be an object")
        try:
            # RegistrySourceError (raised by the frozen R1 AssetKey contract on
            # malformed addresses/chains) is a ValueError subclass and is
            # intentionally converted here into the R4 typed failure — verified
            # by tests/test_radar_r4_reference_state.py::test_s4.
            keys.append(
                AssetKey(
                    chain_id=int(deployment["chainId"]),
                    contract_address=str(deployment["contractAddress"]),
                )
            )
        except KeyError as exc:
            raise _invalid("corporate action deployment is missing identity") from exc
        except (TypeError, ValueError) as exc:
            raise _invalid("corporate action deployment is malformed") from exc
    if len(set(keys)) != len(keys):
        raise _invalid("corporate action row contains duplicate deployment identity")
    return tuple(keys)


def _parse_details(action_type: str, known_type: bool, value: Any) -> Mapping[str, Any]:
    """Validate the details variant without interpreting its economics.

    Known types must carry their own canonical variant object; a known variant
    of a DIFFERENT action type is a conflict. Unknown/forward types keep their
    raw details verbatim.
    """
    if value is None:
        if known_type:
            raise _invalid(f"corporate action {action_type} is missing its details variant")
        return {}
    if not isinstance(value, Mapping):
        raise _invalid("corporate action details must be an object")
    present_known_variants = sorted(set(value.keys()) & _KNOWN_VARIANTS)
    if known_type:
        expected_variant = _TYPE_VARIANTS[action_type]
        if expected_variant not in value:
            raise _invalid(
                f"corporate action {action_type} is missing details variant "
                f"{expected_variant}"
            )
        foreign = [v for v in present_known_variants if v != expected_variant]
        if foreign:
            raise _invalid(
                f"corporate action {action_type} carries a conflicting details "
                f"variant {foreign[0]}"
            )
        if not isinstance(value[expected_variant], Mapping):
            raise _invalid("corporate action details variant must be an object")
    return dict(value)


class RobinhoodCorporateActionAdapter:
    """Read-only fetcher/parser for the official corporate-actions endpoint."""

    source_name = "ROBINHOOD_STOCK_TOKEN_CORPORATE_ACTIONS_API"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = "https://api.robinhood.com/rhj",
        timeout_seconds: float = 20.0,
    ) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            headers={"accept": "application/json"},
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "RobinhoodCorporateActionAdapter":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def fetch_rows(self) -> tuple[tuple[CorporateActionRow, ...], datetime]:
        """Fetch and parse all rows; return them with the fetch observed time."""
        observed_at = datetime.now(timezone.utc)
        response = self.client.get("/corporate-actions")
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise _invalid("corporate actions endpoint returned invalid JSON") from exc
        return self.parse_rows(payload), observed_at

    @classmethod
    def parse_rows(
        cls,
        payload: Mapping[str, Any],
        *,
        observed_at: datetime | None = None,
    ) -> tuple[CorporateActionRow, ...]:
        if not isinstance(payload, Mapping):
            raise _invalid("corporate actions payload must be an object")
        rows_raw = payload.get("corpActions")
        if not isinstance(rows_raw, list):
            raise _invalid("corporate actions payload must contain a corpActions list")
        return tuple(cls.parse_row(row) for row in rows_raw)

    @classmethod
    def parse_row(cls, row: Any) -> CorporateActionRow:
        if not isinstance(row, Mapping):
            raise _invalid("corporate action row must be an object")
        action_uid = _parse_action_uid(row.get("id"))
        action_type_raw = row.get("type")
        if not isinstance(action_type_raw, str) or not action_type_raw.strip():
            raise _invalid("corporate action type is required")
        action_type = action_type_raw.strip()
        status_raw = row.get("status")
        if not isinstance(status_raw, str) or not status_raw.strip():
            raise _invalid("corporate action status is required")
        status = status_raw.strip()
        known_type = action_type in _KNOWN_TYPES
        known_status = status in _KNOWN_STATUSES
        try:
            # R1 normalization boundary (Correction A): frozen R1 helpers raise
            # RegistrySourceError, which is R1's exception family. At this R4
            # boundary it is converted to the R4-owned typed failure so source
            # corruption can never escape untyped (and can never be mislabelled
            # as infrastructure by the live proof).
            symbol = normalize_symbol(
                str(row.get("tokenSymbol") or ""),
                field_name="corporate action tokenSymbol",
            )
        except RegistrySourceError as exc:
            raise CorporateActionEvidenceError(
                f"corporate action tokenSymbol is malformed: {exc}",
                ReferenceStateStatus.CORPORATE_ACTION_EVIDENCE_INVALID,
            ) from exc
        return CorporateActionRow(
            action_uid=action_uid,
            action_type=action_type,
            status=status,
            token_symbol=symbol,
            deployments=_parse_deployments(row.get("deployments")),
            process_date=_parse_process_date(row.get("processDate")),
            details=_parse_details(action_type, known_type, row.get("details")),
            known_type=known_type,
            known_status=known_status,
            raw_evidence=dict(row),
        )
