# Reusable backend tools v0.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Run approved application-specific data tools for multiple users without
making a model call on each request, while preserving v0.1 authorization and
transaction safety.

**Architecture:** Introduce immutable typed plan templates and an app-scoped
registry ahead of the existing Runtime. Bind arguments and verified identity,
then execute a strict TransitionPlan through current validation/Executor.
Keep build orchestration out of this first release; publish tools explicitly.

**Tech Stack:** Python 3.12+, PostgreSQL 16+, Pydantic, Psycopg, FastAPI, uv,
pytest. Keep the existing dependency set; PostgreSQL is registry/ledger storage.

**Spec:** [Adaptive backend design](../specs/2026-10-11-adaptive-backend-design.md).

**Status:** Implemented and under final release review, including app-wide schemas, guardrails,
evals and agent observability requested by the owner. v0.3–v0.5 still require
separate task plans at their milestones.

## Global constraints

- Python 3.12+, PostgreSQL 16+, one explicitly registered app per process in v0.2.
- Use current developer-owned policies, allowlists, statement/row/plan limits.
- Never allow callers to bind authenticated identity or change SQL structure.
- No arbitrary generated Python/SQL execution, external API effects, result
  cache, fuzzy mutation routing, Redis, or persistent model workers in v0.2.
- Every new tool invocation checks current permissions and database state.
- Mutations require the existing scoped idempotency key.
- Immutable artifacts; manual publish; explicit version/revision compatibility.
- Default current intent endpoint remains compatible; new tool endpoint is additive.
- Follow a failing test -> minimum implementation -> passing test -> commit
  cycle per task. Retain the complete PostgreSQL regression suite.

## Review focus

- Another user calls a reused tool: ownership is injected afresh and unauthorized
  rows are inaccessible (Tasks 2 and 4).
- Schema/policy changes after publish: affected tools fail closed before a stale
  template executes, including with cached metadata (Tasks 1, 3 and 4).
- Injection/ambiguous inputs: unknown fields, identity overrides and malformed
  references are rejected without modifying the database (Tasks 2 and 4).
- Concurrent retry/revocation: one commit for an identical retry; revocation
  prevents new executions and cannot be lost during version publishing (Tasks 3 and 4).
- Provider error/rollback: inference costs survive failed business transactions;
  missing usage is marked unknown rather than recorded as zero (Task 5).

## File and interface map

| File | Responsibility |
| --- | --- |
| `src/superagent/revisions.py` | Canonical allowed-schema and execution-policy fingerprints |
| `src/superagent/tools/models.py` | Immutable manifest, slot and input contracts |
| `src/superagent/tools/binding.py` | Typed argument/identity binding into strict plans |
| `src/superagent/tools/registry.py` | Transactional artifact publish/load/revoke |
| `src/superagent/tools/service.py` | App/version checks and tool execution coordination |
| `src/superagent/usage.py` | Independent model-attempt and cost ledger |
| `src/superagent/doctor.py` | Read-only setup and tool compatibility checks |
| Existing `runtime.py`, `api.py`, `cli.py`, `audit.py` | Integrations without duplicating the executor |
| `tests/test_tools_*.py`, `tests/test_usage.py`, `tests/test_doctor.py` | New contracts and PostgreSQL integration |

Create `tools/__init__.py` with Task 2. Exact manifest/binder representations
below are the contract; subsequent generated wrappers consume them unchanged.

### Task 1: Schema and policy revisions

**Files:** Create `src/superagent/revisions.py`; test
`tests/test_tools_revisions.py`; modify `src/superagent/setup.py` to include
revision identifiers in snapshots without removing existing metadata.

**Interfaces:** `schema_revision(catalog: Catalog, config: Config) -> str` and
`policy_revision(config: Config) -> str`. Return SHA-256 of canonical sorted JSON.
Schema hash covers allowed columns/types/default/generated/nullability, keys
and visible constraints. Policy hash covers tables, permissions, after rules,
invariants, sensitive fields, auth semantics and execution limits; excludes
credentials, app display name, timestamps and planner settings.

- [x] Write `test_revisions_stable_under_order_and_timestamp_changes` and
  `test_revisions_change_on_column_permission_or_limit_changes`, asserting
  equality for reordered maps and inequality for each behavioral change.
- [x] Run `uv run pytest tests/test_tools_revisions.py -q`; confirm failure.
- [x] Implement both revision functions and snapshot fields. Changes to hidden
  columns must not disclose hidden metadata in the hash input or snapshot.
