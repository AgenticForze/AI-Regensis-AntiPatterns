"""Cost guardrails for LLM-powered products.

One gateway that every model call goes through. It enforces, in order:

  1. Attribution      every call must carry feature / team / tenant / conversation / user-action tags
  2. Circuit breaker  fail fast while the provider is unhealthy (no paid retries into an outage)
  3. Budgets          per request, per user action, per conversation, per tenant and per feature
  4. Retry policy     few attempts, only for retryable errors, capped retry traffic, cheaper each attempt
  5. Metering         actual cost recorded with every tag, for showback and unit economics
  6. Anomaly alerts   spikes in tokens per request or calls per user action

The provider, clock, sleep and alert sink are injected so the module runs anywhere
(tests use a fake provider). In production you back Budgets/Ledger with Redis or a
database and export metrics with OpenTelemetry or Prometheus; see README.md.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Protocol

# --------------------------------------------------------------------------- pricing


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens. Keep this table versioned and reconcile with the invoice monthly."""
    input: float
    output: float
    cached_input: float


PRICES: dict[str, Price] = {          # illustrative numbers, replace with your contract prices
    "large": Price(input=3.00, output=15.00, cached_input=0.30),
    "small": Price(input=0.25, output=1.25, cached_input=0.03),
}


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int = 0
    cached_input_tokens: int = 0


def cost_usd(model: str, u: Usage) -> float:
    p = PRICES[model]
    return (u.input_tokens * p.input + u.output_tokens * p.output + u.cached_input_tokens * p.cached_input) / 1e6


def estimate_tokens(messages: list[dict]) -> int:
    """Cheap pre-flight estimate (~4 chars per token). Replace with the provider's token counter."""
    return sum(math.ceil(len(m["content"]) / 4) for m in messages)


# --------------------------------------------------------------------------- errors


class GuardrailError(Exception):
    """Raised by the gateway itself; never retried."""


class MissingAttribution(GuardrailError):
    pass


class BudgetExceeded(GuardrailError):
    def __init__(self, scope: str, key: str, spent: float, limit: float):
        super().__init__(f"{scope} budget exceeded for {key}: {spent:.4f} / {limit:.4f} USD")
        self.scope, self.key, self.spent, self.limit = scope, key, spent, limit


class CircuitOpen(GuardrailError):
    pass


class ProviderError(Exception):
    """Base for provider failures. `usage` is set when the failed call was still billed (e.g. timeouts)."""
    retryable = False

    def __init__(self, msg: str = "", usage: Usage | None = None):
        super().__init__(msg)
        self.usage = usage


class RateLimited(ProviderError):
    retryable = True


class ServerError(ProviderError):
    retryable = True


class Timeout(ProviderError):
    retryable = True


class ContextTooLong(ProviderError):      # sending it again changes nothing
    retryable = False


class ContentBlocked(ProviderError):      # safety filter: retrying is waste (and can look like abuse)
    retryable = False


class InvalidRequest(ProviderError):
    retryable = False


# --------------------------------------------------------------------------- context


@dataclass
class CallContext:
    feature: str
    team: str
    tenant: str
    conversation_id: str
    user_action_id: str                 # one user click / message; all calls it triggers share this id
    prompt_version: str
    critical: bool = False              # critical features alert at 100% instead of hard-stopping

    def validate(self) -> None:
        missing = [k for k in ("feature", "team", "tenant", "conversation_id", "user_action_id", "prompt_version")
                   if not getattr(self, k)]
        if missing:
            raise MissingAttribution(f"untagged LLM call, missing: {missing}")


@dataclass
class Request:
    model: str
    messages: list[dict]
    max_output_tokens: int


@dataclass
class Response:
    text: str
    model: str
    usage: Usage


class Provider(Protocol):
    def complete(self, req: Request) -> Response: ...


# --------------------------------------------------------------------------- budgets


@dataclass
class Limits:
    per_request_usd: float = 0.50
    per_user_action_usd: float = 1.00
    max_calls_per_user_action: int = 6          # the direct guard against "retry 10 times"
    per_conversation_usd: float = 2.00
    per_tenant_month_usd: dict[str, float] = field(default_factory=dict)
    per_feature_month_usd: dict[str, float] = field(default_factory=dict)
    alert_thresholds: tuple[float, ...] = (0.5, 0.8, 1.0)


