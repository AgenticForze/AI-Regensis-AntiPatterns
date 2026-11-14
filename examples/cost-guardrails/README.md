# Cost guardrails for LLM-powered products

A runnable reference implementation for the anti-pattern **"Retrying failed LLM calls with full context and no budget"**
(the $4K → $40K bill). It puts every model call behind one gateway and adds checks in CI.

```bash
pip install pytest
pytest -q -s                                    # replays the incident
python cost_gate.py sample/baseline.jsonl sample/candidate_retry_bug.jsonl   # CI gate fails
```

Replay output (500 requests, 30k-token context, provider incident where every call times out but is billed):

| Scenario | Cost |
|---|---|
| Healthy day | $47 |
| Incident, naive feature (10 retries, full context) | $497 |
| Incident, behind the gateway | $1.56 |

## What is implemented

| Layer | Guardrail | Where |
|---|---|---|
| Request path | One gateway for every call; untagged calls rejected | `Gateway.call`, `CallContext.validate` |
| Request path | Retries only for retryable errors (timeouts, 429, 5xx); never for context-too-long, safety blocks or bad requests | `ProviderError.retryable` |
| Request path | Max 3 attempts with exponential backoff | `Gateway(max_attempts=3)` |
| Request path | Retry traffic capped at 10% of requests over a sliding window | `RetryBudget` |
| Request path | Circuit breaker: stop calling an unhealthy provider instead of paying for retries | `CircuitBreaker` |
| Request path | Each retry is cheaper: trimmed history, then the small model | `default_degrade` |
| Budgets | Per request, per user action, max calls per user action, per conversation | `Budgets.reserve` |
| Budgets | Per tenant and per feature monthly budgets; alerts at 50 / 80 / 100%; hard stop for non-critical features | `Budgets.settle`, `Limits` |
| Visibility | Every call (including failed, billed ones) metered with feature, team, tenant, conversation, user action and prompt version | `Ledger` |
| Visibility | Spike alerts on tokens per call and calls per user action | `SpikeDetector` |
| Visibility | Cost per successful outcome | `cost_per_successful_outcome` |
| Release | CI gate on cost per successful task (+15% needs approval) and max calls per case | `cost_gate.py` |

## Taking it to production

| Piece here | Production equivalent |
|---|---|
| `Gateway` | An AI gateway every service must use (LiteLLM proxy, Portkey, Azure API Management AI gateway, Kong, or an internal service). Block direct egress to provider APIs at the network layer so nothing bypasses it. |
| `Budgets` (in memory) | Redis `INCRBYFLOAT` counters with TTLs per window, or the gateway's native budgets and virtual keys per team or tenant. Use reserve-then-settle so concurrent requests can't overspend. |
| `RetryBudget`, `CircuitBreaker` | Gateway retry and fallback settings, or a resilience library. Turn off SDK-level retries (`max_retries=0`) so retries happen in exactly one place. |
| `Ledger` | OpenTelemetry spans with GenAI attributes (`gen_ai.usage.input_tokens`, etc.) plus cost and tags, exported to your warehouse. Reconcile monthly against the provider invoice. |
| `SpikeDetector`, alerts | Prometheus or Datadog alerts on `tokens_per_request`, `calls_per_user_action`, `retry_rate` and spend per hour per feature; page the feature owner. |
| `cost_gate.py` | A required CI check on pull requests that change prompts, models, tools or retry logic. Approval comes from a label applied by the budget owner. |
| Rollout | Feature flag plus canary; auto-rollback when spend per hour for the feature exceeds its forecast. |

`.github/workflows/cost-guardrails.yml` runs the tests and the gate on every pull request.
