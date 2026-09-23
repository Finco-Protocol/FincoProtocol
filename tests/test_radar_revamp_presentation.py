"""Presentation-only market precision keeps exact evidence intact."""
from app.radar_ui.router import _market_price_display


def test_market_price_presentation_is_usd_two_decimals_without_float_conversion():
    exact = "340.67774176960105807146"
    assert _market_price_display(exact) == "$340.68"
    assert exact == "340.67774176960105807146"
    assert _market_price_display("0") == "$0.00"
    assert _market_price_display("-5.004") == "-$5.00"
    assert _market_price_display(None) == "—"
    assert _market_price_display("unavailable") == "unavailable"
