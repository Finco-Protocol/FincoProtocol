"""Authenticated metadata-only synthetic merge regeneration. No app/engine mocks or financial assertion changes."""
import copy
import subprocess
import pytest
from tools.ci_acceptance import EvidenceError
from tools.ci_merge_tree_guard import prove_merge_tree

H,E,M,B,T,X = (c*40 for c in 'abcdef')
REPO='Finco-Protocol/FincoProtocol'
ENV={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'pull_request','GITHUB_SHA':E,
     'GITHUB_REF':'refs/pull/428/merge','GITHUB_REPOSITORY':REPO,'GITHUB_SERVER_URL':'https://github.com'}
EVENT={'action':'reopened','number':428,'repository':{'full_name':REPO},'pull_request':{'number':428,
       'merge_commit_sha':E,'head':{'sha':H},'base':{'sha':B,'ref':'main','repo':{'full_name':REPO}}}}

class Git:
    def __init__(self):
        self.refs={'refs/heads/main':B,'refs/pull/428/head':H,'refs/pull/428/merge':M}
        self.after=None;self.n=0;self.fetch=M;self.trees={E:T,M:T}
        self.parents={E:[E,B,H],M:[M,B,H]};self.origin='https://github.com/'+REPO
        self.final_head=H;self.ancestor=True;self.event_fetch=E;self.head_calls=0
    def __call__(self,*a):
        if a==('rev-parse','HEAD'):
            self.head_calls+=1;return H if self.head_calls==1 else self.final_head
        if a==('rev-parse','HEAD^{tree}'):return T
        if a==('fetch','--no-tags','origin','refs/pull/428/merge'):self.fetch=M;return ''
        if a==('fetch','--no-tags','origin',E):self.fetch=self.event_fetch;return ''
        if a==('rev-parse','FETCH_HEAD'):return self.fetch
        if a[0]=='check-ref-format':return ''
        if a==('remote','get-url','origin'):return self.origin
        if a[0]=='ls-remote':
            self.n+=1;refs=self.after if self.n>1 and self.after is not None else self.refs
            return '\n'.join(f'{sha}\t{ref}' for ref,sha in refs.items())
        if a[:4]==('rev-list','--parents','-n','1'):return ' '.join(self.parents[a[4]])
        if a[0]=='rev-parse' and a[1].endswith('^{tree}'):return self.trees[a[1][:-7]]
        if a==('merge-base','--is-ancestor',B,H):
            if not self.ancestor:raise subprocess.CalledProcessError(1,a)
            return ''
        raise AssertionError(a)

def prove(g=None,event=None,env=None):
    return prove_merge_tree(H,E,'428',g or Git(),event=copy.deepcopy(EVENT) if event is None else event,
                            environment=copy.deepcopy(ENV) if env is None else env)

def test_same_parents_trees_and_stable_authenticated_refs_preserve_both_sha_identities():
    p=prove();assert p['merge_sha']==E and p['tree']==p['merge_tree']==T
    assert p['mode']=='identical-tree' and p['authenticated_drift']['fetched_merge_sha']==M
    assert p['authenticated_drift']['refs_before']==p['authenticated_drift']['refs_after']

def test_sha_drift_without_runner_event_still_fails_closed():
    with pytest.raises(EvidenceError,match='moved'):prove_merge_tree(H,E,'428',Git())

@pytest.mark.parametrize('field,value',[('GITHUB_ACTIONS','false'),('GITHUB_EVENT_NAME','workflow_dispatch'),
    ('GITHUB_SHA',X),('GITHUB_REF','refs/pull/429/merge'),('GITHUB_REPOSITORY','foreign/repo'),
    ('GITHUB_SERVER_URL','https://foreign.invalid')])
def test_wrong_runner_identity_fails(field,value):
    env=dict(ENV);env[field]=value
    with pytest.raises(EvidenceError):prove(env=env)

