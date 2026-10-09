"""Financing F3 — reference compatibility and isolation (NON-AUTHORITATIVE prototype).

Proves the foundation changes nothing: the candidate mapping only READS legacy financing,
ProjectInputs / fingerprints are untouched, no production module imports the candidate, no route
exposes it, and nothing is persisted.
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

from app import project_factories as pf
from app.model_v2.financing_f3_candidate.contracts import (
    CommitmentAuthority,
    InstrumentType,
    candidate_identity,
)
from app.model_v2.financing_f3_candidate.legacy_mapping import map_legacy_financing
from finco_core.inputs import hash_inputs_for_cache, project_inputs_to_dict

REPO = Path(__file__).resolve().parents[1]
REFERENCES = {
    "solar": pf.create_generic_solar_reference,
    "wind": pf.create_generic_wind_reference,
    "data_center": pf.create_generic_data_center_reference,
    "ev": pf.create_generic_ev_charging_reference,
}


@pytest.mark.parametrize("name", sorted(REFERENCES))
class TestLegacyMapping:
    def test_mapping_is_read_only_and_leaves_fingerprints_unchanged(self, name):
        pi = REFERENCES[name]()
        before_dict = copy.deepcopy(project_inputs_to_dict(pi))
        before_hash = hash_inputs_for_cache(pi)
        map_legacy_financing(pi)
        assert project_inputs_to_dict(pi) == before_dict
        assert hash_inputs_for_cache(pi) == before_hash
        assert not hasattr(pi, "financing_instruments")           # ProjectInputs gained nothing

    def test_exactly_one_senior_and_its_amount_is_never_read_as_zero(self, name):
        coll = map_legacy_financing(REFERENCES[name]())
        seniors = [i for i in coll.instruments if i.instrument_type is InstrumentType.SENIOR_TERM_LOAN]
        assert len(seniors) == 1
        assert seniors[0].commitment_keur is None
        assert seniors[0].commitment_authority is CommitmentAuthority.CANONICAL_SIZING_DERIVED

    def test_mapping_is_deterministic(self, name):
        assert candidate_identity(map_legacy_financing(REFERENCES[name]())) == \
            candidate_identity(map_legacy_financing(REFERENCES[name]()))

    def test_explicit_equity_equals_the_legacy_fields(self, name):
        pi = REFERENCES[name]()
        coll = {i.instrument_id: i for i in map_legacy_financing(pi).instruments}
        cap = coll.get("legacy-share-capital")
        assert (cap.commitment_keur if cap else 0.0) == float(pi.financing.share_capital_keur)
        prem = coll.get("legacy-share-premium")
        assert (prem.commitment_keur if prem else 0.0) == float(pi.financing.share_premium_keur)


class TestIsolation:
    NAME = "financing_f3_candidate"

    def _python_files(self):
        for root in ("app", "financial_engine", "finco_core", "domain", "main_web.py"):
            p = REPO / root
            if p.is_file():
                yield p
            elif p.is_dir():
                yield from p.rglob("*.py")

    def test_no_production_module_imports_the_candidate(self):
        offenders = []
        for path in self._python_files():
            if self.NAME in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                if any(self.NAME in m for m in mods):
                    offenders.append(str(path.relative_to(REPO)))
        assert offenders == []

    def test_candidate_package_imports_nothing_from_the_engine_or_persistence(self):
        forbidden = ("financial_engine", "app.persistence", "app.v2", "app.workbook", "fastapi", "sqlite3")
        for path in (REPO / "app/model_v2" / self.NAME).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                        else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                assert not any(m.startswith(forbidden) for m in mods), (path.name, mods)

    def test_no_runtime_route_exposes_the_candidate(self):
        import main_web
        paths = [getattr(r, "path", "") for r in main_web.app.routes]
        assert not [p for p in paths if "f3" in p.lower() or "financing-instrument" in p.lower()]

    def test_candidate_declares_itself_non_authoritative(self):
        import app.model_v2.financing_f3_candidate as pkg
        assert pkg.NON_AUTHORITATIVE is True

    def test_project_inputs_schema_is_unchanged(self):
        import dataclasses
        from finco_core.inputs import ProjectInputs
        names = {f.name for f in dataclasses.fields(ProjectInputs)}
        assert not {n for n in names if "instrument" in n or "tranche" in n or "facilit" in n}
