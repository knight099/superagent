"""Internal durable audit and idempotency storage, unreachable by transition plans."""
import json
from psycopg.types.json import Jsonb


def json_safe(value):
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def initialize_internal(conn):
    with conn.transaction():
        conn.execute('''CREATE SCHEMA IF NOT EXISTS superagent_internal;
            CREATE TABLE IF NOT EXISTS superagent_internal.audit (
                id uuid PRIMARY KEY,
                created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                record jsonb NOT NULL
            );
            CREATE TABLE IF NOT EXISTS superagent_internal.requests (
                app text NOT NULL,
                identity text NOT NULL,
                key text NOT NULL,
                fingerprint text NOT NULL,
                response jsonb,
                created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                PRIMARY KEY (app, identity, key)
            );
            CREATE TABLE IF NOT EXISTS superagent_internal.tools (
                app text NOT NULL,
                tool_id text NOT NULL,
                version integer NOT NULL CHECK (version > 0),
                digest text NOT NULL,
                manifest jsonb NOT NULL,
                status text NOT NULL CHECK (status IN ('active','revoked')),
                created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                revoked_at timestamptz,
                reason text,
                PRIMARY KEY (app,tool_id,version)
            );
            CREATE TABLE IF NOT EXISTS superagent_internal.model_attempts (
                id uuid PRIMARY KEY,
                app text NOT NULL,
                purpose text NOT NULL,
                provider text NOT NULL,
                model text NOT NULL,
                status text NOT NULL CHECK (status IN ('started','succeeded','failed','unknown')),
                usage jsonb,
                rates jsonb,
                estimated_usd numeric,
                created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                finished_at timestamptz
            )''')


def redact(value, config):
    sensitive = {column for table in config.tables.values() for column in table.sensitive_columns}
    def walk(item):
        if isinstance(item, dict):
            predicate_sensitive = item.get('field') in sensitive
            return {k: '[REDACTED]' if k in sensitive or
                    (predicate_sensitive and k == 'value') else walk(v)
                    for k,v in item.items()}
        if isinstance(item, list):
            return [walk(v) for v in item]
        return item
    return walk(json_safe(value))


def write_audit(conn, audit_id, record, config):
    conn.execute('INSERT INTO superagent_internal.audit (id, record) VALUES (%s, %s)',
                 (audit_id, Jsonb(redact(record, config))))
