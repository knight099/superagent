"""Deterministic revisions of application-wide allowed metadata and rules."""
from dataclasses import asdict
import hashlib
import json


def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),
                                    allow_nan=False).encode()).hexdigest()


def schema_revision(catalog, config):
    tables={}
    for name,allowed in config.tables.items():
        table=catalog.tables[name]
        tables[name]={'columns':{k:asdict(table.columns[k]) for k in sorted(allowed.columns)},
            'primary_key':[k for k in table.primary_key if k in allowed.columns],
            'constraints':sorted(table.constraints,key=lambda c:json.dumps(c,sort_keys=True))}
    return digest(tables)


def policy_revision(config):
    tables={}
    for name,table in config.tables.items():
        data=table.model_dump()
        data['columns']=sorted(data['columns'])
        data['sensitive_columns']=sorted(data['sensitive_columns'])
        tables[name]=data
    return digest({'tables':tables,'auth':config.auth.model_dump(),
                   'limits':config.limits.model_dump()})
