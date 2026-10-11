"""Seven acceptance demos. All application operations are declarative plans."""
import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
from time import perf_counter
import uuid
import psycopg
from superagent.audit import initialize_internal
from superagent.config import load_config
from superagent.models import TransitionPlan
from superagent.runtime import Runtime
from superagent.schema import introspect


def scenarios():
    today = date.today()
    due = (today + timedelta(days=(4-today.weekday()) % 7 or 7)).isoformat()
    def lookup(name, ident):
        return {'id':ident,'kind':'select','table':'public.users',
                'select':['id'],'where':[{'field':'name','op':'eq','value':name}]}
    create = {'operations':[lookup('Rahul','rahul'), {'id':'create','kind':'insert',
        'table':'public.tasks','values':{'title':'Demo high priority task','project_id':1,
            'creator_id':1,'assignee_id':{'ref':'rahul','column':'id'},'priority':'high',
            'due_date':due},'returning':['id','title','assignee_id']}]}
    reassign = {'operations':[lookup('John','john'),lookup('Rahul','rahul'),
        {'id':'move','kind':'update','table':'public.tasks',
         'values':{'assignee_id':{'ref':'rahul','column':'id'}},
         'where':[{'field':'assignee_id','op':'eq','value':{'ref':'john','column':'id'}},
                  {'field':'done','op':'eq','value':False}], 'returning':['id','assignee_id']}]}
    overdue = {'operations':[{'id':'overdue','kind':'select','table':'public.tasks',
        'select':['id','title','due_date'], 'where':[
            {'field':'due_date','op':'lt','value':today.isoformat()},
            {'field':'done','op':'eq','value':False}]}]}
    bounded = {'operations':[{'id':'bounded','kind':'update','table':'public.tasks',
        'values':{'priority':'low'},'where':[{'field':'creator_id','op':'eq','value':1},
        {'field':'done','op':'eq','value':False},{'field':'priority','op':'eq','value':'normal'}],
        'returning':['id','priority']}]}
    denied = {'operations':[{'id':'denied','kind':'update','table':'public.tasks',
        'values':{'title':'Unauthorized'},'where':[{'field':'id','op':'eq','value':3}]}]}
    invariant = {'operations':[
        {'id':'complete','kind':'update','table':'public.tasks','values':{'done':True},
         'where':[{'field':'id','op':'eq','value':1}]},
        {'id':'reopen','kind':'update','table':'public.tasks','values':{'done':False},
         'where':[{'field':'id','op':'eq','value':1}]}]}
    return [
        ('Create a high-priority task for Rahul due Friday',create,'committed'),
        ("Move all John's unfinished tasks to Rahul",reassign,'committed'),
        ('Find my overdue unfinished tasks',overdue,'committed'),
        ('Set my normal-priority unfinished tasks to low priority',bounded,'committed'),
        ('Change task 3 owned by Alice to Unauthorized',denied,'rejected'),
        ('Complete task 1 then reopen it',invariant,'rejected'),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true',help='Use a configured model instead of fixtures')
    parser.add_argument('--config',default='examples/project_management/config.yaml')
    parser.add_argument('--write-plans',action='store_true')
    args = parser.parse_args()
    cases = scenarios()
    if args.write_plans:
        Path('examples/project_management/plans.json').write_text(json.dumps(cases,indent=2)+'\n')
        return
    cfg = load_config(args.config)
    url = os.environ[cfg.database.url_env]
    with psycopg.connect(url,autocommit=True) as db:
        initialize_internal(db)
        catalog = introspect(db,cfg)
        if args.live:
            from superagent.planner import OpenAIPlanner
            planner = OpenAIPlanner(cfg.planner)
        else:
            planner = None
        rt = Runtime(url,cfg,catalog,planner)
        identity = {'user_id':1}
        prefix = str(uuid.uuid4())
        timings, responses = [], []
        for index,(intent, fixture, expected) in enumerate(cases):
            started = perf_counter()
            result = rt.execute(intent,identity,f'{prefix}-{index}',
                                plan=None if args.live else TransitionPlan.model_validate(fixture))
            timings.append(round((perf_counter()-started)*1000,2))
            assert result['status'] == expected, result
            responses.append(result)
            print(json.dumps({'demo':index+1,'intent':intent,'latency_ms':timings[-1],
                              'result':result},default=str))
        replay = rt.execute(cases[0][0],identity,f'{prefix}-0',
            plan=None if args.live else TransitionPlan.model_validate(cases[0][1]))
        assert replay == responses[0], 'retry must return the original response'
        assert db.execute('SELECT done FROM tasks WHERE id=1').fetchone()[0] is False
        print(json.dumps({'demo':7,'intent':'Retry creation with identical idempotency key',
                          'result':replay},default=str))
        print(json.dumps({'measurements':{'required_workflows':7,
            'workflows_requiring_new_backend_functions':0,'application_backend_LOC':0,
            'policy_config_lines':len(Path(args.config).read_text().splitlines()),
            'latency_ms':timings,'model_mode':'live' if args.live else 'fixture',
            'model_tokens':getattr(planner,'usage',None),
            'note':'Fixtures measure runtime correctness, not natural-language plan accuracy. '
                   'Live-model accuracy/cost and the 80% hypothesis require further measurement.'}}))


if __name__ == '__main__':
    main()
