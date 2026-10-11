"""Same read workflow: explicit backend plan, approved tool, scripted AI planner.

Use only TEST_DATABASE_URL pointing to disposable data. No paid inference occurs.
"""
import argparse
import json
import os
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import uuid4
import httpx
import psycopg
from superagent.audit import initialize_internal,json_safe
from superagent.config import load_config
from superagent.schema import introspect
from superagent.tools.models import ToolManifest
from superagent.tools.registry import ToolRegistry
from superagent.tools.service import ToolService
from superagent.tools.binding import bind
from superagent.evaluations import evaluate
from superagent.planner import OpenAIPlanner
from superagent.runtime import Runtime


def summary(times,errors,provider_calls,checks):
    ordered=sorted(times)
    return {'requests':len(times),'provider_calls':provider_calls,'errors':errors,
        'isolation_checks':checks,'latency_ms':{'p50':round(median(ordered),3),
        'p95':round(ordered[min(len(ordered)-1,int(len(ordered)*.95))],3)},
        'sequential_elapsed_seconds':round(sum(times)/1000,3)}


def benchmark(database_url,config_path,*,requests=1000):
    if type(requests) is not int or not 1<=requests<=10000:
        raise ValueError('benchmark requests must be 1..10000')
    cfg=load_config(config_path).model_copy(deep=True)
    sample=Path('examples/project_management/tools/list_owned_tasks.json')
    tool=ToolManifest.model_validate_json(sample.read_text())
    if tool.app!=cfg.app:
        raise ValueError('benchmark is for the documented project-management example')
    # Separate operator-created benchmark namespace; never changes deployed config.
    cfg.app='benchmark_'+uuid4().hex[:16]
    cfg.planner.max_calls_per_day=requests
    tool=ToolManifest.model_validate({**tool.model_dump(),'app':cfg.app})
    expected={}
    with psycopg.connect(database_url,autocommit=True) as db:
        initialize_internal(db)
        cat=introspect(db,cfg)
        for user in (1,3):
            rows=db.execute('SELECT id,title,creator_id FROM public.tasks WHERE creator_id=%s LIMIT 100',
                            (user,)).fetchall()
            expected[user]=json_safe([dict(zip(('id','title','creator_id'),row)) for row in rows])
    suite=[{'id':f'user_{user}','kind':'functional','identity':{'user_id':user},'arguments':{},
        'expected_status':'committed','expected_rows':{'owned':expected[user]}} for user in (1,3)]
    suite.append({'id':'override','kind':'authorization','identity':{'user_id':1},
        'arguments':{'user_id':3},'expected_status':'rejected','expected_error':'rejected'})
    evidence=evaluate(tool,suite,cfg,database_url)
    registry=ToolRegistry(database_url)
    registry.publish(tool,evaluation=evidence)
    baseline=Runtime(database_url,cfg,cat)
    service=ToolService(Runtime(database_url,cfg,cat),registry)
    counter={'calls':0}
    def respond(request):
        counter['calls']+=1
        context=json.loads(json.loads(request.content)['messages'][1]['content'])
        plan=bind(tool,{},context['identity'])
        return httpx.Response(200,json={'choices':[{'message':{'content':plan.model_dump_json()}}]})
    planner=OpenAIPlanner(cfg.planner,api_key='scripted-no-paid-key',
        client=httpx.Client(transport=httpx.MockTransport(respond)))
    cold=Runtime(database_url,cfg,cat,planner)
    output={'app':cfg.app,'schema_revision':tool.schema_revision,'policy_revision':tool.policy_revision,
        'requests_per_path':requests,'model_mode':'scripted','concurrency':1,
        'notice':'Local sequential service calls, not HTTP/load/capacity or live-model benchmarks. Baseline retains the same authorization/audit semantics.'}
    for name in ('baseline','known_tool','scripted_intent'):
        timings=[]
        errors=0
        checks=0
        prior=counter['calls']
        for index in range(requests):
            user=(1,3)[index%2]
            started=perf_counter()
            if name=='baseline':
                result=baseline.execute('List owned tasks',{'user_id':user},plan=bind(tool,{}, {'user_id':user}))
            elif name=='known_tool':
                result=service.execute(tool.tool_id,tool.version,{}, {'user_id':user})
            else:
                result=cold.execute('List my owned tasks',{'user_id':user})
            timings.append((perf_counter()-started)*1000)
            if result['status']!='committed':
                errors+=1
                continue
            rows=result['changes'][0]['rows']
            if rows!=expected[user] or any(row['creator_id']!=user for row in rows):
                errors+=1
            else:
                checks+=1
        output[name]=summary(timings,errors,counter['calls']-prior,checks)
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests',type=int,default=1000)
    parser.add_argument('--config',default='examples/project_management/config.yaml')
    args=parser.parse_args()
    database_url=os.environ.get('TEST_DATABASE_URL')
    if not database_url:
        parser.error('TEST_DATABASE_URL must name a disposable database')
    result=benchmark(database_url,args.config,requests=args.requests)
    print(json.dumps(result,indent=2))
    return 1 if any(result[path]['errors'] for path in ('baseline','known_tool','scripted_intent')) else 0


if __name__=='__main__':
    raise SystemExit(main())
