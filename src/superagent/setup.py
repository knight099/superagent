"""Developer-invoked database discovery and credential-free schema snapshots."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import os
from dataclasses import asdict
from psycopg.rows import dict_row
from .config import Config


RESERVED_SCHEMAS = {'superagent_internal', 'pg_catalog', 'information_schema'}


def discover_config(conn, schema='public'):
    if schema in RESERVED_SCHEMAS or schema.startswith('pg_'):
        raise ValueError('reserved schema cannot be discovered')
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('''SELECT c.relname AS name, array_agg(a.attname ORDER BY a.attnum) AS columns
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid
            WHERE n.nspname = %s AND c.relkind = 'r'
            AND a.attnum > 0 AND NOT a.attisdropped
            GROUP BY c.relname ORDER BY c.relname''', (schema,))
        tables = {f'{schema}.{row["name"]}': {'columns':row['columns'],
            'permissions':{'select':False,'insert':False,'update':False,'delete':False}}
            for row in cur.fetchall()}
    return Config.model_validate({'app':'my_app','tables':tables})


def save_schema(catalog, config, path):
    """Persist only allowlisted metadata; snapshots never authorize requests."""
    tables = {}
    for name, table in catalog.tables.items():
        allowed = set(config.tables[name].columns)
        tables[name] = {'schema':table.schema, 'name':table.name,
            'columns':{k:asdict(v) for k,v in table.columns.items() if k in allowed},
            'primary_key':[k for k in table.primary_key if k in allowed],
            'constraints':table.constraints}
    data = {'format_version':1, 'app':config.app,
            'captured_at':datetime.now(timezone.utc).isoformat(), 'catalog':{'tables':tables}}
    destination = Path(path)
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',
                dir=destination.parent,prefix='.schema-',delete=False) as handle:
            temporary=Path(handle.name)
            json.dump(data,handle,indent=2)
            handle.write('\n')
        os.replace(temporary,destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
