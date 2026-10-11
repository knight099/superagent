import json
from test_tools_execution import configured


def test_observability_app_scoped_and_excludes_intents_identity_and_rows(db,db_url):
    from superagent.observability import report
    service,registry,tool=configured(db,db_url)
    service.execute(tool.tool_id,1,{'title':'private-row-value'},{'user_id':1},'observed')
    service.execute(tool.tool_id,1,{'title':'bad','user_id':2},{'user_id':1},'rejected')
    data=report(tool.app,db_url,'2000-01-01','2100-01-01')
    assert data['executions']==2
    assert data['outcomes']=={'committed':1,'rejected':1}
    assert data['usage']['attempts']==0
    assert data['latency_ms']['p95']>0
    assert data['tools'][0]['tool_id']==tool.tool_id
    assert 'private-row-value' not in json.dumps(data)
    assert 'identity' not in json.dumps(data)
    assert db_url not in json.dumps(data)
    assert report('other',db_url,'2000-01-01','2100-01-01')['executions']==0


def test_structured_events_redact_values_and_logging_failure_cannot_reject_commit(db,db_url,caplog):
    import logging
    service,registry,tool=configured(db,db_url)
    with caplog.at_level(logging.INFO,logger='superagent.events'):
        result=service.execute(tool.tool_id,1,{'title':'private-log-value'},{'user_id':1},'logged')
    assert result['status']=='committed'
    assert 'private-log-value' not in caplog.text
    assert 'duration_ms' in caplog.text
    class BrokenHandler(logging.Handler):
        def emit(self,record):
            raise RuntimeError('sink offline')
    logger=logging.getLogger('superagent.events')
    handler=BrokenHandler()
    logger.addHandler(handler)
    previous=logger.level
    logger.setLevel(logging.INFO)
    try:
        result=service.execute(tool.tool_id,1,{'title':'committed-despite-log-sink'},{'user_id':1},'sink-fail')
        assert result['status']=='committed'
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    assert db.execute("SELECT count(*) FROM tasks WHERE title='committed-despite-log-sink'").fetchone()[0]==1
