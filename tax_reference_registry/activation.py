"""Activation seam: fail-closed by construction.

T01-D implements a reference registry only. ``activate_country`` and
``get_effective_run_profile`` exist solely so that any accidental caller
receives a typed refusal instead of an ImportError-driven workaround; they
can never succeed in this phase. All 34 country profiles remain
CANDIDATE_NOT_ACTIVE.
"""
from __future__ import annotations


class ActivationBlockedError(RuntimeError):
    """Raised unconditionally: no country activation exists in this phase."""

    REASON = (
        "ACTIVATION_BLOCKED: the tax reference registry is reference-only "
        "(CANDIDATE_NOT_ACTIVE). Country activation and run-profile selection "
        "require a future owner-approved integration with versioned opt-in, "
        "advisor sign-off and clean-Run acceptance."
    )


def activate_country(*args, **kwargs) -> None:
    """Always fails closed. No arguments can change this."""
    raise ActivationBlockedError(ActivationBlockedError.REASON)


def get_effective_run_profile(*args, **kwargs) -> None:
    """Always fails closed. Returns no profile, no rates, no defaults."""
    raise ActivationBlockedError(ActivationBlockedError.REASON)
