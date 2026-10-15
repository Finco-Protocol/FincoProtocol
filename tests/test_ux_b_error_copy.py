"""Stream B (UX-031): a refusal leads with the customer sentence; the internal code is only a trailing reference."""
import re

import pytest

from app.v2.router import _ENGINE_FAIL_CLOSED_MESSAGES, _engine_failure_message


@pytest.mark.parametrize("token,message", _ENGINE_FAIL_CLOSED_MESSAGES)
def test_no_refusal_message_starts_with_an_internal_code(token, message):
    assert not re.match(r"^[A-Z][A-Z0-9_]{3,}:", message)
    assert "no Run was saved" in message or "unchanged" in message or "No Run was saved" in message   # honesty about state kept


def test_the_cash_shortfall_refusal_stays_visible_and_keeps_its_reference():
    msg = _engine_failure_message(RuntimeError("F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL"))
    assert msg.startswith("Base cash cannot pay the contractual Senior service")
    assert "Reference: F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL" in msg


def test_the_workbook_page_has_one_main_landmark_one_h1_and_a_skip_link():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "app/templates/v2/workbook.html").read_text(encoding="utf-8")
    assert html.count("<main ") == 1 and html.count("</main>") == 1
    assert html.count("<h1 ") == 1
    assert 'class="v2-skip-link" href="#v2-workbook-shell"' in html
    assert '/static/css/model_tokens.css' in html
