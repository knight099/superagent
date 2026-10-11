# Conventional backend versus Superagent: cost comparison

Checked 2026-10-11. The numbers below are transparent **assumptions**, not a
measured cloud deployment, provider invoice, or claim of guaranteed savings.
The runtime tests prove safety behavior; they cannot prove economic benefits.

## What you still pay for

| Cost | Conventional deterministic backend | Superagent |
| --- | --- | --- |
| PostgreSQL and storage | Required | Required; same app/data |
| API/runtime hosting | Required | Required; capacity can differ |
| Authentication gateway, monitoring, backups, security reviews | Required | Required |
| AI inference for CRUD | None assumed | One call per new intent in v0.1 |
| Controllers/services/repos/endpoints | You implement or generate them | Generic runtime covers supported plans |
| App schema, permissions and business rules | Required | Required; supported rules are declarative |
| Unsupported domain logic | Custom code | Still needs custom code outside this runtime |

The conventional baseline accepts deterministic CRUD requests, rather than
natural-language intents. A custom backend offering the same AI assistant
experience may also pay similar inference costs; compare equivalent capabilities
when choosing an architecture.

AI coding tools, frameworks and generated CRUD APIs can lower the conventional
backend's development effort too. Comparing Superagent with a handwritten
backend while ignoring those alternatives would exaggerate its benefit.

## Sourced rates

- [OpenAI GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini):
  $0.40 per million input tokens, $1.60 per million output tokens, $0.10 per
  million cached input tokens. Use uncached rates below; v0.1 does not control
  or guarantee provider prompt-cache hits.
