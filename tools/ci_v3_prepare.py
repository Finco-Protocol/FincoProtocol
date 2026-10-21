"""Actual collect-only proposal preparation. Produces no owner or execution admission."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import subprocess

from tools.ci_v3_container import image_ref, observe_container
from tools.ci_v3_isolation import assess
from tools.ci_v3_process_observer import observe
from tools.ci_v3_schema import ContractError, read_json, require, seal, write_json


def prepare(project, output, image=None):
    project, output = Path(project).resolve(), Path(output).resolve()
    require(not output.is_relative_to(project) and not project.is_relative_to(output), "proposal must be outside source")
    require(not output.exists(), "preserve previous proposal evidence")
    def git(*args):
        return subprocess.check_output(['git','-C',str(project),*args],text=True).strip()
    require(Path(git('rev-parse','--show-toplevel')).resolve() == project, "proposal project must be Git root")
    require(not git('status','--porcelain','--untracked-files=all'), "proposal requires clean committed source")
    source={'head':git('rev-parse','HEAD'),'tree':git('rev-parse','HEAD^{tree}')}
    output.mkdir(parents=True)
    if image is None:
        observed=observe({'mode':'discover','project':str(project),'worker':None,'context':{'source':source}},output/'collection-process',120)
        report=read_json(output/'collection-process/adapter.json')
    else:
        # Linux evidence: collection runs in the immutable image as a private non-root, no-network container.
        context={'run_id':'0','attempt':1,'repository':'Finco-Protocol/FincoProtocol','source':source}
        child,observed=observe_container({'mode':'discover','context':context,'worker':None},output/'collection-container',project,image_ref(image),900)
        report=read_json(child/'adapter.json')
    require(observed['normal_successful_exit'] and not report['phases'] and not report['unauthorized_deselection'], "actual collect-only failed")
    collection=report['collection']
    require(collection['complete'] and not collection['errors'], "incomplete collection proposal")
    nodes=collection['nodes'];require(nodes and len(nodes)==len(set(nodes)), "missing/duplicate collection identities")
    modules=sorted({n.split('::',1)[0] for n in nodes});risk=assess(project)
    inventory=seal({'schema':1,'kind':'ci-v3-inventory','authority':'offline-prototype',
        'source':source,'repository':'Finco-Protocol/FincoProtocol',
        'nodes':[{'nodeid':n,'module':n.split('::',1)[0],'fixture_unit':n.split('::',1)[0],
            'execution_owner':'plan.module_workers','optional_overlap_ownership':'policy.module_overlaps',
            'domain':'F','confidence':'unresolved','mandatory':True,'obligations':['full-regression'],
            'dependency_evidence':'current actual collection; isolation remains blocked'} for n in nodes],
        'modules':{m:{'isolation_review':'unproven','dependency_evidence':risk['modules'].get(m,{})} for m in modules},
        'collection_skips':collection['skips']})
    policy=seal({'schema':1,'kind':'ci-v3-policy','authority':'offline-prototype','inventory_digest':inventory['digest'],
        'new_nodes':'fail-closed','selective_execution':False,'module_overlaps':{},'allowed_nonpass':{}})
    counts=Counter(n.split('::',1)[0] for n in nodes)
    weights=seal({'schema':1,'kind':'ci-v3-weights','source':source,'inventory_digest':inventory['digest'],
        'measurement':'EXPLICIT NODE-COUNT PROXY ONLY; integer slots are not measured milliseconds. Owner must review runtime weights.',
        'modules_ms':dict(sorted(counts.items()))})
    isolation=seal({'schema':3,'kind':'ci-v3-isolation-policy','source':source,
        'profile':'docker-no-network-private-workspace-v1','fixture_tree_reviewed':False,'review_reference':None,
        'modules':{m:{**risk['modules'].get(m,{}),'reviewed':False,'mode':'blocked','rationale':None} for m in modules}})
    for name,value in [('inventory',inventory),('policy',policy),('weights',weights),('isolation',isolation),('isolation-analysis',risk),('collection',collection)]:
        write_json(output/(name+'.json'),value)
    write_json(output/'proposal-status.json',{'source':source,'actual_collection_nodes':len(nodes),'modules':len(modules),
        'collection_skips':len(collection['skips']),'executed_test_phases':len(report['phases']),
        'environment':report['environment'],'process':observed,'admitted':False,'authoritative_acceptance':False,
        'checkout_attestation':'Preparation permits Git newline filters; hosted execution additionally requires exact canonical bytes.',
        'remaining':'Independent Linux/image collection, exact inventory/nonpass/isolation review, real runtime weights and protected owner root.'})
    return len(nodes)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--image',help='immutable registry@sha256 image; collects inside a private container')
    args=parser.parse_args()
    try:
        count=prepare(args.project,args.output,args.image)
    except (ContractError,OSError,KeyError,ValueError,subprocess.SubprocessError) as exc:
        print('CI_V3_PREPARATION_REJECTED: '+str(exc));return 1
    print(f'ACTUAL_COLLECTION_ONLY={count}; EXECUTION_ADMISSION=false');return 0


if __name__=='__main__':
    raise SystemExit(main())
