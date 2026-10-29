"""Owner-only explicit-field drafts, durable request receipts and version CAS.

No project/workspace/Run/scenario or seeded creator is called by this module.
Promotion stays fail-closed on the canonical readiness blocker.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid

from app.persistence.project_lifecycle_repository import LifecycleError, _now
from app.services.blank_readiness_service import VERTICALS, readiness


def ensure_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS setup_drafts (
        draft_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, technology TEXT NOT NULL,
        name TEXT NOT NULL, country TEXT NOT NULL, fields_json TEXT NOT NULL,
        draft_version INTEGER NOT NULL CHECK(draft_version>=0),
        state TEXT NOT NULL CHECK(state IN ('SETUP_DRAFT','READY','PROMOTED','ABANDONED')),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        requests_json TEXT NOT NULL DEFAULT '{}', promoted_project_id TEXT,
        promotion_key TEXT, promotion_digest TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_setup_drafts_owner ON setup_drafts(user_id,updated_at,draft_id)")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ux_setup_promoted_project
        ON setup_drafts(promoted_project_id) WHERE promoted_project_id IS NOT NULL""")


def _body(data, *, editing):
    keys = {"request_id", "technology", "name", "country", "fields"} | ({"draft_version"} if editing else set())
    if not isinstance(data, dict) or set(data) != keys:
        raise LifecycleError("INVALID_SETUP_BODY", 422)
    if (not isinstance(data["request_id"], str) or re.fullmatch(r"[0-9a-f]{32}", data["request_id"]) is None
            or type(data["technology"]) is not str or data["technology"] not in VERTICALS or type(data["name"]) is not str or len(data["name"]) > 80
            or type(data["country"]) is not str or len(data["country"]) > 8
            or type(data["fields"]) is not dict or len(data["fields"]) > 256
            or any(type(k) is not str or type(v) is not str or len(k)>128 or len(v)>20000 for k,v in data["fields"].items())):
        raise LifecycleError("INVALID_SETUP_BODY", 422)
    if editing and (type(data["draft_version"]) is not int or data["draft_version"] < 0):
        raise LifecycleError("INVALID_SETUP_VERSION", 422)
    from app.workbook.country_options import COUNTRY_CODE_TO_LABEL
    if data["country"] and data["country"] not in COUNTRY_CODE_TO_LABEL:
        raise LifecycleError("INVALID_SETUP_COUNTRY", 422)


