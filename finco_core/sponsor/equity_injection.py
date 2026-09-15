"""Phase 6F-B — Equity Injection schema foundation.

Immutable dataclass for sponsor equity injection events.
Audit-friendly, deterministic, no waterfall mutation.

Future Phase 7 sponsor economics will use this schema for capital account evolution.
"""
from __future__ import annotations

import math
import json as _json
from typing import Any


class EquityInjection:
    """Single equity injection event from sponsor into a project entity.

    Immutable. Validated on construction. Designed for audit trail and
    future sponsor capital account integration.

    Parameters
    ----------
    period_index : int
        Semiannual period index (0-based) when the injection occurs.
        Must be >= 0.
    amount_keur : float
        Equity amount in thousands of EUR. Must be >= 0 and finite.
    investor_id : str
        Non-empty sponsor/investor identifier (e.g., "SPONSOR-1", "EQUITY-CO-1").
    target_entity : str
        Non-empty target entity code (e.g., "SPV-1", "HOLDCO", "PORTFOLIO").
    purpose : str
        Non-empty reason/purpose for the injection
        (e.g., "equityContribution", "topUp", "reganEquity", "deferredEquity").
    notes : str, optional
        Free-form audit notes.
    metadata : dict[str, Any], optional
        Arbitrary key-value pairs for future extension.
        Stored internally as an immutable frozen sorted tuple of (key, value) items.
        The `metadata` property returns a fresh dict on each access, so callers
        cannot mutate the internal state. Keys and values must be JSON-serializable.

    Attributes
    ----------
    audit_note : str
        Fixed string confirming this is an audit-only artifact (property).
    frozen_metadata : tuple[tuple[str, Any], ...]
        Immutable sorted tuple of metadata items (property).
    """
    __slots__ = (
        '_period_index',
        '_amount_keur',
        '_investor_id',
        '_target_entity',
        '_purpose',
        '_notes',
        '_metadata_tuple',
    )

    def __init__(
        self,
        period_index: int,
        amount_keur: float,
        investor_id: str,
        target_entity: str,
        purpose: str,
        notes: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        # Validate and set period_index
        if not isinstance(period_index, int):
            raise TypeError(f"period_index must be int, got {type(period_index).__name__}")
        if period_index < 0:
            raise ValueError(f"period_index must be >= 0, got {period_index}")
        object.__setattr__(self, '_period_index', period_index)

        # Validate and set amount_keur
        if not isinstance(amount_keur, float):
            raise TypeError(f"amount_keur must be float, got {type(amount_keur).__name__}")
        if amount_keur < 0.0:
            raise ValueError(f"amount_keur must be >= 0, got {amount_keur}")
        if math.isnan(amount_keur) or math.isinf(amount_keur):
            raise ValueError(f"amount_keur must be finite, got {amount_keur}")
        object.__setattr__(self, '_amount_keur', amount_keur)

        # Validate and set investor_id
        if not isinstance(investor_id, str) or not investor_id.strip():
            raise ValueError(f"investor_id must be a non-empty string, got {investor_id!r}")
        object.__setattr__(self, '_investor_id', investor_id)

        # Validate and set target_entity
        if not isinstance(target_entity, str) or not target_entity.strip():
            raise ValueError(f"target_entity must be a non-empty string, got {target_entity!r}")
        object.__setattr__(self, '_target_entity', target_entity)

        # Validate and set purpose
        if not isinstance(purpose, str) or not purpose.strip():
            raise ValueError(f"purpose must be a non-empty string, got {purpose!r}")
        object.__setattr__(self, '_purpose', purpose)

        # Validate and set notes
        if notes is not None and not isinstance(notes, str):
            raise TypeError(f"notes must be str or None, got {type(notes).__name__}")
        object.__setattr__(self, '_notes', notes)

        # Validate and normalize metadata to immutable sorted tuple
        if metadata is None:
            object.__setattr__(self, '_metadata_tuple', ())
        else:
            if not isinstance(metadata, dict):
                raise TypeError(f"metadata must be dict or None, got {type(metadata).__name__}")
            _IMMUTABLE_JSON_SCALARS = (str, int, float, bool, type(None))

            for k, v in metadata.items():
                if not isinstance(k, str):
                    raise TypeError(f"metadata keys must be str, got {type(k).__name__}")
                if not isinstance(v, _IMMUTABLE_JSON_SCALARS):
                    raise TypeError(
                        f"metadata values must be immutable JSON scalars "
                        f"(str, int, float, bool, None); "
                        f"key {k!r} has value of type {type(v).__name__}"
                    )
            object.__setattr__(self, '_metadata_tuple', tuple(sorted(metadata.items())))

    def __repr__(self) -> str:
        return (
            f"EquityInjection(period_index={self._period_index}, "
            f"amount_keur={self._amount_keur}, investor_id={self._investor_id!r}, "
            f"target_entity={self._target_entity!r}, purpose={self._purpose!r}, "
            f"notes={self._notes!r}, metadata={self.metadata})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EquityInjection):
            return NotImplemented
        return (
            self._period_index == other._period_index
            and self._amount_keur == other._amount_keur
            and self._investor_id == other._investor_id
            and self._target_entity == other._target_entity
            and self._purpose == other._purpose
            and self._notes == other._notes
            and self._metadata_tuple == other._metadata_tuple
        )

    def __hash__(self) -> int:
        return hash((
            self._period_index,
            self._amount_keur,
            self._investor_id,
            self._target_entity,
            self._purpose,
            self._notes,
            self._metadata_tuple,
        ))

    # --- Properties ---

    @property
    def period_index(self) -> int:
        return self._period_index

    @property
    def amount_keur(self) -> float:
        return self._amount_keur

    @property
    def investor_id(self) -> str:
        return self._investor_id

    @property
    def target_entity(self) -> str:
        return self._target_entity

    @property
    def purpose(self) -> str:
        return self._purpose

    @property
    def notes(self) -> str | None:
        return self._notes

    @property
    def metadata(self) -> dict[str, Any] | None:
        """Return metadata as a dict. Returns a fresh dict on each call.

        Mutations of the returned dict do not affect the immutable internal state.
        """
        if self._metadata_tuple:
            return dict(self._metadata_tuple)
        return None

    @property
    def frozen_metadata(self) -> tuple[tuple[str, Any], ...]:
        """Return metadata as an immutable sorted tuple of (key, value) items."""
        return self._metadata_tuple

    @property
    def audit_note(self) -> str:
        return (
            "AUDIT-ONLY: Equity injection records are read-only governance artifacts. "
            "They do not modify model outputs or trigger any distribution or payment."
        )

    # --- Methods ---

    def with_metadata(self, **kwargs: Any) -> EquityInjection:
        """Return a new EquityInjection with additional metadata merged in.

        Existing metadata is preserved; new keys override if duplicate.
        Does not mutate the original.
        """
        merged = dict(self._metadata_tuple)
        merged.update(kwargs)
        return EquityInjection(
            period_index=self._period_index,
            amount_keur=self._amount_keur,
            investor_id=self._investor_id,
            target_entity=self._target_entity,
            purpose=self._purpose,
            notes=self._notes,
            metadata=merged,
        )