import sys,importlib; root=sys.argv[1]; sys.path.insert(0,root)
from pathlib import Path
from tests import fin_v2_cohorts as K, finval_f01_scope as F
R=Path(root); mods=K.cohorts()
bad=[m.__name__.split('.')[-1] for m in mods if not m.exact_blobs_ok(R,None)]
print("cohorts failing exact_blobs_ok:",bad,"| composite valid:",K.valid(),"| F01 scope valid:",F.valid())
