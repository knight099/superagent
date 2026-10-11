from concurrent.futures import ThreadPoolExecutor
from superagent.audit import initialize_internal
from superagent.config import load_config
from superagent.schema import introspect
from superagent.runtime import Runtime
from test_tools_binding import manifest_data


def configured(db,db_url,planner=None):
    from superagent.tools.models import ToolManifest
    from superagent.tools.registry import ToolRegistry
    from superagent.tools.service import ToolService
    from superagent.revisions import schema_revision,policy_revision
    cfg=load_config('examples/project_management/config.yaml')
    cat=introspect(db,cfg)
    data=manifest_data()
    data.update(app=cfg.app,schema_revision=schema_revision(cat,cfg),policy_revision=policy_revision(cfg))
    tool=ToolManifest.model_validate(data)
    initialize_internal(db)
    registry=ToolRegistry(db_url)
    from superagent.evaluations import evaluate
    from test_evaluations import cases
    registry.publish(tool,evaluation=evaluate(tool,cases(),cfg,db_url))
    rt=Runtime(db_url,cfg,cat,planner)
    return ToolService(rt,registry),registry,tool


class NoPlanner:
    calls=0
    usage={'prompt_tokens':999}
    def plan(self,*args):
        self.calls+=1
        raise AssertionError('direct tools must not plan')


def test_known_tool_makes_zero_provider_calls(db,db_url):
    planner=NoPlanner()
    service,registry,tool=configured(db,db_url,planner)
    result=service.execute(tool.tool_id,1,{'title':'reusable'},{'user_id':1},'tool-1')
    assert result['status']=='committed'
    assert planner.calls==0
    record=db.execute('SELECT record FROM superagent_internal.audit').fetchone()[0]
    assert record['tool']['tool_id']==tool.tool_id
    assert record['tool']['version']==1
    assert 'planner_usage' not in record
    assert record['app']=='project_management'


def test_two_users_share_definition_not_permissions(db,db_url):
    service,registry,tool=configured(db,db_url)
    for user in (1,2):
        assert service.execute(tool.tool_id,1,{'title':f'owner-{user}'},{'user_id':user},'same')['status']=='committed'
    rows=db.execute("SELECT title,creator_id FROM tasks WHERE title LIKE 'owner-%' ORDER BY creator_id").fetchall()
    assert rows==[('owner-1',1),('owner-2',2)]
    assert db.execute('SELECT count(*) FROM superagent_internal.tools').fetchone()[0]==1
    assert db.execute("SELECT count(*) FROM pg_namespace WHERE nspname LIKE 'user_%'").fetchone()[0]==0


def test_revoked_or_drifted_tool_fails_closed(db,db_url):
    service,registry,tool=configured(db,db_url)
    first=service.execute(tool.tool_id,1,{'title':'first'},{'user_id':1},'same')
    assert first['status']=='committed'
    db.execute('ALTER TABLE tasks ALTER COLUMN title TYPE varchar(200)')
    assert service.execute(tool.tool_id,1,{'title':'new'},{'user_id':1},'new')['status']=='rejected'
    registry.revoke(tool.app,tool.tool_id,1,'stop')
    assert service.execute(tool.tool_id,1,{'title':'first'},{'user_id':1},'same')['status']=='rejected'
    assert db.execute("SELECT count(*) FROM tasks WHERE title='new'").fetchone()[0]==0


def test_policy_drift_blocks_cached_tools(db,db_url):
    service,registry,tool=configured(db,db_url)
    service.runtime.config.tables['public.tasks'].permissions['insert']=False
    assert service.execute(tool.tool_id,1,{'title':'denied'},{'user_id':1},'no')['status']=='rejected'


def test_tool_version_is_in_retry_fingerprint(db,db_url):
    service,registry,tool=configured(db,db_url)
    from superagent.evaluations import evaluate
    from test_evaluations import cases
    next_tool=tool.model_copy(update={'version':2})
    registry.publish(next_tool,evaluation=evaluate(next_tool,cases(),service.runtime.config,db_url))
    assert service.execute(tool.tool_id,1,{'title':'a'},{'user_id':1},'same')['status']=='committed'
    result=service.execute(tool.tool_id,2,{'title':'a'},{'user_id':1},'same')
    assert result['status']=='rejected'
    assert 'conflicts' in result['error']['message']


def test_concurrent_tool_retry_commits_once(db,db_url):
    service,registry,tool=configured(db,db_url)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:service.execute(tool.tool_id,1,{'title':'concurrent'},
            {'user_id':1},'parallel'),range(4)))
    assert all(result==results[0] for result in results)
    assert results[0]['status']=='committed'
    assert db.execute("SELECT count(*) FROM tasks WHERE title='concurrent'").fetchone()[0]==1


def test_invalid_tool_arguments_are_audited_without_application_effects(db,db_url):
    service,registry,tool=configured(db,db_url)
    result=service.execute(tool.tool_id,1,{'title':'bad','user_id':2},{'user_id':1},'bad')
    assert result['status']=='rejected'
    assert db.execute("SELECT count(*) FROM tasks WHERE title='bad'").fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM superagent_internal.audit').fetchone()[0]==1


def test_changed_database_default_invalidates_existing_tool(db,db_url):
    service,registry,tool=configured(db,db_url)
    db.execute("ALTER TABLE tasks ALTER COLUMN priority SET DEFAULT 'high'")
    result=service.execute(tool.tool_id,1,{'title':'unexpected-default'},{'user_id':1},'default-drift')
    assert result['status']=='rejected'
    assert db.execute("SELECT count(*) FROM tasks WHERE title='unexpected-default'").fetchone()[0]==0
