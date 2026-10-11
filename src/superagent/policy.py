"""Generic three-valued row/identity policy AST, shared by SQL and postconditions."""
import operator
from datetime import date, datetime
from psycopg import sql
from .compiler import Statement, OPERATORS
from .models import Operand
from .validation import Rejection


COMPARISONS = {'eq': operator.eq, 'ne': operator.ne, 'lt': operator.lt,
               'lte': operator.le, 'gt': operator.gt, 'gte': operator.ge}


def operand(value, context):
    if isinstance(value, Operand):
        source = context.get(value.source, {})
        if value.field not in source:
            raise Rejection(f'missing policy operand: {value.source}.{value.field}')
        return source[value.field]
    return value


def evaluate(expr, context):
    if isinstance(expr, bool):
        return expr
    if expr.op in ('all', 'any', 'not'):
        # Evaluate all operands, so missing claims never hide behind a true branch.
        values = [evaluate(a, context) for a in expr.args]
        if expr.op == 'not':
            return None if values[0] is None else not values[0]
        if expr.op == 'all':
            return False if False in values else (None if None in values else True)
        return True if True in values else (None if None in values else False)
    left = operand(expr.left, context)
    if expr.op == 'is_null':
        return left is None
    right = operand(expr.right, context)
    if left is None or right is None:
        return None
    try:
        if isinstance(left, (date, datetime)) and isinstance(right, str):
            right = type(left).fromisoformat(right)
        if isinstance(right, (date, datetime)) and isinstance(left, str):
            left = type(right).fromisoformat(left)
        return COMPARISONS[expr.op](left, right)
    except (TypeError, ValueError) as exc:
        raise Rejection('incompatible policy operand types') from exc


def policy_sql(expr, identity):
    if isinstance(expr, bool):
        return Statement(sql.SQL('TRUE' if expr else 'FALSE'), [])
    if expr.op in ('all', 'any', 'not'):
        parts = [policy_sql(a, identity) for a in expr.args]
        params = [p for part in parts for p in part.params]
        if expr.op == 'not':
            return Statement(sql.SQL('NOT ({})').format(parts[0].sql), params)
        joined = sql.SQL(' AND ' if expr.op == 'all' else ' OR ').join(
            sql.SQL('({})').format(p.sql) for p in parts)
        return Statement(joined, params)
    def term(value):
        if isinstance(value, Operand) and value.source == 'row':
            return Statement(sql.Identifier(value.field), [])
        if isinstance(value, Operand) and value.source != 'identity':
            raise Rejection('pre-operation policy can only use row and identity')
        return Statement(sql.Placeholder(), [operand(value, {'identity':identity})])
    left = term(expr.left)
    if expr.op == 'is_null':
        return Statement(sql.SQL('{} IS NULL').format(left.sql), left.params)
    right = term(expr.right)
    return Statement(sql.SQL('{} {} {}').format(left.sql, sql.SQL(OPERATORS[expr.op]), right.sql),
                     [*left.params, *right.params])


def check_after(cfg, kind, before, after, identity):
    context = {'before':before,'after':after,'row':after,'identity':identity}
    if kind in cfg.after and evaluate(cfg.after[kind], context) is not True:
        raise Rejection('after-row authorization denied')
    for invariant in cfg.invariants:
        if evaluate(invariant, context) is not True:
            raise Rejection('invariant rejected transition')