- [x] Run the new tests and existing setup tests against disposable PostgreSQL;
  all pass, existing snapshot fields remain valid.
- [x] Commit `feat: version allowed schema and execution policies`.

### Task 2: Typed tool manifests and binding

**Files:** Create `src/superagent/tools/models.py`, `binding.py`, `__init__.py`;
test `tests/test_tools_binding.py`.

**Interfaces:** `ToolManifest` has `format_version=1`, `app`, `tool_id`,
integer `version >= 1`, `description`, `schema_revision`, `policy_revision`,
`runtime_contract=1`, `output_contract='runtime_result_v1'`, input declarations
and a parameterized plan. v0.2 uses the existing runtime result envelope;
generated per-tool response models are a v0.3 deliverable. Input names
use existing `Name`; JSON scalar input types are `string`, `integer`, `number`,
`boolean`, with required/default and optional max-length/range constraints.
Reject undeclared arguments and implicit coercions. Add dedicated `ArgumentSlot`
and `IdentitySlot` types; only `IdentitySlot(field='user_id')` is allowed initially.

`bind(manifest: ToolManifest, arguments: dict, identity: dict) -> TransitionPlan`
replaces slots only in literal value positions of predicates, insert/update
values and calculation operands, including supported list values. It does not
replace table/column/kind/policy/reference fields. Validate the final strict plan;
do not add these template-only slots to the current untrusted planner contract.

- [x] Write `test_same_tool_binds_distinct_caller_identity` with callers 1 and 2;
  resulting creator values differ. Write `test_identity_override_and_extra_input_rejected`,
  `test_structure_slots_rejected`, `test_typed_input_bounds`, and
  `test_missing_input_is_not_silently_invented`.
- [x] Run `uv run pytest tests/test_tools_binding.py -q`; confirm failure.
- [x] Implement immutable contracts and binder. Inputs contain no stored real-user
  examples or implicit business assumptions. Slot declarations distinguish
  constants from parameters explicitly.
- [x] Run binding tests plus strict model/core regressions; all pass.
- [x] Commit `feat: bind typed arguments to reusable backend tools`.

### Task 3: Versioned registry and controlled publication

**Files:** Create `src/superagent/tools/registry.py`; modify
`src/superagent/audit.py` internal initialization; test `tests/test_tools_registry.py`.

**Interfaces:** `ToolRegistry(database_url)` implements
`publish(manifest: ToolManifest) -> str` (artifact digest),
`get(app: str, tool_id: str, version: int) -> ToolManifest`, and
`revoke(app: str, tool_id: str, version: int, reason: str) -> None`.
Store immutable manifests/digests and active/revoked status in internal PostgreSQL
tables. The same app/ID/version with different content conflicts; exact repeat
publication is idempotent. Publishing never broadens application policy.

- [x] Write `test_registry_scopes_versions_to_application`,
  `test_artifact_overwrite_conflicts`, `test_repeat_publish_is_idempotent`, and
  `test_revocation_survives_concurrent_publish`. Use real PostgreSQL transactions.
- [x] Run `uv run pytest tests/test_tools_registry.py -q`; confirm failure.
- [x] Implement transactional publish/get/revoke and an additive idempotent
  internal-schema upgrade. Enforce app/version keys and digests in storage.
- [x] Run registry tests; upgrading a v0.1 database preserves existing audit and
  request rows. An unauthorized app lookup returns no artifact.
- [x] Commit `feat: store immutable application tool versions`.

### Task 4: Direct execution endpoint, API contract and audit

**Files:** Create `src/superagent/tools/service.py`; modify `api.py`, `runtime.py`;
test `tests/test_tools_execution.py` and `tests/test_tools_api.py`.

**Interfaces:** `ToolService(runtime: Runtime, registry: ToolRegistry)` provides
`execute(tool_id: str, version: int, arguments: dict, identity: dict,
key: str | None, *, dry_run: bool = False) -> dict`.
Add `POST /v1/tools/{tool_id}/execute` accepting `{version, arguments, dry_run}`;
reuse verified identity/header semantics and idempotency header from v0.1.
Application comes from configured runtime, never an unverified body parameter.

