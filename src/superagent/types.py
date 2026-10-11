"""Static compatibility for the v0.1 scalar PostgreSQL type subset."""
from datetime import date, datetime
import math
import re
from uuid import UUID
from .validation import Rejection


def family(pg_type):
    base = re.sub(r'\([^)]*\)', '', pg_type).strip()
    if base in ('smallint','integer','bigint'):
        return 'integer'
    if base in ('numeric','decimal','real','double precision'):
        return 'number'
    if base in ('text','character varying','character','varchar','char'):
        return 'text'
    if base.startswith('timestamp'):
        return 'timestamp'
    if base in ('boolean','date','uuid'):
        return base
    return None


def compatible(source, target):
    src, dst = family(source.type), family(target.type)
    return (src == dst and src is not None) or (src == 'integer' and dst == 'number')


def check_literal(value, column):
    if value is None:
        if not column.nullable:
            raise Rejection('non-null column cannot be null')
        return
    category = family(column.type)
    valid = False
    if category == 'integer':
        valid = type(value) is int
    elif category == 'number':
        valid = type(value) in (int,float) and math.isfinite(value)
    elif category == 'boolean':
        valid = type(value) is bool
    elif category == 'text':
        valid = type(value) is str
    elif category in ('date','timestamp','uuid') and type(value) is str:
        try:
            {'date':date.fromisoformat,'timestamp':datetime.fromisoformat,'uuid':UUID}[category](value)
            valid = True
        except ValueError:
            pass
    if not valid:
        raise Rejection(f'value type is incompatible with column {column.name}')
