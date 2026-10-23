"""Direct production admission using real mandatory control, never a fabricated pilot.

Independent protected owners pin this profile. Authentication and full comparison
run before selection and again in both mandatory verification jobs.
"""
from __future__ import annotations
from copy import deepcopy
import os
from pathlib import Path
import re
import shutil
import subprocess

from tools.ci_v3_schema import check_seal,digest,read_json,require,write_json
from tools.ci_v3_hosted_transport import receive_mandatory_control,receive_browser_proof
from tools.ci_v3_real_contract import outcome
from tools.ci_v3_pytest_config import semantic_plugin_profile

PROFILE='direct-production-v1'


def validate_profile(activation,profile,source):
    check_seal(profile,'ci-v3-direct-production-admission')
    require(profile['digest']==activation.get('direct_admission_digest') and profile.get('source')==source,
            'direct admission content/source changed')
    waiver=activation.get('pilot_waiver',{})
    require(waiver.get('Financial_reference') and waiver.get('separate_pilot_required') is False
            and waiver.get('pre_activation_two_x_required') is False,'explicit Financial pilot/performance waiver absent')
    require('accepted_pair_digest' not in activation and 'performance' not in profile,
            'direct admission must not masquerade as accepted pilot evidence')
    require(profile.get('source_equivalence_review_reference'),'independent source-equivalence review missing')
    for name in ('control','browser'):
        value=profile[name];original=value['source']
        require(all(re.fullmatch('[0-9a-f]{40}',original.get(k,'')) for k in ('head','tree'))
                and original['tree']==source['tree'],'original '+name+' tree differs')
        require(value['binding'].get('attempt')==1 and type(value['binding'].get('run_id')) is int
                and value['binding']['run_id']>0,'original '+name+' run/attempt missing')
        require(re.fullmatch('[0-9a-f]{64}',value.get('proof_sha256','')),'original '+name+' proof pin missing')
    decisions=profile['accepted_decisions']
    for field,key in [('nonpass_policy_sha256','nonpass'),('isolation_policy_sha256','isolation'),
                      ('environment_decision_sha256','environment')]:
        require(activation.get(field)==decisions[key]['sha256'],'direct '+key+' review pin differs')
    require(activation.get('daemon_lifecycle_review_reference')==decisions['daemon_lifecycle']['reference']
            and activation.get('daemon_lifecycle_review_reference'),'direct lifecycle review missing')
    env=profile['environment_decision']
    require(all(env.get(role) for role in ('Security_reference','CI_reference')),'independent runtime reviews missing')
    for field in ('control_environment_sha256','control_plugins_sha256','worker_environment_sha256','worker_plugins_sha256'):
        require(re.fullmatch('[0-9a-f]{64}',env.get(field,'')),'direct runtime/plugin pin missing: '+field)
    require(digest(env)==decisions['environment']['sha256'],'runtime review bytes changed')
    host=env['worker_host_contract']
    require(host.get('machine')=='x86_64' and type(host.get('minimum_cpus')) is int and host['minimum_cpus']>=2
            and host.get('memory_limit_bytes')==6*1024**3 and host.get('kernel_prefixes')
            and all(isinstance(p,str) and re.fullmatch(r'[0-9]+\.[0-9]+\.',p) for p in host['kernel_prefixes']),
            'reviewed worker host constraints missing')
    return {'mode':'parallel','reason':'direct production with authenticated mandatory control; Financial pilot waiver',
            'retry_on_parallel_failure':False,'direct_admission_digest':profile['digest']}


def check_environment(root,bundle,control,workers=()):
    decision=root['direct_admission']['environment_decision']
    require(digest(control['environment'])==decision['control_environment_sha256']
            and digest(semantic_plugin_profile(control['plugin_registrations']))==decision['control_plugins_sha256'],
            'unreviewed original control runtime/plugins')
    require(digest(bundle['environment'])==decision['worker_environment_sha256']
            and root['shadow_plugin_profile_sha256']==decision['worker_plugins_sha256'],
            'unreviewed worker environment/plugin target')
    host=decision['worker_host_contract']
    for worker in workers:
        require(digest(worker['environment'])==decision['worker_environment_sha256']
                and digest(semantic_plugin_profile(worker['plugin_registrations']))==decision['worker_plugins_sha256'],
                'actual production runtime/plugin drift')
        actual=worker['runtime_host']
        require(actual['machine']==host['machine'] and actual['cpu_count']>=host['minimum_cpus']
                and int(actual['cgroup_limits']['memory.max'])==host['memory_limit_bytes']
                and any(actual['kernel'].startswith(p) for p in host['kernel_prefixes']),
                'production host outside reviewed contract')
    return digest(decision)