Define `ToolExecutionContext` in `tools/models.py` with `app`, `tool_id`,
`version`, `digest`, `schema_revision`, and `policy_revision`. Add an optional
server-only `tool_context: ToolExecutionContext | None` keyword to
`Runtime.execute`; include it in fingerprints and audits. Registry adds
`load_for_execution(conn, app: str, tool_id: str, version: int) -> ToolManifest`,
which reads active state under a shared row lock on the caller's transaction.
Runtime verifies this manifest matches the execution context before any
application operation; the lock remains held through commit/rollback.

Pin artifact/version and compatibility before binding. Load current registry
state for each invocation. Coordinate a version-state read lock through the
execution transaction with revocation's write lock: revocation blocks new
executions after it commits, while already-started executions may finish.
Check catalog compatibility inside execution; policy/config changes require
coordinated reload/restart. Exclude uncontrolled concurrent DDL from supported
operation; schema-changing deployments drain requests before changing revisions.

For v0.2 perform fresh allowed-schema introspection and revision comparison
inside the execution transaction. Measure its overhead in Task 7 before adding
a coordinated invalidation optimization; a stale local cache is insufficient.

Include tool ID/version/digest in request fingerprints and durable audit via a
server-only execution context; clients cannot forge this context. Fix usage
attachment so supplied plans never inherit a previous planner's usage. Unknown,
revoked, incompatible or malformed tools return explicit rejection, with no
planning fallback unless the caller submits a separate new intent request.

- [x] Write `test_known_tool_makes_zero_provider_calls` using a spy planner;
  `test_two_users_share_definition_not_permissions`; `test_revoked_or_drifted_tool_fails_closed`;
  `test_tool_version_is_in_retry_fingerprint`; and
  `test_concurrent_tool_retry_commits_once`. Assert actual rows and audits.
- [x] Run `uv run pytest tests/test_tools_execution.py tests/test_tools_api.py -q`;
  confirm failure.
- [x] Implement service/API integration through `Runtime.execute(..., plan=...)`;
  preserve strict static validation, runtime authorization and transactional audit.
  Add internal registry locking/context support without exposing arbitrary plans
  at the public tool endpoint.
- [x] Run all new tests and complete PostgreSQL suite. Existing intent endpoint,
  dry-run, denied access, rollback and retry behavior remain covered.
- [x] Commit `feat: execute approved tools without inference`.

### Task 5: Usage ledger and measured costs

**Files:** Create `src/superagent/usage.py`; modify `planner.py`, `runtime.py`,
`audit.py`, `scripts/cost_compare.py`; test `tests/test_usage.py`.

**Interfaces:** `UsageLedger.begin(app: str, purpose: str, provider: str,
model: str) -> str` returns attempt ID. `finish(attempt_id: str, status: str,
usage: dict | None, rates: dict | None) -> None` persists outcome independently
of the business transaction. Status includes `succeeded`, `failed`, `unknown`;
configured rates are timestamped assumptions, not provider invoices.
`report(app: str, start: str, end: str) -> dict` returns counts, known usage,
estimated spend and unknown-usage attempts. Direct calls record zero planner
attempts. Per-request correlation must not expose raw secret-bearing intents.

- [x] Write `test_billable_attempt_survives_execution_rollback`,
  `test_invalid_provider_response_records_attempt`,
  `test_missing_usage_is_unknown`, and `test_supplied_tool_has_no_planner_usage`.
- [x] Run `uv run pytest tests/test_usage.py -q`; confirm failure.
- [x] Implement independent recording with stale `started` attempts reported as
  unknown after interruption. Do not equate parsing failure with zero billing.
  Ledger outages fail new planning closed; already approved no-model tools do
  not depend on provider accounting, but their transaction audit stays mandatory.
- [x] Run usage tests; reconcile a scripted provider's declared usage with the
  report. Extend cost calculations with hit fraction and explicit build costs.
- [x] Commit `feat: measure inference attempts and reusable tool costs`.

### Task 6: Publish/import/export CLI and local diagnostics

**Files:** Create `src/superagent/doctor.py`; modify `cli.py`, `README.md`;
test `tests/test_doctor.py` and `tests/test_tools_cli.py`.

**Interfaces:** Add `superagent tools publish --file manifest.json`,
`tools list`, `tools revoke --id NAME --version N --reason TEXT`, and
`tools export --id NAME --version N --output PATH`. Scope all commands to the
configured app; explicit publication is the v0.2 manual promotion action.
`doctor(config: Config, database_url: str) -> dict` reports connectivity,
internal tables, schema/tool compatibility and credential presence without
printing secrets or performing paid inference. CLI exit code 1 for blockers.

