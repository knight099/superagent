import json
from pathlib import Path
from superagent.config import load_config
from superagent.schema import introspect
from superagent.revisions import schema_revision,policy_revision
from superagent.tools.models import ToolManifest


def test_example_tool_manifests_match_the_shared_application_schema(db):
    cfg=load_config('examples/project_management/config.yaml')
    cat=introspect(db,cfg)
    for name in ('create_task','list_owned_tasks'):
        tool=ToolManifest.model_validate_json(Path(f'examples/project_management/tools/{name}.json').read_text())
        assert tool.app==cfg.app
        assert tool.schema_revision==schema_revision(cat,cfg)
        assert tool.policy_revision==policy_revision(cfg)


def test_repeat_workload_uses_no_model_and_keeps_user_data_isolated(db,db_url):
    from scripts.benchmark_tools import benchmark
    result=benchmark(db_url,'examples/project_management/config.yaml',requests=12)
    assert result['requests_per_path']==12
    assert result['known_tool']['provider_calls']==0
    assert result['scripted_intent']['provider_calls']==12
    assert result['known_tool']['isolation_checks']==12
    assert result['known_tool']['errors']==0
    assert result['baseline']['errors']==0
    assert result['model_mode']=='scripted'
    json.dumps(result)


def test_reusable_cost_scenario_accounts_for_build_cost():
    from scripts.cost_compare import estimate
    result=estimate(requests=100000,input_tokens=4000,output_tokens=500,input_rate=.4,
        output_rate=1.6,compute=6,database=15.15,planner_fraction=.05,build_cost=5)
    assert result['ai_monthly']==12
    assert result['runtime_monthly']==38.15
    assert result['backend_monthly']==21.15
