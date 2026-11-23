"""FINCO 35 Batch 2 — Extra Queue: C1F-A-3 encoding alignment & #478 follow-up errors.html 429."""
from __future__ import annotations

import time
import pytest

from app.model_import.intake import IntakeError, SUPPORTED_CSV_ENCODINGS, _csv_rows


def test_c1f_a3_supported_csv_encodings_match_parser_and_exclude_latin1():
    assert "cp1250" in SUPPORTED_CSV_ENCODINGS
    assert "latin-1" not in SUPPORTED_CSV_ENCODINGS

    # cp1250 parses cleanly
    sample = "Field;Value\np50_hours;1500\n".encode("cp1250")
    rows = _csv_rows(sample, encoding="cp1250", start=time.monotonic())
    assert len(rows) == 1 and len(rows[0][1]) >= 2

    # latin-1 fails closed with IMPORT_ENCODING_UNSUPPORTED
    with pytest.raises(IntakeError, match="IMPORT_ENCODING_UNSUPPORTED"):
        _csv_rows(sample, encoding="latin-1", start=time.monotonic())


def test_errors_html_template_exists_and_renders_429_message():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader

    tpl_dir = Path(__file__).resolve().parents[1] / "app" / "templates"
    env = Environment(loader=FileSystemLoader(str(tpl_dir)), autoescape=True)
    tpl = env.get_template("errors.html")
    rendered = tpl.render(error_title="Run limit reached", error_message="Demo sessions are limited to 20 model runs per hour.")
    assert "Run limit reached" in rendered
    assert "20 model runs per hour" in rendered