@pytest.mark.parametrize('attack',['number','nested-number','head','merge','repository','base-repository','missing','action','branch'])
def test_wrong_or_incomplete_event_identity_fails(attack):
    e=copy.deepcopy(EVENT)
    if attack=='number':e['number']=429
    elif attack=='nested-number':e['pull_request']['number']=429
    elif attack=='head':e['pull_request']['head']['sha']=X
    elif attack=='merge':e['pull_request']['merge_commit_sha']=X
    elif attack=='repository':e['repository']['full_name']='foreign/repo'
    elif attack=='base-repository':e['pull_request']['base']['repo']['full_name']='foreign/repo'
    elif attack=='missing':del e['pull_request']['base']
    elif attack=='action':e['action']='edited'
    elif attack=='branch':e['pull_request']['base']['ref']='main*'
    with pytest.raises(EvidenceError):prove(event=e)

@pytest.mark.parametrize('attack',['stale-main','wrong-head','foreign-merge','missing-ref','concurrent-base','concurrent-head',
    'concurrent-merge','event-tree','merge-tree','event-parent','merge-parent','extra-parent','origin','event-object','ancestry','local-head'])
def test_live_refs_immutable_objects_and_concurrency_fail_closed(attack):
    g=Git()
    if attack=='stale-main':g.refs['refs/heads/main']=X
    elif attack=='wrong-head':g.refs['refs/pull/428/head']=X
    elif attack=='foreign-merge':g.refs['refs/pull/428/merge']=X
    elif attack=='missing-ref':del g.refs['refs/pull/428/head']
    elif attack.startswith('concurrent-'):
        key={'concurrent-base':'refs/heads/main','concurrent-head':'refs/pull/428/head','concurrent-merge':'refs/pull/428/merge'}[attack]
        g.after={**g.refs,key:X}
    elif attack=='event-tree':g.trees[E]=X
    elif attack=='merge-tree':g.trees[M]=X
    elif attack=='event-parent':g.parents[E]=[E,X,H]
    elif attack=='merge-parent':g.parents[M]=[M,B,X]
    elif attack=='extra-parent':g.parents[M]=[M,B,H,X]
    elif attack=='origin':g.origin='https://github.com/foreign/repo'
    elif attack=='event-object':g.event_fetch=X
    elif attack=='ancestry':g.ancestor=False
    elif attack=='local-head':g.final_head=X
    with pytest.raises((EvidenceError,subprocess.CalledProcessError)):prove(g)


def test_real_git_metadata_regeneration_and_stale_main(tmp_path):
    """Real immutable objects + real bare PR refs; only GitHub hostname is a local transport fixture."""
    origin=tmp_path/'origin.git';work=tmp_path/'work'
    def run(*a,input=None):return subprocess.check_output(['git',*a],cwd=work if work.exists() else tmp_path,text=True,input=input,stderr=subprocess.DEVNULL).strip()
    subprocess.check_call(['git','init','--bare','-q',str(origin)])
    subprocess.check_call(['git','init','-q',str(work)])
    run('config','user.name','Synthetic merge proof');run('config','user.email','noreply@users.noreply.github.com')
    (work/'source.txt').write_text('base\n');run('add','.');run('commit','-qm','base');base=run('rev-parse','HEAD')
    (work/'source.txt').write_text('head\n');run('commit','-qam','head');head=run('rev-parse','HEAD');tree=run('rev-parse','HEAD^{tree}')
    event=run('commit-tree',tree,'-p',base,'-p',head,input='event synthetic merge\n')
    current=run('commit-tree',tree,'-p',base,'-p',head,input='regenerated synthetic merge\n')
    run('remote','add','origin',str(origin))
    run('push','-q','origin',base+':refs/heads/main',head+':refs/pull/428/head',current+':refs/pull/428/merge',event+':refs/events/original')
    payload=copy.deepcopy(EVENT);payload['pull_request']['base']['sha']=base;payload['pull_request']['head']['sha']=head;payload['pull_request']['merge_commit_sha']=event
    env={**ENV,'GITHUB_SHA':event}
    def transport(*a):return 'https://github.com/'+REPO if a==('remote','get-url','origin') else run(*a)
    proof=prove_merge_tree(head,event,'428',transport,event=payload,environment=env)
    assert proof['merge_sha']==event and proof['authenticated_drift']['fetched_merge_sha']==current
    assert proof['tree']==proof['merge_tree']==tree
    run('push','-q','origin',head+':refs/heads/main')
    with pytest.raises(EvidenceError,match='changed'):prove_merge_tree(head,event,'428',transport,event=payload,environment=env)
