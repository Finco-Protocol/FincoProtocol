"""Independently authenticate one authorized hosted pair and compare original evidence.

This command performs GET requests only. It cannot dispatch, approve, publish,
activate or retry a workflow. A protected external hash pin supplies authority;
a successful comparison does not supply production activation authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import math
from pathlib import Path

from tools.ci_v3_hosted_controller import (STAGES, aggregate, context, load_bundle, load_root, make_plan,
    read_plan, validate_controller, validate_merge, validate_receipt)
from tools.ci_v3_hosted_transport import GitHub, receive, receive_mandatory_control, receive_browser_proof, timestamp
from tools.ci_v3_phase_compare import compare, control_report
from tools.ci_v3_real_contract import file_sha
from tools.ci_v3_schema import ContractError, digest, read_json, require, seal, skip_counter, write_json


def validate_authorization(value):
    require(value.get('schema') == 1 and value.get('kind') == 'ci-v3-pair-authorization'
            and value.get('approved') is True, 'pair spending/admission authorization absent')
    refs = value.get('owner_references', {})
    require(set(refs) == {'Financial','Security','CI'} and all(isinstance(v,str) and v.strip() for v in refs.values()),
            'exact independent Financial/Security/CI decisions required')
    require(value.get('experiment_pairs') == 1 and value.get('workers') == 3, 'one pair only')
    budget = value.get('budget', {})
    for key, limit in [('shadow_max_minutes',350), ('pair_max_minutes',590)]:
        require(type(budget.get(key)) is int and 0 < budget[key] <= limit, 'missing/excess authorized '+key)
    require(budget.get('ancillary_accounting') in ('included-in-pair','separately-authorized'),
            'browser/governance/dependency/compile spending must be explicit')
    require(type(budget.get('ancillary_max_minutes')) is int and budget['ancillary_max_minutes'] >= 0,
            'missing ancillary allocation')
    for name in ('environment','nonpass','isolation','daemon_lifecycle','workflow_governance'):
        item = value.get('decisions', {}).get(name, {})
        require(item.get('approved') is True and item.get('reference') and item.get('sha256'),
                'missing exact decision: '+name)
    return value


def runner_minutes(jobs):
    total = 0
    for job in jobs:
        if job['conclusion'] == 'skipped':
            continue
        require(job['status'] == 'completed' and job.get('started_at') and job.get('completed_at'),
                'running job cannot be accepted or budgeted as complete')
        seconds = (timestamp(job['completed_at']) - timestamp(job['started_at'])).total_seconds()
        require(seconds >= 0, 'invalid job interval')
        total += math.ceil(seconds / 60)
    return total


def performance(control_start, control_end, shadow_start, proof_completed):
    control_s = (timestamp(control_end) - timestamp(control_start)).total_seconds()
    shadow_s = (timestamp(proof_completed) - timestamp(shadow_start)).total_seconds()
    require(control_s > 0 and shadow_s > 0, 'invalid end-to-end observation')
    return {'control_end_to_end_s':control_s, 'shadow_to_independent_proof_s':shadow_s,
            'observed_speedup': control_s / shadow_s, 'performance_success':control_s / shadow_s >= 2,
            'target_speedup':2, 'repeatability_established':False,
            'mandatory_ci_acceleration_established':False}


def check_budget(auth, control_minutes, shadow_minutes, ancillary_minutes):
    b = auth['budget']
    require(shadow_minutes <= b['shadow_max_minutes'], 'shadow allocation exceeded')
    require(ancillary_minutes <= b['ancillary_max_minutes'], 'ancillary allocation exceeded')
    charged_pair = control_minutes + shadow_minutes + (ancillary_minutes if b['ancillary_accounting']=='included-in-pair' else 0)
    require(charged_pair <= b['pair_max_minutes'], 'total pair allocation exceeded')
    return {'control_minutes':control_minutes, 'shadow_minutes':shadow_minutes,
            'ancillary_minutes':ancillary_minutes, 'charged_pair_minutes':charged_pair,
            'estimated_billing_rounded_per_job':True, 'allocation':b}


def authenticate_pair(api, auth, auth_path, project, output):
    require(api.authenticated_service is True, 'mock/local transport cannot establish hosted acceptance')
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    roots = {}; bundles = {}; transports = {}; runs = {}; jobs = {}
    for side in ('control','shadow'):
        binding = auth[side]
        path = Path(auth_path).resolve().parent / binding['root_path']
        root = load_root(path, binding['root_sha256'])
        require(root['execution_mode'] == side and root['source'] == auth['source'], 'stale/wrong pair source or side')
        validate_controller(root); validate_merge(api, root)
        bundle = load_bundle(api, root)
        expected = {'control':'ci-v3-control'} if side=='control' else STAGES
        transport = receive(api, root, root['run_id'], root['run_attempt'], binding['anchors'], output/side, expected)
        require(transport['provenance_authenticated'] is True, 'unauthenticated pair artifacts')
        roots[side],bundles[side],transports[side] = root,bundle,transport
        runs[side] = api.get(f"/repos/{root['repository']}/actions/runs/{root['run_id']}/attempts/{root['run_attempt']}")
        require(runs[side]['status']=='completed' and runs[side]['conclusion']=='success', 'pair run not successful')
        jobs[side] = api.listing(f"/repos/{root['repository']}/actions/runs/{root['run_id']}/attempts/{root['run_attempt']}/jobs", 'jobs')
    c,s = roots['control'], roots['shadow']
    require(c['run_id'] != s['run_id'], 'control/shadow must be separate bound runs')
    for key in ('repository','source','controller_head','controller_tree','controller_files_sha256',
                'workflow_head','workflow_path','workflow_sha256','image','bundle','target_calibration'):
        require(c[key] == s[key], 'incomparable pair '+key)
    require(c['budget_authorization'] == s['budget_authorization'] == auth['budget_authorization'],
            'retrospective approval differs from pre-execution spending authority')
    require(c['nonpass_owner_decisions'] == s['nonpass_owner_decisions'] == auth['nonpass_owner_decisions'],
            'exact current-source per-record owner decisions differ')
    approved_budget = auth['budget_authorization']
    require(all(auth['budget'][k] == approved_budget[k] for k in
                ('shadow_max_minutes','pair_max_minutes','ancillary_accounting','ancillary_max_minutes')),
            'pair comparison budget differs from prospective allocation')
    bundle = bundles['shadow']
    require(bundle['isolation'].get('allowed_daemon_threads',{}) == {}, 'name-only survivor permissions are not accepted')
    aggregate(s,auth['shadow']['root_sha256'],bundle,project,output/'shadow',output/'verified-shadow',
              s['run_id'],s['run_attempt'],transports['shadow'])
    for name in ('environment','isolation'):
        require(digest(bundle[name]) == auth['decisions'][name]['sha256'], 'stale '+name+' decision')
    require(digest(bundle['policy']) == auth['decisions']['nonpass']['sha256'], 'stale exact nonpass decision')
    require(s['workflow_sha256'] == auth['decisions']['workflow_governance']['sha256'], 'stale workflow review')
    lifecycle = auth['lifecycle_evidence']
    require(lifecycle.get('source') == s['source'] and lifecycle.get('residual_threads') == []
            and lifecycle.get('outstanding_leases') == 0 and lifecycle.get('shutdown_verified') is True,
            'source-bound lifecycle completion missing')
    require(digest(lifecycle) == auth['decisions']['daemon_lifecycle']['sha256'], 'stale lifecycle evidence decision')
    # Recompute only the reviewed whole-module plan, never original test IDs.
    control_plan = read_json(output/'control/control/plan.json')
    require(control_plan == make_plan(project, bundles['control']), 'control plan substituted')
    cctx = context(c,bundles['control'],control_plan,c['run_id'],c['run_attempt'])
    creceipt = validate_receipt(output/'control/control','control',auth['control']['root_sha256'],cctx,c)
    require(file_sha(output/'control/control/plan.json') == creceipt['observation']['plan_sha256'], 'control plan hash')
    plan,sctx,_ = read_plan(output/'shadow/plan',s,auth['shadow']['root_sha256'],bundle,project,s['run_id'],s['run_attempt'])
    reports = [control_report(read_json(output/'control/control/child/adapter.json'))]
    native = [(output/'control/control/child/native.xml').read_bytes()]
    receipts = [creceipt]
    for worker in ('worker-0','worker-1','worker-2'):
        directory = output/'shadow'/worker
        receipts.append(validate_receipt(directory,worker,auth['shadow']['root_sha256'],sctx,s))
        reports.append(read_json(directory/'child/adapter.json'))
        native.append((directory/'child/native.xml').read_bytes())
    for report in reports:
        require(report.get('plugin_registrations'), 'complete actual plugin inventory missing')
        require(report['environment'].get('runtime_fingerprint'), 'OS/native/tool fingerprint missing')
    comparison = compare(reports[0],reports[1:],native,receipts)
    # Review pins the entire observed runtime AND plugin profiles, including any accepted differences.
    from tools.ci_v3_pytest_config import semantic_plugin_profile
    profiles = [{'environment':r['environment'],'runtime_host':r['runtime_host'],
                 'plugin_registrations':semantic_plugin_profile(r['plugin_registrations'])} for r in reports]
    require(digest(profiles) == auth['environment_profiles_sha256'], 'unreviewed runtime/plugin differences')
    ancillary = []
    for binding in auth['ancillary_runs']:
        require(binding['repository'] == s['repository'], 'foreign ancillary repository')
        run = api.get(f"/repos/{s['repository']}/actions/runs/{binding['run_id']}/attempts/{binding['attempt']}")
        require(run['head_sha'] == s['source']['head'] and run['status']=='completed' and run['conclusion']=='success',
                'missing/failed current-source ancillary acceptance')
        workflow = api.get(f"/repos/{s['repository']}/actions/workflows/{run['workflow_id']}")
        require(workflow['path'] == binding['workflow_path'], 'wrong ancillary workflow')
        require(file_sha_bytes(api.content(s['repository'],run['head_sha'],workflow['path'])) == binding['workflow_sha256'],
                'ancillary workflow bytes substituted')
        ancillary.extend(api.listing(f"/repos/{s['repository']}/actions/runs/{binding['run_id']}/attempts/{binding['attempt']}/jobs",'jobs'))
    require(auth.get('mandatory_browser_context')=='mandatory-browser-evidence', 'browser context cannot be substituted')
    browser_binding=auth['browser_run']
    require(browser_binding['run_id'] in {b['run_id'] for b in auth['ancillary_runs']},'browser spending omitted')
    browser_transport=receive_browser_proof(api,s['repository'],s['source'],browser_binding,output/'browser-proof')
    budget = check_budget(auth,runner_minutes(jobs['control']),runner_minutes(jobs['shadow']),runner_minutes(ancillary))
    # Authenticate the original mandatory workflow, full unsharded inventory,
    # native JUnit and independently produced aggregate proof, not a green badge.
    baseline = auth['mandatory_sequential_baseline']
    baseline_transport = receive_mandatory_control(api,s['repository'],s['source'],baseline,output/'mandatory-baseline')
    from tools.ci_single_gate import verify_control
    from tools.ci_v3_real_contract import git_source
    require(git_source(project)==s['source'], 'baseline verifier checkout mismatch')
    import os
    original_directory = Path.cwd()
    try:
        os.chdir(project)
        baseline_proof = verify_control((output/'mandatory-baseline').resolve(),s['source']['head'],'success','success',
                                        baseline.get('merge_sha',''))
    finally:
        os.chdir(original_directory)
    original_proof = read_json(output/'mandatory-baseline/public-shadow-proof/public-single-proof.json')
    require(original_proof == baseline_proof, 'mandatory proof bytes disagree with original control evidence')
    require(baseline_proof['selected_test_ids']==comparison['original_nodes'], 'mandatory original coverage differs')
    mandatory_report = control_report(read_json(output/'mandatory-baseline/public-verification-results/inventory.json'))
    from tools.ci_v3_phase_compare import phase_map, native_cases
    require(mandatory_report['source']==s['source'] and phase_map(mandatory_report)==phase_map(reports[0]),
            'mandatory/control phase or nonpass equivalence differs')
    require(skip_counter(mandatory_report['collection']['skips']) == skip_counter(reports[0]['collection']['skips']),
            'mandatory/control collection skips differ')
    mandatory_native = (output/'mandatory-baseline/public-verification-results/results.xml').read_bytes()
    require(native_cases(mandatory_native,mandatory_report)==native_cases(native[0],reports[0]),
            'mandatory/control native JUnit differs')
    require(baseline.get('comparability_approved') is True and baseline.get('review_reference')
            and digest({'environment':mandatory_report['environment'],
                        'plugin_registrations':semantic_plugin_profile(mandatory_report['plugin_registrations']),
                        'runtime_host':mandatory_report['runtime_host']})==baseline['environment_profile_sha256'],
            'mandatory environment comparability not explicitly reviewed')
    require(baseline['run_id'] in {b['run_id'] for b in auth['ancillary_runs']}, 'mandatory baseline spending omitted')
    now = api.observation_time(f"/repos/{s['repository']}/actions/runs/{s['run_id']}/attempts/{s['run_attempt']}")
    require(timestamp(now)>=timestamp(runs['shadow']['updated_at']), 'proof completion precedes shadow completion')
    perf = performance(baseline_transport['run']['created_at'],baseline_transport['proof_completed_at'],
                       runs['shadow']['created_at'],now)
    plugin_profiles=[digest(semantic_plugin_profile(r['plugin_registrations'])) for r in reports[1:]]
    require(len(set(plugin_profiles))==1,'shadow plugin configurations differ')
    proof = seal({'schema':1,'kind':'ci-v3-pair-acceptance','source':s['source'],
        'authorization_sha256':file_sha(auth_path),'accepted_decisions':auth['decisions'],
        'environment_profiles_sha256':auth['environment_profiles_sha256'],
        'accepted_shadow_plugin_profile_sha256':plugin_profiles[0],'roots_sha256':{k:auth[k]['root_sha256'] for k in roots},
        'technical_validity':True,'phase_comparison':comparison,'budget':budget,'performance':perf,
        'proof_completed_at':now,'timing_contract':'workflow-created-to-independent-proof/server-UTC-v1',
        'mandatory_baseline_transport':baseline_transport,'browser_transport':browser_transport,'transports':transports,'production_activation_authorized':False})
    write_json(output/'pair-proof.json',proof)
    return proof


def file_sha_bytes(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('authorization','authorization-sha256','project','output'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args(argv)
    try:
        require(file_sha(args.authorization)==args.authorization_sha256, 'protected authorization pin mismatch')
        auth = validate_authorization(read_json(args.authorization))
        result = authenticate_pair(GitHub(),auth,args.authorization,args.project,args.output)
        return 0 if result['performance']['performance_success'] else 2
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        write_json(Path(args.output)/'pair-rejection.json', {'technical_validity':False,'activation_authorized':False,'reason':str(exc)})
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
