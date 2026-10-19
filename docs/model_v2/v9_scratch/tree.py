"""V9-A scratch: nested call tree of the fixed-point hierarchy (runtime wrapping only, no file edits)."""
import sys, time, importlib, functools
sys.path.insert(0, "/home/user/v9")
from app import project_factories as pf
from app.services import production_financial_authority as pfa

TARGETS = [
    ("financial_engine.shareholder_waterfall.model", "run_project_shareholder_waterfall_model", "WF"),
    ("financial_engine.financing.project", "_run_with_construction_idc", "IDC"),
    ("financial_engine.financing.project", "run_project_financing_model", "G2A"),
    ("financial_engine.orchestrator", "run_senior_debt_model", "SDM"),
    ("financial_engine.orchestrator", "_run_senior_debt_model_with_shl", "SHLTAX"),
    ("financial_engine.senior_debt.solver", "solve_senior_debt", "SOLVE"),
]
stack = [{"label": "ROOT", "children": [], "t": 0.0}]

def wrap(orig, label):
    @functools.wraps(orig)
    def w(*a, **k):
        node = {"label": label, "children": [], "t": 0.0}
        stack[-1]["children"].append(node); stack.append(node)
        t = time.perf_counter()
        try:
            return orig(*a, **k)
        except Exception as e:
            node["err"] = type(e).__name__; raise
        finally:
            node["t"] = time.perf_counter() - t; stack.pop()
    return w

def install():
    for mod, name, label in TARGETS:
        m = importlib.import_module(mod); orig = getattr(m, name); w = wrap(orig, label)
        for sm in list(sys.modules.values()):
            d = getattr(sm, "__dict__", None)
            if d is None: continue
            for k, v in list(d.items()):
                if v is orig: d[k] = w

def show(node, depth=0, maxdepth=4):
    from collections import Counter
    c = Counter(ch["label"] for ch in node["children"])
    if depth <= maxdepth and node["label"] != "SOLVE":
        sub = " ".join(f"{k}x{v}" for k, v in c.items())
        print("  " * depth + f"{node['label']} {node['t']:.3f}s {node.get('err','')} [{sub}]")
        for ch in node["children"]:
            if ch["label"] not in ("SOLVE",):
                show(ch, depth + 1, maxdepth)

if __name__ == "__main__":
    import matrix as _M
    F = {"S16": lambda: _M.scale_capex(pf.create_default_solar_project(capacity_mw=16.0), 0.26), "Wind25": lambda: pf.create_default_wind_project(capacity_mw=25.0), "Solar": pf.create_default_solar_project, "Wind": pf.create_default_wind_project,
         "DC": pf.create_default_data_center_project}
    which = sys.argv[1]; install()
    pi = F[which]()
    t = time.perf_counter(); pfa.run_clean_production(pi, project_type={"DC":"DataCenter","Wind25":"Wind","S16":"Solar"}.get(which, which))
    print(which, time.perf_counter() - t)
    show(stack[0], 0, int(sys.argv[2]) if len(sys.argv) > 2 else 5)
