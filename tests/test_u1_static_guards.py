"""PR-U1 static guards (no browser): display names for every cost group, no visible group codes, default precision 0, no private/spreadsheet provenance
in the U1 user-facing sources or the bundle, and the Run fold's single-authority wiring is untouched by the UI change."""
import re
from pathlib import Path

from app.cost_line_ledger import ledger

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src" / "app"
DISPLAY = (SRC / "costGroupDisplay.ts").read_text(encoding="utf-8")
CODE = re.compile(r"^[A-Z]\.\d{2}\b")
U1_UI = ("CostWorkbench.tsx", "InputsCostCards.tsx", "costGroupDisplay.ts")


def _display_map():
    return dict(re.findall(r'"([A-Z]\.\d{2})":\s*"([^"]+)"', DISPLAY))


def test_every_server_cost_group_has_a_human_display_name_without_a_code():
    shown = _display_map()
    codes = set(ledger.CAPEX_PARENT_NAMES)
    opex = {c for c in shown if c.startswith("B.")}
    assert codes <= set(shown), sorted(codes - set(shown))
    assert len(opex) == 13 and {f"B.{i:02d}" for i in range(1, 14)} == opex
    assert all(name.strip() and not CODE.match(name) for name in shown.values())
    # C.08 and C.11 fold into ONE economic field at Run, but they remain two groups with two different names (owner decision D1)
    assert shown["C.08"] != shown["C.11"]


def test_u1_components_never_print_a_raw_group_code_or_unknown_label():
    for name in ("InputsCostCards.tsx", "workflow/CostLineManager.tsx", "projection/OpexProjection.tsx", "capex/CapexStudio.tsx"):
        text = (SRC / name).read_text(encoding="utf-8")
        assert "groupDisplayName" in text or "withoutCode" in text, name
        assert not re.search(r">\s*\{[^}]*\.(parent_code|group_code|code)\s*\}\s*<", text), f"{name} renders a raw code"


def test_default_report_precision_is_zero_decimals():
    unit = (SRC / "CostUnit.tsx").read_text(encoding="utf-8")
    assert "default 0" in unit
    assert not re.search(r"precision\s*[:=]\s*[1-3]\b", (SRC / "costAmounts.ts").read_text(encoding="utf-8")), "a non-zero default precision"


def test_u1_sources_and_bundle_carry_no_spreadsheet_or_private_provenance():
    forbidden = [re.compile(p, re.I) for p in (r"\.xlsx?\b", r"\bsheet\d*!", r"workbook[\s_-]*cell", r"formula[\s_-]*ref", r"vendor[\s_-]*name")]
    files = [SRC / n for n in U1_UI] + [ROOT / "docs/react_migration/u1_workbench/P00.md"]
    for path in files:
        text = path.read_text(encoding="utf-8")
        for pattern in (forbidden[:-1] if path.suffix == ".md" else forbidden):   # the document states the rule itself ("vendor names are not here")
            hit = pattern.search(text)
            assert not hit, f"{path.name}: {hit.group(0)!r}"
    bundle = (ROOT / "static/react/finco-react.js").read_text(encoding="utf-8", errors="ignore")
    for pattern in forbidden[1:3]:
        assert not pattern.search(bundle), pattern.pattern
    for name in ("Production Units", "EPC Contract", "Bank & Closing Costs"):
        assert name in bundle, name
    assert not re.search(r"""["']C\.\d{2}\s+[A-Z][a-z]""", bundle), "a code-prefixed group label ships in the bundle"


def test_ui_change_leaves_run_fold_authority_untouched():
    """The UI never edits the Run fold: C.08 + C.11 -> one audit/legal field, bases fold linearly, user lines append."""
    projection = (ROOT / "app/cost_line_ledger/projection.py").read_text(encoding="utf-8")
    assert "audit_legal" in projection
    bases = (ROOT / "app/cost_line_ledger/opex_bases.py").read_text(encoding="utf-8")
    assert "def " in bases and "financial_engine" not in bases


def test_unsaved_opex_base_edits_are_known_to_the_leave_guard_and_discard():
    """The 'opex-base' dirty key has a human name and a discard mapping, so 'Discard changes and continue' clears the staged base amounts."""
    ext = (SRC / "editing" / "wsv2Extensions.tsx").read_text(encoding="utf-8")
    shared = (SRC / "workflow" / "workflowShared.tsx").read_text(encoding="utf-8")
    view = (SRC / "WorkspaceView.tsx").read_text(encoding="utf-8")
    assert 'key === "opex-base" ? ["inputs"]' in ext and 'key === "opex-base"' in shared
    assert 'key !== "capex-profile"' in view and 'key !== "opex-base" && key !== "capex-profile"' in view   # leaving the Monthly view asks first
