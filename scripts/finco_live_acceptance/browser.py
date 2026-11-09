"""Existing Playwright runtime, one bounded context; diagnostics contain counts only."""
from __future__ import annotations
import hashlib
import json
import re
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from .policy import Refused, NetworkPolicy, PREFIX


class Browser:
    def __init__(self, base, policy, timeout, deadline, storage=None, borrowed_browser=None):
        self.base=base;self.policy=policy;self.timeout=timeout;self.deadline=deadline;self.storage=storage
        self.observed_build_headers=set();self.context=None;self.browser=None;self.pw=None;self.borrowed_browser=borrowed_browser

    def remaining(self):
        left=int((self.deadline-time.monotonic())*1000)
        if left<=0:raise Refused('GLOBAL_TIMEOUT')
        return max(1,min(left,int(self.timeout*1000)))

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        if self.borrowed_browser is None:self.pw=sync_playwright().start()
        try:
            options={'headless':True,'args':['--no-sandbox']}
            # Preserve managed runtime's proxy and CA; never disable TLS verification.
            proxy=os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
            if proxy and urlsplit(self.base).hostname not in ('127.0.0.1','localhost','::1'):
                options['proxy']={'server':proxy}
            self.browser=self.borrowed_browser or self.pw.chromium.launch(**options)
            self.context=self.browser.new_context(storage_state=str(self.storage) if self.storage else None,
                service_workers='block',accept_downloads=False)
            self.context.set_default_timeout(self.remaining())
            def intercept(route):
                req=route.request
                if not self.policy.permit(req.url,req.method,req.post_data):route.abort('blockedbyclient');return
                if req.method=='POST' and urlsplit(req.url).path=='/v2/model-react/new-project/create':
                    try:
                        response=route.fetch(max_redirects=0,timeout=self.remaining())
                        if response.ok:
                            body=response.json();created=body.get('project',{});intent=json.loads(req.post_data or '{}')
                            code=created.get('code');name=created.get('name')
                            if (body.get('ok') is not True or not isinstance(code,str) or not re.fullmatch('[A-Za-z0-9_-]{1,160}',code)
                                or name!=intent.get('name') or not str(name).startswith(PREFIX) or code in self.policy.projects):
                                raise Refused('CREATE_RESPONSE_SCOPE_REFUSED')
                            self.policy.created[code]=name;self.policy.projects.add(code)
                        route.fulfill(response=response)
                    except Exception:
                        self.policy.blocked.append('CREATE_OUTCOME_UNRESOLVED');route.abort('failed')
                else:route.continue_()
            self.context.route('**/*',intercept)
            def header_observation(response):
                if urlsplit(response.url).netloc!=urlsplit(self.base).netloc:return
                observed=response.headers.get('x-finco-build-sha','')
                if re.fullmatch('[a-f0-9]{40}',observed):self.observed_build_headers.add(observed)
            self.context.on('response',header_observation)
            if hasattr(self.context,'route_web_socket'):
                self.context.route_web_socket('**/*',lambda ws:ws.close())
            return self
        except BaseException:
            self.__exit__(None,None,None);raise

    def __exit__(self,*_):
        try:
            if self.context:self.context.close()
        finally:
            try:
                if self.browser and self.borrowed_browser is None:self.browser.close()
            finally:
                if self.pw:self.pw.stop()

    def get(self,path):
        url=self.base+path
        if not self.policy.permit(url,'GET'):raise Refused('UNSAFE_READ_REFUSED')
        return self.context.request.get(url,max_redirects=0,timeout=self.remaining())

    def json_get(self,path):
        result=self.get(path)
        if result.status in (401,403):raise Refused('BLOCKED_AUTH')
        if not result.ok:raise Refused('AUTHORITATIVE_READ_REFUSED')
        try:d=result.json()
        except ValueError:raise Refused('INVALID_AUTHORITATIVE_RESPONSE') from None
        if not isinstance(d,dict):raise Refused('INVALID_AUTHORITATIVE_RESPONSE')
        return d


def deployment(browser,expected):
    artifacts={}
    for ext in ('js','css'):
        item={'expected_sha256':expected.get(ext),'status':None,'size':None,'actual_sha256':None}
        try:
            response=browser.get('/static/react/finco-react.'+ext+'?onaccept01='+str(time.time_ns()))
            item['status']=response.status
            if response.ok:
                raw=response.body()
                if len(raw)>16*1024*1024:raise Refused('ARTIFACT_TOO_LARGE')
                item.update(size=len(raw),actual_sha256=hashlib.sha256(raw).hexdigest())
        except Refused as e:
            if str(e)=='GLOBAL_TIMEOUT':raise
            item['error']='ARTIFACT_ACCESS_UNAVAILABLE'
        except Exception:
            item['error']='ARTIFACT_ACCESS_UNAVAILABLE'
        artifacts[ext]=item
    provable=all(artifacts[x]['expected_sha256'] and artifacts[x]['actual_sha256'] for x in artifacts)
    state='FRONTEND_NOT_PROVABLE' if not provable else 'FRONTEND_EXACT_MATCH' if all(v['expected_sha256']==v['actual_sha256'] for v in artifacts.values()) else 'FRONTEND_MISMATCH'
    return {'frontend':state,'backend':'BACKEND_NOT_HTTP_VERIFIABLE','backend_reason':'No authenticated HTTP build-identity proof has been verified. Host observations are not HTTP proof.','artifacts':artifacts}


