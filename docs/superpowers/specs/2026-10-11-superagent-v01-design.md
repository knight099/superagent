# Superagent v0.1 design

Status: proposed for review. Source: https://github.com/knight099/superagent/issues/1.

## Purpose and success criteria

Turn user intent into safe, validated PostgreSQL state transitions without
application-specific controllers, services, repositories, or tool functions.
The planner proposes operations; deterministic code owns authorization,
validation, SQL generation, transaction boundaries, and limits.

The repository is empty. Use Python 3.12+, Pydantic 2 for strict data contracts,
Psycopg 3 for PostgreSQL, YAML configuration, and pytest. Add FastAPI and an
OpenAI-compatible HTTP planner adapter only after the execution core works.
PostgreSQL is the sole database. No UI, multi-agent system, arbitrary SQL, code
execution, financial workflows, or distributed orchestration.

The first deliverable is the issue's recommended dry-run vertical slice. Full
v0.1 additionally demonstrates all seven required example intents and retries,
with PostgreSQL integration tests proving safety and atomicity.

## Approach and alternatives

Recommended: a small typed plan, explicit generic policy AST, and direct Psycopg
SQL composition. This keeps the security boundary readable and auditable.
An ORM would add mapping and session behavior without replacing the need for
schema introspection or authorization. PostgreSQL functions/RLS alone can add a
hard boundary, but do not provide the required portable plan/explain contract.
Use constraints and optional RLS as additional defenses.

## Components and flow

`Identity + intent -> Planner -> TransitionPlan -> Validator -> Compiler ->
Transaction executor -> Audit/result`

- `config`: strict configuration, allowlisted objects, limits, policies, invariants.
- `db/schema`: introspected immutable metadata, separate from connection secrets.
- `planner/models`: versioned plan and result contracts, no database access.
- `planner/provider`: an async provider interface with a fixture provider for tests.
- `policy`: generic row/identity expressions and deny-by-default decisions.
- `invariants`: generic before/after assertions checked inside the transaction.
- `db/compiler`: validated operations to quoted SQL identifiers and bound values.
- `runtime`: coordinates planning, validation, dry-run, and execution.
- `audit`: structured request decisions, effects, errors, and timing.
- `api`, `cli`: thin adapters around the same runtime.

The initial dry-run runtime accepts supplied plan JSON. Natural-language planning
arrives later behind the same interface; the security core requires no LLM.

## Plan contract

Version 1 contains ordered operations with unique IDs and discriminated kinds
`select`, `insert`, `update`, and `delete`. Reject unknown properties, coercive
types, excessive nesting, unbounded strings/lists, and unsupported operators.

Each operation names an allowlisted schema/table and explicit columns. Predicates
support conjunction of `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in`, and `is_null`.
No SQL fragments, joins, wildcard columns, arbitrary expressions, or subqueries.
Reads have an enforced limit. Updates/deletes require a predicate and a row bound.
Database constraints remain authoritative for supported data types.

References explicitly identify an earlier operation, one returned column, and
require exactly one result row. Reject forward references, cycles, missing
columns, and ambiguous cardinality. Only allowlisted selected/returning columns
can be referenced. The compiler resolves references during execution; dry-run
shows symbolic bindings without running referenced reads.

Later bounded calculations support a closed AST for numeric addition and
date-plus-days with literal operands and earlier scalar references. No general
programming language or implicit calculation syntax.

## Metadata and deterministic validation

Introspect configured schemas through PostgreSQL catalogs: table/column names,
types, nullability, defaults, generated/identity properties, primary keys,
foreign keys, unique constraints, and check-constraint descriptions. Only expose
configured tables/columns to the planner. Never expose credentials or database
row contents to the model by default.

Validation checks the plan shape, all referenced objects, operation grants,
writable columns, required insert fields, generated columns, predicates,
reference compatibility, and configured limits before compilation. Reserve a
separate `superagent_internal` schema for audit/idempotency; ordinary plans
cannot access it even if accidentally listed in configuration.

Compiled SQL uses Psycopg identifier composition and bound parameters for every
value. Only compiler-owned operator tokens enter SQL syntax. Dry-run returns
the proposed plan, static decision, parameterized statements, symbolic bindings,
and limits. It executes no plan statements. It cannot promise success for row
authorization, invariants, or constraints that require actual database state;
these checks are explicitly reported as pending execution.

## Policies and invariants

Use a typed expression AST rather than natural-language rules or named Python
callbacks. Operands are literals, identity claims, and allowlisted row fields.
Expressions support comparisons, `all`, `any`, and `not`. Explicit grants are
required for every operation. Missing grants/claims fail closed.

