# Founder console and application onboarding

Status: proposed design for review; not implemented. Baseline: v0.2 at
`f639d99`. This refines the earlier adaptive-backend roadmap around the founder's
requested experience. The completed v0.2 execution and safety contracts remain.

## Product goal

A founder describes an application, connects a database and AI provider, configures
identity and integrations, and connects a frontend. The runtime builds the supported
backend capabilities and reuses tested tools across the application's users.
The founder manages that runtime through an admin console rather than writing
backend implementations or manually invoking publication commands.

Application schemas, tables, columns and tools are shared application definitions.
Users have separate identities and authorized data access, not separate generated
schemas. A database connection alone cannot establish business rules or user access:
the console collects an application brief, roles and access rules during onboarding.

## Scope and order

This is an architectural change with several dependent subsystems. Deliver them in
focused increments, each with an implementation plan and acceptance evidence:

1. Founder console foundation: administrator authentication, application settings,
   encrypted credential storage, integration health checks, agent controls, and an
   asynchronous bridge to existing v0.2 draft/evaluate/publish/revoke/report services.
2. Application onboarding: empty-database setup, shared schema design, governed
   migrations, application authentication, browser-safe API and frontend SDK.
3. Automatic reuse: workflow capture, deduplicated builds, evaluations, controlled
   activation and stable frontend action routing; bounded subagent orchestration.
4. Integration execution: reviewed payment/email/external-service capabilities,
   verified webhooks, durable effects and retry handling. Configuration screens alone
   do not establish support for executing an integration.

Introduce database adapter interfaces during onboarding, preserve PostgreSQL, then
add SQLite and MySQL/MariaDB with real conformance tests. Document stores need a
separate document-oriented contract. A dropdown must show only implemented adapters.
Do not postpone the founder journey behind generated standalone backend packages;
package export, multi-app supervision and arbitrary domain extensions follow it.

## Deployment choices

Recommended: ship a local/self-hosted console with the runtime, served from the same
origin. Founders retain their database, credentials and AI billing relationships.
A React/TypeScript UI can be developed separately and bundled as static assets in the
Python distribution; installing/running the package must not require Node.js.

A separately hosted control service could manage fleets later, but requires a secure
remote management protocol and a separate operator trust/billing boundary. A CLI-only
implementation is smaller but does not fulfill the requested founder experience.

Start with one registered application per runtime. Keep application IDs and scopes
in records from the beginning without claiming multi-app isolation is implemented.

## Founder experience

1. Initialize an administrator account locally, then open the console. Bootstrap
   cannot be claimed by an unauthenticated remote visitor. Initial setup works before
   an application database, AI key or table configuration exists.
2. Create an application brief; select a supported database and verify connectivity.
   Discover existing tables or enter the empty-database schema-design flow.
3. Configure the AI endpoint/model/key, verified application identity provider,
   allowed frontend origins, roles, rules and call/build limits.
4. Add integrations: authentication provider settings, Stripe test/live credentials,
   email SMTP settings, and approved adapter-specific settings. Show configured,
   verified, unsupported and disconnected states distinctly.
5. Receive the runtime URL, public application identifier and frontend connection
   example. Secrets never appear in this connection snippet.
6. Request a change such as "Add a create-task tool that only project members can use."
   Click Create tool. A job generates a typed candidate, tests it in a disposable
   database, and activates it only within the founder's approval rules.
7. Inspect failures, evaluation results, tool versions, usage and costs. Change rules,
   disable new agent work, revoke a tool, or disconnect an integration.

A button starts a job, not an immediate successful deployment. The console shows
queued/running/testing/awaiting approval/active/failed/cancelled states with safe
errors and a correlation ID. It does not replay a user mutation after building a tool.

## Console sections

| Section | Responsibilities |
| --- | --- |
| Setup | Application brief, database, AI, identity, frontend connection and readiness |
| Agent | Workflow requests, queued/running builds, pause/resume and budget settings |
| Schema | Shared catalog, proposed changes, migration impact and history |
| Tools | Candidates, contracts, evaluation results, versions, activation and revocation |
| Users and rules | Provider identities, app roles/access rules and scoped restrictions |
| Integrations | Credential references, test/live modes, health, rotation and disconnection |
| Activity and costs | Agent attempts, outcomes, latency, unknown usage, estimated costs and admin audit |

Pause new agent work preserves approved deterministic tools unless the founder
explicitly disables application execution. Cancellation stops work cooperatively
and prevents later activation using job state checks; it does not undo a committed
operation or a sent payment/email.

## Authentication and control boundaries

Administrator login is distinct from ordinary application-user login. A verified
application token or caller-supplied role never grants console access. Start with a
single founder account and prepare explicit owner/operator/viewer permissions for
later team administration.

Initialize the owner through a local command, hash passwords with Argon2id and use
server-side revocable sessions. Rate-limit login; reject default credentials. Use
HttpOnly, SameSite cookies, Secure cookies over HTTPS, origin checks and CSRF
protection for state-changing browser requests. Bind to loopback by default; remote
access requires HTTPS through a supported deployment configuration.

Serve UI assets and admin APIs from the same origin under `/admin` and
`/admin/api/v1`; every admin API checks administrator identity and application scope.
Ordinary frontend runtime APIs verify identity tokens, issuer, audience and expiry.
The existing trusted-header mode remains for configured authenticating gateways;
a browser-supplied X-User-ID is not an authentication mechanism.

