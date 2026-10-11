# v0.2: application backend tools, agents, guardrails and evaluation

Checked 2026-10-11 against real PostgreSQL 16. v0.2 extends the earlier
[v0.1 claim audit](claims-verification.md); it remains experimental.

## What is implemented

| Capability | Evidence | Boundary |
| --- | --- | --- |
| Shared application schema | One catalog/config/revision per app; two users invoke one tool version | No per-user schema generation; policies still control rows |
| Agent drafts backend tools | Actual OpenAI-compatible adapter proposes a typed ToolManifest, checked against owner contract/revisions | Scripted provider verified; live semantic quality unmeasured; no arbitrary code execution |
| Agent handles schema design proposals | Structured add-table/add-column drafts bound to the application schema revision | No executable SQL, policy changes or automatic migrations; owner applies reviewed DDL |
| Reuse across users | Creator identity injected at invocation; shared definition, separate idempotency scopes | Caller cannot replace identity; backend trusts an authenticating gateway |
| Model-free repeated operations | 1,000 known-tool requests, zero provider calls, 1,000 ownership checks | Explicit tool IDs; new natural-language intents still plan |
| Guarded release | Publish rejects absent/failed/mismatched eval evidence; versions immutable; revoked tools reject even retries | Reports are local owner-controlled evidence, not cryptographic independent attestations |
| Drift handling | Fresh allowed-schema/policy comparisons before tool execution; changed default expressions invalidate tools | Coordinated config reload/DDL required; DB triggers/components remain trusted |
| Independent accounting | Model-attempt rows survive business rollback and malformed output | Missing usage/unpriced calls remain unknown; provider billing authoritative |
| Bounded inference | Transactional per-app daily call reservation, context/output/token bounds, streamed uncompressed response bounds and between-chunk deadline | Call cap is not a guaranteed dollar budget; no automatic repairs/fan-out yet |
| Evaluation isolation | Cases force deferred constraints before rollback on a separate CLI-selected disposable DB | Sequences and external trigger effects cannot be undone; never use real application data |
| Observability | App-scoped outcome/latency/tool aggregates, purpose-specific attempts, structured audit/attempt correlation | Aggregate/log exports omit identity, intent and rows; original intent remains in controlled audit |
| Optional telemetry failure | Broken log sink cannot turn an already committed operation into rejection | Required transactional audit failure still rolls back |
| Input bounds | 64 KiB ASGI body bound before JSON parsing, strict argument/plan contracts | Rejected HTTP validation/body-limit requests do not enter runtime audit |

## Commands and verification

```sh
uv sync --extra test
TEST_DATABASE_URL='postgresql://user:password@host/disposable_test_db' uv run pytest -q
uv run ruff check .
uv build
```

At release verification, **144 tests passed**, including all earlier safety
regressions. Starlette/httpx TestClient emits one upstream deprecation warning.
Both wheel and source distribution built. An isolated wheel installation passed
real CLI and HTTP service smoke checks on two newly created disposable databases:

- Discovery creates denied initial permissions and application metadata snapshot.
- A locally hosted scripted provider drafts a backend tool and an app-wide schema proposal.
- Schema proposal performs no DDL and tool draft performs no application writes/publication.
- Evaluation uses the separate database and leaves its application rows unchanged.
- Publication, doctor, and `run --tools-only` work without a model key at serving time.
- Two users call one tool; identical-key replay does not duplicate their mutations.
- Operator telemetry matches outcomes; revoked tool versions reject new calls.

Only two scripted provider requests occurred, for draft/proposal; direct runtime
tool calls made none. No paid inference or live-provider quality test was run.
Linux/macOS/Windows native install checks and a PostgreSQL benchmark are included
in CI; local smoke evidence alone is not proof of every operating system.

## Local repeat-workflow measurements

[Raw JSON result](benchmarks/2026-10-11-tools-local.json). The example alternates
two user identities on one read workflow, sequentially, using the same database,
policies and audit semantics. Application-layer service calls are timed; HTTP,
concurrent load, real model latency and production capacity are not measured.

| Path | Requests | Provider calls | Errors | Ownership checks | p50 / p95 milliseconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Explicit backend plan baseline | 1,000 | 0 | 0 | 1,000 | 12.146 / 20.011 |
| Approved reusable tool | 1,000 | 0 | 0 | 1,000 | 23.523 / 34.351 |
| Scripted provider intent path | 1,000 | 1,000 | 0 | 1,000 | 37.306 / 61.027 |

The baseline represents developer-supplied deterministic backend behavior through
the same policy/audit executor, not a complete separately deployed backend app.
The tool path adds registry locking, artifact checks and fresh schema introspection.
It avoids inference but is **not faster than the deterministic baseline** here.
The scripted provider has no real network/model latency or bill, so its timing
is not an LLM latency estimate. The benchmark permits exactly its declared number
of scripted calls in a new app namespace; it never changes deployed budgets.

Reproduce on fresh sample data in a disposable database:

```sh
TEST_DATABASE_URL='postgresql://user:password@host/disposable_sample_db' \
  uv run python scripts/benchmark_tools.py --requests 1000
```

The script retains benchmark registry/audit/accounting rows in that disposable
DB and does not drop user data. CI uploads its own result, rather than asserting
that a cloud runner must reproduce these latencies. Mutation/retry correctness
is checked separately by real transactional tests and installed-CLI smoke tests.

## Economics

Use [the cost analysis](cost-comparison.md) and:

```sh
python scripts/cost_compare.py --requests 100000 --planner-fraction .05 --build-cost 5
```

With the sourced earlier rates and assumed 4,000-input/500-output calls, that is
$12 inference + $5 assumed monthly builds + $21.15 shared infrastructure = $38.15,
versus $21.15 conventional infrastructure before engineering costs. The 95%
explicit-tool workload, monthly build spend and engineering savings are
assumptions, not results of this read-only benchmark. General backend automation,
production cost advantage and live model interpretation quality remain unproven.

## Operational boundaries

Owners define authentication integration, permissions, invariants, evaluation
cases and retention. Schema changes describe the app as a whole; agents do not
create a schema per user. Apply migrations separately, refresh config/catalog,
and publish newly evaluated compatible tools. Versioned generated Python packages,
bounded subagent build orchestration and custom domain extensions remain future
releases in the [architecture](superpowers/specs/2026-10-11-adaptive-backend-design.md).

Model/network work still runs within v0.1's transaction on cold intent requests.
Direct tools avoid that wait entirely. Moving inference outside transactions
requires leases/deduplication work; this release does not weaken exactly-once
committed retries to claim lower connection usage. Optional result caching and
semantic routing are not implemented; fresh state and authorization remain
mandatory. Audit aggregates include v0.2 app-tagged records and exclude legacy
untagged records, replays and requests rejected before the runtime.

Implementation choices and review resolutions are recorded in [v0.2 decisions](v02-decisions.md).
