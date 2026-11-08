"""Fail-closed target, identity and network policy; no configurable production writer."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qs

PREFIX = 'ZZ-SYNTH-ONACCEPT01-'
PRODUCTION = 'app.finco.one'
LOOPBACK = {'localhost', '127.0.0.1', '::1'}
READ_API = frozenset({
 '/v2/model-react/library', '/v2/model-react/my-projects', '/v2/model-react/templates',
 '/v2/model-react/workspace', '/v2/model-react/inputs', '/v2/model-react/statements',
 '/v2/model-react/costlines', '/v2/model-react/revenue', '/v2/model-react/runs',
 '/v2/model-react/diagnostics', '/v2/model-react/trust', '/v2/model-react/scenarios',
 '/v2/model-react/fields/debt', '/v2/model-react/fields/project_setup',
 '/v2/model-react/fields/tax', '/v2/model-react/fields/revenue',
 '/v2/model-react/financing/studio', '/v2/model-react/analysis/credit-decision',
 '/v2/model-react/opex-projection', '/v2/model-react/opex-run-projection',
 '/v2/model-react/revenue-contracts', '/v2/model-react/setup-drafts',
 '/v2/model-react/new-project/options', '/v2/model-react/new-project/preview',
 '/v2/model-react/new-project/status',
})

class Refused(ValueError):
    """A fixed reason code, never an exception containing request secrets."""


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def target(value: str) -> str:
    try:
        u=urlsplit(value)
        port=u.port
    except ValueError:
        raise Refused('INVALID_TARGET') from None
    if (u.username or u.password or u.query or u.fragment or u.path not in ('','/')
        or value!=value.strip() or any(ord(c)<32 for c in value) or '\\' in value or '%' in value or u.hostname not in LOOPBACK | {PRODUCTION}
        or u.scheme not in ('http','https')):
        raise Refused('TARGET_NOT_ALLOWLISTED')
    if u.hostname==PRODUCTION and (u.scheme!='https' or port not in (None,443)):
        raise Refused('PRODUCTION_REQUIRES_HTTPS_DEFAULT_PORT')
    if u.hostname in LOOPBACK and port is None:
        raise Refused('LOCAL_TARGET_REQUIRES_EXPLICIT_PORT')
    return value.rstrip('/')


def origin(value: str) -> tuple[str,str,int]:
    u=urlsplit(value)
    return u.scheme,u.hostname or '',u.port or (443 if u.scheme=='https' else 80)


def writable_target(value: str, allow: bool) -> None:
    value=target(value)
    if urlsplit(value).hostname not in LOOPBACK:
        raise Refused('BLOCKED_UNSAFE_TARGET')
    if not allow:
        raise Refused('SYNTHETIC_WRITE_OPT_IN_REQUIRED')


def safe_label(value: str) -> str:
    return value if re.fullmatch(r'[a-z0-9_-]{1,70}', value) else 'redacted-'+digest(value)[:12]


def checked_scope(payload: dict, project: str, expected_name: str, technology: str | None=None) -> dict:
    p=payload.get('project',{})
    if (payload.get('ok') is not True or p.get('code')!=project or p.get('name')!=expected_name
        or not expected_name.startswith(PREFIX) or p.get('protected_reference') is not False
        or payload.get('save_all',{}).get('available') is not True
        or (technology is not None and p.get('project_type')!=technology)):
        raise Refused('SYNTHETIC_PROJECT_OWNERSHIP_NOT_PROVEN')
    # save_all.available is the existing server's owner==session-user and not-protected guard.
    return {'project_hash':digest(project),'scenario_hash':digest(str(payload.get('workbook',{}).get('scenario_id')))}


@dataclass
class Session:
    storage_state: Path
    account_scope: str
    projects: dict

    @classmethod
    def read(cls, path: Path) -> 'Session':
        try:
            d=json.loads(path.read_text())
            state=Path(d['storage_state']).resolve()
            if (set(d)!={'storage_state','account_scope_sha256','synthetic_account','projects'}
                or d['synthetic_account'] is not True
                or not re.fullmatch('[a-f0-9]{64}',d['account_scope_sha256'])
                or not state.is_file() or state.is_symlink() or not isinstance(d['projects'],dict)):
                raise ValueError()
            for tech,p in d['projects'].items():
                if tech not in ('solar','wind') or set(p)!={'code','name'} or not p['name'].startswith(PREFIX) or not re.fullmatch('[A-Za-z0-9_-]{1,160}',p['code']):
                    raise ValueError()
            return cls(state,d['account_scope_sha256'],d['projects'])
        except (OSError,ValueError,TypeError,KeyError):
            raise Refused('INVALID_PRIVATE_SESSION_SPEC') from None


class NetworkPolicy:
    def __init__(self, base: str, mode='read-only'):
        self.base=target(base)
        if mode=='synthetic-writable':writable_target(base,True)
        self.mode=mode;self.projects=set();self.created={};self.allowed_post=None;self.authenticated=False
        self.attempted_mutations=0;self.sent_mutations=0;self.blocked=[];self.posts=[]

    def permit(self, url: str, method: str, body: str | None=None) -> bool:
        try:
            u=urlsplit(url)
            if origin(url)!=origin(self.base) or u.username or u.password:
                raise Refused('CROSS_ORIGIN_REFUSED')
            if method not in ('GET','HEAD'):
                self.attempted_mutations+=1
                if self.mode!='synthetic-writable' or method!='POST' or self.allowed_post is None or not self.authenticated:
                    raise Refused('MUTATION_BLOCKED')
                path,project,scenario=self.allowed_post
                if u.path!=path:raise Refused('UNEXPECTED_WRITER')
                try:d=json.loads(body or '')
                except ValueError:
                    form=parse_qs(body or '',keep_blank_values=True)
                    if any(len(v)!=1 for v in form.values()):raise Refused('DUPLICATE_FORM_SCOPE_REFUSED')
                    d={k:v[0] for k,v in form.items()}
                if project is not None and (d.get('project')!=project or project not in self.projects):raise Refused('CROSS_PROJECT_REFUSED')
                if path=='/v2/workbook/save-all':
                    if 'scenario_id' not in d or d.get('scenario_id')!=scenario:raise Refused('CROSS_SCENARIO_REFUSED')
                    if d.get('profile_json') is not None or d.get('profiles') or d.get('contracts_json') is not None or d.get('cost_lines'):raise Refused('NON_SCALAR_WRITER_REFUSED')
                if path.endswith('/create') and not str(d.get('name','')).startswith(PREFIX):raise Refused('PROJECT_PREFIX_REFUSED')
                self.allowed_post=None  # one-shot; retries require explicit stage reconciliation
                self.sent_mutations+=1;self.posts.append({'path':path,'body_sha256':digest(body or '')})
                return True
            path=u.path
            # The Legacy workbook GET normalizes saved inputs. Never navigate it in this tool.
            if path.startswith(('/v2/workbook','/logout','/demo','/reset','/reference-seed')):
                raise Refused('STATEFUL_OR_UNAUDITED_GET_BLOCKED')
            if path.startswith('/static/') or path=='/favicon.ico' or path=='/login':return True
            if not self.authenticated and path!='/v2/model-react/setup-drafts':raise Refused('ANONYMOUS_DEMO_PROVISIONING_GET_REFUSED')
            if path in READ_API:
                project=parse_qs(u.query).get('project',[None])[0]
                if project is not None and project not in self.projects:raise Refused('CROSS_PROJECT_READ_REFUSED')
                return True
            if path in ('/v2/model-react','/v2/model-react/'):
                return True
            if path.startswith('/v2/model-react/'):
                code=path.removeprefix('/v2/model-react/').rstrip('/')
                if code in self.projects:return True
            raise Refused('UNREGISTERED_ROUTE_BLOCKED')
        except (Refused,ValueError) as e:
            self.blocked.append(str(e) if isinstance(e,Refused) else 'INVALID_REQUEST_URL')
            return False
