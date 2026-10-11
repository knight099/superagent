# Superagent

### Build PostgreSQL apps without writing repetitive backend CRUD code.

**Bring your database. Bring your AI API. Define your rules. Let the runtime handle the data operations.**

Superagent connects to an existing PostgreSQL database, discovers its schema,
and lets your client submit requests such as “Create a task for Rahul” or
“Reassign John's unfinished tasks.” An AI proposes a structured plan; the runtime
checks permissions and invariants, generates parameterized SQL, and executes
allowed operations in one transaction.

**v0.2 adds application-wide reusable backend tools.** An agent can draft a
typed tool and propose application schema changes. Evaluate the draft on a
disposable database, review it, then publish an immutable version. Frontends or
agents call that tool repeatedly without another model call. All users share
the application's schema and tool definitions; identity and row permissions
are checked afresh on each execution.

You can add supported CRUD workflows without a new controller, service,
repository, endpoint, or tool function for each one. You still own your schema,
access rules, identity provider, hosting, and any business logic outside the
supported plan language. v0.2 is an experimental runtime.

**Database + Policies + Agent = Backend**

[Get started](#get-started-with-your-database) · [Try the example](#try-it-without-an-ai-key) ·
[Cost comparison](#what-does-it-cost) · [What is verified](#does-it-do-what-it-claims)

## Who is this useful for?

| You are building… | How Superagent helps |
| --- | --- |
| A frontend backed by PostgreSQL | Use one intent API for supported data actions instead of writing separate CRUD endpoints. |
| An MVP or small SaaS application | Try new data workflows by changing schema and policies rather than adding backend functions each time. |
| An internal tool or admin assistant | Give authenticated users a way to request bounded, authorized changes in plain language. |
| An application with an existing PostgreSQL database | Discover tables and relationships without migrating your data into a new platform. |
| An agent that must read and update application data | Put deterministic validation, transactions, audit, and retry protection between the model and your database. |

It is most useful when ordinary reads, inserts, updates, deletes, and small
workflows are a large part of your backend work. The example handles seven
scenarios with zero application-specific backend functions and 65 lines of
policy/configuration YAML. That is evidence for the example, not proof that
all applications can eliminate their backend code.

## How it works

```mermaid
flowchart LR
    DB[(Your PostgreSQL)] --> S[Discover and save schema]
    S --> AI[Your AI provider]
    I[User intent] --> AI
    AI --> P[Structured plan]
    P --> V[Permissions and invariants]
    V --> T[Bounded transaction]
    T --> DB
    T --> A[Result and durable audit]
```

1. **Connect:** supply your PostgreSQL URL through an environment variable.
2. **Discover:** `init --from-db` generates a table/column config and saves
   metadata to `.superagent/schema.json`. It reads table definitions, not row data.
3. **Configure:** decide which users may read or change which rows. Discovered
   permissions start denied; the AI never decides your access rules.
4. **Bring an AI API:** supply your key and choose a supported provider/model.
5. **Send intent:** the runtime validates the proposed plan and either commits
   the entire transition or rejects it. Mutation retries use an idempotency key.

`run` refreshes and saves the allowed schema on startup. `superagent schema`
refreshes the snapshot manually. The running process uses fresh in-memory
metadata, not a potentially stale file; restart it after database/schema changes.
Snapshots include allowed columns, types, nullability/default flags, keys, and
permitted constraints/relationships. They contain no database URL, API key, or
row contents and do not grant permissions.

## Get started with your database

Requires PostgreSQL 16+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).
uv supplies an isolated installation and can provision Python 3.12 for you.
Install directly from this repository; no PyPI publication is assumed:

```sh
uv tool install --python 3.12 'git+https://github.com/knight099/superagent.git'
```

Add uv's tool directory to your shell's PATH if prompted. Then connect your
existing database and supply **your own paid or locally hosted compatible AI API**:

```sh
export DATABASE_URL='postgresql://user:password@host:5432/your_database'
export OPENAI_API_KEY='your-api-key'
superagent init --from-db
```

Open `superagent.yaml`. Discovery saves you typing table/column definitions, but
permissions remain your decision. Remove tables/columns you do not want exposed
and enable only the actions you need. For example, on a table with `owner_id`:

```yaml
permissions:
  select:
    op: eq
    left: {source: row, field: owner_id}
    right: {source: identity, field: user_id}
```

Place this under the discovered table entry. Use the [sample configuration](examples/project_management/config.yaml)
for create/update/delete rules and invariants, or read the [policy reference](docs/reference.md#generic-policyinvariant-dsl).
Permission names are the plan operations: `select`, `insert`, `update`, `delete`.

Initialize the internal audit/retry tables once, then start:

```sh
superagent init-db
superagent run
```

Submit a request using a verified identity appropriate to your application:

```sh
curl http://127.0.0.1:8000/v1/execute \
  -H 'Content-Type: application/json' \
  -H 'X-User-ID: 1' \
  -H 'Idempotency-Key: request-001' \
  -d '{"intent":"Find records I own","dry_run":true}'
```

Remove `dry_run` to execute an allowed plan; use a new key for a new mutation.
Dry-run proposes and explains a transition without executing application-data
operations; state-dependent checks are deferred. Intent/API dry-run records an
audit. [Deployment and identity requirements](#deployment-and-current-limits)
apply before exposing the service to users.

<details>
<summary>Prefer pip instead of uv?</summary>

Use Python 3.12+:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install 'git+https://github.com/knight099/superagent.git'
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell and set
credentials using `$env:DATABASE_URL` and `$env:OPENAI_API_KEY`.

</details>

## Bring your own AI provider

The default is `gpt-4.1-mini` through OpenAI's Chat Completions API. The key is
read from `OPENAI_API_KEY`; it is never stored in YAML or the schema snapshot.
You pay your provider directly; Superagent has no software license fee.

For another provider, edit the generated config:

```yaml
planner:
  url: https://your-provider.example/v1/chat/completions
  model: your-model-id
  key_env: YOUR_AI_API_KEY
  timeout_seconds: 30
```

Then set `YOUR_AI_API_KEY` in the environment. v0.2 supports providers that accept
OpenAI-compatible Chat Completions, `response_format: json_schema`, and
`max_completion_tokens`. This does not mean every AI API/model is compatible.
A locally hosted compatible provider can avoid per-token API billing, but you
still pay for its compute and operations.

The model receives allowed schema metadata, rules, user ID, and intent. It does
not receive a database connection or rows by default. Every returned plan goes
through strict parsing and deterministic validation. Live model quality and
latency depend on your chosen provider; bring your key to evaluate them.

## Let the agent build reusable backend tools

Tool definitions belong to **one application**, not one user. Schemas describe
the whole application backend. A tool such as `create_task` binds authenticated
ownership on each invocation and can be reused by other authorized users.
v0.2 creates declarative tool artifacts; generated Python service packages and
subagent build fan-out are later milestones.

Start with the project-management sample below, or supply your own input contract
and evaluation cases. To draft a tool using your AI API:

```sh
superagent tools draft --id create_task --version 1 \
  --intent 'Create an owned task after resolving an assignee by name' \
  --inputs examples/project_management/tools/create_task.inputs.json \
  --output create_task.draft.json
```

Review the file. The agent cannot publish it, modify permissions, execute SQL,
or change the database schema. Prepare a **separate disposable evaluation
database** with the same application schema and test fixtures. For the sample:

```sh
docker compose exec -T postgres createdb -U superagent superagent_eval
docker compose exec -T postgres psql -U superagent -d superagent_eval \
  < examples/project_management/schema.sql
export EVAL_DATABASE_URL='postgresql://superagent:superagent_dev@localhost:5432/superagent_eval'
```

The repository includes revision-bound sample tools to try without an AI key.
Evaluate and explicitly publish one:

```sh
superagent tools evaluate \
  --file examples/project_management/tools/create_task.json \
  --cases examples/project_management/tools/create_task.cases.json \
  --output create_task.eval.json
superagent tools publish \
  --file examples/project_management/tools/create_task.json \
  --evaluation create_task.eval.json
superagent run --tools-only
```

To evaluate an agent-generated draft, substitute `create_task.draft.json` in both
commands and review/update the cases for its declared result projections.
Eval cases must assert successful behavior and an authorization guard. They run
in rollback transactions; use disposable data because sequences can advance
and trusted triggers can have effects outside a transaction. The CLI refuses
the configured application database. Reports are owner-reviewed evidence,
not signed independent attestations.

Call the published backend tool directly:

```sh
curl http://127.0.0.1:8000/v1/tools/create_task/execute \
  -H 'Content-Type: application/json' \
  -H 'X-User-ID: 1' \
  -H 'Idempotency-Key: create-task-001' \
  -d '{"version":1,"arguments":{"title":"Ship the MVP","project_id":1,"assignee_name":"Rahul","due_date":"2099-01-01"}}'
```

This makes **zero AI calls**. New natural-language requests to `/v1/execute`
still use the planner; v0.2 does not automatically route similar wording to a
cached tool. Clients and other agents can call the known tool endpoint.
List/export/revoke versions using `superagent tools --help`. Changed schema
or policies require a compatible newly evaluated tool version.

For application-wide schema evolution and operator visibility:

```sh
superagent schema-propose --intent 'Add optional notes to application tasks' \
  --output schema-proposal.json
superagent doctor
superagent observe --start 2026-10-01 --end 2026-11-01
```

Schema proposals are structured, revision-bound suggestions. v0.2 never applies
DDL automatically or creates a schema for each user. The owner reviews and
implements migrations, updates allowlists/rules, and evaluates affected tools.
Observability includes app-scoped outcomes, p50/p95 runtime duration, tool
versions, agent attempt counts by purpose, token usage and unknown costs.
Structured `superagent.events` logs correlate execution audit IDs and planning
attempt IDs. Logs and aggregate reports exclude identities, raw intents and
row values; durable audit has the retention/privacy requirements below.

Default guardrails include a **100-call/day per-app model budget**, bounded
provider context/response bytes, a 64 KiB HTTP body limit, denied initial
permissions, immutable tool versions, explicit evaluation/publication and
revocation. Configure `planner.max_calls_per_day`, `max_prompt_bytes`,
`max_response_bytes` and `max_completion_tokens` as the owner. The call cap is
not a guaranteed dollar cap. Exhausting it leaves approved no-model tools
available. Tool definitions are reused; private results and authorization
decisions are not cached. Production identity/gateway requirements still apply.

See [v0.2 verification and benchmark boundaries](docs/reusable-tools-verification.md).

## Try it without an AI key

The example includes scripted plans, so you can test the runtime before paying
for an API. Docker Compose is needed only to start the sample database:

```sh
git clone https://github.com/knight099/superagent.git
cd superagent
docker compose up -d --wait
export DATABASE_URL='postgresql://superagent:superagent_dev@localhost:5432/superagent'
uv run --python 3.12 superagent init
uv run superagent init-db
uv run python examples/project_management/demo.py
```

This verifies task creation by Rahul's name, atomic reassignment, overdue reads,
a bounded update, unauthorized-change rejection, invariant rollback, and a
retry that does not duplicate a mutation. Each accepted application operation
is a declarative plan. No task controller/service functions are added.

To use a real model, set your API key and run
`uv run python examples/project_management/demo.py --live` **against fresh sample
data**. A fixture demo changes who owns tasks, so a second run may have no rows
to reassign. Reset only disposable example data when needed. Model-generated
mistakes can be rejected, and fixture success is not an LLM accuracy benchmark.

## Does it do what it claims?

The automated suite exercises real PostgreSQL, not SQLite or mocked transactions.
It verifies introspection, schema snapshots, strict types, row policies,
invariants, parameterization, commit/rollback, limits/timeouts, before/after
audit, concurrent retries, dry-run, hidden metadata, and API identity handling.
It also runs an intent through the actual provider adapter into PostgreSQL using
a scripted provider response, and proves a hostile proposal cannot bypass rules.

[CI](https://github.com/knight099/superagent/actions) runs these tests on PostgreSQL 16.
See the [claim-by-claim verification record](docs/claims-verification.md).
The seven fixture demos are reproducible. Live-provider semantic accuracy,
production throughput, and universal “no backend development” claims remain
unproven. Unsupported requests reject; they do not cause the AI to invent new
backend code or unrestricted SQL.

## What does it cost?

Superagent's MIT-licensed software is free. **Database, runtime hosting, and AI
usage still cost money.** A conventional deterministic backend can have lower
running costs because it has no model call for ordinary CRUD.

Illustrative monthly costs, using one 4,000-input/500-output-token model call per
new intent, no prompt-caching discount, and the same assumed hosting/database:

| Planned requests/month | Conventional backend | Superagent AI cost | Superagent total |
| ---: | ---: | ---: | ---: |
| 1,000 | $21.15 | $2.40 | $23.55 |
| 10,000 | $21.15 | $24.00 | $45.15 |
| 100,000 | $21.15 | $240.00 | $261.15 |

Pricing checked **2026-10-11**: assumed compute is a
[$6/month DigitalOcean Droplet](https://www.digitalocean.com/pricing/droplets),
shared database cost is the listed
[$15.15/month starting PostgreSQL plan](https://www.digitalocean.com/pricing/managed-databases),
and [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
costs $0.40/million input tokens and $1.60/million output tokens. This yields
**$0.0024 per planned request**. These are arithmetic scenarios, not measured
model token counts, a hosting recommendation, or demonstrated capacity at these
traffic levels. Extra storage, HA, scaling, backups, auth, monitoring, taxes and
other common costs are excluded from both sides.

The potential saving is developer time on supported workflows. For an explicitly
hypothetical example, saving one maintenance hour/month valued at $50 could
outweigh $24 of extra AI cost at 10,000 requests; we have not measured that saving.
At higher volume, deterministic endpoints/templates are often cheaper.
Identical committed retries, supplied CLI plans and direct approved-tool calls
skip the model. v0.2 has no semantic plan cache for different-but-equivalent
new natural-language requests.

At 100,000 requests, if 95% are explicit tool calls and 5% need the assumed
planner call, inference falls from $240 to **$12/month**, plus generation/eval
costs. This is a workload assumption, not a measured routing rate. With $5 of
assumed builds and the same $21.15 infrastructure, total is $38.15. Equal
infrastructure plus positive model/build costs still exceeds the conventional
backend's infrastructure bill; measure development savings separately.

Read the [full cost analysis and editable calculator](docs/cost-comparison.md),
including token-size sensitivity, development effort, and break-even assumptions.

## Deployment and current limits

- **Identity:** `X-User-ID` is trusted, not authenticated by Superagent. Use a
  gateway that verifies users and replaces client-supplied identity headers.
  Default binding is loopback; `auth.mode: dev` is only for local experiments.
  Set `auth.user_id_type` to `integer` (canonical decimal IDs) or `string`
  (exact opaque IDs).
- **Database:** configure a limited runtime role with necessary application DML
  and internal-table access. `init-db` needs schema creation privileges. Do not
  run the service as database owner/superuser. Constraints/RLS can add defenses;
  v0.2 does not provision RLS or JWT/OIDC automatically.
- **Scope:** PostgreSQL only; explicit scalar columns and small sequential
  workflows. No joins, subqueries, aggregate/cross-table invariants, loops,
  arbitrary SQL, shell execution, payments, or distributed workflows. This is a
  poor fit for complex domain services or strict latency requirements.
- **Bounds:** defaults are 20 operations, 100 total mutated rows, 100 rows/read,
  a 2-second statement timeout, and a 64 KiB plan. Excessive mutation sets abort
  instead of being silently truncated.
- **Audit:** required audit failure rolls back changes. Named sensitive fields
  can be redacted, but original free-text intent is retained. Manage audit
  access/retention. v0.2 provides rollback and replay protection, not universal undo.

## Development

```sh
uv sync --extra test
export TEST_DATABASE_URL='postgresql://user:password@localhost:5432/disposable_test_db'
uv run pytest -q
uv run ruff check .
```

Integration tests reset schemas in `TEST_DATABASE_URL`; use a dedicated disposable
database. Without it, those tests explicitly skip. Full technical detail is in
the [runtime reference](docs/reference.md), [design](docs/superpowers/specs/2026-10-11-superagent-v01-design.md),
and [implementation plan](docs/superpowers/plans/2026-10-11-superagent-v01.md).

[MIT license](LICENSE).
