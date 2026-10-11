# Superagent 0.1

**Database + Policies + Agent = Backend.** Superagent turns natural-language
intent into a typed, validated PostgreSQL transition. A planner proposes reads,
inserts, updates, and deletes; deterministic code authorizes and executes them
in one bounded transaction. No application-specific CRUD controllers, services,
repositories, or tool functions are required by the example.

This first version is an experimental runtime with a deliberately small plan
language. It includes a real PostgreSQL test suite, durable audit and retry
handling, an intent API, a CLI, and seven reproducible example scenarios.

## Quick start

Requires Python 3.12+ and Docker Compose (or an existing PostgreSQL 16+ database).

```sh
git clone https://github.com/knight099/superagent.git
cd superagent
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
docker compose up -d --wait
export DATABASE_URL='postgresql://superagent:superagent_dev@localhost:5432/superagent'
superagent init
superagent init-db
python examples/project_management/demo.py
```

The fixture demo runs all seven required workflows without an LLM key. Run it
against fresh sample data: reassigning all John's work changes what a second run
can match. `docker compose down -v` deletes the **example database** when you
explicitly want to reset it; then start Compose again. It is unnecessary for
normal runtime usage and must not be used against a database you want to keep.

The demos create a task by Rahul's name, reassign John's unfinished tasks,
query overdue work, update a bounded conditional set, reject Alice's unauthorized
change, roll back a complete-then-reopen invariant violation, and replay creation
without duplication. They print audit IDs, row results, latency, and configuration
size. Fixtures prove runtime behavior; they do not measure natural-language
accuracy or prove the 80% product hypothesis.

To use natural-language planning:

```sh
export OPENAI_API_KEY='your-key'
superagent run
curl http://127.0.0.1:8000/v1/execute \
  -H 'Content-Type: application/json' \
  -H 'X-User-ID: 1' \
  -H 'Idempotency-Key: create-task-001' \
  -d '{"intent":"Create a high-priority task for Rahul due Friday in project Launch"}'
```

Set `planner.model`, `planner.url`, and `planner.key_env` in `superagent.yaml` for
an OpenAI-compatible provider supporting JSON-schema response formatting.
`python examples/project_management/demo.py --live` exercises the same scenarios
with the model. Model mistakes can produce rejected plans; live-model evaluation
is separate from deterministic security tests. No credentials or live-model
access are bundled, and token prices depend on your provider.

API request fields are only `intent` and optional `dry_run`. Plans and policies
cannot be supplied through the HTTP endpoint. `X-User-ID` is a **trusted header**:
put the service behind a gateway that authenticates users, strips client-supplied
identity headers, and supplies verified identity. The default host is loopback.
`auth.mode: dev` permits a missing header to become user 1 for local experiments;
never deploy that mode publicly. There is no built-in JWT/OIDC verification yet.

## Connect another PostgreSQL application

1. Point the configured `database.url_env` at your existing database URL.
2. Replace `tables` with explicitly allowed qualified tables and columns.
3. Add operation permissions, after-row permissions, and invariants in YAML.
4. Run `superagent init-db` once with a role permitted to create the internal
   schema, then use a restricted runtime role with only necessary application
   DML and internal table access. Do not give it database-owner/superuser rights.
5. Run `superagent explain --intent 'your request' --user-id 1`, then execute
   through the API or `superagent execute --intent 'your request' --user-id 1 --key unique-key`.

The runtime introspects columns, types, defaults, generated fields, primary keys,
foreign keys, unique and check constraints. The planner receives allowlisted
metadata and policy context, not database rows or connection credentials.
Refresh/restart after schema changes. Config must stay developer-owned.

PostgreSQL constraints remain authoritative. RLS can add another authorization
boundary if your deployment configures verified database identity; Superagent
v0.1 does not automatically provision RLS or impersonate database roles.
Database triggers, functions, constraints and the configured model endpoint are
trusted deployment components, not agent-managed infrastructure.

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
value conversion and constraint validation; the compiler owns SQL syntax and
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
intent, proposed plan, decision, results/errors, timing and audit ID. Committed
records and request responses share the mutation transaction; failed records
are written after rollback. Missing audit storage rejects execution. Raw SQL
exception text and provider response bodies are never returned. Set table
`sensitive_columns` to redact named fields in plans, results and audit records.
Original free-text intent is retained, so avoid putting secrets into intents.
Audit and idempotency records require your own retention/access policy. v0.1
promises rollback on failure, not universal undo or guaranteed success after
an ambiguous network disconnect; retry using the same idempotency key.

## Development and verification

Use a separate disposable database: integration fixtures reset its public and
internal schemas. Never set `TEST_DATABASE_URL` to production or sample data you
want to retain.

```sh
export TEST_DATABASE_URL='postgresql://superagent:superagent_dev@localhost:5432/superagent'
pytest -q
ruff check .
pip wheel . --no-deps -w dist
```

Without `TEST_DATABASE_URL`, PostgreSQL tests explicitly skip; CI provisions
PostgreSQL 16 and runs them. Tests cover introspection, strict parsing, policies,
null/missing claims, parameterization, commit/rollback, limits, timeout, references,
server defaults, invariants, audit failure, concurrent idempotency, dry-run,
adversarial plans, provider parsing, API identity, and CLI bootstrap.

See [design](docs/superpowers/specs/2026-10-11-superagent-v01-design.md) and
[implementation plan](docs/superpowers/plans/2026-10-11-superagent-v01.md).
License: MIT.
