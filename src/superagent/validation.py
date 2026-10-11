"""Fail-closed static plan validation, performed before SQL compilation."""
from .models import Reference, Calculation


class Rejection(ValueError):
    pass


def validate(plan, catalog, config):
    if len(plan.operations) > config.limits.max_operations:
        raise Rejection('maximum operations exceeded')
    prior = {}
    for op in plan.operations:
        if op.table not in config.tables or op.table not in catalog.tables:
            raise Rejection(f'table is not allowed: {op.table}')
        cfg, table = config.tables[op.table], catalog.tables[op.table]
        if cfg.permissions.get(op.kind, False) is False:
            raise Rejection(f'{op.kind} is not granted on {op.table}')
        fields = set(getattr(op, 'values', {})) | set(getattr(op, 'select', []))
        fields |= set(getattr(op, 'returning', [])) | {p.field for p in getattr(op, 'where', [])}
        if fields - set(cfg.columns) or fields - set(table.columns):
            raise Rejection('unknown or disallowed column')
        values = getattr(op, 'values', {})
        if any(table.columns[k].generated for k in values):
            raise Rejection('generated columns are not writable')
        if op.kind == 'insert':
            required = {k for k, c in table.columns.items()
                        if not c.nullable and not c.default and not c.generated}
            if required - values.keys():
                raise Rejection('required insert columns missing')
        for k, v in values.items():
            if v is None and not table.columns[k].nullable:
                raise Rejection('non-null column cannot be null')
        if op.kind == 'select' and op.limit > config.limits.max_read_rows:
            raise Rejection('read limit exceeds configuration')
        def check(v):
            if isinstance(v, Reference):
                if v.ref not in prior or v.column not in prior[v.ref]:
                    raise Rejection('reference must name an earlier returned column')
            elif isinstance(v, Calculation):
                check(v.left)
                check(v.right)
        for v in [*values.values(), *(p.value for p in getattr(op, 'where', []))]:
            check(v)
        prior[op.id] = getattr(op, 'select', getattr(op, 'returning', []))