For reads, updates, and deletes, compile applicable row policies into predicates.
For inserts, evaluate the create policy against proposed values plus database
defaults in the transaction. Update policies can constrain both before and after
rows, preventing changes to ownership that evade authorization.

Invariants use the same bounded AST over `before` and `after` rows. This expresses
assignee presence, due-date ordering, and forbidden completed-to-open changes.
Cross-table/arbitrary aggregate invariants are outside the initial subset;
document database constraints as the appropriate additional boundary.

## Transactions, bounds, retries, and audit

Execute one accepted plan in one transaction with a local statement timeout.
Lock targeted mutation rows and inspect at most the configured bound plus one;
abort rather than silently truncate if too many rows match. Validate before/after
rows and postconditions before commit. Any failure rolls back every operation.
Concurrent conflicting workflows may fail with a retryable database error;
never automatically regenerate or retry an uncertain mutation.

Mutation requests require an idempotency key scoped to stable identity and app.
Atomically claim the key in an internal table with a unique constraint. Store a
request fingerprint and final response in the same transaction as mutations.
An identical retry returns the saved response without planning/execution; a
different request with the same key fails. Concurrent duplicates serialize on
the unique key. Dry-runs do not claim execution keys.

Committed audit records are persisted with mutations; rejection/rollback events
are persisted separately after rollback. If required audit persistence fails,
execution fails closed. Record identity, original intent, proposal, decisions,
executed operations, affected-row counts, permitted before/after fields,
result/error, timestamps, and correlation IDs. Redact configured sensitive
fields. v0.1 promises rollback, not universal undo.

## Interfaces and example

CLI: `superagent init`, `superagent explain --plan plan.json`, and later
`superagent run`. Resolve database/model credentials from named environment
variables; never serialize secret values into configuration or model context.

API: `POST /v1/execute` accepts intent and dry-run flag, with trusted identity
headers and an idempotency header for mutations. Dev identity is explicit;
trusted headers require deployment behind an authenticating gateway. Requests
cannot supply policies or change identity through plan content.

Responses distinguish `explained`, `committed`, and `rejected`, with audit ID,
validation errors, operation results, and safe change summaries. Reject malformed
LLM output without executing it. Planner context contains only allowed metadata,
supported plan syntax, identity claims permitted for model use, and the intent.

Ship project-management SQL, YAML policies/invariants, fixture plans, and later
natural-language examples. Human-readable name lookups must return exactly one
user before mutation. The example contains no application-specific backend code.

## Independently testable milestones

1. **Dry-run vertical slice:** package, schema metadata/introspection, strict
   plans, static allowlist validator, parameterized compiler, explain interface,
   project-management schema, unit tests, and real PostgreSQL introspection tests.
   Acceptance: hostile values stay parameters; invalid/disallowed plans fail;
   explain runs no plan SQL and states deferred checks clearly.
2. **Bounded execution:** ordered references, transaction commit/rollback, read
   and affected-row limits, statement timeout, and bounded calculations.
   Acceptance: a later failure reverses earlier mutations; ambiguous references
   and oversized mutation sets leave all rows unchanged.
3. **Authorization and invariants:** identity context, generic AST, row filters,
   before/after checks. Acceptance: unauthorized access and ownership escalation
   fail; completed tasks cannot reopen; invalid due dates roll back.
4. **Idempotency and durable audit:** internal schema migrations and request
   claims. Acceptance: sequential/concurrent retries execute once; changed
   payloads conflict; rejections and committed effects have durable records.
5. **Planner, API, CLI, demos:** provider abstraction, one model adapter, bootstrap,
   trusted-header API, README and all seven required demos. Acceptance: a new
   developer follows the README against PostgreSQL and runs the demos without
   writing application-specific functions.

Use TDD for each milestone's core behavior. PostgreSQL integration tests use a
real disposable instance, never SQLite or mocked transaction semantics. Keep
incremental commits on `feat/v01-dry-run`; publish a PR when the first slice is
tested. No experimental changes go directly to main.

## Experiment measurements and risks

Track demo requirements solved with zero new backend functions, policy/invariant
configuration size, setup time, latency and token usage, invalid plans, and
adversarial policy failures. Fixture tests isolate security from model accuracy;
live-model experiments are optional and do not become security assertions.

The narrow plan language will reject some useful workflows; report that rather
than expand into arbitrary SQL. Policy configuration may become complex; count
it honestly against eliminated backend code. Metadata snapshots can become
stale; schema errors must reject/roll back and require refresh. Dry-run is static
explanation, not proof of future transaction success.
