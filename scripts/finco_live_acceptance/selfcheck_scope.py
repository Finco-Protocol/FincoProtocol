"""MANUAL ONLY bounded source/lineage controls; never auto-collected."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from tests import tax_reference_registry_scope as T,fin_v2_cohorts as C
try:
    from tests import onaccept01_scope as N
except ImportError:
    N=None

@contextmanager
def restore(p):
    p=N.ROOT/p;raw=p.read_bytes();mode=p.stat().st_mode
    try:yield p
    finally:
        if p.is_symlink():p.unlink()
        p.write_bytes(raw);p.chmod(mode)

class SourceChecks(unittest.TestCase):
    def test_current_registered_closed_cohort(self):
        with C.call_scope():self.assertTrue(N.exact_blobs_ok());self.assertTrue(T.exact_blobs_ok());self.assertTrue(C.valid())
    def test_own_byte_mode_link_refused(self):
        for kind in ('byte','mode','link'):
            with self.subTest(kind=kind),restore('scripts/finco_live_acceptance/policy.py') as p:
                if kind=='byte':p.write_bytes(p.read_bytes()+b'\n')
                elif kind=='mode':p.chmod(p.stat().st_mode|0o111)
                else:p.unlink();p.symlink_to(N.ROOT/'scripts/finco_live_acceptance/evidence.py')
                self.assertFalse(N.exact_blobs_ok());self.assertFalse(T.exact_blobs_ok())
    def test_foreign_tracked_and_untracked_refused(self):
        for relative in ('app/onaccept-unreviewed.py','scripts/finco_live_acceptance/unreviewed.py'):
            p=N.ROOT/relative
            try:
                p.write_text('unsigned\n');self.assertFalse(N.exact_blobs_ok());self.assertFalse(C.valid())
                # Source signatures never judge foreign drift, full exactness does.
                self.assertTrue(N.signature_ok());self.assertTrue(T.signature_ok())
            finally:p.unlink(missing_ok=True)
    def test_manifest_base_tree_schema_and_cross_path_pin_refused(self):
        for kind in ('base','base_tree','schema','blob','base_blob'):
            with self.subTest(kind=kind),restore(N.MANIFEST) as p:
                d=json.loads(p.read_text())
                if kind in ('base','base_tree'):d[kind]='0'*40
                elif kind=='schema':d['schema_version']='wrong'
                elif kind=='blob':d['source_blobs']['scripts/finco_live_acceptance/policy.py']=d['source_blobs']['scripts/finco_live_acceptance/evidence.py']
                else:d['base_blobs']['tests/fin_v2_cohorts.py']='0'*40
                p.write_text(json.dumps(d));self.assertFalse(N.exact_blobs_ok());self.assertFalse(T.exact_blobs_ok())
    def test_deregistered_successor_cannot_widen_scope(self):
        with patch.object(C,'COHORT_MODULES',tuple(x for x in C.COHORT_MODULES if x!=N.__name__)):
            self.assertFalse(N.exact_blobs_ok());self.assertFalse(T.exact_blobs_ok());self.assertFalse(C.valid())
    def test_immutable_historical_manifests(self):
        for p in ('docs/tax_reference_registry/SOURCE_SUCCESSOR.json','docs/react_migration/ux_pr3b2/UX_PR3B2_EXACT_SOURCE.json','docs/react_migration/ux_pr3b1/UX_PR3B1_EXACT_SOURCE.json'):
            self.assertEqual((N.ROOT/p).read_bytes(),subprocess.check_output(['git','show',N.BASE+':'+p],cwd=N.ROOT))
    def test_committed_head_and_same_tree_orphan(self):
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=N.ROOT,text=True).strip()
        self.assertTrue(N.exact_blobs_ok(ref=head));self.assertFalse(N.exact_blobs_ok(ref=N.BASE))
        tree=subprocess.check_output(['git','rev-parse',head+'^{tree}'],cwd=N.ROOT,text=True).strip()
        env=dict(os.environ,GIT_AUTHOR_NAME='Synthetic control',GIT_COMMITTER_NAME='Synthetic control',GIT_AUTHOR_EMAIL='synthetic.invalid',GIT_COMMITTER_EMAIL='synthetic.invalid')
        orphan=subprocess.check_output(['git','commit-tree',tree],input='Synthetic ancestry control\n',cwd=N.ROOT,text=True,env=env).strip()
        self.assertFalse(N.exact_blobs_ok(ref=orphan))
    def test_no_automatic_runner_or_test_registration(self):
        changed=subprocess.check_output(['git','diff','--name-only',N.BASE],cwd=N.ROOT,text=True).splitlines()
        self.assertFalse(any(p.startswith(('.github/','app/','frontend/','static/','financial_engine/','finco_core/','domain/','tools/','tax_reference_registry/','revenue_reference_core/')) for p in changed))
        import ast
        for p in (N.ROOT/'scripts/finco_live_acceptance').glob('*.py'):
            self.assertFalse(p.name.startswith('test'))
            ast.parse(p.read_text())

if __name__=='__main__':
    if N is None:
        print('SOURCE_INTEGRATION_BLOCKED_ACTIVE_PR433; private bounded patch-plan required')
        raise SystemExit(2)
    unittest.main(verbosity=2)
