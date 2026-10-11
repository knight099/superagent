"""Model attempt accounting commits independently of application transactions."""
import math
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class UsageLedger:
    def __init__(self,database_url):
        self.database_url=database_url

    def begin(self,app,purpose,provider,model):
        attempt=str(uuid4())
        with psycopg.connect(self.database_url) as conn:
            conn.execute('''INSERT INTO superagent_internal.model_attempts
                (id,app,purpose,provider,model,status) VALUES (%s,%s,%s,%s,%s,'started')''',
                (attempt,app,purpose,provider,model))
        return attempt

    def finish(self,attempt_id,status,usage,rates):
        if status not in ('succeeded','failed','unknown'):
            raise ValueError('invalid attempt status')
        clean=None
        if isinstance(usage,dict) and all(type(usage.get(k)) is int and 0<=usage[k]<=1_000_000_000
                for k in ('prompt_tokens','completion_tokens')):
            clean={k:usage[k] for k in ('prompt_tokens','completion_tokens')}
        estimate=None
        if rates is not None:
            keys=('input_per_million','output_per_million')
            if (not isinstance(rates,dict) or not isinstance(rates.get('checked_at'),str)
                    or not all(type(rates.get(k)) in (int,float) and math.isfinite(rates[k])
                               and 0<=rates[k]<=1_000_000 for k in keys)):
                raise ValueError('explicit finite token rates and date are required')
            rates={k:rates[k] for k in (*keys,'checked_at')}
            if clean is not None:
                estimate=(clean['prompt_tokens']*rates[keys[0]]+
                          clean['completion_tokens']*rates[keys[1]])/1_000_000
        with psycopg.connect(self.database_url) as conn:
            result=conn.execute('''UPDATE superagent_internal.model_attempts
                SET status=%s,usage=%s,rates=%s,estimated_usd=%s,finished_at=clock_timestamp()
                WHERE id=%s AND status='started' ''',
                (status,Jsonb(clean),Jsonb(rates),estimate,attempt_id))
            if result.rowcount!=1:
                raise ValueError('attempt is unknown or already finished')

    def report(self,app,start,end):
        with psycopg.connect(self.database_url,row_factory=dict_row) as conn:
            row=conn.execute('''SELECT count(*) AS attempts,
                count(*) FILTER (WHERE status='failed') AS failed,
                count(*) FILTER (WHERE status='started' OR usage IS NULL OR usage='null'::jsonb)
                    AS unknown_usage_attempts,
                count(*) FILTER (WHERE estimated_usd IS NULL) AS unpriced_attempts,
                COALESCE(sum((usage->>'prompt_tokens')::bigint),0) AS prompt_tokens,
                COALESCE(sum((usage->>'completion_tokens')::bigint),0) AS completion_tokens,
                sum(estimated_usd) AS estimated_usd
                FROM superagent_internal.model_attempts
                WHERE app=%s AND created_at >= %s::timestamptz AND created_at < %s::timestamptz''',
                (app,start,end)).fetchone()
        row['estimated_usd']=float(row['estimated_usd']) if row['estimated_usd'] is not None else (
            0.0 if row['attempts']==0 else None)
        return row
