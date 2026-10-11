"""Closed scalar calculations and references; never evaluate source code."""
from datetime import date, datetime, timedelta
import math
from decimal import Decimal
from .models import Reference, Calculation
from .validation import Rejection


def resolve_value(value, results):
    if isinstance(value, Reference):
        rows = results[value.ref]
        if len(rows) != 1:
            raise Rejection('reference requires exactly one result row')
        return rows[0][value.column]
    if isinstance(value, Calculation):
        left, right = resolve_value(value.left, results), resolve_value(value.right, results)
        if value.calc == 'date_add_days':
            if type(right) is not int or abs(right) > 3650:
                raise Rejection('date adjustment must be an integer within 3650 days')
            if isinstance(left, str):
                try:
                    left = date.fromisoformat(left)
                except ValueError as exc:
                    raise Rejection('date calculation requires ISO date') from exc
            if not isinstance(left, (date, datetime)):
                raise Rejection('date calculation requires a date')
            return left + timedelta(days=right)
        if type(left) not in (int, float, Decimal) or type(right) not in (int, float, Decimal):
            raise Rejection('addition requires numbers')
        if isinstance(left, Decimal) or isinstance(right, Decimal):
            left, right = Decimal(str(left)), Decimal(str(right))
        total = left + right
        finite = total.is_finite() if isinstance(total, Decimal) else math.isfinite(total)
        if not finite or abs(total) > 10**12:
            raise Rejection('calculation magnitude exceeds limit')
        return total
    return value
