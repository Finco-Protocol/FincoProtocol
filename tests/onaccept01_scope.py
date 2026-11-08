"""Closed ON-ACCEPT-01 source provenance. No runner execution on import/check.

One finite source inventory, immutable base/tree/blobs, modes and closed diff.
No financial paths or CI definitions; no predecessor/composite evaluation.
"""
from pathlib import Path
from contextlib import contextmanager
import json
import subprocess

ROOT=Path(__file__).resolve().parents[1]
BASE='91e89bdd2127f5ec5d0e62833a1f9c3397ad5d14'
BASE_TREE='e9573d7802b319deb943dab60667778a431370e4'
MANIFEST='docs/onaccept01/SOURCE_SUCCESSOR.json'
SCHEMA='ON_ACCEPT01_EXACT_SOURCE_V1'
OWNED_PATHS=frozenset(('scripts/__init__.py', 'scripts/finco_live_acceptance/__init__.py', 'scripts/finco_live_acceptance/__main__.py', 'scripts/finco_live_acceptance/policy.py', 'scripts/finco_live_acceptance/routes.py', 'scripts/finco_live_acceptance/evidence.py', 'scripts/finco_live_acceptance/browser.py', 'scripts/finco_live_acceptance/lifecycle.py', 'scripts/finco_live_acceptance/runner.py', 'scripts/finco_live_acceptance/selfcheck.py', 'scripts/finco_live_acceptance/selfcheck_scope.py', 'scripts/finco_live_acceptance/checks_finco_fixture.py', 'scripts/finco_live_acceptance/README.md', 'scripts/finco_live_acceptance/RUNBOOK.md', 'tests/onaccept01_scope.py', 'tests/fin_v2_cohorts.py', 'tests/tax_reference_registry_scope.py', 'tests/ux_pr3b2_scope.py', 'tests/test_tax_reference_registry_scope.py'))
SUPERSEDED=frozenset(('tests/fin_v2_cohorts.py', 'tests/tax_reference_registry_scope.py', 'tests/ux_pr3b2_scope.py', 'tests/test_tax_reference_registry_scope.py'))
INTEGRATION_MANIFESTS=frozenset(('docs/ci_v4/SOURCE_SUCCESSOR.json', 'docs/react_migration/g10_d8/G10_D8_EXACT_SOURCE.json', 'docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json', 'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json', 'docs/react_migration/post413_r17/SOURCE_SUCCESSOR.json', 'docs/react_migration/post413_r18/SOURCE_SUCCESSOR.json', 'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json'))

_SCOPE=[]
_FACTS={}

def _git(root,*args):
    return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL)

def _fact(root,*args):
    k=(str(root),)+args
    if k not in _FACTS:_FACTS[k]=_git(root,*args)
    return _FACTS[k]

def _read(root,p,ref):return (root/p).read_bytes() if ref is None else _git(root,'show',ref+':'+p)

def manifest(repo=None,ref=None):
    try:
        d=json.loads(_read(Path(repo) if repo is not None else ROOT,MANIFEST,ref))
        return d if set(d)=={'schema_version','base','base_tree','source_blobs','base_blobs'} and d['schema_version']==SCHEMA and d['base']==BASE and d['base_tree']==BASE_TREE else {}
    except (OSError,ValueError,TypeError,subprocess.CalledProcessError):return {}

@contextmanager
def scoped():
    if _SCOPE:yield;return
    _SCOPE.append({})
    try:yield
    finally:_SCOPE.pop()

def _verdict(repo,ref,closure):
    if not _SCOPE:
        with scoped():return _verdict(repo,ref,closure)
    k=(str(repo if repo is not None else ROOT),ref,closure)
    if k not in _SCOPE[-1]:_SCOPE[-1][k]=_exact(repo,ref,closure)
    return _SCOPE[-1][k]

def exact_blobs_ok(repo=None,ref=None):return _verdict(repo,ref,True)
def signature_ok(repo=None,ref=None):return _verdict(repo,ref,False)

def _exact(repo,ref,closure):
    from tests.fin_v2_cohorts import COHORT_MODULES
    if __name__ not in COHORT_MODULES:return False
    root=Path(repo) if repo is not None else ROOT
    try:
        d=manifest(root,ref);pins=d.get('source_blobs',{})
        if set(pins)!=OWNED_PATHS or set(d.get('base_blobs',{}))!=SUPERSEDED:return False
        _git(root,'merge-base','--is-ancestor',BASE,ref or 'HEAD')
        if _fact(root,'rev-parse',BASE+'^{tree}').decode().strip()!=BASE_TREE:return False
        baseline={l.split('\t',1)[1]:l.split()[2] for l in _fact(root,'ls-tree','-r',BASE,'--',*sorted(SUPERSEDED)).decode().splitlines()}
        if baseline!=d['base_blobs']:return False
        permitted=OWNED_PATHS|{MANIFEST}|INTEGRATION_MANIFESTS
        if ref is None:
            for p in permitted:
                f=root/p
                if not f.is_file() or f.is_symlink() or f.stat().st_mode&0o111:return False
            computed=dict(zip(sorted(pins),_git(root,'hash-object',*sorted(pins)).decode().splitlines()))
        else:
            ls=_git(root,'ls-tree','-r',ref,'--',*sorted(permitted)).decode().splitlines()
            if len(ls)!=len(permitted) or any(not l.startswith('100644 ') for l in ls):return False
            computed={l.split('\t',1)[1]:l.split()[2] for l in ls if l.split('\t',1)[1] in pins}
        if computed!=pins:return False
        if closure:
            for p in INTEGRATION_MANIFESTS:
                before=json.loads(_fact(root,'show',BASE+':'+p));now=json.loads(_read(root,p,ref))
                if set(now)!=set(before) or any(now[k]!=before[k] for k in before if k!='source_blobs'):return False
                a,b=before['source_blobs'],now['source_blobs']
                if set(a)!=set(b) or any(b[k]!=a[k] and (k not in SUPERSEDED or a[k]!=baseline[k] or b[k]!=pins[k]) for k in a):return False
            changed=set(_git(root,'diff','--name-only','--no-renames',BASE,*([ref] if ref else []),'--').decode().splitlines())
            if changed-permitted:return False
            if ref is None and set(_git(root,'ls-files','--others','--exclude-standard').decode().splitlines())-permitted:return False
        return True
    except (OSError,ValueError,KeyError,TypeError,AttributeError,subprocess.CalledProcessError):return False

def allowed_path(path,repo=None,ref=None):return path in OWNED_PATHS|INTEGRATION_MANIFESTS|{MANIFEST}
def base_blob(path,repo=None,ref=None):return manifest(repo,ref).get('base_blobs',{}).get(path)
def effective_pins(repo=None,ref=None,**_):return dict(manifest(repo,ref).get('source_blobs',{}))
def supersedes(path,value,repo=None,ref=None):return path in SUPERSEDED and exact_blobs_ok(repo,ref) and effective_pins(repo,ref).get(path)==value
def valid(repo=None,ref=None):
    from tests.fin_v2_cohorts import valid as composite
    return exact_blobs_ok(repo,ref) and composite(repo,ref)
def protected_blobs(repo=None,ref=None):return {}
def matches(path,source=None,*,repo=None,ref=None):
    import hashlib
    raw=source.encode() if isinstance(source,str) else source
    return path in OWNED_PATHS and valid(repo,ref) and (raw is None or hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==effective_pins(repo,ref).get(path))
