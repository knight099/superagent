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
