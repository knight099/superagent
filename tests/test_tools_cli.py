from superagent.cli import main
from superagent.audit import initialize_internal
from test_tools_execution import configured


def test_export_import_preserves_digest(db,db_url,tmp_path,monkeypatch):
    from superagent.tools.registry import artifact_digest
    from superagent.tools.models import ToolManifest
    service,registry,tool=configured(db,db_url)
    config=tmp_path/'config.yaml'
    import yaml
    config.write_text(yaml.safe_dump(service.runtime.config.model_dump()))
    destination=tmp_path/'tool.json'
    monkeypatch.setenv('DATABASE_URL',db_url)
    assert main(['tools','export','--config',str(config),'--id',tool.tool_id,
                 '--version','1','--output',str(destination)])==0
    exported=ToolManifest.model_validate_json(destination.read_text())
    assert artifact_digest(exported)==artifact_digest(tool)
    assert 'superagent_test' not in destination.read_text()
    assert main(['tools','publish','--config',str(config),'--file',str(destination)])==0
    assert main(['tools','revoke','--config',str(config),'--id',tool.tool_id,
                 '--version','1','--reason','testing'])==0
    assert registry.list(tool.app)[0]['status']=='revoked'


def test_cli_publish_requires_compatible_app(db,db_url,tmp_path,monkeypatch):
    import yaml
    from superagent.config import load_config
    from test_tools_registry import tool
    initialize_internal(db)
    cfg=load_config('examples/project_management/config.yaml')
    config=tmp_path/'app.yaml'
    config.write_text(yaml.safe_dump(cfg.model_dump()))
    manifest=tmp_path/'tool.json'
    manifest.write_text(tool('other').model_dump_json())
    monkeypatch.setenv('DATABASE_URL',db_url)
    assert main(['tools','publish','--config',str(config),'--file',str(manifest)])==1
    assert db.execute('SELECT count(*) FROM superagent_internal.tools').fetchone()[0]==0
