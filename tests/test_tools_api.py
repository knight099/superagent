from fastapi.testclient import TestClient
from superagent.api import create_app
from test_tools_execution import configured


def test_tools_api_identity_and_closed_request_contract(db,db_url):
    service,registry,tool=configured(db,db_url)
    client=TestClient(create_app(service.runtime))
    endpoint=f'/v1/tools/{tool.tool_id}/execute'
    payload={'version':1,'arguments':{'title':'via-http'}}
    assert client.post(endpoint,json=payload).status_code==401
    assert client.post(endpoint,headers={'X-User-ID':'1'},json={**payload,'app':'other'}).status_code==422
    result=client.post(endpoint,headers={'X-User-ID':'1','Idempotency-Key':'api-tool'},json=payload)
    assert result.status_code==200
    assert result.json()['status']=='committed'
    assert client.post(endpoint,headers={'X-User-ID':'1','Idempotency-Key':'dry'},
        json={**payload,'dry_run':True}).json()['status']=='explained'


def test_http_request_size_bound_prevents_oversized_tool_body(db,db_url):
    service,registry,tool=configured(db,db_url)
    client=TestClient(create_app(service.runtime))
    response=client.post(f'/v1/tools/{tool.tool_id}/execute',
        headers={'X-User-ID':'1','Idempotency-Key':'large'},
        json={'version':1,'arguments':{'title':'x'*70000}})
    assert response.status_code==413
    assert db.execute('SELECT count(*) FROM superagent_internal.audit').fetchone()[0]==0
