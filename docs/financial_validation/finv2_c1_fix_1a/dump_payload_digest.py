import json, sys, hashlib
from app import project_factories as pf
from app.api.project_runner import run_project
out={}
for kind,fn in (("generic_solar_reference","create_generic_solar_reference"),("generic_wind_reference","create_generic_wind_reference"),("generic_data_center_reference","create_generic_data_center_reference"),("generic_ev_charging_reference","create_generic_ev_charging_reference")):
    r=run_project(kind,"Base",project_inputs_override=getattr(pf,fn)())
    r["financing_evidence"].pop("senior_debt_evidence",None)
    def enc(o):
        if isinstance(o,float): return {"__f":o.hex()}
        if isinstance(o,dict): return {k:enc(v) for k,v in o.items()}
        if isinstance(o,(list,tuple)): return [enc(v) for v in o]
        return o if isinstance(o,(int,str,bool)) or o is None else repr(o)
    blob=json.dumps(enc(r),sort_keys=True)
    out[kind]={"sha256":hashlib.sha256(blob.encode()).hexdigest(),"bytes":len(blob),"keys":sorted(r)}
json.dump(out,open(sys.argv[1],"w"),indent=1)