def project_view(row):
    explicit = json.loads(row["fields_json"])
    return {"draft_id": row["draft_id"], "technology": row["technology"], "name": row["name"],
            "country": row["country"], "fields": explicit, "draft_version": row["draft_version"],
            "state": row["state"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "readiness": readiness(row["technology"], explicit, name=row["name"], country=row["country"])}


def read(owner, draft_id):
    from app.persistence.db import get_cursor
    with get_cursor() as cur:
        row = cur.execute("SELECT * FROM setup_drafts WHERE user_id=? AND draft_id=?", (owner,draft_id)).fetchone()
        if row is None:
            raise LifecycleError("SETUP_DRAFT_NOT_FOUND", 404)
        return project_view(row)


def list_owned(owner):
    from app.persistence.db import get_cursor
    with get_cursor() as cur:
        return [project_view(row) for row in cur.execute("SELECT * FROM setup_drafts WHERE user_id=? ORDER BY updated_at DESC,draft_id DESC", (owner,))]


def write(owner, data, draft_id=None):
    from app.persistence.db import get_connection
    _body(data, editing=draft_id is not None)
    check = readiness(data["technology"], data["fields"], name=data["name"], country=data["country"])
    # Invalid drafts may be saved for recovery, but unknown/noneditable fields
    # are rejected rather than persisted as a covert arbitrary JSON store.
    from app.services.blank_readiness_service import catalogue
    if set(data["fields"]) - {f["field_id"] for f in catalogue(data["technology"])}:
        raise LifecycleError("SETUP_FIELD_NOT_ALLOWED", 422)
    key=data["request_id"]
    digest=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",", ":"),allow_nan=False).encode()).hexdigest()
    conn=get_connection()
    try:
        conn.execute("BEGIN EXCLUSIVE")
        # Creation keys are unique for this owner across all drafts; update
        # receipts live in their draft and remain independently scoped.
        if draft_id is None:
            row=conn.execute("SELECT * FROM setup_drafts WHERE user_id=? AND json_extract(requests_json,?) IS NOT NULL",
                             (owner, '$."'+key+'"')).fetchone()
        else:
            row=conn.execute("SELECT * FROM setup_drafts WHERE user_id=? AND draft_id=?", (owner,draft_id)).fetchone()
            if row is None: raise LifecycleError("SETUP_DRAFT_NOT_FOUND",404)
        requests=json.loads(row["requests_json"]) if row else {}
        if key in requests:
            receipt=requests[key]
            if receipt["digest"]!=digest or receipt["action"]!=("UPDATE" if draft_id else "CREATE"):
                raise LifecycleError("SETUP_KEY_REUSED")
            conn.rollback()
            return {"ok":True,"replayed":True,"receipt":receipt,"draft":project_view(row)}
        if row and (row["state"] in ("PROMOTED","ABANDONED") or row["draft_version"]!=data["draft_version"]):
            raise LifecycleError("SETUP_STALE")
        if row and row["technology"]!=data["technology"]:
            raise LifecycleError("SETUP_TECHNOLOGY_IMMUTABLE")
        stamp=_now()
        identity=row["draft_id"] if row else uuid.uuid4().hex
        version=row["draft_version"]+1 if row else 0
        receipt={"digest":digest,"request_id":key,"draft_id":identity,"draft_version":version,
                 "action":"UPDATE" if row else "CREATE","occurred_at":stamp}
        requests[key]=receipt
        if len(json.dumps(requests))>1_000_000:
            raise LifecycleError("SETUP_RECEIPT_LIMIT",422)  # no silent receipt pruning/key reuse
        payload=(data["name"],data["country"],json.dumps(data["fields"],sort_keys=True),version,stamp,json.dumps(requests,sort_keys=True))
        if row:
            conn.execute("UPDATE setup_drafts SET name=?,country=?,fields_json=?,draft_version=?,updated_at=?,requests_json=?,state='SETUP_DRAFT' WHERE user_id=? AND draft_id=?",
                         (*payload,owner,identity))
        else:
            conn.execute("INSERT INTO setup_drafts (name,country,fields_json,draft_version,updated_at,requests_json,user_id,draft_id,technology,state,created_at) VALUES (?,?,?,?,?,?,?,?,?,'SETUP_DRAFT',?)",
                         (*payload,owner,identity,data["technology"],stamp))
        current=conn.execute("SELECT * FROM setup_drafts WHERE user_id=? AND draft_id=?",(owner,identity)).fetchone()
        conn.commit()
        return {"ok":True,"replayed":False,"receipt":receipt,"draft":project_view(current)}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def request_status(owner,draft_id,key):
    from app.persistence.db import get_cursor
    if not isinstance(key,str) or re.fullmatch(r"[0-9a-f]{32}",key) is None:
        raise LifecycleError("INVALID_REQUEST_ID",422)
    with get_cursor() as cur:
        row=cur.execute("SELECT * FROM setup_drafts WHERE user_id=? AND draft_id=?",(owner,draft_id)).fetchone()
        if row is None: raise LifecycleError("SETUP_DRAFT_NOT_FOUND",404)
        receipt=json.loads(row["requests_json"]).get(key)
        return {"ok":True,"outcome":"COMMITTED" if receipt else "UNKNOWN","receipt":receipt,"draft":project_view(row)}


def creation_status(owner,key):
    from app.persistence.db import get_cursor
    if not isinstance(key,str) or re.fullmatch(r"[0-9a-f]{32}",key) is None:
        raise LifecycleError("INVALID_REQUEST_ID",422)
    with get_cursor() as cur:
        row=cur.execute("SELECT * FROM setup_drafts WHERE user_id=? AND json_extract(requests_json,?) IS NOT NULL",
                        (owner,'$."'+key+'"')).fetchone()
        if row is None: return {"ok":True,"outcome":"UNKNOWN","receipt":None,"draft":None}
        receipt=json.loads(row["requests_json"])[key]
        if receipt["action"]!="CREATE": return {"ok":True,"outcome":"UNKNOWN","receipt":None,"draft":None}
        return {"ok":True,"outcome":"COMMITTED","receipt":receipt,"draft":project_view(row)}


def promote(owner,draft_id,data):
    # Readiness is recomputed from durable explicit fields, never a browser
    # supplied can_promote flag. No canonical persistence is reached.
    current=read(owner,draft_id)
    if type(data) is not dict or set(data)!={"request_id","draft_version"} or type(data["draft_version"]) is not int or not isinstance(data["request_id"],str) or re.fullmatch(r"[0-9a-f]{32}",data["request_id"]) is None:
        raise LifecycleError("INVALID_PROMOTION_BODY",422)
    if current["draft_version"]!=data["draft_version"]:
        raise LifecycleError("SETUP_STALE")
    raise LifecycleError("UNSEEDED_PROMOTION_UNPROVEN")
