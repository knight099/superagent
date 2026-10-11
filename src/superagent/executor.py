"""Bounded operations in a single transaction. Database errors propagate to rollback."""
from psycopg import sql
from psycopg.rows import dict_row
from .compiler import compile_operation, predicate_sql
from .expressions import resolve_value
from .validation import Rejection, validate


class Executor:
    def __init__(self, config, catalog):
        self.config, self.catalog = config, catalog

    def execute(self, conn, plan, identity):
        validate(plan, self.catalog, self.config)
        results, changes = {}, []
        affected_total = 0
        with conn.transaction():
            conn.execute("SELECT set_config('statement_timeout', %s, true)",
                         (str(self.config.limits.statement_timeout_ms),))
            with conn.cursor(row_factory=dict_row) as cur:
                for op in plan.operations:
                    resolve = lambda value: resolve_value(value, results)
                    cfg = self.config.tables[op.table]
                    table = self.catalog.tables[op.table]
                    qualified = sql.Identifier(*op.table.split('.'))
                    if op.kind == 'select':
                        statement = compile_operation(op, resolve)
                        cur.execute(statement.sql, statement.params)
                        rows = cur.fetchall()
                        affected = 0
                    elif op.kind == 'insert':
                        if affected_total >= self.config.limits.max_rows:
                            raise Rejection('plan row limit exceeded')
                        statement = compile_operation(op, resolve)
                        # Fetch server defaults/generated fields for later checks.
                        base = op.model_copy(update={'returning': cfg.columns})
                        statement = compile_operation(base, resolve)
                        cur.execute(statement.sql, statement.params)
                        row = cur.fetchone()
                        rows = [{k: row[k] for k in op.returning}]
                        affected = 1
                    else:
                        if not table.primary_key:
                            raise Rejection('mutations require a primary key')
                        where = predicate_sql(op.where, resolve)
                        lock_columns = list(dict.fromkeys([*cfg.columns, *table.primary_key]))
                        cur.execute(sql.SQL('SELECT {} FROM {} WHERE {} LIMIT %s FOR UPDATE').format(
                            sql.SQL(', ').join(map(sql.Identifier, lock_columns)),
                            qualified, where.sql), [*where.params, self.config.limits.max_rows + 1])
                        targets = cur.fetchall()
                        if len(targets) + affected_total > self.config.limits.max_rows:
                            raise Rejection('plan row limit exceeded')
                        if not targets:
                            raise Rejection('no authorized matching rows')
                        rows = []
                        for before in targets:
                            pk = sql.SQL(' AND ').join(sql.SQL('{} = %s').format(sql.Identifier(k))
                                                       for k in table.primary_key)
                            pk_values = [before[k] for k in table.primary_key]
                            if op.kind == 'delete':
                                cur.execute(sql.SQL('DELETE FROM {} WHERE {}').format(qualified, pk),
                                            pk_values)
                                after = before
                            else:
                                assignments = sql.SQL(', ').join(sql.SQL('{} = %s').format(
                                    sql.Identifier(k)) for k in op.values)
                                cur.execute(sql.SQL('UPDATE {} SET {} WHERE {} RETURNING {}').format(
                                    qualified, assignments, pk,
                                    sql.SQL(', ').join(map(sql.Identifier, cfg.columns))),
                                    [*[resolve(v) for v in op.values.values()], *pk_values])
                                after = cur.fetchone()
                            rows.append({k: after[k] for k in op.returning})
                        affected = len(targets)
                    affected_total += affected
                    results[op.id] = rows
                    changes.append({'id': op.id, 'kind': op.kind, 'table': op.table,
                                    'affected': affected, 'rows': rows})
        return changes
