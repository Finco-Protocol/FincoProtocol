"""SYNTHETIC service metadata around six real local tests. Never hosted evidence."""
from copy import deepcopy
import os
from pathlib import Path

from tests.ci_v3_hosted_fixtures import archive,real_bundle
from tools.ci_v3_hosted_controller import context,receipt
from tools.ci_v3_hosted_transport import sha
from tools.ci_v3_isolation import constrained_plan
from tools.ci_v3_process_observer import observe
from tools.ci_v3_pytest_config import semantic_plugin_profile
from tools.ci_v3_real_contract import actual_execution_records,file_sha
from tools.ci_v3_schema import canonical_bytes,digest,read_json,write_json
from tools.ci_v3_shadow_local import bridge_worker


def pair_bundle(directory):
    data=real_bundle(directory/'shadow-fixture');api=data['api'];repo=data['root']['repository'];prefix='/repos/'+repo
    root=deepcopy(data['root']);root.update(execution_mode='control',run_id=122,run_attempt=1)
    root_sha=sha(canonical_bytes(root));bundle=data['bundle'];project=data['project']
    plan=constrained_plan(project,bundle['inventory'],bundle['policy'],bundle['weights'],bundle['isolation'])
    ctx=context(root,bundle,plan,122,1);control=directory/'control-payload';control.mkdir()
    request={'mode':'worker','context':ctx,'project':str(project),'worker':'control',
             'inventory':bundle['inventory'],'owned_modules':sorted(bundle['inventory']['modules'])}
    observed=observe(request,control/'child',30)
    assert observed['normal_successful_exit']
    observed=bridge_worker(control/'child',observed,ctx);write_json(control/'plan.json',plan)
    observed['plan_sha256']=file_sha(control/'plan.json')
    value=receipt(control,'control',root_sha,ctx,observed,root);value['synthetic_only']=True;write_json(control/'receipt.json',value)
    run=deepcopy(api.data[prefix+'/actions/runs/123/attempts/2'])
    run.update(id=122,run_attempt=1,status='completed',conclusion='success',created_at='2026-10-21T08:00:00Z',updated_at='2026-10-21T09:00:00Z')
    api.data[prefix+'/actions/runs/122']=run;api.data[prefix+'/actions/runs/122/attempts/1']=run
    job={'id':200,'name':'ci-v3-control','run_id':122,'run_attempt':1,'head_sha':root['workflow_head'],
         'status':'completed','conclusion':'success','started_at':'2026-10-21T08:00:00Z','completed_at':'2026-10-21T09:00:00Z'}
    api.data[prefix+'/actions/runs/122/attempts/1/jobs']={'jobs':[job],'total_count':1}
    def artifact(artifact_id,name,path,job,created):
        payload=archive(path);api.payloads[artifact_id]=payload
        return {'id':artifact_id,'name':name,'expired':False,'digest':'sha256:'+sha(payload),
            'created_at':created,'updated_at':created,'workflow_run':{'id':job['run_id'],'head_sha':job['head_sha'],'repository_id':99}}
    control_artifact=artifact(20,'ci-v3-control-122-1',control,job,'2026-10-21T08:59:00Z')
    api.data[prefix+'/actions/runs/122/artifacts']={'artifacts':[control_artifact],'total_count':1}
    anchor={'artifact_id':20,'artifact_digest':control_artifact['digest'][7:],'job_id':200,'receipt_sha256':file_sha(control/'receipt.json')}
    for suffix in ['/actions/runs/123','/actions/runs/123/attempts/2']:
        api.data[prefix+suffix].update(status='completed',conclusion='success',created_at='2026-10-21T10:00:00Z',updated_at='2026-10-21T10:20:00Z')
    # Completed aggregate artifact remains present and must not break raw worker transfer.
    api.data[prefix+'/actions/runs/123/artifacts']['artifacts'].append({'name':'finco-v3-advisory-123-2'})
    api.data[prefix+'/actions/runs/123/artifacts']['total_count']+=1
    report=read_json(control/'child/adapter.json')
    profiles=[{'environment':r['environment'],'runtime_host':r['runtime_host'],
               'plugin_registrations':semantic_plugin_profile(r['plugin_registrations'])}
              for r in [report,*[read_json(data['paths'][n]/'child/adapter.json') for n in ['worker-0','worker-1','worker-2']]]]
    lifecycle={'source':root['source'],'residual_threads':[],'outstanding_leases':0,'shutdown_verified':True,
               'reference':'SYNTHETIC ONLY: not application lifecycle approval'}
    budget={'shadow_max_minutes':350,'pair_max_minutes':590,'ancillary_accounting':'separately-authorized','ancillary_max_minutes':315}
    auth={'schema':1,'kind':'ci-v3-pair-authorization','approved':True,'experiment_pairs':1,'workers':3,
        'owner_references':{k:'SYNTHETIC TEST ONLY' for k in ['Financial','Security','CI']},'source':root['source'],
        'budget':budget,'budget_authorization':root['budget_authorization'],'lifecycle_evidence':lifecycle,
        'nonpass_owner_decisions':root['nonpass_owner_decisions'],
        'environment_profiles_sha256':digest(profiles),
        'decisions':{k:{'approved':True,'reference':'SYNTHETIC TEST ONLY','sha256':h} for k,h in
          [('environment',digest(bundle['environment'])),('isolation',digest(bundle['isolation'])),
           ('nonpass',digest(bundle['policy'])),('daemon_lifecycle',digest(lifecycle)),('workflow_governance',root['workflow_sha256'])]},
        'control':{'root_path':'control-root.json','root_sha256':root_sha,'anchors':{'control':anchor}},
        'shadow':{'root_path':'shadow-root.json','root_sha256':data['root_sha'],'anchors':data['anchors']},
        'mandatory_browser_context':'mandatory-browser-evidence'}
    write_json(directory/'control-root.json',root);write_json(directory/'shadow-root.json',data['root'])
    # Normal-control representation uses ACTUAL original phases/native JUnit from the real tiny control.
    baseline=directory/'baseline';folder=baseline/'public-verification-results';folder.mkdir(parents=True)
    inventory={'head':root['source']['head'],'tree':root['source']['tree'],'phase_schema':1,'pytest_exit':0,
        'collection_errors':[],'collected':sorted(report['collection']['nodes']),'selected':sorted(report['selected']),
        'deselected':[],'shard':None,'collection_skip_records':report['collection']['skips'],
        'collection_skips':report['collection']['skips'],'phases':report['phases'],'environment':report['environment'],
        'pytest_plugins':report['pytest_plugins'],'plugin_registrations':report['plugin_registrations'],'runtime_host':report['runtime_host'],
        'outcomes':{r['nodeid']:{'status':r['status'],'reason':r['reason']} for r in actual_execution_records(report)}}
    write_json(folder/'inventory.json',inventory)
    (folder/'results.xml').write_bytes((control/'child/native.xml').read_bytes())
    write_json(folder/'process.json',{**root['source'],'label':'control','exit_code':0,'normal_exit':True,
        'process_markers':{'pytest_return_code':0,'child_exit_code':0},'environment_sha256':digest(report['environment']),
        'junit_sha256':file_sha(folder/'results.xml'),'junit_failures':0})
    write_json(folder/'merge-tree.json',{**root['source'],'mode':'main-head','equivalent':True})
    for name in ('scan','compile'):write_json(baseline/'public-source-safety'/f'{name}.json',{**root['source'],'exit_code':0,'normal_exit':True})
    from tools.ci_single_gate import verify_control
    old=Path.cwd()
    try:
        os.chdir(project);proof=verify_control(baseline,root['source']['head'],'success','success')
    finally:os.chdir(old)
    write_json(baseline/'public-shadow-proof/public-single-proof.json',proof)
    baseline_head=root['source']['head'];workflow=b'SYNTHETIC mandatory workflow only'
    api.contents[(repo,baseline_head,'.github/workflows/public_safety_and_smoke.yml')]=workflow
    api.data[prefix+'/actions/workflows/88']={'path':'.github/workflows/public_safety_and_smoke.yml'}
    run={**run,'id':121,'workflow_id':88,'head_sha':baseline_head,'created_at':'2026-10-21T06:00:00Z','updated_at':'2026-10-21T08:00:00Z'}
    api.data[prefix+'/actions/runs/121']=run;api.data[prefix+'/actions/runs/121/attempts/1']=run
    jobs=[];artifacts=[];anchors={}
    for i,(name,context_name) in enumerate([('public-source-safety','source-safety'),('public-verification-results','safety-and-smoke / tests'),('public-shadow-proof','mandatory-evidence')]):
        job={**job,'id':300+i,'name':context_name,'run_id':121,'head_sha':baseline_head,
             'started_at':'2026-10-21T06:00:00Z','completed_at':'2026-10-21T08:00:00Z'}
        intervals=[('06:00:00','06:02:00','06:01:00'),('06:02:00','07:55:00','07:54:00'),('07:55:00','08:00:00','07:59:00')]
        start,end,created=intervals[i]
        job.update(started_at='2026-10-21T'+start+'Z',completed_at='2026-10-21T'+end+'Z')
        jobs.append(job);a=artifact(30+i,name,baseline/name,job,'2026-10-21T'+created+'Z');artifacts.append(a)
        anchors[name]={'job_id':job['id'],'artifact_id':a['id'],'artifact_digest':a['digest'][7:]}
    api.data[prefix+'/actions/runs/121/attempts/1/jobs']={'jobs':jobs,'total_count':3}
    api.data[prefix+'/actions/runs/121/artifacts']={'artifacts':artifacts,'total_count':3}
    auth['mandatory_sequential_baseline']={'run_id':121,'attempt':1,'workflow_sha256':sha(workflow),'anchors':anchors,
        'comparability_approved':True,'review_reference':'SYNTHETIC ONLY',
        'environment_profile_sha256':digest({'environment':report['environment'],
            'plugin_registrations':semantic_plugin_profile(report['plugin_registrations']),'runtime_host':report['runtime_host']})}
    browser=directory/'browser';browser.mkdir()
    write_json(browser/'browser-proof.json',{**root['source'],'mandatory_roles':{r:{'normal_exit':True,'exit_code':0}
        for r in ['protocol','import','grid','q4','outputs','consolidation']}})
    browser_workflow=b'SYNTHETIC browser workflow only'
    api.contents[(repo,baseline_head,'.github/workflows/protocol_ui_browser.yml')]=browser_workflow
    api.data[prefix+'/actions/workflows/89']={'path':'.github/workflows/protocol_ui_browser.yml'}
    run={**run,'id':120,'workflow_id':89};api.data[prefix+'/actions/runs/120']=run;api.data[prefix+'/actions/runs/120/attempts/1']=run
    job={**job,'id':400,'name':'mandatory-browser-evidence','run_id':120,'started_at':'2026-10-21T06:00:00Z','completed_at':'2026-10-21T06:20:00Z'}
    api.data[prefix+'/actions/runs/120/attempts/1/jobs']={'jobs':[job],'total_count':1}
    a=artifact(40,'browser-mandatory-proof',browser,job,'2026-10-21T06:19:00Z')
    api.data[prefix+'/actions/runs/120/artifacts']={'artifacts':[a],'total_count':1}
    auth['browser_run']={'run_id':120,'attempt':1,'workflow_sha256':sha(browser_workflow),
        'proof_anchor':{'artifact_id':40,'artifact_digest':a['digest'][7:],'job_id':400}}
    auth['ancillary_runs']=[{'repository':repo,'run_id':121,'attempt':1,'workflow_path':'.github/workflows/public_safety_and_smoke.yml','workflow_sha256':sha(workflow)},
        {'repository':repo,'run_id':120,'attempt':1,'workflow_path':'.github/workflows/protocol_ui_browser.yml','workflow_sha256':sha(browser_workflow)}]
    write_json(directory/'authorization.json',auth)
    return {**data,'api':api,'auth':auth,'auth_path':directory/'authorization.json','control_path':control}
