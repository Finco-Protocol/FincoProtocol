"""Explicit route vocabulary from the merged UI; no guessed route multiplication.

Sources: workspaceNavigation.ts, FinancingStudio.tsx, react_poc_router.py.
The unsafe Legacy GET is inventoried but deliberately NOT visited.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Route:
    key: str
    fragment: str
    selector: str
    source: str='frontend/src/app/workspaceNavigation.ts'
    query: str=''
    global_route: bool=False
    unsafe_get: bool=False
    path: str='/v2/model-react/'

ROUTES=(
 Route('login','','form',global_route=True,path='/login',source='main_web.py'),
 Route('my-projects','','[data-new-project-cta]',global_route=True,source='tests/model_react_rcm_new_project_acceptance.py'),
 Route('wizard','#new-project','[data-new-project-wizard]',global_route=True,source='tests/model_react_rcm_new_project_acceptance.py'),
 Route('overview','#overview','[data-react-workspace-version]'),
 Route('inputs','#inputs','[data-inputs-overview]'),
 Route('capex-lines','#inputs/capex','[data-cost-workbench="capex"][data-cost-view="lines"]'),
 Route('capex-monthly','#inputs/capex/monthly','[data-capex-monthly]'),
 Route('opex-lines','#inputs/opex','[data-cost-workbench="opex"][data-cost-view="lines"]'),
 Route('opex-years','#inputs/opex/years','[data-opex-years]'),
 Route('financing','#financing','[data-financing-editing]',source='tests/model_react_pr3b2_acceptance.py'),
 Route('advanced-debt','#financing','[data-sheet-editor="debt"]',query='financing=terms',source='frontend/src/app/financing/FinancingStudio.tsx'),
 Route('bankability','#financing','[data-bankability-editor]',query='financing=bankability',source='frontend/src/app/financing/FinancingStudio.tsx'),
 Route('debt-metrics','#debt-metrics','[data-debt-metrics], [data-dm-empty]'),
 Route('covenant','#financing','[data-debt-metrics], [data-dm-empty]',query='financing=debt-metrics',source='frontend/src/app/financing/FinancingStudio.tsx'),
 Route('revenue','#inputs/revenue','[data-revenue-assumptions]'),
 Route('results','#results','[data-react-workspace-version]'),
 Route('statements','#statements','[data-react-workspace-version]'),
 Route('scenarios','#scenarios','[data-scenario-workspace]'),
 Route('legacy-workbook','','body',unsafe_get=True,source='app/v2/router.py'),
)


def url_for(base, route, project=None):
    if route.unsafe_get:return None
    if not route.global_route and not project:return None
    return base+route.path+('' if route.global_route else project)+('?' + route.query if route.query else '')+route.fragment
