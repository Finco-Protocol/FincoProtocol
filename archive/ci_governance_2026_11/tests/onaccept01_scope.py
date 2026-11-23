"""Finite operator-only acceptance successor over accepted post433 main.

The signature uses only immutable Git facts and closed reviewed transformations.
Only full closure reads foreign working bytes or the predecessor's unchanged
pure evidence validator. No predecessor or composite verdict is a signature input.
"""
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = '0191ef1af9080c7769a86d8fa58dfab936e74305'
BASE_TREE = '0ad5e401ca0efe4cb493eed86a2dfc9085df94ae'
SOURCE_ANCHOR = '5bba59c9607ab47c804c0904f549e6bced6c5d31'
PREDECESSOR_BASE = '91e89bdd2127f5ec5d0e62833a1f9c3397ad5d14'
REVIEWED_OPERATOR_BLOBS = {'scripts/finco_live_acceptance/README.md': '49222d1df87b31e44ffe1377097ce1683c258b2f', 'scripts/finco_live_acceptance/RUNBOOK.md': 'c069c505e983640e20b71451d48259587553517a', 'scripts/finco_live_acceptance/selfcheck_scope.py': 'b12f0b48a4e2dda29e2feca65b1d2e779a887989'}
MANIFEST = 'docs/onaccept01/SOURCE_SUCCESSOR.json'
SCHEMA = 'ON_ACCEPT01_OPERATOR_ONLY_EXACT_SOURCE_V1'
SOURCE_PATHS = frozenset(('scripts/__init__.py', 'scripts/finco_live_acceptance/README.md', 'scripts/finco_live_acceptance/RUNBOOK.md', 'scripts/finco_live_acceptance/__init__.py', 'scripts/finco_live_acceptance/__main__.py', 'scripts/finco_live_acceptance/browser.py', 'scripts/finco_live_acceptance/checks_finco_fixture.py', 'scripts/finco_live_acceptance/evidence.py', 'scripts/finco_live_acceptance/lifecycle.py', 'scripts/finco_live_acceptance/policy.py', 'scripts/finco_live_acceptance/routes.py', 'scripts/finco_live_acceptance/runner.py', 'scripts/finco_live_acceptance/selfcheck.py', 'scripts/finco_live_acceptance/selfcheck_scope.py'))
CURRENT_MAPS = frozenset(('docs/ci_v4/SOURCE_SUCCESSOR.json', 'docs/react_migration/g10_d8/G10_D8_EXACT_SOURCE.json', 'docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json', 'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json', 'docs/react_migration/post413_r17/SOURCE_SUCCESSOR.json', 'docs/react_migration/post413_r18/SOURCE_SUCCESSOR.json', 'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json', 'docs/tax_reference_registry/SOURCE_SUCCESSOR.json'))
HANDOFFS = {'tests/on_bess01_scope.py': (('def _exact(repo, ref, closure):', "def _successor():\n    from tests.fin_v2_cohorts import COHORT_MODULES\n    if 'tests.onaccept01_scope' not in COHORT_MODULES:\n        return None\n    from tests import onaccept01_scope\n    return onaccept01_scope\n\n\ndef effective_pins(repo=None, ref=None, *, signature=False):\n    pins = dict(manifest(repo, ref).get('source_blobs', {}))\n    S = _successor()\n    if S is not None and S.signature_ok(repo, ref):\n        pins.update({p: b for p, b in S.manifest(repo, ref)['source_blobs'].items() if p in S.SUPERSEDED})\n    return pins\n\n\ndef _exact(repo, ref, closure):"), ('        identity_paths = OWNED_PATHS if closure else OWNED_PATHS - CURRENT_MAPS\n        if any(_blob(_read(root, p, ref)) != pins[p] for p in identity_paths):', "        S = _successor()\n        next_ok = S is not None and S.signature_ok(root, ref)\n        next_pins = S.manifest(root, ref)['source_blobs'] if next_ok else {}\n        current_pins = dict(pins, **next_pins)\n        identity_paths = OWNED_PATHS if closure else OWNED_PATHS - CURRENT_MAPS\n        if any(_blob(_read(root, p, ref)) != current_pins[p] for p in identity_paths):"), ('if closure and not _maps_ok(root, ref, pins):', 'if closure and not _maps_ok(root, ref, current_pins):'), ('        if registry != old_registry.replace("\'tests.tax_reference_registry_scope\')", "\'tests.tax_reference_registry_scope\', \'tests.on_bess01_scope\')"):\n            return False\n        allowed = OWNED_PATHS | {MANIFEST}', '        if (registry != old_registry.replace("\'tests.tax_reference_registry_scope\')", "\'tests.tax_reference_registry_scope\', \'tests.on_bess01_scope\')")\n                and not (next_ok and _blob(registry.encode()) == next_pins.get(\'tests/fin_v2_cohorts.py\'))):\n            return False\n        allowed = OWNED_PATHS | {MANIFEST}\n        if next_ok:\n            allowed = allowed | S.OWNED_PATHS | {S.MANIFEST}'), ('    return path in OWNED_PATHS | {MANIFEST} or (ref is None and _generated_evidence_ok(root, path))', '    S = _successor()\n    return (path in OWNED_PATHS | {MANIFEST} or (ref is None and _generated_evidence_ok(root, path))\n            or (S is not None and S.signature_ok(root, ref) and S.allowed_path(path, root, ref)))'), ("return path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref)['source_blobs'].get(path) == value", 'return path in SUPERSEDED and exact_blobs_ok(repo, ref) and effective_pins(repo, ref).get(path) == value')), 'tests/tax_reference_registry_scope.py': (("B.manifest(repo, ref)['source_blobs'].items() if p in B.SUPERSEDED", 'B.effective_pins(repo, ref, signature=signature).items() if p in B.SUPERSEDED'),), 'tests/on_bess01_reviewed_successors.py': (('    from tests import on_bess01_scope as B, fin_v2_cohorts as C\n    root = Path(repo) if repo is not None else B.ROOT', '    from tests import onaccept01_scope as N\n    if N.nontrust_scope_authorized(changed, repo):\n        return True\n    from tests import on_bess01_scope as B, fin_v2_cohorts as C\n    root = Path(repo) if repo is not None else B.ROOT'),)}
GOVERNANCE_PATHS = frozenset(HANDOFFS) | {'tests/fin_v2_cohorts.py', 'tests/onaccept01_scope.py'}
OWNED_PATHS = SOURCE_PATHS | GOVERNANCE_PATHS | CURRENT_MAPS
SUPERSEDED = frozenset(HANDOFFS) | {'tests/fin_v2_cohorts.py'} | CURRENT_MAPS
REVIEWED_OPERATOR_FILES = frozenset(('scripts/finco_live_acceptance/README.md',
    'scripts/finco_live_acceptance/RUNBOOK.md', 'scripts/finco_live_acceptance/selfcheck_scope.py'))
