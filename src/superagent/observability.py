"""Operator-only app-scoped aggregates; never export private intent or row data."""
import psycopg
import json
import logging
from psycopg.rows import dict_row
from .usage import UsageLedger


def _write(event):
    try:
        logging.getLogger('superagent.events').info(json.dumps(event,sort_keys=True))
    except Exception:
        # Optional sinks cannot change execution or accounting outcomes.
        pass


def emit_attempt(app,attempt_id,purpose,status):
    _write({'event':'model_attempt','app':app,'attempt_id':attempt_id,
            'purpose':purpose,'status':status})


def emit(record,*,replayed=False):
    event={key:record.get(key) for key in ('app','audit_id','status','duration_ms','planner_attempt_id')
           if key in record}
    event.update(event='execution',replayed=replayed)
    if 'tool' in record:
        event['tool']={k:v for k,v in record['tool'].items() if k in ('tool_id','version','digest')}
    if 'error' in record:
        event['error_code']=record['error'].get('code')
    _write(event)


def report(app,database_url,start,end):
    with psycopg.connect(database_url,row_factory=dict_row) as conn:
        filters="record->>'app'=%s AND created_at >= %s::timestamptz AND created_at < %s::timestamptz"
        outcomes=conn.execute(f'''SELECT record->>'status' AS status,count(*) AS count
            FROM superagent_internal.audit WHERE {filters} GROUP BY record->>'status' ''',
            (app,start,end)).fetchall()
        latency=conn.execute(f'''SELECT
            COALESCE(percentile_cont(.5) WITHIN GROUP (ORDER BY (record->>'duration_ms')::double precision),0) AS p50,
            COALESCE(percentile_cont(.95) WITHIN GROUP (ORDER BY (record->>'duration_ms')::double precision),0) AS p95
            FROM superagent_internal.audit WHERE {filters}''',(app,start,end)).fetchone()
        tools=conn.execute(f'''SELECT record->'tool'->>'tool_id' AS tool_id,
            record->'tool'->>'version' AS version,record->>'status' AS status,count(*) AS count
            FROM superagent_internal.audit WHERE {filters} AND record ? 'tool'
            GROUP BY 1,2,3 ORDER BY 1,2,3''',(app,start,end)).fetchall()
    return {'app':app,'start':start,'end':end,'executions':sum(row['count'] for row in outcomes),
        'outcomes':{row['status']:row['count'] for row in outcomes},'latency_ms':latency,
        'tools':tools,'usage':UsageLedger(database_url).report(app,start,end),
        'notice':'Audit counts exclude replayed responses and pre-runtime HTTP validation failures. Costs may be unknown.'}