The agent cannot alter its own permissions, administrator identity, budget or secret
access. Founder changes are independently validated, audited and revisioned.
Rules are enforced on the backend regardless of what the console hides or disables.

## Credential storage

The founder enters provider credentials in the console. Store secrets server-side
with authenticated encryption and an independent deployment master key supplied
outside the application/control database and its backups. Use environment/secret
manager references where supported. Never bundle keys in the frontend, generated
code, Git, exports, agent prompts, error messages or logs.

Use a dedicated local SQLite control store for settings, encrypted credentials,
administrator sessions, job state and admin audit. This permits onboarding before
an application database exists and avoids imposing PostgreSQL on every connection.
This control store is separate from application tables and v0.2 runtime records.
SQLite concurrency and durability limits must be documented and tested; a hosted
multi-instance supervisor requires a separate storage implementation.

Secrets are write-only through the API: responses contain an opaque reference,
provider, scope and update metadata. Only allowlisted server-side adapters resolve
references for specific actions. Agents see integration availability and public
capability contracts, never raw keys. Rotation uses versioned secret references;
deleting one prevents new use but cannot retract an already sent external request.
Audit credential changes without values, recover safely from failed rotations, and
provide documented backup/restore and master-key recovery requirements.

Authentication settings mean provider configuration and signing/verification
material, not storing users' external-provider passwords. Payment settings mean
provider credentials and webhook secrets, not collecting card details; use the
provider's hosted checkout/tokenization flow.

## Jobs, tool creation and release

A durable coordinator invokes existing v0.2 services through narrow interfaces:
create a typed tool draft, evaluate it, publish its immutable version, revoke it,
and read operational reports. The console must not duplicate executor policy logic.
Use secret references to inject AI credentials; production database credentials
must not become model context.

Start with one build worker per application. Deduplicate jobs by application,
normalized owner-declared contract, schema revision and policy revision. Claim jobs
with leases and fencing; verify current state/revisions before activation. Durable
state records attempts and outcomes so restart cannot double-publish or exceed an
accepted budget reservation. No unbounded repair loop: initial attempt plus at
most one configured repair. Reuse the existing per-app inference ledger.

Tool requests require a declared input/output intent and meaningful positive and
negative cases. The console helps create and inspect them; model-generated tests
are not independent proof of correctness. Publication still requires exact matching
passing evidence and current revisions. Missing disposable evaluation infrastructure
blocks activation with an actionable message, rather than running tests on production.

First-release promotion is explicit through an Activate button. Later a founder may
preauthorize tested classes of tools for automatic activation. Agents cannot widen
that rule. Reject stale evaluation reports and incompatible fallback versions.

## Schema controls and integrations

The agent proposes application-wide structured changes. The first console shows
proposals only because v0.2 has no migration executor. The onboarding increment adds
versioned, adapter-compiled migrations with locks, dry runs, compatibility checks and
history. Automatic initial creation/additive changes require an explicit founder
policy; destructive/data-rewriting changes and permission expansion require review.
Database-specific atomicity must be surfaced; do not promise portable transactional DDL.

Integration configuration and execution have separate permissions. Ship server-side
connectivity/credential checks for explicitly supported providers; an unsupported
adapter cannot be marked operational merely because a key was saved. Restrict
outbound destinations and prevent connectivity tests becoming SSRF endpoints.

Payment/email tools require capability allowlists, verified webhook signatures,
provider event deduplication, idempotency keys, retry limits and a durable outbox.
External effects cannot be rolled back with a database transaction. Use sandbox/test
accounts for evaluation; never charge real customers or email them as an eval side effect.
Disconnected credentials invalidate affected capabilities before new requests.

## Acceptance evidence

- A new install opens setup before any application database is configured.
- An unauthenticated visitor and ordinary application user cannot read or alter
  admin state; cross-application paths and role claims are rejected.
- CSRF, session revocation, login bounds and scoped administrator checks are tested.
- Saved secrets survive restart encrypted; API responses, prompts, generated artifacts,
  exports, logs and error paths never contain fixture secrets; rotation is verified.
- A founder creates, evaluates, activates and revokes one shared tool through the UI;
  two users invoke it with current authorization and separate retry scopes.
- Failed/malicious candidates, stale evidence and missing disposable evaluation
  infrastructure cannot activate. Duplicate jobs and crash recovery do not publish twice.
- Pause/budget exhaustion stops new agent work while approved tools remain usable.
- A real frontend can use verified authentication, allowed origins and stable actions.
- The onboarding increment demonstrates an empty database becoming a shared schema
  and working backend; destructive migrations remain gated.
- Provider configuration uses test credentials and bounded health checks; operational
  adapters separately prove webhook/retry/external-effect behavior.
- Measure build costs separately from repeat requests; retain zero model calls for
  approved tool execution and disclose overhead versus an equivalent backend.

## Explicit current limitations

No admin UI, secret vault, admin session system, automatic workflow builder, migration
executor, browser SDK, payment/email adapter or non-PostgreSQL runtime is implemented
by writing this design. v0.2 remains available and unchanged. Each increment must
prove its claimed behavior before README or console readiness labels advertise it.
