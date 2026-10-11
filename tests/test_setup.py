"""Claims about connecting a new database and saving metadata use real PostgreSQL."""
import json
import pytest
from superagent.cli import main
from superagent.config import load_config


def test_init_discovers_database_and_stores_schema(db,db_url,tmp_path,monkeypatch,capsys):
    monkeypatch.setenv('DATABASE_URL',db_url)
    config=tmp_path/'app.yaml'
    snapshot=tmp_path/'schema.json'
    assert main(['init','--from-db','--config',str(config),'--schema-file',str(snapshot)]) == 0
    cfg=load_config(config)
    assert set(cfg.tables) == {'public.users','public.projects','public.project_members','public.tasks'}
    assert 'assignee_id' in cfg.tables['public.tasks'].columns
    assert all(not any(t.permissions.values()) for t in cfg.tables.values())
    saved=json.loads(snapshot.read_text())
    assert saved['format_version'] == 1
    assert saved['app'] == cfg.app
    table=saved['catalog']['tables']['public.tasks']
    assert table['primary_key'] == ['id']
    assert table['columns']['assignee_id']['type'] == 'integer'
    assert {'p','f','c'} <= {c['kind'] for c in table['constraints']}
    assert 'superagent_test' not in snapshot.read_text()
    assert 'Fix login' not in snapshot.read_text()
    assert 'permissions' in capsys.readouterr().out
    original=snapshot.read_text()
    assert main(['init','--from-db','--config',str(config),'--schema-file',str(snapshot)]) == 1
    assert snapshot.read_text() == original


def test_discovery_never_includes_internal_or_other_schemas(db,db_url,tmp_path,monkeypatch):
    from superagent.audit import initialize_internal
    initialize_internal(db)
    db.execute('CREATE SCHEMA hidden; CREATE TABLE hidden.secret (id int PRIMARY KEY)')
    monkeypatch.setenv('DATABASE_URL',db_url)
    config=tmp_path/'app.yaml'
    snapshot=tmp_path/'schema.json'
    assert main(['init','--from-db','--config',str(config),'--schema-file',str(snapshot)]) == 0
    assert 'hidden' not in snapshot.read_text()
    assert 'superagent_internal' not in snapshot.read_text()
    assert main(['init','--from-db','--schema','superagent_internal',
                 '--config',str(tmp_path/'bad.yaml'),'--schema-file',str(tmp_path/'bad.json')]) == 1
    assert not (tmp_path/'bad.yaml').exists()


def test_schema_refresh_preserves_allowlist_and_excludes_hidden_metadata(
        db,db_url,tmp_path,monkeypatch):
    import yaml
    db.execute('ALTER TABLE tasks ADD COLUMN internal_note text')
    cfg={'app':'test','tables':{'public.tasks':{
        'columns':['id','title'],'permissions':{'select':True}}}}
    config=tmp_path/'app.yaml'
    config.write_text(yaml.safe_dump(cfg))
    snapshot=tmp_path/'schema.json'
    monkeypatch.setenv('DATABASE_URL',db_url)
    assert main(['schema','--config',str(config),'--schema-file',str(snapshot)]) == 0
    saved=json.loads(snapshot.read_text())
    assert set(saved['catalog']['tables']['public.tasks']['columns']) == {'id','title'}
    assert 'internal_note' not in snapshot.read_text()
    db.execute('ALTER TABLE tasks ADD COLUMN another_hidden integer')
    assert main(['schema','--config',str(config),'--schema-file',str(snapshot)]) == 0
    assert 'another_hidden' not in snapshot.read_text()


def test_failed_discovery_leaves_no_config(db,db_url,tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_URL',db_url)
    assert main(['init','--from-db','--schema','does_not_exist',
                 '--config',str(tmp_path/'app.yaml'),'--schema-file',str(tmp_path/'schema.json')]) == 1
    assert not (tmp_path/'app.yaml').exists()


def test_cost_estimator_reproduces_documented_example():
    from scripts.cost_compare import estimate
    result=estimate(requests=10000,input_tokens=4000,output_tokens=500,
                    input_rate=0.40,output_rate=1.60,compute=6,database=15.15)
    assert result['ai_per_request'] == pytest.approx(0.0024)
    assert result['ai_monthly'] == pytest.approx(24)
    assert result['backend_monthly'] == pytest.approx(21.15)
    assert result['runtime_monthly'] == pytest.approx(45.15)


@pytest.mark.parametrize('command', ['init', 'schema', 'run'])
def test_schema_destination_cannot_alias_config(command,db,db_url,tmp_path,monkeypatch):
    from importlib.resources import files
    monkeypatch.setenv('DATABASE_URL',db_url)
    config=tmp_path/'app.yaml'
    original=files('superagent').joinpath('templates/project_management.yaml').read_text()
    if command != 'init':
        config.write_text(original)
    args=[command,'--config',str(config),'--schema-file',str(config)]
    if command == 'init':
        args.append('--from-db')
    assert main(args) == 1
    if command == 'init':
        assert not config.exists()
    else:
        assert config.read_text() == original


def test_config_creation_failure_preserves_snapshot(db,db_url,tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_URL',db_url)
    snapshot=tmp_path/'schema.json'
    snapshot.write_text('existing snapshot')
    config=tmp_path/'missing'/'app.yaml'
    assert main(['init','--from-db','--config',str(config),'--schema-file',str(snapshot)]) == 1
    assert snapshot.read_text() == 'existing snapshot'
    assert not config.exists()


def test_snapshot_failure_removes_new_config(db,db_url,tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_URL',db_url)
    snapshot=tmp_path/'schema.json'
    snapshot.mkdir()
    config=tmp_path/'app.yaml'
    assert main(['init','--from-db','--config',str(config),'--schema-file',str(snapshot)]) == 1
    assert not config.exists()
    assert snapshot.is_dir()
