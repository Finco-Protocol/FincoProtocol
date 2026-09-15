"""Offline OPEX templates."""

from domain.opex.templates.generic_solar_reference import build_generic_solar_reference_opex_template
from domain.opex.templates.generic_wind_reference import build_generic_wind_reference_opex_template

__all__ = ["build_generic_solar_reference_opex_template", "build_generic_wind_reference_opex_template"]
