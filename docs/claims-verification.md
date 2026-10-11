# What Superagent actually verifies

2026-10-11. This report separates tested runtime behavior from product hypotheses
and model-dependent behavior. Commands use a disposable PostgreSQL 16 instance.

## Claim-by-claim evidence

| Claim | Evidence | Boundary |
| --- | --- | --- |
| Connect an existing PostgreSQL database | `tests/test_setup.py` discovers the real users/projects/members/tasks schema into a valid config | Ordinary tables in an explicitly selected schema; current identifiers/type subset applies |
| Fetch and store schema | Init writes a snapshot; explicit schema refresh and run startup use the same atomic writer | Configured/allowed metadata only; no row data, connection URL or API key. Snapshot never authorizes requests |
| Avoid per-operation backend functions | Seven project-management scenarios are declarative plans over a generic runtime | Example evidence; unsupported workflows still require other backend code |
| Bring your own compatible AI API | `tests/test_claims.py` calls the actual provider adapter and validates/parses a scripted response before real PostgreSQL execution | Validates HTTP contract, not a live model's interpretation quality |
| Agent can resolve names and perform operations | Intent → provider request with allowed schema → lookup Rahul → insert with result reference → committed row | Provider response scripted to isolate runtime correctness; live generation remains unmeasured |
| Deterministic authorization | Hostile provider proposal targeting Alice's task rejected; original row unchanged | Trusted gateway supplies verified user ID; no JWT/OIDC in v0.1 |
| Atomic writes | Later constraint/invariant failure rolls back earlier mutations | Database triggers/components are trusted; no distributed effects |
| Safe retries | Sequential/concurrent committed retries execute once and return the saved response | Same key/request/identity; failed transactions may be retried |
| Durable audit | Before/after effects stored without needing returning fields; required audit failure rolls back | Retention/access are deployment responsibilities; original intent retained |
| Dry-run doesn't execute application operations | Real database rows unchanged, execution key unclaimed | Intent/API dry-run still writes an audit; state checks deferred |
| Metadata/value privacy | Hidden foreign relationships excluded; named sensitive values redacted from plans/results/audit | Intent may itself contain secrets; developer must configure sensitive fields |
| UUID ownership and numeric reference calculations | New reproducing PostgreSQL/policy regressions pass | UUID comparisons normalize UUID operands; exact string identity scoping is preserved |
| Bounds and parameterization | Unknown objects/raw SQL plans reject; limits/timeouts and bound injection values tested | Simple supported plan language, not arbitrary SQL access |
| Lower development effort or total cost | Cost analysis exposes assumptions; example has zero app backend functions | No measured engineering-time saving, universal 80% coverage result or production cloud benchmark |

## Commands and results

```sh
uv sync --extra test
TEST_DATABASE_URL=postgresql://postgres:superagent_test@127.0.0.1:55432/superagent_test uv run pytest -q
uv run ruff check .
```

The expanded suite passes **80 tests** against real PostgreSQL, including the
existing 64 safety tests, setup/cost tests, provider-adapter integration and
regressions for UUID/decimal behavior. No PostgreSQL test is silently substituted
with SQLite or a transaction mock. TestClient currently emits one upstream
Starlette/httpx deprecation warning; it does not fail the tests.

The simplified isolated `uv tool install --python 3.12 .` installation was tested
against this checkout. Its installed CLI exposes `init --from-db` and `schema`.
The documentation also provides a pip/venv alternative; the distribution is
installed from GitHub source, not a claimed PyPI release. `uv.lock` records the
project dependency resolution used by `uv run`/`uv sync`; direct tool/pip installs
resolve the package's declared dependency ranges independently.

The seven example demos passed on fresh seeded data, with a nonempty overdue
result and a retry matching the original response. The isolated installed CLI
also passed database discovery, denied initial permissions, schema refresh,
server startup/health, and a real HTTP dry-run through a locally hosted scripted
provider. Wheel and source-distribution builds passed. These checks exercise
packaging and the service path without claiming live-model accuracy.

## Bugs found while checking claims

1. Python after-insert policy evaluation compared a database `UUID` object to a
   string identity directly, unlike PostgreSQL's UUID comparison. Valid ownership
   therefore rejected. UUID/string operands now normalize when one operand is a
   UUID; ordinary opaque text IDs remain unchanged.
2. PostgreSQL `numeric` result references return `Decimal`, but addition only
   accepted Python int/float. Numeric references now support Decimal and convert
   the other numeric operand through its decimal string representation. Existing
   finite/magnitude bounds remain in force.

3. Setup wrote the snapshot before it knew configuration creation would succeed.
   A failed config write could therefore replace an existing snapshot. Setup now
   creates config first, removes a newly created config if snapshot saving fails,
   and rejects config/snapshot paths that identify the same file. Schema refresh
   and server startup also reject aliased paths to protect the YAML config.

The bugs were reproduced before fixing. They are correctness fixes,
not a reason to broaden permissions or bypass deterministic checks.

## Live-provider measurement remains outstanding

No model API credential is configured in this environment, so no paid inference
was performed. Fixture and scripted-provider success cannot establish semantic
accuracy, unsupported-request handling by a real model, provider latency, actual
token counts or dollar invoices. Use your own compatible provider and fresh data
with `uv run python examples/project_management/demo.py --live`; record both
successful and rejected/billed calls and evaluate adversarial requests.

The cost table is arithmetic using sourced rates and explicitly assumed token
sizes. Use provider billing/usage exports for actual spend; successful-plan audit
usage alone misses billed failures. See [cost comparison](cost-comparison.md).
