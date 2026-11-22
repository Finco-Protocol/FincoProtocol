"""Historical pins and rejection behavior survive separately reviewed successors."""
import ast
from pathlib import Path
import subprocess

import pytest


BASE = "76b7215baf9dfe02d83382d6c33d01559eba9641"
REPO = Path(__file__).resolve().parents[1]

APPROVED = {
    "financial_engine/book_basis.py": "1281cc05a5638714e78279968ee739d9af2cfc02",
    "financial_engine/financial_statements/assembly.py": "778610e8bb5c2a61b022f147a601cc0f02d66982",
    "financial_engine/financial_statements/contracts.py": "f5a15655d58b1d4a5ac7c02f0cdde5bc2a069358",
    "financial_engine/financing/generic_product_policy.py": "2894334e7241c4ac9f8967d4ce4ca6ce77a32fa0",
    "financial_engine/financing/junior_debt.py": "2205cfbcca33889975c964a5748797c82af5792f",
    "financial_engine/financing/project.py": "30536cec8779fdb6a490d82fd80bfce2c09e16fe",
    "financial_engine/financing/project_uses.py": "489cbcc800158326a5b3764aef25514b6ad6ab48",
    "financial_engine/project_returns/contracts.py": "2a43b4e82db2fa6eee956970c5a5c6087245b36f",
    "financial_engine/project_returns/model.py": "711bf15d954c5e20cce13fd6df1067e5d00182e2",
    "financial_engine/senior_debt/project_adapter.py": "a73611a117f0c04ecc7bd7350eac64456520f265",
    "financial_engine/shareholder_waterfall/contracts.py": "19cff0f003a9fdf8921cae8e5c18e703d93e2408",
    "financial_engine/shareholder_waterfall/model.py": "e3473e1a2064c8310e41b434da2b0aff9d5753b8",
    "finco_core/inputs/_models.py": "b896d3c071ee22c1c82c48f23d4c169e058c7a7b",
    "finco_core/inputs/junior_debt.py": "ef63e3355f30541a69b503a3a2e2c02feaf1803f",
    "finco_core/inputs/serialization.py": "31f70570376b2f5b50ece583c54c1d9811e90a3c",
}


def historical_authorities():
    original = subprocess.run(["git", "show", f"{BASE}:tests/model_v2_governance.py"],
        cwd=REPO, capture_output=True, check=True).stdout.decode("utf-8-sig")
    maps = {}
    for node in ast.parse(original).body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        for name in names:
            if name.endswith("_AUTHORITIES"):
                maps[name] = ast.literal_eval(node.value)
    return maps


HISTORICAL_AUTHORITIES = historical_authorities()


def test_candidate_release_is_closed():
    from app.workbook.junior_debt_config import ACTIVATION_ENABLED
    assert ACTIVATION_ENABLED is False
