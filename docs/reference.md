# Runtime reference

This page describes the v0.1 plan language and deterministic execution boundary.

## Typed plans and explain

```json
{
  "version": 1,
  "operations": [
    {"id": "rahul", "kind": "select", "table": "public.users", "select": ["id"],
     "where": [{"field": "name", "op": "eq", "value": "Rahul"}], "limit": 2},
    {"id": "move", "kind": "update", "table": "public.tasks",
     "values": {"assignee_id": {"ref": "rahul", "column": "id"}},
     "where": [{"field": "id", "op": "eq", "value": 1}],
     "returning": ["id", "assignee_id"]}
  ]
}
```

Save this as `plan.json`:

```sh
superagent explain --plan plan.json --user-id 1
superagent execute --plan plan.json --intent 'Assign task 1 to Rahul' --user-id 1 --key assign-1
```

Explain compiles templates and reports row-policy predicates separately from the
mutation template. The executor combines them, locks a bounded target set, then
updates/deletes rows by their primary keys. **Explain executes no plan SQL**;
state-dependent authorization, references, invariants, and constraints are marked
as deferred. It is not a guarantee a later transaction will commit. CLI supplied-
plan explain emits JSON without persisting audit; intent/API dry-run persists an
explanation audit without claiming an execution key or mutating application rows.

Supported predicates: AND of `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in` (1–100
literals), and `is_null` with a boolean value. All columns are explicit.
Updates/deletes require predicates. A reference must select/return its column
from an earlier operation with exactly one row; zero or multiple rows reject.
There are no SQL fragments, wildcard projections, joins, subqueries or loops.
Calculations support `{"calc":"add","left":1,"right":2}` and
`{"calc":"date_add_days","left":{"ref":"task","column":"due_date"},"right":3}`.
Date adjustment is limited to ±3650 days; numeric results to magnitude 10^12.

All values are parameterized, including identity and limits. PostgreSQL owns
constraint validation; static validation checks scalar/reference compatibility
for integers, numerics, booleans, text, dates, timestamps and UUIDs. Writes to
other PostgreSQL types are rejected in v0.1. The compiler owns SQL syntax and
identifier quoting. Model responses are strictly parsed with Pydantic before
validation. Provider constrained decoding is advisory: dynamic column maps use
JSON-schema mode without vendor-specific strict decoding.

## Generic policy/invariant DSL

```yaml
permissions:
  update:
    op: any
    args:
      - op: eq
        left: {source: row, field: creator_id}
        right: {source: identity, field: user_id}
      - op: eq
        left: {source: row, field: assignee_id}
        right: {source: identity, field: user_id}
after:
  update:
    op: eq
    left: {source: after, field: creator_id}
    right: {source: before, field: creator_id}
invariants:
  - op: gte
    left: {source: after, field: due_date}
    right: {source: after, field: created_at}
```

This is a generic AST, not hidden functions named `creator_or_assignee`.
Boolean permissions are supported; missing permissions deny. Comparisons are
`eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `is_null`; logical expressions are `all`,
`any`, and single-argument `not`. Operands are literals or fields from `row`,
`identity`, `before`, and `after`. Read/update/delete pre-operation predicates
use `row` and `identity`; insert permission sees database-returned defaults.
After-row policies and invariants run after inserts/updates before commit.
Insert `before` fields are null. Use `is_null` explicitly for optional fields.
Null comparisons remain unknown, including under `not`; only true authorizes.
Missing claims reject. Invariants do not run on deletes; express delete rights
with permissions and use database constraints for cross-table integrity.

The sample prevents creator changes and reopening completed tasks, requires an
assignee and enforces date ordering. Cross-table/aggregate invariants are outside
this DSL. Configuration complexity is part of the experiment and is printed by
the demos, rather than counted as eliminated business logic.

## Safety, audit, and retries

Defaults: 20 operations, 100 total mutated rows, 100 rows per read, 2-second
statement timeout, 64 KiB serialized plan. Configuration bounds have hard ceilings.
Mutation sets that exceed limits abort without silently truncating. Reads are
explicitly limited. Updates/deletes require primary keys and lock selected rows.
All mutations in an intent roll back together on policy, invariant, constraint,
reference, timeout or required audit failure. No automatic mutation retries.

Mutation execution requires an idempotency key. Keys are scoped by app and stable
user ID; the fingerprint includes intent, identity and a supplied plan. Concurrent
retries serialize and return the original saved response; changed payloads with
the same key conflict. Failed transactions do not claim a committed key. Provider
planning happens after replay lookup. Claims may wait up to the statement timeout;
a timed-out duplicate can safely retry the same request/key.

`superagent_internal.audit` stores JSON records containing identity, original
intent, proposed plan, decision, results/errors, permitted before/after mutation effects independent of
requested returning columns, provider token usage when available, timing and audit ID. Committed
records and request responses share the mutation transaction; failed records
are written after rollback. Missing audit storage rejects execution. Raw SQL
exception text and provider response bodies are never returned. Set table
`sensitive_columns` to redact named fields in plans, results and audit records.
Original free-text intent is retained, so avoid putting secrets into intents.
Audit and idempotency records require your own retention/access policy. v0.1
promises rollback on failure, not universal undo or guaranteed success after
an ambiguous network disconnect; retry using the same idempotency key.

