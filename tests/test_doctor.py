import json
from superagent.config import load_config
from superagent.audit import initialize_internal


def test_doctor_redacts_credentials(db,db_url,monkeypatch):
    from superagent.doctor import doctor
    cfg=load_config('examples/project_management/config.yaml')
    monkeypatch.setenv(cfg.planner.key_env,'private-api-secret')
    initialize_internal(db)
    report=doctor(cfg,db_url)
    assert report['ready'] is True
    assert report['app']==cfg.app
    assert report['planner_key_present'] is True
    assert 'private-api-secret' not in json.dumps(report)
    assert db_url not in json.dumps(report)
    assert 'superagent_test' not in json.dumps(report)


def test_doctor_detects_schema_drift(db,db_url):
    from superagent.doctor import doctor
    from test_tools_execution import configured
    service,registry,tool=configured(db,db_url)
    db.execute('ALTER TABLE tasks ALTER COLUMN title TYPE varchar(200)')
    report=doctor(service.runtime.config,db_url)
    assert not report['ready']
    assert report['incompatible_tools']==[{'tool_id':tool.tool_id,'version':1}]
