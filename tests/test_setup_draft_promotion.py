"""Independent durable-draft CAS/replay/isolation/no-canonical-write oracles."""
import json
import uuid
import pytest
from app.persistence import db
from app.persistence.project_lifecycle_repository import LifecycleError
from app.persistence.setup_draft_repository import write, read, promote, request_status


@pytest.fixture
def draft_db(tmp_path,monkeypatch):
    monkeypatch.setattr(db,"DB_PATH",str(tmp_path/'drafts.sqlite'))
    db.init_db()


def body(tech="wind"):
    return {"request_id":uuid.uuid4().hex,"technology":tech,"name":"My explicit setup","country":"",
            "fields":{"project_setup.technical.capacity_mw":"40"}}


@pytest.mark.parametrize("technology",["solar","wind","data_center","ev_charging"])
def test_durable_setup_replay_and_refused_promotion_make_no_canonical_rows(draft_db,technology):
    data=body(technology)
    made=write("owner",data)
    assert made["draft"]["state"]=="SETUP_DRAFT"
    assert made["draft"]["fields"]==data["fields"]
    assert write("owner",data)["replayed"]
    identity=made["draft"]["draft_id"]
    assert read("owner",identity)["fields"]==data["fields"]
    assert request_status("owner",identity,data["request_id"])["outcome"]=="COMMITTED"
    with pytest.raises(LifecycleError,match="UNSEEDED_PROMOTION_UNPROVEN"):
        promote("owner",identity,{"request_id":uuid.uuid4().hex,"draft_version":0})
    with db.get_cursor() as cur:
        for table in ("projects","workspace_states","scenarios","model_run_history","model_run_intents","save_all_requests"):
            assert cur.execute(f"SELECT count(*) FROM {table}").fetchone()[0]==0


def test_two_tenants_two_tabs_and_changed_body_key_are_independently_scoped(draft_db):
    data=body()
    made=write("owner",data)
    identity=made["draft"]["draft_id"]
    with pytest.raises(LifecycleError) as e: read("stranger",identity)
    assert e.value.status==404
    with pytest.raises(LifecycleError,match="SETUP_KEY_REUSED"):
        write("owner",{**data,"name":"Changed"})
    update={**data,"request_id":uuid.uuid4().hex,"draft_version":0,"name":"Tab A"}
    saved=write("owner",update,identity)
    assert saved["draft"]["draft_version"]==1
    replay=write("owner",update,identity)
    assert replay["replayed"] and replay["receipt"]==saved["receipt"]
    with pytest.raises(LifecycleError,match="SETUP_STALE"):
        write("owner",{**update,"request_id":uuid.uuid4().hex,"name":"Tab B"},identity)
    # Same user-visible creation key in a different tenant creates only that
    # tenant's separate draft, never discloses the first receipt.
    other=write("stranger",data)
    assert other["draft"]["draft_id"]!=identity


def test_noneditable_arbitrary_fields_and_unknown_keys_cannot_be_persisted(draft_db):
    for data in ({**body(),"extra":1},{**body(),"fields":{"unreviewed.hidden.economics":"1"}},
                 {**body(),"fields":{"project_setup.technical.capacity_mw":0}}):
        with pytest.raises(LifecycleError): write("owner",data)
