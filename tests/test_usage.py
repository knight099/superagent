import json
import httpx
from superagent.audit import initialize_internal
from superagent.runtime import Runtime
from superagent.planner import OpenAIPlanner
from superagent.models import TransitionPlan
from test_runtime import mutation
from test_tools_execution import configured


class DeclaredUsage:
    usage={'prompt_tokens':4000,'completion_tokens':500,'total_tokens':4500}
    def plan(self,*args):
        data=mutation().model_dump()
        data['operations'][0]['values']['assignee_id']=999
        return TransitionPlan.model_validate(data)


def test_billable_attempt_survives_execution_rollback(db,db_url,cfg,cat):
    from superagent.usage import UsageLedger
    initialize_internal(db)
    result=Runtime(db_url,cfg,cat,DeclaredUsage()).execute('create',{'user_id':1},'fail')
    assert result['status']=='rejected'
    report=UsageLedger(db_url).report(cfg.app,'2000-01-01','2100-01-01')
    assert report['attempts']==1
    assert report['prompt_tokens']==4000
    assert report['completion_tokens']==500
    assert report['estimated_usd'] is None
    assert db.execute("SELECT count(*) FROM tasks WHERE title='new'").fetchone()[0]==0


def test_invalid_provider_response_records_attempt_and_declared_usage(db,db_url,cfg,cat):
    from superagent.usage import UsageLedger
    initialize_internal(db)
    provider=OpenAIPlanner(cfg.planner,api_key='fake',client=httpx.Client(
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
            'usage':{'prompt_tokens':120,'completion_tokens':20},
            'choices':[{'message':{'content':json.dumps({'sql':'DROP TABLE tasks'})}}]}))))
    result=Runtime(db_url,cfg,cat,provider).execute('attack',{'user_id':1},'bad')
    assert result['status']=='rejected'
    report=UsageLedger(db_url).report(cfg.app,'2000-01-01','2100-01-01')
    assert report['attempts']==1
    assert report['failed']==1
    assert report['prompt_tokens']==120


def test_missing_usage_is_unknown_and_rate_estimates_explicit(db,db_url):
    from superagent.usage import UsageLedger
    initialize_internal(db)
    ledger=UsageLedger(db_url)
    attempt=ledger.begin('test','planning','provider','model')
    ledger.finish(attempt,'failed',None,None)
    attempt=ledger.begin('test','planning','provider','model')
    ledger.finish(attempt,'succeeded',{'prompt_tokens':4000,'completion_tokens':500},
        {'input_per_million':.4,'output_per_million':1.6,'checked_at':'2026-10-11'})
    ledger.begin('test','planning','provider','model')
    report=ledger.report('test','2000-01-01','2100-01-01')
    assert report['unknown_usage_attempts']==2
    assert report['estimated_usd']==.0024
    assert report['unpriced_attempts']==2
    assert ledger.report('other','2000-01-01','2100-01-01')['attempts']==0


def test_supplied_tool_has_no_planner_attempts(db,db_url):
    from superagent.usage import UsageLedger
    service,registry,tool=configured(db,db_url,DeclaredUsage())
    assert service.execute(tool.tool_id,1,{'title':'direct'},{'user_id':1},'tool')['status']=='committed'
    assert UsageLedger(db_url).report(tool.app,'2000-01-01','2100-01-01')['attempts']==0


def test_concurrent_agent_budget_reserves_only_one_attempt(db,db_url):
    from concurrent.futures import ThreadPoolExecutor
    from superagent.usage import UsageLedger
    initialize_internal(db)
    ledger=UsageLedger(db_url)
    def reserve(_):
        try:
            return ledger.begin('test','draft','provider','model',limit=1)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        attempts=list(pool.map(reserve,range(4)))
    assert len([attempt for attempt in attempts if attempt])==1
    assert ledger.report('test','2000-01-01','2100-01-01')['attempts']==1
