"""Data precondition gate. It can only block live sampling; it can never enable authority."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from finco_radar.authority.contracts import AuthoritySnapshot, AuthorityState


LIVE_SAMPLE_BLOCKED = "RWA_REFLEX_LIVE_SAMPLE_BLOCKED_BY_CANONICAL_DATA"


@dataclass(frozen=True)
class ReflexLivePreflight:
    chain_4663_canonical_identity_count: int
    approved_independent_token_reference_count: int
    premium_available_count: int
    eligible_historical_observation_count: int
    regular_session_observation_count: int
    live_sample_allowed: bool
    reason: str | None

    def to_payload(self) -> dict[str, object]:
        return {
            "chain_4663_canonical_identity_count": self.chain_4663_canonical_identity_count,
            "approved_independent_token_reference_count": self.approved_independent_token_reference_count,
            "premium_available_count": self.premium_available_count,
            "eligible_historical_observation_count": self.eligible_historical_observation_count,
            "regular_session_observation_count": self.regular_session_observation_count,
            "live_sample_allowed": self.live_sample_allowed,
            "reason": self.reason,
        }


def assess_live_sample_preconditions(
    authorities: Iterable[AuthoritySnapshot],
    *,
    eligible_historical_observation_count: int,
    regular_session_observation_count: int,
    minimum_historical_observations: int = 20,
) -> ReflexLivePreflight:
    if min(eligible_historical_observation_count, regular_session_observation_count,
           minimum_historical_observations) < 0:
        raise ValueError("preflight counts must be nonnegative")
    identity = token_reference = premium = 0
    for snapshot in authorities:
        if snapshot.canonical_token.chain_id != 4663 or snapshot.economic_asset_uid is None:
            continue
        identity += 1
        # An AuthoritySnapshot token layer is AVAILABLE only after the authority
        # engine has accepted its independent source under AuthorityPolicy.
        if snapshot.token.state is AuthorityState.AVAILABLE and snapshot.token.source:
            token_reference += 1
        if (snapshot.premium.state is AuthorityState.AVAILABLE
                and snapshot.underlying.state is AuthorityState.AVAILABLE
                and snapshot.token.state is AuthorityState.AVAILABLE
                and snapshot.premium.value_bps is not None):
            premium += 1

    allowed = (
        premium > 0
        and eligible_historical_observation_count >= minimum_historical_observations
        and regular_session_observation_count >= minimum_historical_observations
    )
    return ReflexLivePreflight(
        chain_4663_canonical_identity_count=identity,
        approved_independent_token_reference_count=token_reference,
        premium_available_count=premium,
        eligible_historical_observation_count=eligible_historical_observation_count,
        regular_session_observation_count=regular_session_observation_count,
        live_sample_allowed=allowed,
        reason=None if allowed else LIVE_SAMPLE_BLOCKED,
    )