- [x] Write `test_doctor_redacts_credentials`, `test_doctor_detects_schema_drift`,
  `test_export_import_preserves_digest` and `test_cli_publish_requires_compatible_app`.
- [x] Run `uv run pytest tests/test_doctor.py tests/test_tools_cli.py -q`; confirm failure.
- [x] Implement diagnostics and lifecycle commands; document current executable
  uv setup and the new tool path. Clearly label Docker packaging and generated
  application wrappers as later milestones.
- [x] Run installed-wheel CLI smoke tests on Linux and native uv smoke checks
  on macOS/Windows in CI. Test manifest export without user rows/credentials.
- [x] Commit `feat: manage backend tools and diagnose local setup`.

### Task 7: Repeat-workflow benchmark and release evidence

**Files:** Create `scripts/benchmark_tools.py`,
`examples/project_management/tools/create_task.json`,
`examples/project_management/tools/list_owned_tasks.json`, and
`docs/reusable-tools-verification.md`; extend CI.

**Interfaces:** Benchmark output is JSON with workload definition, app/schema
revisions, request counts, direct/planned counts, usage, build costs if any,
errors, correctness checks and p50/p95 latency. Tool-only and scripted-provider
measurements must be distinguished from opt-in paid live-provider measurements.

- [x] Add acceptance assertions for 1,000 known-tool requests, zero provider
  calls, two-user ownership isolation, unchanged data after rejected operations,
  and retries without duplicate effects.
- [x] Run acceptance tests before implementing fixtures; confirm missing tools
  or benchmark contract cause failure.
- [x] Add explicit typed fixtures and benchmark a deterministic endpoint baseline,
  v0.1 planner path, and tool path using identical database/hardware/data. Keep
  live measurement opt-in with an explicit spend limit; do not call a paid model
  1,000 times by default.
- [x] Run full PostgreSQL suite, lint, wheel build, installed CLI and acceptance
  workload. Record actual model usage when available; do not manufacture a
  95% routing result or a conventional-backend cost advantage.
- [x] Commit release evidence; stop at v0.2. Use results to write the v0.3
  generated-backend/build-worker task plan.

## Later release planning boundaries

### Task 8: Guarded agent drafts, application schema proposals and evals

Create `src/superagent/agents.py`, `evaluations.py`, `observability.py` and
`tests/test_agents.py`, `test_evaluations.py`, `test_observability.py`.
Agent drafts use the actual provider adapter with a strict ToolManifest output
schema, configured request timeout/output bounds and independently recorded
usage. Drafting receives only allowed application metadata, contracts and
rules. It produces a reviewable file; it cannot publish, execute code, perform
DDL or alter policies. Add an app-wide schema-change proposal contract with a
base schema revision and structured change descriptions, never executable SQL.

Write failing tests for application scoping, identity override rejection,
untrusted SQL/code/policy fields, output bounds, invalid provider output and
recorded usage. Add deterministic evaluation cases invoking candidate tools
against a disposable database, checking declared statuses/row results, denied
access and rollback; case state is rolled back and no production eval flag
exists. Production publication remains explicit and records a compatible eval
report/artifact hash; stale/mismatched reports reject. Read-only app-scoped
observability reports aggregate audit outcomes, latency, tool versions, planner
attempts and unknown costs. Reports/logs exclude credentials, raw intents and
private row values. No public unauthenticated admin/metrics endpoints.

Run agent, eval and observability tests plus the full PostgreSQL suite, then
commit the guarded proposal/evaluation flow and operator CLI documentation.

v0.3 defines generated Python/Pydantic/FastAPI package contracts and isolated
build/test/promotion jobs. v0.4 defines supervisor authentication, app-scoped
capabilities, job DAGs, leases/recovery, two-job fan-out and budgets. v0.5 defines
custom-code sandbox capabilities and external-effect/outbox semantics. Detailed
implementation decisions for these systems follow v0.2 measurements; none is
silently included in this plan's execution.

Recommended execution for v0.2: implement tasks sequentially in one session,
with one independent security/concurrency review before release. The tasks share
the binder/registry/runtime contracts, and repeated agent context duplication
would work against the project's cost goal. Runtime build-worker fan-out in
later releases is separate from how this development plan is executed.
