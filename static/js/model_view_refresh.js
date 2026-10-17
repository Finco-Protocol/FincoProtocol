// Conservative presentation invalidation, never a financial dependency/authorization authority.
(function () {
  'use strict';
  var shell = document.getElementById('v2-workbook-shell');
  if (!shell || window.FincoModelViews) return;
  var generation = 0, writes = 0, pendingWrites = new Set(), queued = false;
  var sharedReadyGeneration = 0;
  var definitions = [
    ['capex','capex','capex',true], ['opex','opex','opex',true], ['revenue','revenue','revenue',true],
    ['project_setup','project-setup','project-setup',true], ['tax','tax','tax',true],
    ['debt','debt','senior-debt',true], ['investor','investor','investor',true],
    ['inputs','inputs','inputs',true], ['returns','returns','returns',false],
    ['fs','fs','financial-statements',false], ['outputs','outputs','outputs',false],
    ['run_history','run-history','run-history',false]
  ];
  var views = definitions.map(function (d) {
    return {name:d[0], panel:'panel-'+d[1], id:'v2-sheet-'+d[2], editable:d[3], dirty:false, active:null, node:null};
  });
  function capture() {
    var input = document.querySelector('#v2-canonical-run-form [name="content_hash"]');
    return {generation:generation, project:shell.dataset.project, hash:input ? input.value : ''};
  }
  function current(ticket) {
    var now = capture();
    return ticket.generation === now.generation && ticket.project === now.project && ticket.hash === now.hash;
  }
  function visible(view) { var panel=document.getElementById(view.panel); return panel && !panel.hidden; }
  function warning(view, node, text) {
    var previous=node.querySelector('[data-model-view-notice]'); if(previous)previous.remove();
    var notice=document.createElement('div');notice.dataset.modelViewNotice='';notice.setAttribute('role','status');
    var p=document.createElement('p');p.textContent=text;notice.appendChild(p);
    var retry=document.createElement('button');retry.type='button';retry.dataset.modelViewRetry=view.name;
    retry.textContent=view.dirty ? 'Reload sheet and discard these unsaved edits' : 'Refresh view';notice.appendChild(retry);
    if(!view.editable){
      var bar=node.querySelector('#fs-runtime-bar');
      node.replaceChildren(notice);if(bar)node.appendChild(bar);
    }else node.prepend(notice);
  }
  function invalidate() {
    generation++;
    sharedReadyGeneration=-1;
    views.forEach(function (view) {
      var node=document.getElementById(view.id);if(!node)return;
      if(view.name==='run_history' && !node.querySelector('[data-testid="run-history-table"], [data-testid="run-history-empty"]'))return;
      view.active=null;view.node=node;node.dataset.modelViewState='pending';
      warning(view,node,view.dirty ? 'This sheet changed while it had unsaved edits. Your draft is kept; reload before saving.' :
        'This view needs refreshing. Previous results are not current.');
    });
  }
  function request(url, target, ticket, savedGrid, view) {
    var node=document.querySelector(target), source=document.createElement('span');source.hidden=true;
    document.body.appendChild(source);
    var accepted=false;
    source.addEventListener('htmx:beforeOnLoad',function(event){
      var xhr=event.detail.xhr;
      accepted=current(ticket) && node===document.querySelector(target) && !writes && !pendingWrites.size &&
        !(view && view.dirty) && xhr.status===200 && xhr.getResponseHeader('X-Finco-View-Hash')===ticket.hash;
      // A grid-state read belongs to the in-flight grid Save itself.
      if(target==='#v2-input-grid')accepted=current(ticket) && node===document.querySelector(target) &&
        xhr.status===200 && xhr.getResponseHeader('X-Finco-View-Hash')===ticket.hash &&
        (savedGrid || (!writes && !pendingWrites.size && window.FincoInputGrid &&
          !FincoInputGrid.stagedCount() && !FincoInputGrid.validating() &&
          !(document.activeElement && node.contains(document.activeElement) && document.activeElement.classList.contains('ig-input'))));
      if(!accepted)event.preventDefault();
    });
    return htmx.ajax('GET',url,{source:source,target:target,swap:'outerHTML'}).then(function(){
      source.remove();return accepted;
    },function(){source.remove();return false;});
  }
  function ensure(view) {
    var node=document.getElementById(view.id);if(!node)return;
    if(node!==view.node){
      view.node=node;view.dirty=false;
      if(!node.dataset.modelViewState)node.dataset.modelViewState='loaded';
    }
    if(!visible(view) || view.dirty || view.active || writes || pendingWrites.size ||
       node.dataset.modelViewState!=='pending')return;
    var ticket=capture();view.active=ticket;node.setAttribute('aria-busy','true');
    var query='project='+encodeURIComponent(ticket.project)+'&content_hash='+encodeURIComponent(ticket.hash);
    var url=view.name==='outputs' ? '/v2/workbook/outputs?'+query :
      '/v2/workbook/grid/sheet?'+query+'&presentation_only=1&sheet='+view.name;
    request(url,'#'+view.id,ticket,false,view).then(function(ok){
      if(view.active!==ticket)return;
      view.active=null;
      var fresh=document.getElementById(view.id);if(!fresh)return;
      fresh.removeAttribute('aria-busy');
      if(ok && current(ticket)){
        view.node=fresh;view.dirty=false;fresh.dataset.modelViewState='loaded';
        document.dispatchEvent(new CustomEvent('model:view-loaded',{detail:{sheet:view.name}}));
      }else if(current(ticket)){
        fresh.dataset.modelViewState='error';warning(view,fresh,'This view could not refresh. Try again before editing or using results.');
      }
    });
  }
  function schedule(){if(queued)return;queued=true;queueMicrotask(function(){queued=false;views.forEach(ensure);});}
  function viewOf(node){return views.find(function(view){var root=document.getElementById(view.id);return root && root.contains(node);});}
  function block(event){
    var view=viewOf(event.target);if(!view || !view.editable)return;
    var node=document.getElementById(view.id);
    if(node.dataset.modelViewState==='loaded')return;
    event.preventDefault();event.stopImmediatePropagation();schedule();
  }
  document.addEventListener('input',function(event){var view=viewOf(event.target);if(view && view.editable && event.isTrusted)view.dirty=true;});
  document.addEventListener('change',function(event){var view=viewOf(event.target);if(view && view.editable && event.isTrusted)view.dirty=true;});
  document.addEventListener('submit',block,true);
  document.addEventListener('htmx:confirm',function(event){
    var elt=(event.detail||{}).elt,view=elt && viewOf(elt);
    if(view && document.getElementById(view.id).dataset.modelViewState!=='loaded'){
      event.preventDefault();event.stopImmediatePropagation();schedule();
    }
  });
  document.addEventListener('click',function(event){
    var retry=event.target.closest('[data-model-view-retry]');
    if(retry){
      var view=views.find(function(v){return v.name===retry.dataset.modelViewRetry;});
      if(view){view.dirty=false;document.getElementById(view.id).dataset.modelViewState='pending';schedule();}
      return;
    }
    if(event.target.closest('button,input[type="submit"]') && !event.target.closest('[data-nav-tab]'))block(event);
  },true);
  document.addEventListener('htmx:configRequest',function(event){
    if(/^\/v2\/(workbook|capex|opex)\//.test(String(event.detail.path||'')))event.detail.headers['X-Finco-Lazy-Views']='1';
  });
  document.addEventListener('htmx:beforeRequest',function(event){
    var detail=event.detail||{},cfg=detail.requestConfig||{};
    if(String(cfg.verb).toLowerCase()!=='post' || !/^\/v2\/(workbook|capex|opex)\//.test(String(cfg.path||'')))return;
    var sourceView=viewOf(detail.elt||event.target);
    var isRun=String(cfg.path||'').split('?')[0]==='/v2/workbook/run';
    var previousHealth=document.getElementById('v2-model-health');
    pendingWrites.add(detail.xhr);invalidate();
    var writeGeneration=generation;
    detail.xhr.addEventListener('loadend',function(){
      pendingWrites.delete(detail.xhr);
      var health=document.getElementById('v2-model-health');
      if(isRun && detail.xhr.status===200 && generation===writeGeneration &&
         health && health!==previousHealth && health.dataset.state==='CURRENT')sharedReadyGeneration=generation;
      // Existing cost writers update one row plus authorized OOB identities,
      // not the whole sheet. Keep their remaining drafts and keyboard focus.
      if(sourceView && sourceView.editable && detail.xhr.status===200 && generation===writeGeneration){
        var node=document.getElementById(sourceView.id);
        if(node && node===sourceView.node){
          node.dataset.modelViewState='loaded';
          var notice=node.querySelector('[data-model-view-notice]');if(notice)notice.remove();
        }
      }
      schedule();
    },{once:true});
  });
  document.addEventListener('model:diagnostics-write-start',function(){writes++;invalidate();});
  document.addEventListener('model:diagnostics-write-end',function(){writes=Math.max(0,writes-1);schedule();});
  document.addEventListener('ct:saved',function(){invalidate();schedule();});
  document.addEventListener('htmx:afterSettle',schedule);
  // Browser Back/Forward returns to the read-only Outputs projection through a freshly authorized read (it re-initializes the
  // statement tree, which restores its view/expansion/period/focus/scroll from history state).  Only the Outputs view and only on
  // history traversal: ordinary tab clicks never refetch, and nothing else is loaded eagerly.
  window.addEventListener('popstate',function(){
    var outputs=views.find(function(v){return v.name==='outputs';});
    var node=outputs && document.getElementById(outputs.id);
    if(node && !outputs.active && node.dataset.modelViewState==='loaded')node.dataset.modelViewState='pending';
    schedule();
  });
  window.addEventListener('hashchange',schedule);
  window.FincoModelViews={capture:capture,isCurrent:current,generation:function(){return generation;},
    refreshSavedGrid:function(hash,saved){
      if(!saved && (writes || pendingWrites.size))return Promise.resolve(false);
      var ticket=capture();ticket.hash=hash;
      var gridOnly=!saved && sharedReadyGeneration===generation;
      return request('/v2/workbook/grid/panel?project='+encodeURIComponent(ticket.project)+
        '&refresh_state=1&content_hash='+encodeURIComponent(hash)+(gridOnly?'&grid_only=1':''),'#v2-input-grid',ticket,saved)
        .then(function(ok){if(ok && current(ticket) && saved)sharedReadyGeneration=ticket.generation;return ok;});
    }};
  function boot(){
    views.forEach(function(view){var panel=document.getElementById(view.panel);if(panel)
      new MutationObserver(schedule).observe(panel,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden']});});
    schedule();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
}());
