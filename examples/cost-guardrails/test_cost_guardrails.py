"""Replays the incident: a feature retries failed calls 10 times with full context during a provider incident."""
import pytest

from cost_guardrails import (
    Budgets, BudgetExceeded, CallContext, CircuitBreaker, CircuitOpen, ContentBlocked, Gateway, Ledger, Limits,
    MissingAttribution, Request, Response, RetryBudget, ServerError, SpikeDetector, Timeout, Usage, cost_usd,
    estimate_tokens,
)

LONG_HISTORY = [{"role": "system", "content": "You are a support assistant." * 20}] + [
    {"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 4000} for i in range(30)
]  # ~30k tokens of context per call


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s


class FlakyProvider:
    """Healthy, or in an incident where every call times out after the input was processed (and billed)."""

    def __init__(self, incident: bool):
        self.incident, self.calls = incident, 0

    def complete(self, req: Request) -> Response:
        self.calls += 1
        n_in = estimate_tokens(req.messages)
        if self.incident:
            raise Timeout("upstream timeout", usage=Usage(input_tokens=n_in))
        return Response("ok", req.model, Usage(input_tokens=n_in, output_tokens=300))


def ctx(i=0, **kw):
    base = dict(feature="smart_reply", team="care-ai", tenant="acme", conversation_id=f"c{i}",
                user_action_id=f"a{i}", prompt_version="smart_reply@7")
    base.update(kw)
    return CallContext(**base)


def make_gateway(provider, limits=None, alerts=None):
    clock = Clock()
    alerts = alerts if alerts is not None else []
    budgets = Budgets(limits or Limits(per_request_usd=1.0, per_user_action_usd=1.0, per_conversation_usd=5.0),
                      alert=alerts.append)
    gw = Gateway(provider, budgets, Ledger(), SpikeDetector(alerts.append), RetryBudget(clock=clock),
                 CircuitBreaker(clock=clock), sleep=clock.sleep, clock=clock)
    return gw, alerts


def naive_feature(provider, n_requests):
    """What shipped: retry up to 10 times, same full context, no budget, no breaker."""
    spent = 0.0
    for _ in range(n_requests):
        for _attempt in range(11):
            try:
                r = provider.complete(Request("large", LONG_HISTORY, 1000))
                spent += cost_usd("large", r.usage)
                break
            except Timeout as e:
                spent += cost_usd("large", e.usage)
    return spent


def guarded_feature(gw, n_requests):
    for i in range(n_requests):
        try:
            gw.call(ctx(i), Request("large", LONG_HISTORY, 1000))
        except (Timeout, CircuitOpen, BudgetExceeded):
            pass                                   # degrade: show a fallback / queue / hand off
    return gw.ledger.total()


def test_incident_cost_is_bounded():
    n = 500
    healthy = naive_feature(FlakyProvider(incident=False), n)
    naive = naive_feature(FlakyProvider(incident=True), n)
    gw, alerts = make_gateway(FlakyProvider(incident=True))
    guarded = guarded_feature(gw, n)
    print(f"\nhealthy ${healthy:.2f} | naive incident ${naive:.2f} | guarded incident ${guarded:.2f}")
    assert naive > 9 * healthy                     # the 10x bill
    assert guarded < 0.2 * healthy                 # breaker + retry budget stop paying for the outage
    assert gw.p.calls < 0.05 * 11 * n


def test_non_retryable_errors_are_not_retried():
    class Blocked:
        calls = 0
        def complete(self, req):
            self.calls += 1
            raise ContentBlocked("safety filter")
    p = Blocked()
    gw, _ = make_gateway(p)
    with pytest.raises(ContentBlocked):
        gw.call(ctx(), Request("large", LONG_HISTORY[:3], 500))
    assert p.calls == 1


def test_retries_get_cheaper():
    class FailTwice:
        def __init__(self): self.seen = []
        def complete(self, req):
            self.seen.append((req.model, estimate_tokens(req.messages)))
            if len(self.seen) < 3:
                raise ServerError("503")
            return Response("ok", req.model, Usage(estimate_tokens(req.messages), 200))
    p = FailTwice()
    gw, _ = make_gateway(p)
    gw.call(ctx(), Request("large", LONG_HISTORY, 1000))
    (m0, t0), (m1, t1), (m2, t2) = p.seen
    assert t1 < t0 and m2 == "small"


def test_calls_per_user_action_cap():
    gw, _ = make_gateway(FlakyProvider(incident=False), Limits(max_calls_per_user_action=3, per_request_usd=1.0))
    c = ctx(user_action_id="same-click")
    for _ in range(3):
        gw.call(c, Request("small", LONG_HISTORY[:3], 200))
    with pytest.raises(BudgetExceeded) as e:
        gw.call(c, Request("small", LONG_HISTORY[:3], 200))
    assert e.value.scope == "calls_per_user_action"


def test_tenant_budget_hard_stop_and_alerts():
    alerts = []
    gw, _ = make_gateway(FlakyProvider(incident=False),
                         Limits(per_request_usd=1.0, per_user_action_usd=1.0, per_conversation_usd=5.0,
                                per_tenant_month_usd={"acme": 1.00}), alerts)
    with pytest.raises(BudgetExceeded) as e:
        for i in range(100):
            gw.call(ctx(i), Request("large", LONG_HISTORY, 1000))
    assert e.value.scope == "tenant_month"
    assert any("50%" in a for a in alerts) and any("80%" in a for a in alerts)


def test_untagged_calls_rejected():
    gw, _ = make_gateway(FlakyProvider(incident=False))
    with pytest.raises(MissingAttribution):
        gw.call(ctx(feature=""), Request("small", LONG_HISTORY[:2], 100))


def test_spike_alert_on_context_growth():
    alerts = []
    gw, _ = make_gateway(FlakyProvider(incident=False), alerts=alerts)
    for i in range(60):
        gw.call(ctx(i), Request("small", LONG_HISTORY[:2], 100))         # small prompts build the baseline
    gw.call(ctx(999), Request("small", LONG_HISTORY, 100))               # sudden 30k-token prompt
    assert any("spike" in a and "input_tokens_per_call" in a for a in alerts)
