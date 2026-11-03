"""R1 — server-side CHARACTERISATION (not a fix): the Save All endpoint carries no token for the PPA document's own version.

A PPA document serialised under H1 and sent with the CURRENT content hash H2 is accepted and reverts a concurrent term. The fix in this
change is client-side (the document is bound to the version it was serialised from and fails closed in the request builder, see
frontend/src/app/editing/__tests__/editing.test.mjs). This test pins the remaining raw-API behaviour so a future server-side
`contracts_base_token` (owner question O1, NOT approved here) changes it deliberately. Disposable DB; synthetic contracts only.
"""
import json, uuid
from tests.test_save_all_atomic_v1 import world, _project, _body, _state, _identity, URL  # noqa: F401


def _doc(world, rec, price, indexation):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    payload = world.owner.get("/v2/model-react/revenue", params={"project": rec.project_code}).json()
    w = payload["contracts"]["operating_window"]
    return json.dumps({"version": 2, "technology": payload["contracts"].get("technology") or "solar",
                       "indexation_basis": "OPERATING_YEAR",
                       "streams": [{"id": "ppa", "type": "ppa", "start_date": w["start"], "end_date": w["end"],
                                    "volume_share": 1, "price_eur_mwh": price, "indexation_rate": indexation,
                                    "source_ref": "Entered in FINCO workspace", "settlement": "SAME_PERIOD"}]})


def _stored(world, rec):
    payload = world.owner.get("/v2/model-react/revenue", params={"project": rec.project_code}).json()
    s = json.loads(payload["contracts"]["raw"])["streams"][0]
    return {"price_eur_mwh": s["price_eur_mwh"], "indexation_rate": s["indexation_rate"],
            "content_hash": payload["save"]["content_hash"][:12]}


def test_r1_server_without_a_contracts_token_accepts_a_document_authored_under_an_older_version(world):
    rec = _project()
    # H1: a contract book exists (price 55, indexation 2%)
    r = world.owner.post(URL, json=_body(rec, world.owner, cells=[], cost_lines=[], contracts_json=_doc(world, rec, 55, 0.02)))
    assert r.status_code == 200, r.text
    h1, _ = _identity(rec)
    print("\nH1 stored:", _stored(world, rec))
    # Tab A stages a PRICE edit; its document is serialised from the H1 contract (indexation 2%)
    doc_a = _doc(world, rec, 60, 0.02)
    # Tab B changes INDEXATION to 3% and saves -> H2
    r = world.owner.post(URL, json=_body(rec, world.owner, cells=[], cost_lines=[], contracts_json=_doc(world, rec, 55, 0.03)))
    assert r.status_code == 200, r.text
    h2, _ = _identity(rec)
    # Tab A Save All #1 under H1 -> refused, reload:true (the tested two-tab guard)
    r1 = world.owner.post(URL, json=_body(rec, world.owner, cells=[], cost_lines=[], contracts_json=doc_a, content_hash=h1))
    assert r1.status_code == 409
    # Client onRefetch = loadWorkspace only -> identity H2; the staged PPA document is NOT rebuilt (see TOP_RISK_REPRODUCTIONS)
    r2 = world.owner.post(URL, json=_body(rec, world.owner, cells=[], cost_lines=[], contracts_json=doc_a, content_hash=h2,
                                          request_id="req-" + uuid.uuid4().hex[:16]))
    after = _stored(world, rec)
    assert r2.status_code == 200
    assert after["indexation_rate"] == 0.02 and after["price_eur_mwh"] == 60   # raw-API behaviour today (O1): tab B's 3% is reverted