GEOMETRY='''() => {
 const vw=window.innerWidth, width=document.documentElement.scrollWidth;
 let clipped=0, unlabelled=0, misaligned=0;
 const controls=[...document.querySelectorAll('input:not([type=hidden]),select,textarea,button,a[href]')];
 const visible=el=>!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
 for (const el of controls.filter(visible)) {
  const r=el.getBoundingClientRect();let inner=false,p=el.parentElement;
  while(p && p!==document.body){const s=getComputedStyle(p);if(['auto','scroll'].includes(s.overflowX)&&p.scrollWidth>p.clientWidth+1){inner=true;break;}p=p.parentElement;}
  if(!inner&&(r.left < -1 || r.right>vw+1))clipped++;
  if(el.labels?.length){const l=el.labels[0].getBoundingClientRect();if(Math.max(0,r.top-l.bottom,l.top-r.bottom)>80)misaligned++;}
  if(el.matches('input,select,textarea')&&!el.labels?.length&&!el.getAttribute('aria-label')&&!el.getAttribute('aria-labelledby')&&!el.getAttribute('title'))unlabelled++;
 }
 const inner=[...document.querySelectorAll('*')].filter(el=>visible(el)&&['auto','scroll'].includes(getComputedStyle(el).overflowX)&&el.scrollWidth>el.clientWidth+1).length;
 return {page_width:width,viewport_width:vw,overflow:width>vw+1,clipped_controls:clipped,unlabelled_controls:unlabelled,misaligned_labels:misaligned,inner_scroll_regions:inner};
}'''


def inspect_route(browser,url,selector,width,out,row_id):
    page=browser.context.new_page();page.set_viewport_size({'width':width,'height':1000})
    errors={'console_errors':0,'page_errors':0,'api_failures':0};before=browser.policy.attempted_mutations;blocked=len(browser.policy.blocked)
    page.on('console',lambda m:errors.__setitem__('console_errors',errors['console_errors']+(m.type=='error')))
    page.on('pageerror',lambda _:errors.__setitem__('page_errors',errors['page_errors']+1))
    page.on('requestfailed',lambda _:errors.__setitem__('api_failures',errors['api_failures']+1))
    page.on('response',lambda r:errors.__setitem__('api_failures',errors['api_failures']+(r.status>=400)))
    result={'status':'FAIL','reason':'ROUTE_NOT_VERIFIED','screenshot_viewport':'','screenshot_full':'','evidence_status':'NOT_CAPTURED',
        'page_width':'','viewport_width':width,'overflow':'','clipped_controls':'','essential_visible':False,'keyboard_focusable':False,**errors,'mutation_attempts':0}
    try:
        page.goto(url,wait_until='domcontentloaded',timeout=browser.remaining())
        if urlsplit(page.url).path=='/login' and urlsplit(url).path!='/login':
            result.update(status='BLOCKED_AUTH',reason='LOGIN_REQUIRED')
        else:
            page.locator(selector).first.wait_for(state='visible',timeout=browser.remaining())
            result['essential_visible']=True
            fragment=urlsplit(url).fragment
            found=page.locator('a[href]').evaluate_all('(els,fragment) => els.some(a=>new URL(a.href,location.href).hash==="#"+fragment)',fragment) if fragment else True
            result['navigation_reachability']='DIRECT_ROUTE_AND_LINK_DISCOVERED' if found else 'DIRECT_ROUTE_ONLY'
            result['notes_toggle']='NOT_PRESENT'
            for details in page.locator('details').all():
                summary=details.locator('summary').first
                if summary.count() and summary.is_visible() and 'Notes' in summary.inner_text():
                    before_open=details.get_attribute('open') is not None
                    summary.click();changed=(details.get_attribute('open') is not None)!=before_open
                    summary.click();restored=(details.get_attribute('open') is not None)==before_open
                    result['notes_toggle']='PASS' if changed and restored else 'FAIL'
                    break
            # DOM-only actions, no form input or submission in read-only coverage.
            page.keyboard.press('Tab')
            result['keyboard_focusable']=page.evaluate("() => !!document.activeElement && document.activeElement!==document.body")
            result.update(page.evaluate(GEOMETRY))
            result.update(status='PASS',reason='ROUTE_LAYOUT_AND_ESSENTIAL_MARKER_ONLY')
        # Mask credentials and editable values; never record HAR, request bodies, console text or raw API JSON.
        mask=page.locator('input,textarea,[data-sensitive],[data-account-name]')
        for full,key,suffix in ((False,'screenshot_viewport','viewport'),(True,'screenshot_full','full')):
            relative='screenshots/'+row_id+'-'+suffix+'.png'
            page.screenshot(path=str(out/relative),full_page=full,mask=[mask],timeout=browser.remaining())
            result[key]=relative
        result['evidence_status']='CAPTURED'
    except Refused as e:
        if str(e)=='GLOBAL_TIMEOUT':raise
        result['reason']=str(e)
    except Exception:
        result['reason']='BOUNDED_NAVIGATION_OR_CAPTURE_FAILURE'
    finally:
        result.update(errors);result['mutation_attempts']=browser.policy.attempted_mutations-before
        if result['status']=='PASS' and (result.get('overflow') or result.get('clipped_controls') or result.get('unlabelled_controls') or result.get('misaligned_labels') or result.get('notes_toggle')=='FAIL' or not result['keyboard_focusable'] or any(errors.values()) or result['mutation_attempts'] or len(browser.policy.blocked)>blocked):
            result.update(status='FAIL',reason='LAYOUT_ACCESSIBILITY_NETWORK_OR_MUTATION_FAILURE')
        page.close()
    return result
