"""Explicit, backward-compatible shareholder-loan calendar authority."""
from enum import Enum


class ShlTimingBasis(str, Enum):
    ABSOLUTE_INDEX = "ABSOLUTE_INDEX"
    COD_RELATIVE = "COD_RELATIVE"


class ShlTimingIssue(str, Enum):
    SHL_MATURITY_NOT_AT_MODEL_END = "SHL_MATURITY_NOT_AT_MODEL_END"
