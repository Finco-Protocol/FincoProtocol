"""A1 Radar API typed error classes.

These are internal service-layer errors; the router maps them to HTTP responses.
Never exposes raw stack traces to callers.
"""
from __future__ import annotations


class AssetUidInvalidError(ValueError):
    """The `economic_asset_uid` parameter failed normalize_asset_uid() validation."""

    def __init__(self, uid: str, reason: str = "") -> None:
        self.uid = uid
        msg = f"Invalid economic_asset_uid {uid!r}"
        if reason:
            msg = f"{msg}: {reason}"
        super().__init__(msg)


class AssetNotFoundError(LookupError):
    """The UID is syntactically valid but no canonical asset record exists for it."""

    def __init__(self, uid: str) -> None:
        self.uid = uid
        super().__init__(f"No canonical asset found for uid={uid!r}")


class RegistryUnavailableError(RuntimeError):
    """The asset registry source is unavailable (network/config error)."""


class FundamentalsUnavailableError(RuntimeError):
    """The equity fundamentals DB is unconfigured or unreadable."""


class SimulationRequestInvalidError(ValueError):
    """The request body (direction or notional_usd) failed validation."""

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(detail or "Simulation request is invalid")