- [DigitalOcean Droplets](https://www.digitalocean.com/pricing/droplets): a listed
  Basic 1 GiB/1 vCPU plan costs $6/month. This is a budget assumption for both
  services, not a measured sizing recommendation.
- [DigitalOcean managed databases](https://www.digitalocean.com/pricing/managed-databases):
  PostgreSQL Standard's listed starting 1 GiB/1 vCPU plan is $15.15/month.
  [Database pricing details](https://docs.digitalocean.com/products/databases/postgresql/details/pricing/)
  describe additional storage and availability costs. Use your actual total
  database bill in the calculator. Both designs retain this shared cost.

The smaller database plan is a development/testing baseline, not a production
HA deployment. The comparison excludes extra storage, HA, compute scaling,
network overages, backups not included in your plan, authentication, monitoring,
taxes, support, and engineering salaries. Add applicable costs equally unless
you have measured a difference. Rates can change.

## Model-call arithmetic

Let `N` be monthly new requests, `f` the fraction needing planning, `r` the average
model calls per planned request, and `I`/`O` the average billed input/output tokens.

```text
AI per request = f × r × (I × input_rate + O × output_rate) / 1,000,000
Conventional monthly = conventional_compute + database + common_operating_costs
Superagent monthly   = runtime_compute + database + common_operating_costs + N × AI per request
```

v0.1 makes one planner call per new intent, without automatic model retries or
semantic caching. Failed plans and model-based dry-runs can still incur inference
cost. A committed identical-key replay avoids planning; a supplied CLI plan
avoids the model. Distinct keys with equivalent intents do not get a template
cache. The calculator's `f` is a scenario assumption, not an implemented router.

**Baseline assumption:** 4,000 input + 500 output tokens, `f=1`, `r=1`. Input
includes intent, schema, policy context, system instructions and output schema.
This token count is not measured from a live provider. A larger database/policy
context can substantially increase it. No batch, free-tier or cache discounts.

```text
(4,000 × $0.40 + 500 × $1.60) / 1,000,000 = $0.0024
10,000 × $0.0024 = $24.00/month
```

| Requests/month | Shared assumed infrastructure | AI cost | Conventional total | Superagent total |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | $21.15 | $2.40 | $21.15 | $23.55 |
| 10,000 | $21.15 | $24.00 | $21.15 | $45.15 |
| 100,000 | $21.15 | $240.00 | $21.15 | $261.15 |
| 1,000,000 | $21.15 | $2,400.00 | $21.15 | $2,421.15 |

The fixed hosting number makes the inference difference easy to compare. It
does **not** assert that either backend can handle one million requests on that
server. Long model calls hold request/database resources; measure concurrency,
connection usage and throughput before choosing hosting capacity.

### Token-size sensitivity at 10,000 planned requests/month

| Assumed input / output tokens | AI per request | Monthly AI |
| --- | ---: | ---: |
| 2,000 / 300 | $0.00128 | $12.80 |
| 4,000 / 500 | $0.00240 | $24.00 |
| 12,000 / 1,000 | $0.00640 | $64.00 |
| 32,000 / 2,000 | $0.01600 | $160.00 |

Doubling model calls doubles inference cost. Schema snapshots do not make input
tokens free: the planner still sends allowed metadata for each new request.
A self-hosted compatible model changes the cost into inference compute, GPU/CPU
capacity, energy and maintenance; it is not automatically free or cheaper.

## Developer time and break-even

This is the primary hypothesis: supported workflows may require fewer backend
functions and therefore less development/maintenance time. That saving is **not
measured yet**. The sample's zero application-backend functions and 65 config
lines demonstrate a capability, not a time/cost benchmark across applications.

Assume, solely as an example, a $50/hour internal value for developer time:

| Monthly hours saved | Hypothetical value | Break-even planned requests at $0.0024/request |
| ---: | ---: | ---: |
| 1 | $50 | about 20,833 |
| 4 | $200 | about 83,333 |
| 10 | $500 | about 208,333 |

These assume equal infrastructure, equal non-inference operations cost, and that
the saved hours actually exist. Break-even is `(hours_saved × hourly_value) /
AI_per_request`; subtract any additional runtime hosting/operations overhead
first. At 10,000 requests, $24 of AI cost would be offset by 0.48 hours/month at
$50/hour. At 100,000 requests, it would need 4.8 hours/month. One-time development
savings should be amortized over your chosen lifetime, not counted every month.

## Reproduce or change the assumptions

From the repository (the standalone calculator uses only Python's standard library):

```sh
python scripts/cost_compare.py --requests 10000
python scripts/cost_compare.py --requests 100000 --input-tokens 12000 --output-tokens 1000
python scripts/cost_compare.py --requests 10000 --input-rate 0.40 --output-rate 1.60 \
  --compute 12 --database 30.45 --planner-fraction 1 --calls-per-request 1
```

It emits all assumptions and calculated totals. Set `--database` to zero only
when intentionally comparing incremental costs over a database you already pay
for; it does not eliminate the existing database bill.

For actual model usage, inspect `planner_usage.prompt_tokens` and
`planner_usage.completion_tokens` in durable audit records from your own provider.
Rates and which tokens are discounted depend on that provider. Some providers
omit usage, and errors/refusals may still be billed without a recorded parsed
plan. Provider usage/billing exports are the authoritative total, not a sum of
only successful Superagent audits. Measure malformed plans, rejects, latency,
connection concurrency, configuration effort and time spent reviewing policies.

**Decision:** choose Superagent for flexible, authorized natural-language data
workflows where you expect reduced backend effort to outweigh inference and
review costs. A conventional deterministic backend is often the better fit for
high-volume repetitive endpoints, complex domain logic or strict latency budgets.

## v0.2 reusable tool scenario

v0.2 adds direct approved-tool execution with no model call; natural-language
intent requests still plan. Use the fraction of requests that actually reach
planning, not a hoped-for semantic cache hit rate:

```sh
python scripts/cost_compare.py --requests 100000 --planner-fraction .05 --build-cost 5
```

This yields $12 monthly inference, $5 **assumed** generation/evaluation expense,
and $38.15 total under the earlier $21.15 infrastructure assumption. A 95% direct
tool fraction must come from the actual client workload. Tool drafting, schema
proposals, failed provider output and evaluations can add cost. The daily model
call cap limits calls, not dollar invoices. [v0.2 evidence](reusable-tools-verification.md)
shows 1,000 explicit tool calls with zero provider calls; it does not establish
that 95% of arbitrary natural-language requests route without planning, or that
running infrastructure is cheaper than a conventional backend.
