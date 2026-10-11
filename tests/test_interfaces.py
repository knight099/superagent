import json
import httpx
import pytest
from fastapi.testclient import TestClient
from superagent.planner import OpenAIPlanner, PlannerError
from superagent.api import create_app
from superagent.cli import main
from superagent.audit import initialize_internal
from superagent.runtime import Runtime
from superagent.config import load_config
from test_runtime import mutation, CountingPlanner


def test_planner_uses_strict_schema_and_no_rows_or_credentials(cfg):
    from test_core import catalog
    def respond(request):
        body = json.loads(request.content)
        assert body['response_format']['type'] == 'json_schema'
        assert 'DATABASE_URL' not in request.content.decode()
        assert body['messages'][1]['role'] == 'user'
        return httpx.Response(200,json={'choices':[{'message':{
            'content':mutation().model_dump_json()}}], 'usage':{'total_tokens':123}})
    client = httpx.Client(transport=httpx.MockTransport(respond))
    planner = OpenAIPlanner(cfg.planner, api_key='test-secret',client=client)
    result = planner.plan('create task',catalog(),cfg,{'user_id':1})
    assert result.operations[0].kind == 'insert'
    assert planner.usage['total_tokens'] == 123


@pytest.mark.parametrize('content', ['not-json', '{"sql":"DROP TABLE tasks"}',
                                    '{"operations":[]}'])
def test_planner_rejects_malformed_output(content,cfg):
    from test_core import catalog
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200,
        json={'choices':[{'message':{'content':content}}]})))
    with pytest.raises(PlannerError):
        OpenAIPlanner(cfg.planner,api_key='test',client=client).plan('x',catalog(),cfg,{'user_id':1})


def test_provider_errors_are_sanitized(cfg):
    from test_core import catalog
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401,
                                                                                 text='secret')))
    with pytest.raises(PlannerError,match='provider request failed') as error:
        OpenAIPlanner(cfg.planner,api_key='secret',client=client).plan('x',catalog(),cfg,{'user_id':1})
    assert 'secret' not in str(error.value)


def test_api_requires_trusted_identity_and_excludes_plan_payload(db,db_url,cfg,cat):
    initialize_internal(db)
    client = TestClient(create_app(Runtime(db_url,cfg,cat,CountingPlanner())))
    assert client.post('/v1/execute',json={'intent':'create'}).status_code == 401
    headers = {'X-User-ID':'1','Idempotency-Key':'api-key'}
    assert client.post('/v1/execute',headers=headers,json={'intent':'create','plan':{}}).status_code == 422
    result = client.post('/v1/execute',headers=headers,json={'intent':'create'})
    assert result.status_code == 200
    assert result.json()['status'] == 'committed'
    assert client.post('/v1/execute',headers=headers,json={'intent':'create'}).json() == result.json()


def test_api_dry_run(db,db_url,cfg,cat):
    initialize_internal(db)
    client = TestClient(create_app(Runtime(db_url,cfg,cat,CountingPlanner())))
    result = client.post('/v1/execute',headers={'X-User-ID':'1'},
                         json={'intent':'create','dry_run':True})
    assert result.json()['status'] == 'explained'
    assert db.execute("SELECT count(*) FROM tasks WHERE title='new'").fetchone()[0] == 0


def test_cli_init_writes_valid_config_without_overwriting(tmp_path):
    target = tmp_path/'superagent.yaml'
    assert main(['init','--config',str(target)]) == 0
    assert load_config(target).app == 'project_management'
    assert main(['init','--config',str(target)]) == 1


def test_cli_explain_runs_no_plan_sql(db,db_url,tmp_path,monkeypatch,capsys):
    monkeypatch.setenv('DATABASE_URL',db_url)
    target = tmp_path/'config.yaml'
    main(['init','--config',str(target)])
    planfile = tmp_path/'plan.json'
    planfile.write_text(mutation().model_dump_json())
    assert main(['explain','--config',str(target),'--plan',str(planfile),'--user-id','1']) == 0
    assert 'explained' in capsys.readouterr().out
    assert db.execute("SELECT count(*) FROM tasks WHERE title='new'").fetchone()[0] == 0


def test_string_identity_preserves_leading_zero_and_idempotency_scope(db,db_url,cfg,cat):
    cfg.auth.user_id_type = 'string'
    initialize_internal(db)
    client = TestClient(create_app(Runtime(db_url,cfg,cat,CountingPlanner())))
    first = client.post('/v1/execute',headers={'X-User-ID':'01','Idempotency-Key':'shared'},
                        json={'intent':'create'})
    second = client.post('/v1/execute',headers={'X-User-ID':'1','Idempotency-Key':'shared'},
                         json={'intent':'create'})
    assert first.status_code == second.status_code == 200
    assert first.json()['audit_id'] != second.json()['audit_id']
    scopes = {row[0] for row in db.execute('SELECT identity FROM superagent_internal.requests')}
    assert scopes == {'"01"','"1"'}


def test_integer_identity_rejects_noncanonical_form(db,db_url,cfg,cat):
    initialize_internal(db)
    client = TestClient(create_app(Runtime(db_url,cfg,cat,CountingPlanner())))
    assert client.post('/v1/execute',headers={'X-User-ID':'01'},
                       json={'intent':'query','dry_run':True}).status_code == 401


def test_planner_does_not_receive_hidden_foreign_relationship(db,cfg):
    from superagent.schema import introspect
    from superagent.config import Config
    db.execute('CREATE SCHEMA hidden; CREATE TABLE hidden.secret_table (secret_id int PRIMARY KEY);'
               'CREATE TABLE public.visible (id int PRIMARY KEY, link int REFERENCES hidden.secret_table)')
    cfg = Config.model_validate({'app':'meta','tables':{'public.visible':{
        'columns':['id','link'],'permissions':{'select':True}}}})
    cat = introspect(db,cfg)
    def respond(request):
        assert 'secret_table' not in request.content.decode()
        assert 'secret_id' not in request.content.decode()
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({
            'operations':[{'id':'r','kind':'select','table':'public.visible','select':['id']}]})}}]})
    client=httpx.Client(transport=httpx.MockTransport(respond))
    OpenAIPlanner(cfg.planner,api_key='test',client=client).plan('read',cat,cfg,{'user_id':1})


def test_cli_identity_parser_uses_explicit_type():
    from superagent.config import AuthConfig, parse_user_id
    assert parse_user_id('01',AuthConfig(user_id_type='string')) == '01'
    assert parse_user_id('1',AuthConfig()) == 1
    with pytest.raises(ValueError):
        parse_user_id('01',AuthConfig())
