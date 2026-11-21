"""Tarefas 4.1, 4.2 e 4.4: resolução de política, backoff com relógio falso e circuit breaker."""

import random

import fakeredis
import pytest

from gateway.app.clock import FakeClock
from gateway.app.errors import GatewayError
from gateway.app.policy.backoff import Deadline, backoff_delay_s
from gateway.app.policy.circuit import CircuitBreaker
from gateway.app.policy.resolver import resolve_route
from gateway.app.policy.schemas import TeamPolicy
from gateway.app.providers.base import Hop
from tests.support import default_policy


def test_class_alias_resolves_to_allowed_model():
    policy = TeamPolicy.model_validate(default_policy())
    route = resolve_route(policy, "cheap")
    assert route.served_model == "mock-small" and route.via_class == "cheap"
    assert [h.provider for h in route.chain] == ["mock_a", "mock_b"]


def test_model_outside_policy_is_not_allowed():
    policy = TeamPolicy.model_validate(default_policy())
    with pytest.raises(GatewayError) as info:
        resolve_route(policy, "gpt-4o")
    assert info.value.code == "model_not_allowed"


def test_class_without_mapping_is_not_allowed():
    policy = TeamPolicy.model_validate(default_policy(classes={"cheap": "mock-small"}))
    with pytest.raises(GatewayError) as info:
        resolve_route(policy, "balanced")
    assert info.value.code == "model_not_allowed"


def test_max_hops_truncates_chain():
    policy = TeamPolicy.model_validate(default_policy(max_hops=1))
    assert len(resolve_route(policy, "mock-small").chain) == 1


def test_policy_rejects_alias_as_model_name():
    with pytest.raises(ValueError):
        TeamPolicy.model_validate(
            default_policy(
                models={"cheap": {"chain": [{"provider": "mock_a", "model": "x"}]}}, classes={}
            )
        )


def test_backoff_grows_exponentially_within_jitter_band():
    rng = random.Random(1)
    for attempt in range(4):
        base = min(2.0, 0.2 * 2**attempt)
        delay = backoff_delay_s(attempt, base_s=0.2, cap_s=2.0, rng=rng)
        assert 0.5 * base <= delay <= 1.5 * base


def test_backoff_respects_retry_after_minimum():
    delay = backoff_delay_s(0, base_s=0.01, cap_s=0.05, rng=random.Random(2), retry_after_s=1.0)
    assert delay >= 1.0


def test_deadline_uses_injected_clock():
    clock = FakeClock()
    deadline = Deadline(clock, 1_000)
    assert not deadline.expired()
    clock.advance_ms(999)
    assert deadline.remaining_ms() == pytest.approx(1.0)
    clock.advance_ms(2)
    assert deadline.expired()


async def test_sleep_advances_fake_clock_without_waiting():
    clock = FakeClock()
    start = clock.monotonic_ms()
    await clock.sleep(1.5)
    assert clock.monotonic_ms() - start == pytest.approx(1500)


@pytest.fixture
async def breaker_env():
    redis = fakeredis.FakeAsyncRedis()
    clock = FakeClock()
    breaker = CircuitBreaker(
        redis, clock, window_s=30, min_requests=3, failure_ratio=0.5, cooldown_s=5
    )
    yield breaker, clock
    await redis.aclose()


async def test_circuit_opens_skips_then_half_open_recovers(breaker_env):
    breaker, clock = breaker_env
    hop = Hop("mock_a", "mock-small")
    assert await breaker.allow(hop)
    for _ in range(3):
        assert await breaker.allow(hop)
        await breaker.record(hop, ok=False)
    assert await breaker.state(hop) == "open"
    assert not await breaker.allow(hop)  # saltado durante o cooldown

    clock.advance_ms(5_001)
    assert await breaker.allow(hop)  # primeiro probe
    assert not await breaker.allow(hop)  # só um probe em half-open
    await breaker.record(hop, ok=True)
    assert await breaker.state(hop) == "closed"
    assert await breaker.allow(hop)


async def test_failed_probe_reopens_circuit(breaker_env):
    breaker, clock = breaker_env
    hop = Hop("mock_a", "mock-small")
    for _ in range(3):
        await breaker.allow(hop)
        await breaker.record(hop, ok=False)
    clock.advance_ms(5_001)
    assert await breaker.allow(hop)
    assert await breaker.record(hop, ok=False) == "open"
    assert not await breaker.allow(hop)


async def test_below_min_requests_circuit_stays_closed(breaker_env):
    breaker, _ = breaker_env
    hop = Hop("mock_b", "mock-small")
    await breaker.record(hop, ok=False)
    await breaker.record(hop, ok=False)
    assert await breaker.state(hop) == "closed"
