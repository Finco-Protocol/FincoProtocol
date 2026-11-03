"""WF-06B U-06 / P-04: user-facing React source and CSS never expose spreadsheet provenance (static layer; the HTTP layer is in
test_wf06b_costlines_route.py). Legitimate 'paste from Excel' guidance and Excel-format export choices are deliberately allowed."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = [
    re.compile(r"excel[\s_-]*source", re.I),
    re.compile(r"source[\s_-]*(workbook|sheet|cell)", re.I),
    re.compile(r"excel_source_ref|cell_ref|workbook_path|formula_ref", re.I),
    re.compile(r"""['"A-Za-z_ ]+![$]?[A-Z]{1,3}[$]?\d+"""),          # Sheet!A1 / 'Cost Sheet'!$B$4
]


# The Model Import review table shows the owner's OWN uploaded file position (sheet / cell) while mapping it; that is import UX, not cost-line
# provenance, and Excel import is outside WF-06B. Whether to remove it is an open OWNER DECISION (see P00.md), so it is exempted by exact path.
IMPORT_UX_EXEMPT = frozenset({"frontend/src/app/importer/ImportWorkspace.tsx", "frontend/src/app/importer/types.ts"})


def _ui_files():
    base = ROOT / "frontend" / "src"
    for ext in ("*.tsx", "*.ts", "*.css"):
        for p in base.rglob(ext):
            if "__tests__" in p.parts or p.name.endswith(".test.ts") or str(p.relative_to(ROOT)) in IMPORT_UX_EXEMPT:
                continue
            yield p


def test_no_excel_source_in_user_facing_frontend_source():
    hits = []
    for path in _ui_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in FORBIDDEN:
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path.relative_to(ROOT)}:{line}: {m.group(0)!r}")
    assert not hits, "spreadsheet provenance in user-facing source:\n" + "\n".join(hits[:20])


def test_cost_line_ui_declares_only_finco_identity():
    src = (ROOT / "frontend/src/app/editing/CostLinesGridView.tsx").read_text()
    # PR-U1 (owner decision D1): the internal group/line code is an identity only (profile lookup, keys) and is never a visible column or marker.
    assert "finco_display_code" in src and "data-finco-code" not in src and "ws2-code" not in src
    types = (ROOT / "frontend/src/app/types.ts").read_text()
    block = types[types.index("export interface CostLineProjectionLine"):types.index("export interface CostLinesPayload")]
    assert not re.search(r"excel|workbook|sheet_(name|ref)|source_cell|cell_ref", block, re.I)
