# Superagent v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Ship the PostgreSQL intent runtime described in issue #1, with deterministic safety, seven runnable demos, and a tested main branch.

**Architecture:** Strict plans feed static validation and a parameterized compiler. A transaction executor applies generic policies and invariants, enforces bounds, and persists idempotency and audit records. CLI/API and a replaceable planner share the runtime.

**Tech Stack:** Python 3.12+, Pydantic 2, Psycopg 3, PyYAML, FastAPI, HTTPX, pytest, PostgreSQL 16+.

**Spec:** `docs/superpowers/specs/2026-10-11-superagent-v01-design.md`

## Global Constraints

- PostgreSQL is the sole database; Python 3.12+.
- Deny by default; no application-specific backend functions or arbitrary SQL.
- Bound plan size, reads, mutations, references, calculations, and statement duration.
- Dry-run executes no plan SQL and identifies deferred state checks.
- Every accepted mutation plan commits atomically or rolls back completely.
- Internal audit/idempotency tables are inaccessible to ordinary plans.
- Preserve commits and merge/push to main after verification, as explicitly requested.

## Review Focus

- Nulls and missing identity/row values must fail closed, including negation.
- A permissive row policy must not bypass a restrictive after-row check.
- Simultaneous identical requests must execute once; conflicting keys must fail.
- Generated/default values must be checked as returned by PostgreSQL.
- Planner errors and audit persistence errors must not leak credentials or commit partial work.

## Task 1: Typed plans and dry-run compilation

**Files:** `pyproject.toml`, `src/superagent/{models,config,schema,validation,compiler}.py`, `tests/test_core.py`, `tests/conftest.py`.

**Interfaces:** `TransitionPlan.model_validate(data)`; `Config.model_validate(data)`; `introspect(conn, config) -> Catalog`; `validate(plan, catalog, config) -> None`; `compile_operation(op, resolved_values=None) -> Statement`.

- [ ] Write core tests for strict shape rejection, unsafe fields, generated columns, missing required columns, unknown objects, limits, references and injection values.
- [ ] Run `pytest tests/test_core.py -q`; expect missing implementation failures.
- [ ] Implement typed metadata, configuration, validation, compiler, and static explain output. SQL identifiers use Psycopg composition; values are bound parameters.
- [ ] Run `pytest -q`; expect all current tests pass. Commit `feat: add strict plans and safe dry-run compilation`.

## Task 2: PostgreSQL transactions and bounds

**Files:** `src/superagent/{executor,expressions}.py`, `tests/test_execution.py`, example `schema.sql` and `compose.yaml`.

**Interfaces:** `Executor.execute(conn, plan, identity) -> list[dict]`; `resolve_value(value, results) -> scalar`; `evaluate(expression, context) -> bool`.

- [ ] Write real PostgreSQL tests for introspection, commit, late failure rollback, result references, ambiguous references, affected-row bounds, read limits, timeout and numeric/date calculations.
- [ ] Run `pytest tests/test_execution.py -q`; expect missing executor failures.
- [ ] Implement transactions, row locks, timeout, bounded operations and references; never retry a mutation automatically.
- [ ] Run `pytest -q`; expect all pass. Commit `feat: execute bounded atomic PostgreSQL plans`.

## Task 3: Generic policies and invariants

**Files:** `src/superagent/{policy,expressions,executor}.py`, `tests/test_policy.py`, `tests/test_execution.py`.

**Interfaces:** typed `Expression` AST; `policy_sql(expr, identity) -> Statement`; `check_invariants(rules, before, after, identity) -> None`.

- [ ] Write allow/deny, absent claim under negation, row access, ownership escalation, defaults, and invariant rollback tests.
- [ ] Run the new tests; expect failures on missing policy behavior.
- [ ] Implement read/mutation row filters and transactional before/after assertions using the shared bounded AST. Reject inaccessible fields at startup.
- [ ] Run `pytest -q`; expect all pass. Commit `feat: enforce declarative row policies and invariants`.

## Task 4: Runtime, idempotency and audit

**Files:** `src/superagent/{runtime,audit}.py`, `tests/test_runtime.py`.

**Interfaces:** `Runtime.execute(intent, identity, key, dry_run=False, plan=None) -> dict`; `Runtime.explain(plan, identity) -> dict`; `initialize_internal(conn) -> None`.

- [ ] Write PostgreSQL tests proving sequential and concurrent retries execute once, key conflicts reject, committed/failed audit records persist, dry-run never mutates or claims a key, and rejected adversarial plans cannot execute.
- [ ] Run new tests; expect missing runtime failures.
- [ ] Implement durable request claims, request fingerprints, saved responses, rollback audit, redaction, correlation IDs and structured errors. Planner must run only after replay lookup.
- [ ] Run `pytest -q`; expect all pass. Commit `feat: persist audit and idempotent execution`.

## Task 5: Planner, API, CLI and usable example

**Files:** `src/superagent/{planner,api,cli}.py`, `tests/test_interfaces.py`, `examples/project_management/{config.yaml,demo.py,plans.json}`, `README.md`, `.github/workflows/tests.yml`, `LICENSE`.

**Interfaces:** `Planner.plan(intent, catalog, config, identity) -> TransitionPlan`; `create_app(runtime) -> FastAPI`; console entry `superagent = superagent.cli:main`.

- [ ] Write tests for malformed provider output, minimized context, provider HTTP failures, trusted-header identity, payload restrictions, configuration parsing and CLI bootstrap/explain.
- [ ] Run new tests; expect missing adapter failures.
- [ ] Implement an OpenAI-compatible provider with strict output parsing, HTTP timeout, no database tools and no arbitrary endpoints supplied by clients. Add bootstrap/run/explain CLI and intent API.
- [ ] Implement seven demos using fixture plans and a live-model option; record workflow/configuration/latency metrics. Document supported DSL, limits, deployment trust and deferred checks.
- [ ] Run `pytest -q`, `ruff check .`, `superagent --help`, build the wheel, and run all seven demos against PostgreSQL; expect successful checks and expected rejection demos.
- [ ] Commit `feat: ship v0.1 intent API CLI and project management demos`.

## Final verification and integration

- [ ] Obtain whole-branch independent review; fix security/correctness findings with reproducing tests.
- [ ] Run full unit/integration suite, lint, package build and demos after fixes.
- [ ] Fetch origin and inspect divergence before integrating. Never force-push.
- [ ] Merge tested changes into main and push, then verify the remote main SHA. Tag v0.1.0 only if release checks pass.