class Budgets:
    """Reserve-then-commit budgets. In-memory here; use Redis (INCRBYFLOAT + TTL) or a DB in production."""

    def __init__(self, limits: Limits, alert: Callable[[str], None]):
        self.limits, self.alert = limits, alert
        self.spent: dict[tuple[str, str], float] = defaultdict(float)
        self.calls_per_action: dict[str, int] = defaultdict(int)
        self._alerted: set[tuple[str, str, float]] = set()

    def _scopes(self, ctx: CallContext) -> list[tuple[str, str, float | None]]:
        L = self.limits
        return [
            ("user_action", ctx.user_action_id, L.per_user_action_usd),
            ("conversation", ctx.conversation_id, L.per_conversation_usd),
            ("tenant_month", ctx.tenant, L.per_tenant_month_usd.get(ctx.tenant)),
            ("feature_month", ctx.feature, L.per_feature_month_usd.get(ctx.feature)),
        ]

    def reserve(self, ctx: CallContext, estimate_usd: float) -> float:
        if estimate_usd > self.limits.per_request_usd:
            raise BudgetExceeded("request", ctx.user_action_id, estimate_usd, self.limits.per_request_usd)
        if self.calls_per_action[ctx.user_action_id] >= self.limits.max_calls_per_user_action:
            raise BudgetExceeded("calls_per_user_action", ctx.user_action_id,
                                 self.calls_per_action[ctx.user_action_id], self.limits.max_calls_per_user_action)
        for scope, key, limit in self._scopes(ctx):
            if limit is None:
                continue
            projected = self.spent[(scope, key)] + estimate_usd
            if projected > limit:
                hard = scope in ("user_action", "conversation") or not ctx.critical
                if hard:
                    raise BudgetExceeded(scope, key, self.spent[(scope, key)], limit)
                self.alert(f"[critical feature over budget] {scope}={key} {projected:.2f}/{limit:.2f} USD")
        self.calls_per_action[ctx.user_action_id] += 1
        for scope, key, _ in self._scopes(ctx):
            self.spent[(scope, key)] += estimate_usd
        return estimate_usd

    def settle(self, ctx: CallContext, reserved: float, actual: float) -> None:
        """Replace the reservation with the actual billed cost (0 if the call was not billed)."""
        for scope, key, limit in self._scopes(ctx):
            self.spent[(scope, key)] += actual - reserved
            if limit:
                for t in self.limits.alert_thresholds:
                    if self.spent[(scope, key)] >= t * limit and (scope, key, t) not in self._alerted:
                        self._alerted.add((scope, key, t))
                        self.alert(f"{scope}={key} reached {int(t * 100)}% of {limit:.2f} USD")


# --------------------------------------------------------------------------- retry budget and breaker


class RetryBudget:
    """Retries may add at most `ratio` extra traffic over a sliding window (default 10%)."""

    def __init__(self, ratio: float = 0.10, window_s: float = 60.0, min_retries: int = 3,
                 clock: Callable[[], float] = time.monotonic):
        self.ratio, self.window_s, self.min_retries, self.clock = ratio, window_s, min_retries, clock
        self.requests: deque[float] = deque()
        self.retries: deque[float] = deque()

    def _trim(self) -> None:
        cutoff = self.clock() - self.window_s
        for q in (self.requests, self.retries):
            while q and q[0] < cutoff:
                q.popleft()

    def on_request(self) -> None:
        self.requests.append(self.clock())

    def try_acquire(self) -> bool:
        self._trim()
        allowed = max(self.min_retries, int(len(self.requests) * self.ratio))
        if len(self.retries) >= allowed:
            return False
        self.retries.append(self.clock())
        return True


