"""Additive F01 projection successor; all historical pins remain valid."""
import ast,subprocess
from tests import model_mutation_security_successor as S

def test_exactly_one_projection_successor_and_historical_layers_unchanged():
    assert set(S.FINVAL_RATE_SUCCESSORS)=={'app/v2/router.py'}
    old=ast.parse(subprocess.check_output(['git','show','6f10f392:tests/model_mutation_security_successor.py'],cwd=S.ROOT,text=True))
    for node in old.body:
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in {'BLOBS','FINVAL_B2C1_SUCCESSORS','D029_RUN_INTENT_SUCCESSORS'}:
            assert getattr(S,node.targets[0].id)==ast.literal_eval(node.value)
    sources={p:(S.ROOT/p).read_text() for p in S.BLOBS}
    assert S.violations(sources)==[]
    for path,blob in S.FINVAL_RATE_SUCCESSORS.items():
        from tests.fin_v2_3_scope import matches
        assert S.git_blob(sources[path]) in {blob,S.FINVAL_F01_COMPLETE_SUCCESSORS.get(path),S.FINV2_D01_SENSITIVITY_SUCCESSORS.get(path)} or matches(path,sources[path])
        changed=dict(sources);changed[path]+='\n'
        assert S.violations(changed)
        for old_blob in [S.BLOBS[path],S.FINVAL_B2C1_SUCCESSORS[path],S.D029_RUN_INTENT_SUCCESSORS[path]]:
            history=dict(sources);history[path]=subprocess.check_output(['git','cat-file','blob',old_blob],cwd=S.ROOT,text=True)
            assert S.violations(history)==[]
