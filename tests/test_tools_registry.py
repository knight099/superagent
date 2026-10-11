from concurrent.futures import ThreadPoolExecutor
import pytest
from superagent.audit import initialize_internal
from test_tools_binding import manifest_data


def tool(app='test',version=1):
    from superagent.tools.models import ToolManifest
    data=manifest_data()
    data.update(app=app,version=version)
    return ToolManifest.model_validate(data)


def evidence(manifest):
    # Registry storage tests use a report fixture. Execution of eval cases is
    # separately verified in test_evaluations.py against real PostgreSQL.
    from superagent.tools.registry import artifact_digest
    return {'format_version':1,'app':manifest.app,'tool_id':manifest.tool_id,
        'version':manifest.version,'digest':artifact_digest(manifest),
        'schema_revision':manifest.schema_revision,'policy_revision':manifest.policy_revision,
        'suite_revision':'c'*64,'created_at':'2026-10-11T00:00:00+00:00',
        'passed':True,'case_count':2,'functional_checks':1,'authorization_checks':1,
        'results':[
            {'id':'functional','kind':'functional','expected_status':'committed',
             'actual_status':'committed','passed':True,'error_code':None,'asserted_result':True},
            {'id':'authorization','kind':'authorization','expected_status':'rejected',
             'actual_status':'rejected','passed':True,'error_code':'rejected','asserted_result':True,
             'authorization_guard':True}]}


def registry(db,db_url):
    from superagent.tools.registry import ToolRegistry
    initialize_internal(db)
    return ToolRegistry(db_url)


def test_registry_scopes_versions_to_application(db,db_url):
    r=registry(db,db_url)
    r.publish(tool(),evaluation=evidence(tool()))
    assert r.get('test','create_task',1).app=='test'
    with pytest.raises(ValueError):
        r.get('other','create_task',1)
    r.publish(tool('other'),evaluation=evidence(tool('other')))
    assert r.get('other','create_task',1).app=='other'


def test_artifact_overwrite_conflicts(db,db_url):
    r=registry(db,db_url)
    first=tool()
    r.publish(first,evaluation=evidence(first))
    changed=first.model_copy(update={'description':'different'})
    with pytest.raises(ValueError):
        r.publish(changed,evaluation=evidence(changed))
    assert r.get('test','create_task',1).description==first.description


def test_repeat_publish_is_idempotent(db,db_url):
    r=registry(db,db_url)
    assert r.publish(tool(),evaluation=evidence(tool()))==r.publish(tool(),evaluation=evidence(tool()))
    assert db.execute('SELECT count(*) FROM superagent_internal.tools').fetchone()[0]==1
    initialize_internal(db)
    assert r.get('test','create_task',1).version==1


def test_revocation_survives_concurrent_publish(db,db_url):
    r=registry(db,db_url)
    r.publish(tool(),evaluation=evidence(tool()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(r.revoke,'test','create_task',1,'operator revoked'),
                 pool.submit(r.publish,tool(),evaluation=evidence(tool()))]
        for future in futures:
            future.result()
    with pytest.raises(ValueError):
        r.get('test','create_task',1)
    assert r.list('test')[0]['status']=='revoked'