_SCOPE = []
ENCLOSING = ('tests.on_bess01_scope', 'tests.tax_reference_registry_scope', 'tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope', 'tests.fin_v2_d01_scope', 'tests.fin_v2_r1_scope', 'tests.fin_v2_rcux_scope', 'tests.fin_v2_pr394_corr_scope', 'tests.wsv2_core_scope', 'tests.fin_v2_wsv2_scope', 'tests.wf04_scope', 'tests.wf03_lifecycle_scope', 'tests.fin_v2_wf06a_scope', 'tests.fin_v2_integration_409_scope', 'tests.wf06b_scope', 'tests.u1_scope', 'tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', 'tests.u2_scope', 'tests.ci_v4_scope', 'tests.g10_d8_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope', 'tests.ux_pr3b2_scope')


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


@lru_cache(maxsize=None)
def _base(root, *args):
    return _git(root, *args)


def _blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def _read(root, path, ref):
    return (root / path).read_bytes() if ref is None else _git(root, 'show', ref + ':' + path)


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        data = json.loads(_read(root, MANIFEST, ref))
        if (set(data) != {'schema_version','base','base_tree','source_blobs','base_blobs'}
                or data['schema_version'] != SCHEMA or data['base'] != BASE or data['base_tree'] != BASE_TREE
                or not isinstance(data['source_blobs'], dict) or not isinstance(data['base_blobs'], dict)):
            return {}
        return data
    except (OSError,ValueError,TypeError,subprocess.CalledProcessError):
        return {}


@contextmanager
def scoped():
    if _SCOPE:
        yield
        return
    _SCOPE.append({})
    try:
        yield
    finally:
        _SCOPE.pop()


def _verdict(repo, ref, closure):
    key = ('onaccept01',str(repo if repo is not None else ROOT),ref,closure)
    if not _SCOPE:
        for name in ENCLOSING:
            outer = getattr(sys.modules.get(name),'_SCOPE',None)
            if outer:
                if key not in outer[-1]:
                    with scoped():
                        outer[-1][key] = _verdict(repo,ref,closure)
                return outer[-1][key]
        with scoped():
            return _verdict(repo,ref,closure)
    if key not in _SCOPE[-1]:
        _SCOPE[-1][key] = _exact(repo,ref,closure)
    return _SCOPE[-1][key]


