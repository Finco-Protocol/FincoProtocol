// Isolated synthetic preview, never imported by the production entry point.
import { createElement, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { FinancingOverview } from '../FinancingOverview';
import { FinancingReadLayer } from '../FinancingReadLayer';
import { synthetic } from './synthetic.mjs';
function Harness() {
  const [mode,setMode]=useState('CURRENT');
  if(new URLSearchParams(location.search).has('loader'))return createElement(FinancingReadLayer,{scope:{project:'synthetic-project',scenarioId:null},reloadKey:0});
  const e=synthetic(mode==='STALE'?'STALE':'CURRENT');
  if(mode==='MISMATCH')e.studio.sources_uses.view.total_sources.value=101;
  if(mode==='TWO_SENIOR'){
    e.studio.multisenior.active=true;
    e.studio.capital_stack.rows.push({...e.studio.capital_stack.rows[0],instrument_id:'senior-extra',name:'Synthetic Senior extra'});
  }
  return createElement('main',null,
    createElement('nav',{'aria-label':'Synthetic preview states'},['CURRENT','STALE','MISMATCH','TWO_SENIOR'].map(v=>createElement('button',{key:v,onClick:()=>setMode(v)},v))),
    createElement(FinancingOverview,{evidence:e,onReload:()=>setMode('CURRENT'),onHistoryChange:()=>{}}));
}
createRoot(document.getElementById('root')).render(createElement(Harness));
