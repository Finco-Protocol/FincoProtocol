import sys, traceback; sys.path.insert(0, ".")
import harness as H, matrix as M
from app.services import production_financial_authority as pfa
import tree
tree.install()
build, ptype, policy = M.CASES[sys.argv[1]]
try:
    pfa.run_clean_production(build(), project_type=ptype)
except Exception as e:
    c = e
    while c.__cause__ or c.__context__:
        c = c.__cause__ or c.__context__
    print("".join(traceback.format_exception(type(c), c, c.__traceback__)[-14:]))
tree.show(tree.stack[0], 0, 6)