def signature_ok(repo=None, ref=None):
    return _verdict(repo,ref,False)


def exact_blobs_ok(repo=None, ref=None):
    return _verdict(repo,ref,True)


def _tip():
    from tests.fin_v2_cohorts import COHORT_MODULES
    if 'tests.post432_l01_l02_scope' not in COHORT_MODULES:
        return None
    from tests import post432_l01_l02_scope
    return post432_l01_l02_scope


def _tip_pins(root, ref):
    T = _tip()
    if T is None or not T.signature_ok(root, ref):
        return {}
    return dict(T.effective_pins(root, ref))


def _tip_map_keys(root, ref):
    T = _tip()
    return tuple(T.map_keys(root, ref)) if T is not None and T.signature_ok(root, ref) else ()


def later_owned(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    T = _tip()
    return T.closure_paths(root, ref) if T is not None and T.signature_ok(root, ref) else frozenset()


def later_supersedes(path, value, repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    T = _tip()
    return T is not None and T.signature_ok(root, ref) and T.supersedes(path, value, root, ref)


def effective_pins(repo=None, ref=None, *, signature=False):
    root = Path(repo) if repo is not None else ROOT
    pins = {p: b for p, b in manifest(root, ref).get('source_blobs', {}).items() if p in SUPERSEDED}
    pins.update(_tip_pins(root, ref))
    return pins


def _reviewed_handoffs_ok(root, ref):
    T = _tip()
    if T is not None and T.signature_ok(root, ref):
        return T.reviewed_edits_ok(root, ref)
    for path, substitutions in HANDOFFS.items():
        expected = _base(root,'show',BASE+':'+path).decode()
        for old,new in substitutions:
            if expected.count(old) != 1:
                return False
            expected = expected.replace(old,new)
        if _read(root,path,ref) != expected.encode():
            return False
    old = _base(root,'show',BASE+':tests/fin_v2_cohorts.py').decode()
    marker = "'tests.on_bess01_scope')"
    return (old.count(marker) == 1 and _read(root,'tests/fin_v2_cohorts.py',ref).decode()
            == old.replace(marker,"'tests.on_bess01_scope', 'tests.onaccept01_scope')"))


def _maps_ok(root, ref, pins, closure=True):
    for path in CURRENT_MAPS:
        expected = json.loads(_base(root,'show',BASE+':'+path))
        for key in ((SUPERSEDED - CURRENT_MAPS) | (set(_tip_pins(root,ref)) & set(_tip_map_keys(root,ref)))) & expected['source_blobs'].keys():
            expected['source_blobs'][key] = pins[key]
        raw = (json.dumps(expected,indent=2,sort_keys=True)+'\n').encode()
        if _blob(raw) != pins[path] or (closure and _read(root,path,ref) != raw):
            return False
    return True


def _exact(repo, ref, closure):
    root = Path(repo) if repo is not None else ROOT
    try:
        from tests.fin_v2_cohorts import COHORT_MODULES
        if __name__ not in COHORT_MODULES:
            return False
        data = manifest(root,ref); pins = data.get('source_blobs',{})
        if set(pins) != OWNED_PATHS or set(data.get('base_blobs',{})) != SUPERSEDED:
            return False
        _git(root,'merge-base','--is-ancestor',BASE,ref or 'HEAD')
        _git(root,'merge-base','--is-ancestor',SOURCE_ANCHOR,ref or 'HEAD')
        if _base(root,'rev-parse',BASE+'^{tree}').decode().strip() != BASE_TREE:
            return False
        old = {line.split('\t')[1]:line.split()[2] for line in _base(root,'ls-tree','-r',BASE,'--',*sorted(SUPERSEDED)).decode().splitlines()}
        if old != data['base_blobs']:
            return False
        anchor = {line.split('\t')[1]:line.split()[2] for line in _base(root,'ls-tree','-r',SOURCE_ANCHOR,'--',*sorted(SOURCE_PATHS-REVIEWED_OPERATOR_FILES)).decode().splitlines()}
        if (len(anchor) != 11 or any(pins.get(p) != b for p,b in anchor.items())
                or set(REVIEWED_OPERATOR_BLOBS) != REVIEWED_OPERATOR_FILES
                or any(pins.get(p) != b for p,b in REVIEWED_OPERATOR_BLOBS.items())):
            return False
        allowed = OWNED_PATHS | {MANIFEST}
        later = later_owned(root,ref)
        cur = dict(pins, **_tip_pins(root,ref))
        identity = allowed if closure else allowed - CURRENT_MAPS
        if ref is None:
            rows = _git(root,'ls-files','--stage','--',*sorted(identity)).decode().splitlines()
            tracked = {line.split('\t')[1]:line.split('\t')[0].split() for line in rows}
            if (len(rows) != len(identity) or set(tracked) != identity
                    or any(v[0] != '100644' or v[2] != '0' for v in tracked.values())):
                return False
            if any(not (root/p).is_file() or (root/p).is_symlink() or (root/p).stat().st_mode & 0o111 for p in identity):
                return False
            ordered = sorted(identity)
            # One Git invocation hashes the finite reviewed sources with Git clean-filter semantics.
            actual = subprocess.check_output(['git','hash-object','--stdin-paths'],cwd=root,
                input=('\n'.join(ordered)+'\n').encode(),stderr=subprocess.DEVNULL).decode().splitlines()
            if (any(value != cur[p] for p,value in zip(ordered,actual) if p != MANIFEST)
                    or len(actual) != len(ordered)
                    or any(tracked[p][1] != value for p,value in zip(ordered,actual))):
                return False
        else:
            rows = _git(root,'ls-tree','-r',ref,'--',*sorted(identity)).decode().splitlines()
            if len(rows) != len(identity) or any(not line.startswith('100644 blob ') for line in rows):
                return False
            if any(_blob(_read(root,p,ref)) != cur[p] for p in identity if p != MANIFEST):
                return False
        if not _reviewed_handoffs_ok(root,ref) or not _maps_ok(root,ref,cur,closure):
            return False
        if closure:
            changed = set(_git(root,'diff','--name-only','--no-renames',BASE,*([ref] if ref else []),'--').decode().splitlines())
            if not changed <= (allowed | later):
                return False
            if ref is None:
                # A signature never judges foreign drift. Full closure compares ALL accepted foreign bytes/modes directly,
                # including protected BESS files even if the index tries to hide them.
                for line in _base(root,'ls-tree','-r',BASE).decode().splitlines():
                    meta,path = line.split('\t',1)
                    if path in allowed or path in later:
                        continue
                    mode,kind,pin = meta.split(); p=root/path
                    if (kind != 'blob' or mode not in ('100644','100755') or not p.is_file() or p.is_symlink()
                            or _blob(p.read_bytes()) != pin or bool(p.stat().st_mode & 0o111) != (mode=='100755')):
                        return False
                from tests.on_bess01_scope import _generated_evidence_ok
                extra = _git(root,'ls-files','--others','--exclude-standard').decode().splitlines()
                if any(not _generated_evidence_ok(root,p) for p in extra):
                    return False
        return True
    except (OSError,ValueError,TypeError,KeyError,subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS | {MANIFEST} or path in later_owned(repo, ref)


def base_blob(path, repo=None, ref=None):
    return manifest(repo,ref).get('base_blobs',{}).get(path)


def supersedes(path, value, repo=None, ref=None):
    return path in SUPERSEDED and signature_ok(repo,ref) and effective_pins(repo,ref).get(path)==value


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite
    return exact_blobs_ok(repo,ref) and composite(repo,ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo,ref).get('source_blobs',{})
    raw = source.encode() if isinstance(source,str) else source
    return path in pins and exact_blobs_ok(repo,ref) and (source is None or _blob(raw)==pins[path])


def protected_blobs(repo=None, ref=None):
    return {}


def nontrust_scope_authorized(changed, repo=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        T = _tip()
        if T is not None and T.signature_ok(root) and T.nontrust_scope_authorized(changed, root):
            return True
        if _git(root,'merge-base','origin/main','HEAD').decode().strip() != BASE:
            return False
        actual = _git(root,'diff',BASE,'--name-only').decode().splitlines()
        predecessor = _git(root,'diff',PREDECESSOR_BASE,'--name-only').decode().splitlines()
        if not actual or sorted(changed) not in (sorted(actual),sorted(predecessor)):
            return False
        from tests import fin_v2_cohorts as C
        with C.call_scope():
            return exact_blobs_ok(root) and C.valid(root)
    except (OSError,ValueError,TypeError,subprocess.CalledProcessError):
        return False