def _verify_original(root,profile,project,folder):
    """Use the ORIGINAL verifier in an exact original-source checkout, no tests."""
    from tools.ci_single_gate import verify_control
    original=profile['control']['source'];current=root['source']
    require(original['tree']==current['tree'],'control source tree differs')
    subprocess.run(['git','-C',str(project),'merge-base','--is-ancestor',original['head'],current['head']],
                   check=True,capture_output=True,timeout=15)
    checkout=Path(folder).parent/'original-source-check'
    subprocess.run(['git','clone','--quiet','--no-checkout','--shared','--local',str(Path(project).resolve()),str(checkout)],
                   check=True,capture_output=True,timeout=60)
    previous=Path.cwd()
    try:
        subprocess.run(['git','-C',str(checkout),'checkout','--quiet','--detach',original['head']],
                       check=True,capture_output=True,timeout=60)
        os.chdir(checkout)
        binding=profile['control']['binding']
        result=verify_control(Path(folder).resolve(),original['head'],'success','success',binding.get('merge_sha',''))
    finally:
        os.chdir(previous);shutil.rmtree(checkout)
    require(result==read_json(Path(folder)/'public-shadow-proof/public-single-proof.json')
            and digest(result)==profile['control']['proof_sha256'],'original mandatory proof changed')
    return result


def authenticate_control(root,bundle,project,output,api):
    """Original byte/service evidence and reviewed identity alias; no new execution."""
    from tools.ci_v3_phase_compare import control_report,native_cases
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    profile=root['direct_admission'];control_binding=profile['control']
    require(api.authenticated_service is True,'direct production requires real service provenance')
    transport=receive_mandatory_control(api,root['repository'],control_binding['source'],
                                       control_binding['binding'],output/'control')
    proof=_verify_original(root,profile,project,output/'control')
    browser=receive_browser_proof(api,root['repository'],profile['browser']['source'],
                                  profile['browser']['binding'],output/'browser')
    require(digest(browser['proof'])==profile['browser']['proof_sha256'],'original browser proof changed')
    original=read_json(output/'control/public-verification-results/inventory.json')
    control=control_report(original)
    proc=read_json(output/'control/public-verification-results/process.json')
    cleanup=proc.get('process_markers',{}).get('cleanup',{})
    require(proc.get('cleanup_verified') is True and cleanup.get('cleanup_verified') is True
            and cleanup.get('mechanism')=='linux-subreaper-proc-waitpid-v1'
            and cleanup.get('survivors_observed')==cleanup.get('survivors_remaining')==[],
            'original control lacks independent descendant cleanup; normal exit alone is insufficient')
    require(control['source']==control_binding['source'],'original phase source differs')
    require(set(control['collection']['nodes'])=={n['nodeid'] for n in bundle['inventory']['nodes']},
            'original full control does not cover the current inventory')
    phases={}
    for item in control['phases']:phases.setdefault(item['nodeid'],[]).append(item)
    observed={n:outcome(values) for n,values in phases.items() if outcome(values)['status']!='passed'}
    require(observed==bundle['policy']['allowed_nonpass'],'original runtime nonpass policy differs')
    check_environment(root,bundle,control)
    native=(output/'control/public-verification-results/results.xml').read_bytes()
    native_cases(native,control)  # complete original phases/native consistency before selection
    # Original artifacts are immutable. Only the comparison view aliases identity
    # after service authentication, identical-tree and independent CI review.
    view=deepcopy(control);view['original_source']=control['source'];view['source']=root['source']
    view['collection']['source']=root['source']
    process={'source':root['source'],'original_source':control['source'],'exit_code':proc['exit_code'],
             'normal_exit':proc['normal_exit'],'cleanup_verified':proc['cleanup_verified']}
    write_json(output/'authenticated-original.json',{'original_proof':proof,'transport':transport,
               'browser':browser,'source_equivalence_review_reference':profile['source_equivalence_review_reference'],
               'comparison_source':root['source'],'original_source':control['source']})
    return view,native,process


def verify_phases(root,bundle,project,received,output,api):
    from tools.ci_v3_hosted_controller import read_plan,validate_receipt
    from tools.ci_v3_phase_compare import compare
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    control,native,process=authenticate_control(root,bundle,project,output/'original',api)
    _,ctx,_=read_plan(Path(received)/'plan',root,root['_root_sha256'],bundle,project,root['run_id'],root['run_attempt'])
    reports=[];natives=[native];processes=[process]
    for name in ('worker-0','worker-1','worker-2'):
        directory=Path(received)/name
        processes.append(validate_receipt(directory,name,root['_root_sha256'],ctx,root))
        reports.append(read_json(directory/'child/adapter.json'));natives.append((directory/'child/native.xml').read_bytes())
    review=check_environment(root,bundle,control,reports)
    result=compare(control,reports,natives,processes)
    result={**{k:v for k,v in result.items() if k!='digest'},'environment_reviewed':True,
            'environment_decision_sha256':review,'admission_mode':PROFILE}
    from tools.ci_v3_schema import seal
    result=seal(result);write_json(output/'phase-comparison.json',result)
    return result
