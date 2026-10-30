"""CI V3: independent, exact D-029 source-reference admission successor.

Synthetic reports; the real Trust-source facts are checked by production and
separately protected by tests/test_ci_v3_outcome_reconciliation.py.
"""
import copy
import inspect
import pytest
from tools import ci_v3_production as prod
from tools.ci_v3_schema import ContractError


def phase(call="passed", reason=""):
 return [{"when":"setup","outcome":"passed","reason":"","wasxfail":None},
         {"when":"call","outcome":call,"reason":reason,"wasxfail":None},
         {"when":"teardown","outcome":"passed","reason":"","wasxfail":None}]


def report(items):
 return {"selected":sorted(items),
         "phases":[{"nodeid":n,**p} for n,parts in sorted(items.items()) for p in parts]}


def fixture():
 node=prod.D029_NODE
 old={node:phase("skipped","Skipped: "+prod.D029_SKIP_REASON)}
 accepted={node:phase()}
 accepted.update({n:phase() for n in prod.D029_EVIDENCE_NODES+prod.WS2_EXTRA_NODES})
 reference={"report":report(accepted),
            "native":{n:["passed",""] for n in accepted}}
 original=report(old)
 original_native={node:("skipped","trust pack not part of this diff")}
 return reference,original,original_native


def test_strict_historical_gate_is_not_relaxed():
 reference,original,original_native=fixture()
 with pytest.raises(ContractError,match="accepted reference changed historical outcomes"):
  prod.validate_reference_policy(reference,original)
 assert prod.D029_NODE not in inspect.getsource(prod.validate_reference_policy)
 assert prod.validate_accepted_reference_successor(reference,original,original_native)=="exact-D029-authorized-reference-successor"


def test_unmodified_reference_is_still_admitted_strictly():
 reference,original,original_native=fixture()
 reference["report"]=copy.deepcopy(original)
 reference["native"]={prod.D029_NODE:["skipped","trust pack not part of this diff"]}
 assert prod.validate_accepted_reference_successor(reference,original,original_native)=="historical-phase-exact"


@pytest.mark.parametrize("attack",["second_changed_historical_node","missing_successor_test",
                                    "skipped_new_test","false_native_pass","bad_historical_skip",
                                    "missing_historical_native"])
def test_reference_successor_fails_closed_on_any_other_change(attack):
 ref,old,native=fixture()
 if attack=="second_changed_historical_node":
  original={prod.D029_NODE:phase("skipped","Skipped: "+prod.D029_SKIP_REASON),
            "tests/test_other.py::test_existing":phase("skipped","Skipped: another")}
  old=report(original)
  native["tests/test_other.py::test_existing"]=("skipped","another")
  ref["report"]["selected"].append("tests/test_other.py::test_existing")
  ref["report"]["phases"] += [{"nodeid":"tests/test_other.py::test_existing",**p} for p in phase()]
  ref["native"]["tests/test_other.py::test_existing"]=["passed",""]
 elif attack=="missing_successor_test":
  item=prod.D029_EVIDENCE_NODES[0]
  ref["report"]["selected"].remove(item)
  ref["report"]["phases"]=[p for p in ref["report"]["phases"] if p["nodeid"]!=item]
  del ref["native"][item]
 elif attack=="skipped_new_test":
  item=prod.D029_EVIDENCE_NODES[0]
  for p in ref["report"]["phases"]:
   if p["nodeid"]==item and p["when"]=="call":p["outcome"]="skipped";p["reason"]="not available"
  ref["native"][item]=["skipped","not available"]
 elif attack=="false_native_pass":
  ref["native"][prod.D029_NODE]=["skipped","forged"]
 elif attack=="bad_historical_skip":
  old["phases"][1]["reason"]="Skipped: different"
 elif attack=="missing_historical_native":
  native={}
 with pytest.raises(ContractError):
  prod.validate_accepted_reference_successor(ref,old,native)


def test_unreviewed_exact_trust_blob_cannot_admit_successor(monkeypatch):
 ref,old,native=fixture()
 facts=prod.d029_source_facts()
 facts["blobs"]={**facts["blobs"],"app/trust_readiness/registry.py":"0"*40}
 monkeypatch.setattr(prod,"d029_source_facts",lambda:facts)
 with pytest.raises(ContractError,match="D-029 accepted-source successor proof rejected"):
  prod.validate_accepted_reference_successor(ref,old,native)


def test_d029_node_may_reproduce_its_original_historical_outcome_but_nothing_else_may():
 skipped=[{'nodeid':prod.D029_NODE,'when':w,'outcome':o,'reason':r,'wasxfail':None} for w,o,r in (('setup','passed',''),('call','skipped','Skipped: trust pack not part of this diff'),('teardown','passed',''))]
 native_skip=['skipped','trust pack not part of this diff']
 other='tests/test_other.py::test_x'
 bp={prod.D029_NODE:skipped,other:skipped};bn={prod.D029_NODE:native_skip,other:native_skip}
 f=prod.original_d029_outcome_reproduced
 assert f(prod.D029_NODE,skipped,native_skip,bp,bn)                                  # original outcome, D-029 node only
 assert not f(other,skipped,native_skip,bp,bn)                                       # any other node stays strict
 assert not f(prod.D029_NODE,skipped,['skipped','a different reason'],bp,bn)          # native must be identical
 assert not f(prod.D029_NODE,skipped[:2]+[dict(skipped[2],outcome='failed')],native_skip,bp,bn)
 assert not f(prod.D029_NODE,skipped,native_skip,{},{})                              # no authenticated original, no admission
