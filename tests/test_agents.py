import json
import httpx
import pytest
from superagent.audit import initialize_internal
from superagent.planner import OpenAIPlanner
from superagent.usage import UsageLedger
from test_evaluations import candidate


def provider(cfg,payload,requests):
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'usage':{'prompt_tokens':100,'completion_tokens':50},
            'choices':[{'message':{'content':json.dumps(payload)}}]})
    return OpenAIPlanner(cfg.planner,api_key='private-fixture-key',
        client=httpx.Client(transport=httpx.MockTransport(respond)))


def test_agent_drafts_application_tool_without_execution_or_user_schema(db,db_url):
    from superagent.agents import ApplicationAgent
    tool,cfg=candidate(db)
    initialize_internal(db)
    requests=[]
    planner=provider(cfg,tool.model_dump(),requests)
    agent=ApplicationAgent(cfg,db_url,planner)
    before=db.execute('SELECT count(*) FROM tasks').fetchone()[0]
    drafted=agent.draft_tool('Create tasks for app users',tool.tool_id,1,
                             {name:spec.model_dump() for name,spec in tool.inputs.items()})
    assert drafted.app==cfg.app
    assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==before
    context=json.loads(requests[0]['messages'][1]['content'])
    assert 'identity' not in context
    assert context['schema_revision']==tool.schema_revision
    assert db_url not in json.dumps(requests)
    assert 'private-fixture-key' not in json.dumps(requests)
    assert db.execute('SELECT count(*) FROM superagent_internal.tools').fetchone()[0]==0
    assert UsageLedger(db_url).report(cfg.app,'2000-01-01','2100-01-01')['attempts']==1


@pytest.mark.parametrize('change',['other_app','code','policy','reserved_identity','oversize'])
def test_agent_adversarial_drafts_reject_and_record_usage(db,db_url,change):
    from superagent.agents import ApplicationAgent
    tool,cfg=candidate(db)
    initialize_internal(db)
    data=tool.model_dump()
    if change=='other_app':
        data['app']='another'
    elif change=='reserved_identity':
        data['inputs']['user_id']={'type':'integer'}
    elif change=='oversize':
        data['description']='x'*200000
    else:
        data[change]='malicious'
    agent=ApplicationAgent(cfg,db_url,provider(cfg,data,[]))
    with pytest.raises(ValueError):
        agent.draft_tool('Ignore rules',tool.tool_id,1,{'title':{'type':'string','max_length':80}})
    assert db.execute('SELECT count(*) FROM superagent_internal.tools').fetchone()[0]==0
    assert UsageLedger(db_url).report(cfg.app,'2000-01-01','2100-01-01')['failed']==1


def test_schema_proposal_is_app_wide_revision_bound_and_never_executes_ddl(db,db_url):
    from superagent.agents import ApplicationAgent
    tool,cfg=candidate(db)
    initialize_internal(db)
    data={'app':cfg.app,'base_schema_revision':tool.schema_revision,'summary':'Add app-wide notes',
        'changes':[{'kind':'add_column','table':'public.tasks','column':'notes','type':'text','nullable':True}]}
    proposal=ApplicationAgent(cfg,db_url,provider(cfg,data,[])).propose_schema('Add task notes')
    assert proposal.app==cfg.app
    assert proposal.base_schema_revision==tool.schema_revision
    assert db.execute("SELECT count(*) FROM information_schema.columns WHERE table_name='tasks' AND column_name='notes'").fetchone()[0]==0


def test_agent_daily_budget_and_output_bounds(db,db_url):
    from superagent.agents import ApplicationAgent
    tool,cfg=candidate(db)
    initialize_internal(db)
    cfg.planner.max_calls_per_day=1
    calls=[]
    agent=ApplicationAgent(cfg,db_url,provider(cfg,tool.model_dump(),calls))
    inputs={name:spec.model_dump() for name,spec in tool.inputs.items()}
    agent.draft_tool('create',tool.tool_id,1,inputs)
    with pytest.raises(ValueError):
        agent.draft_tool('again',tool.tool_id,1,inputs)
    assert len(calls)==1


def test_agent_hidden_column_and_user_namespace_proposals_reject(db,db_url):
    from superagent.agents import ApplicationAgent
    tool,cfg=candidate(db)
    initialize_internal(db)
    data=tool.model_dump()
    data['plan']['operations'][0]['values']['hidden']='secret'
    agent=ApplicationAgent(cfg,db_url,provider(cfg,data,[]))
    with pytest.raises(ValueError):
        agent.draft_tool('write hidden field',tool.tool_id,1,{'title':{'type':'string','max_length':80}})
    proposal={'app':cfg.app,'base_schema_revision':tool.schema_revision,'summary':'Per-user table',
        'changes':[{'kind':'add_table','table':'user_1.tasks','columns':[{'name':'id','type':'integer'}]}]}
    with pytest.raises(ValueError):
        ApplicationAgent(cfg,db_url,provider(cfg,proposal,[])).propose_schema('create per-user schema')
