"""Opt-in canonical UI lifecycle, loopback only. No financial calculations.

Selectors and writer boundaries are the existing PR3b-2/new-project browser contracts.
No browser fault injection or disposal authority is invented for an unknown target.
"""
from urllib.parse import quote,urlsplit
from .policy import Refused, PREFIX, checked_scope, digest

OPERATIONS=('create','save_reload_no_run','explicit_run','save_makes_outdated','stale_second_tab','save_409','unknown_idempotent_retry','profile_off','no_cross_scenario_write','cleanup','bess_run')


def blocked_rows(technologies,reason):
    return [{'technology':t,'operation':op,'status':'BLOCKED_UNVERIFIED' if op=='bess_run' else 'NOT_TESTED' if op in ('save_409','unknown_idempotent_retry') else 'BLOCKED','reason':reason,'project_hash':'','scenario_hash':''} for t in technologies for op in OPERATIONS]


def cleanup_result(body):
    # There is no per-project disposal API in the inspected product contract.
    if body.get('code')=='CLEANUP_REFUSED_PROTECTED' or 'Protected/reference' in body.get('message',''):
        return 'CLEANUP_REFUSED_PROTECTED'
    return 'CLEANUP_NOT_SUPPORTED'


def run_project(browser,technology,name,ledger,save_ledger):
    policy=browser.policy;rows=[];project=None;stage='template-options';page=browser.context.new_page()
    def record(op,status,reason='',scope=None):
        rows.append({'technology':technology,'operation':op,'status':status,'reason':reason,**(scope or {'project_hash':'','scenario_hash':''})})
    try:
        options=browser.json_get('/v2/model-react/new-project/options')
        template=next((x for x in options.get('technologies',[]) if x.get('key')==technology and x.get('creatable')),None)
        if template is None:raise Refused('SUPPORTED_TEMPLATE_NOT_OFFERED')
        ledger[technology]={'name':name,'state':'CREATE_INTENT_RECORDED'};save_ledger()
        stage='wizard-open'
        page.goto(browser.base+'/v2/model-react/#new-project',timeout=browser.remaining())
        stage='wizard-template-choice'
        page.locator('[data-path-card="template"]').click(timeout=browser.remaining())
        page.locator(f'[data-tech-card="{technology}"]').click(timeout=browser.remaining())
        ack=page.locator('[data-preview-ack]')
        if ack.count():ack.check()
        stage='wizard-details'
        page.locator('[data-wizard-next]').click();page.locator('#rcm-name').fill(name)
        page.locator('[data-wizard-next]').click();page.locator('[data-wizard-panel="review"]').wait_for(timeout=browser.remaining())
        # Never infer the L02 card's financial units from formatted text.
        stage='canonical-create'
        policy.allowed_post=('/v2/model-react/new-project/create',None,None)
        page.locator('[data-wizard-create]').click()
        page.wait_for_selector('[data-react-workspace-version]',timeout=browser.remaining())
        project=urlsplit(page.url).path.rsplit('/',1)[-1]
        if not project or policy.created.get(project)!=name:raise Refused('CREATE_IDENTITY_NOT_NEW')
        ws=browser.json_get('/v2/model-react/workspace?project='+quote(project))
        scope=checked_scope(ws,project,name);scenario=ws['workbook']['scenario_id']
        ledger[technology].update(state='CREATED',project_hash=digest(project));save_ledger();record('create','PASS','NEW_PREFIXED_SERVER_OWNED_PROJECT',scope)
        stage='financing-load'
        page.goto(browser.base+'/v2/model-react/'+quote(project)+'#financing',timeout=browser.remaining())
        root=page.locator('[data-financing-editing]');root.wait_for(timeout=browser.remaining())
        other=browser.context.new_page();other.goto(page.url,timeout=browser.remaining())
        second=other.locator('[data-financing-editing]');second.get_by_label('Tenor',exact=True).fill('13')
        fields=browser.json_get('/v2/model-react/fields/debt?project='+quote(project))
        tenor=next(f for f in fields['fields'] if f['label']=='Tenor' and f.get('binding_label')=='bound')
        if float(tenor['value'])!=15:raise Refused('SEEDED_TENOR_NOT_DOCUMENTED_15')
        runs_before=len([p for p in policy.posts if p['path']=='/v2/workbook/run'])
        def save(value):
            root.get_by_label('Tenor',exact=True).fill(value)
            policy.allowed_post=('/v2/workbook/save-all',project,scenario)
            root.get_by_role('button',name='Save Repayment & Covenants',exact=True).click()
            root.get_by_text('Saved and read back:',exact=False).wait_for(timeout=browser.remaining())
            data=browser.json_get('/v2/model-react/fields/debt?project='+quote(project))
            if next(f['value'] for f in data['fields'] if f['field_id']==tenor['field_id'])!=float(value):raise Refused('CANONICAL_READBACK_MISMATCH')
        stage='save14-readback'
        save('14');page.reload(timeout=browser.remaining())
        if root.get_by_label('Tenor',exact=True).input_value()!='14' or len([p for p in policy.posts if p['path']=='/v2/workbook/run'])!=runs_before:raise Refused('PERSISTENCE_OR_IMPLICIT_RUN_FAILURE')
        record('save_reload_no_run','PASS','CANONICAL_READBACK_AND_RELOAD',scope)
        stage='stale-second-tab'
        before=len(policy.posts);policy.allowed_post=('/v2/workbook/save-all',project,scenario)
        second.get_by_role('button',name='Save Repayment & Covenants',exact=True).click()
        second.locator('[data-state="stale"]').wait_for(timeout=browser.remaining());policy.allowed_post=None
        if len(policy.posts)!=before:raise Refused('STALE_WRITER_SENT_MUTATION')
        record('stale_second_tab','PASS','UI_REFUSAL_WITH_ZERO_MUTATIONS',scope);other.close()
        stage='explicit-run'
        policy.allowed_post=('/v2/workbook/run',project,None)
        stage='explicit-run-click'
        page.locator('[data-wf-run]').click()
        stage='explicit-run-current'
        page.locator('[data-workflow-bar] [data-run-state-label="CURRENT"]').wait_for(timeout=browser.remaining())
        stage='explicit-run-snapshot'
        committed=browser.json_get('/v2/model-react/workspace?project='+quote(project))
        snapshot=(committed.get('identity') or {}).get('snapshot_id')
        if not snapshot:raise Refused('COMMITTED_SNAPSHOT_ID_UNAVAILABLE')
        record('explicit_run','PASS','COMMITTED_IDENTITY_HASH:'+digest(snapshot),scope)
        stage='save15-outdated'
        page.goto(browser.base+'/v2/model-react/'+quote(project)+'#financing',timeout=browser.remaining())
        root.wait_for(timeout=browser.remaining())
        save('15');page.reload(timeout=browser.remaining());page.locator('[data-workflow-bar] [data-run-state-label="STALE"]').wait_for(timeout=browser.remaining())
        after=browser.json_get('/v2/model-react/workspace?project='+quote(project))
        if (after.get('identity') or {}).get('snapshot_id')!=snapshot:raise Refused('LAST_RUN_IDENTITY_CHANGED')
        record('save_makes_outdated','PASS','RELOAD_RETAINS_OUTDATED_AND_PRIOR_SNAPSHOT',scope)
        for op in ('save_409','unknown_idempotent_retry','profile_off','no_cross_scenario_write'):
            record(op,'NOT_TESTED','NOT_INFERRED_FROM_SUCCESSFUL_SAVE',scope)
        record('cleanup','CLEANUP_NOT_SUPPORTED','NO_DOCUMENTED_PER_PROJECT_DISPOSAL_API; operator reconciliation by private ledger name',scope)
        record('bess_run','BLOCKED_UNVERIFIED','NO_VERIFIED_BESS_ENGINE_TEMPLATE',scope)
    except Exception as e:
        category='STRICT_SELECTOR_AMBIGUITY' if 'strict mode violation' in str(e) else 'BROWSER_CLOSED' if 'has been closed' in str(e) else 'BOUNDED_'+type(e).__name__
        record('lifecycle','BLOCKED' if isinstance(e,Refused) else 'FAIL',stage+':'+(str(e) if isinstance(e,Refused) else category))
        for op in OPERATIONS:
            if op not in {r['operation'] for r in rows}:record(op,'NOT_TESTED','EARLIER_STAGE_DID_NOT_PASS')
    finally:
        policy.allowed_post=None;page.close()
    return rows
