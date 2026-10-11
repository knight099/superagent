"""Compiler-owned syntax and bound values. Never accept model-generated SQL."""
from dataclasses import dataclass
from psycopg import sql
from .models import Reference, Calculation


@dataclass
class Statement:
    sql: sql.Composable
    params: list

    def explain(self):
        return {'sql': self.sql.as_string(), 'parameters': self.params}


OPERATORS = {'eq': '=', 'ne': '<>', 'lt': '<', 'lte': '<=', 'gt': '>', 'gte': '>='}


def binding(value, resolve=None):
    if isinstance(value, (Reference, Calculation)):
        return resolve(value) if resolve else value.model_dump()
    return value


def predicate_sql(predicates, resolve=None):
    parts, params = [], []
    for p in predicates:
        name = sql.Identifier(p.field)
        if p.op == 'is_null':
            parts.append(sql.SQL('{} IS {}NULL').format(name, sql.SQL('' if p.value else 'NOT ')))
        elif p.op == 'in':
            parts.append(sql.SQL('{} = ANY(%s)').format(name))
            params.append(p.value)
        else:
            parts.append(sql.SQL('{} {} %s').format(name, sql.SQL(OPERATORS[p.op])))
            params.append(binding(p.value, resolve))
    return Statement(sql.SQL(' AND ').join(parts) if parts else sql.SQL('TRUE'), params)


def compile_operation(op, resolve=None):
    table = sql.Identifier(*op.table.split('.'))
    where = predicate_sql(getattr(op, 'where', []), resolve)
    names = lambda fields: sql.SQL(', ').join(map(sql.Identifier, fields))
    params = []
    if op.kind == 'select':
        query = sql.SQL('SELECT {} FROM {} WHERE {} LIMIT %s').format(
            names(op.select), table, where.sql)
        params = [*where.params, op.limit]
    elif op.kind == 'insert':
        query = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(table, names(op.values),
            sql.SQL(', ').join(sql.Placeholder() for _ in op.values))
        params = [binding(v, resolve) for v in op.values.values()]
    elif op.kind == 'update':
        assignments = sql.SQL(', ').join(sql.SQL('{} = %s').format(sql.Identifier(k))
                                         for k in op.values)
        query = sql.SQL('UPDATE {} SET {} WHERE {}').format(table, assignments, where.sql)
        params = [*[binding(v, resolve) for v in op.values.values()], *where.params]
    else:
        query = sql.SQL('DELETE FROM {} WHERE {}').format(table, where.sql)
        params = where.params
    returning = getattr(op, 'returning', [])
    if returning:
        query += sql.SQL(' RETURNING {}').format(names(returning))
    return Statement(query, params)
