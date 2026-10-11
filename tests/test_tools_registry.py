from concurrent.futures import ThreadPoolExecutor
import pytest
from superagent.audit import initialize_internal
from test_tools_binding import manifest_data


def tool(app='test',version=1):
    from superagent.tools.models import ToolManifest
    data=manifest_data()
    data.update(app=app,version=version)
    return ToolManifest.model_validate(data)


def registry(db,db_url):
    from superagent.tools.registry import ToolRegistry
    initialize_internal(db)
    return ToolRegistry(db_url)


def test_registry_scopes_versions_to_application(db,db_url):
    r=registry(db,db_url)
    r.publish(tool())
    assert r.get('test','create_task',1).app=='test'
    with pytest.raises(ValueError):
        r.get('other','create_task',1)
    r.publish(tool('other'))
    assert r.get('other','create_task',1).app=='other'


def test_artifact_overwrite_conflicts(db,db_url):
    r=registry(db,db_url)
    first=tool()
    r.publish(first)
    changed=first.model_copy(update={'description':'different'})
    with pytest.raises(ValueError):
        r.publish(changed)
    assert r.get('test','create_task',1).description==first.description


def test_repeat_publish_is_idempotent(db,db_url):
    r=registry(db,db_url)
    assert r.publish(tool())==r.publish(tool())
    assert db.execute('SELECT count(*) FROM superagent_internal.tools').fetchone()[0]==1
    initialize_internal(db)
    assert r.get('test','create_task',1).version==1


def test_revocation_survives_concurrent_publish(db,db_url):
    r=registry(db,db_url)
    r.publish(tool())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(r.revoke,'test','create_task',1,'operator revoked'),
                 pool.submit(r.publish,tool())]
        for future in futures:
            future.result()
    with pytest.raises(ValueError):
        r.get('test','create_task',1)
    assert r.list('test')[0]['status']=='revoked'