class CircuitBreaker:
    def __init__(self, failure_ratio: float = 0.5, min_calls: int = 20, window_s: float = 30.0,
                 cooldown_s: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self.failure_ratio, self.min_calls, self.window_s, self.cooldown_s, self.clock = \
            failure_ratio, min_calls, window_s, cooldown_s, clock
        self.events: deque[tuple[float, bool]] = deque()
        self.opened_at: float | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if self.clock() - self.opened_at >= self.cooldown_s:   # half-open: let one probe through
            self.opened_at = None
            self.events.clear()
            return True
        return False

    def record(self, ok: bool) -> None:
        now = self.clock()
        self.events.append((now, ok))
        while self.events and self.events[0][0] < now - self.window_s:
            self.events.popleft()
        fails = sum(1 for _, s in self.events if not s)
        if len(self.events) >= self.min_calls and fails / len(self.events) >= self.failure_ratio:
            self.opened_at = now


# --------------------------------------------------------------------------- metering and anomaly detection


@dataclass
class LedgerRow:
    ts: float
    feature: str
    team: str
    tenant: str
    conversation_id: str
    user_action_id: str
    prompt_version: str
    model: str
    attempt: int
    status: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cost_usd: float


class Ledger:
    """Every call, billed or not. Ship rows to your warehouse / OTel; aggregate for showback."""

    def __init__(self):
        self.rows: list[LedgerRow] = []

    def add(self, row: LedgerRow) -> None:
        self.rows.append(row)

    def total(self, **where) -> float:
        return sum(r.cost_usd for r in self.rows if all(getattr(r, k) == v for k, v in where.items()))

    def by(self, key: str) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        for r in self.rows:
            out[getattr(r, key)] += r.cost_usd
        return dict(out)


class SpikeDetector:
    """EWMA baseline per feature; alert when a value exceeds `factor` × baseline after warm-up."""

    def __init__(self, alert: Callable[[str], None], alpha: float = 0.05, factor: float = 3.0, warmup: int = 50):
        self.alert, self.alpha, self.factor, self.warmup = alert, alpha, factor, warmup
        self.baseline: dict[tuple[str, str], float] = {}
        self.count: dict[tuple[str, str], int] = defaultdict(int)

    def observe(self, feature: str, metric: str, value: float) -> None:
        k = (feature, metric)
        self.count[k] += 1
        b = self.baseline.get(k, value)
        if self.count[k] > self.warmup and value > self.factor * b:
            self.alert(f"spike: {feature}.{metric}={value:.1f} vs baseline {b:.1f}")
        self.baseline[k] = (1 - self.alpha) * b + self.alpha * value


# --------------------------------------------------------------------------- gateway


def default_degrade(attempt: int, req: Request) -> Request:
    """Each retry is cheaper: attempt 1 trims history, attempt 2+ also falls back to the small model."""
    if attempt == 0:
        return req
    system, rest = req.messages[:1], req.messages[1:]
    trimmed = system + rest[-4:]                                  # keep system prompt + last turns
    model = req.model if attempt == 1 else "small"
    return Request(model=model, messages=trimmed, max_output_tokens=min(req.max_output_tokens, 800))


class Gateway:
    def __init__(self, provider: Provider, budgets: Budgets, ledger: Ledger, spikes: SpikeDetector,
                 retry_budget: RetryBudget, breaker: CircuitBreaker, max_attempts: int = 3,
                 degrade: Callable[[int, Request], Request] = default_degrade,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.p, self.budgets, self.ledger, self.spikes = provider, budgets, ledger, spikes
        self.retry_budget, self.breaker, self.max_attempts = retry_budget, breaker, max_attempts
        self.degrade, self.sleep, self.clock = degrade, sleep, clock

    def _record(self, ctx: CallContext, req: Request, attempt: int, status: str, usage: Usage | None) -> float:
        u = usage or Usage(0)
        c = cost_usd(req.model, u) if usage else 0.0
        self.ledger.add(LedgerRow(self.clock(), ctx.feature, ctx.team, ctx.tenant, ctx.conversation_id,
                                  ctx.user_action_id, ctx.prompt_version, req.model, attempt, status,
                                  u.input_tokens, u.output_tokens, u.cached_input_tokens, c))
        if usage:
            self.spikes.observe(ctx.feature, "input_tokens_per_call", u.input_tokens)
        return c

    def call(self, ctx: CallContext, req: Request) -> Response:
        ctx.validate()
        self.retry_budget.on_request()
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            if not self.breaker.allow():
                raise CircuitOpen("provider unhealthy; failing fast instead of paying for retries") from last
            r = self.degrade(attempt, req)
            est = cost_usd(r.model, Usage(estimate_tokens(r.messages), r.max_output_tokens))
            reserved = self.budgets.reserve(ctx, est)                       # may raise BudgetExceeded
            try:
                resp = self.p.complete(r)
            except ProviderError as e:
                self.breaker.record(ok=False)
                actual = self._record(ctx, r, attempt, type(e).__name__, e.usage)
                self.budgets.settle(ctx, reserved, actual)
                last = e
                if not e.retryable:
                    raise
                if attempt + 1 >= self.max_attempts or not self.retry_budget.try_acquire():
                    raise
                self.sleep(min(8.0, 0.5 * 2 ** attempt))                    # exponential backoff (add jitter)
                continue
            self.breaker.record(ok=True)
            actual = self._record(ctx, r, attempt, "ok", resp.usage)
            self.budgets.settle(ctx, reserved, actual)
            calls = self.budgets.calls_per_action[ctx.user_action_id]
            self.spikes.observe(ctx.feature, "calls_per_user_action", calls)
            return resp
        raise last  # pragma: no cover


# --------------------------------------------------------------------------- unit economics


def cost_per_successful_outcome(ledger: Ledger, outcomes: dict[str, bool], feature: str) -> float:
    """Total spend for a feature divided by user actions that ended in success."""
    spend = ledger.total(feature=feature)
    wins = sum(1 for ok in outcomes.values() if ok)
    return spend / wins if wins else float("inf")
