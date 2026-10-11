# v0.2 implementation decisions

These decisions resolve the approved plan's open implementation details and
record the limits of this release.

| Decision | Reason and effect |
| --- | --- |
| Expand the approved tool milestone with agent drafts, schema proposals, guards, evals and telemetry | Implements the latest user request; automatic schema migrations remain future work. |
| Work and integrate directly on main | Existing user authorization explicitly requests main commits and pushes; full verification and independent review cover integration. |
| Resolve and bind immutable tools inside the execution transaction | Prevents context/plan mismatches and holds the revocation lock through commit; adds fresh introspection overhead. |
| Correct logical expression serialization | Full configuration dumps were not reloadable; policy fingerprints changed before v0.2 artifacts were released. |
| Implement guardrails and evaluation before the final benchmark | Stabilizes the publication contract before measuring release examples. |
| Evaluate the executor in forced-rollback transactions on disposable databases | Avoids production execution flags and retry/audit side effects; pending deferred constraints are forced before successful certification. Sequences and external trigger effects are not reversible. |
| Treat evaluation reports as owner-controlled evidence | Reports are unsigned; trusted CLI/database operators can forge evidence. There is no public publication or migration API. |
| Default to a per-app daily model-call cap of 100 | Covers intents, tool drafts and schema proposals; it is not a guaranteed dollar cap. |
| Hash default/generated column definitions | Detects otherwise invisible default changes without storing or exposing raw default expressions. |
| Benchmark a developer-supplied explicit plan through the same executor | Isolates tool overhead; does not establish full conventional backend capacity or a cost advantage. |
| Stream bounded, uncompressed provider responses | Fixes the review's ineffective post-buffer size check. Compression is rejected; elapsed deadlines are checked between chunks alongside HTTPX inactivity timeouts, rather than promising hard cancellation of blocking network I/O. |

Independent review identified two Important findings: unbounded provider buffering
and deferred constraints missed by rollback evaluations. Both were reproduced
with failing regression tests, fixed, and covered by full-suite verification.
No Critical findings or other concrete defects were reported. Live model quality,
deployed gateway authentication, production capacity and economic advantage
cannot be established from scripted local evidence.
