import sys, subprocess, collections
root=sys.argv[1]; sys.path.insert(0,root)
from pathlib import Path
from tests import fin_v2_cohorts as K
mods=K.cohorts(); R=Path(root)
print("modules loaded:",[m.__name__.split('.')[-1] for m in mods])
print("exact_blobs_ok per cohort:",{m.__name__.split('.')[-1]:m.exact_blobs_ok(R,None) for m in mods})
anc=subprocess.run(["git","merge-base","--is-ancestor",K.PARENT,"HEAD"],cwd=root).returncode
changed=subprocess.check_output(["git","diff","--name-only",K.PARENT,"--"],cwd=root).decode().splitlines()
rej=[p for p in changed if not any(m.allowed_path(p,R,None) for m in mods)]
print("PARENT ancestor rc:",anc,"| paths changed since PARENT:",len(changed),"| rejected by ALL cohorts:",len(rej))
print("rejected by top-level dir:",dict(collections.Counter(p.split('/')[0]+'/'+p.split('/')[1] if p.count('/')>1 else p for p in rej)))
print("fin_v2_cohorts.valid():",K.valid())
