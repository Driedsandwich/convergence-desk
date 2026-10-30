"""Synthetic outages, seeded backoff and crash-safe local checkpoint recovery."""

from datetime import timedelta
from email.utils import format_datetime
import json

import pytest

from convergence_desk.core import (CheckpointError, CheckpointStore, CircuitBreaker,
                                   CircuitOpenError, RetryableError, retry)
from convergence_desk.core import resilience


def test_retry_honors_retry_after_beyond_cap():
    waits, calls = [], []
    def operation():
        calls.append(1)
        if len(calls) == 1:
            raise RetryableError("synthetic rate limit", 429, "120")
        return "synthetic success"
    assert retry(operation, sleep=waits.append, max_delay=5, seed=7) == "synthetic success"
    assert waits == [120]
    assert len(calls) == 2


def test_retry_after_http_date(snapshot):
    waits, calls = [], []
    def operation():
        calls.append(1)
        if len(calls) == 1:
            date = format_datetime(snapshot.as_of + timedelta(seconds=35), usegmt=True)
            raise RetryableError("synthetic busy", 429, date)
        return 42
    assert retry(operation, now=lambda: snapshot.as_of, sleep=waits.append) == 42
    assert waits == [35]


def test_seeded_exponential_backoff_is_reproducible():
    def run(seed):
        waits = []
        def failure():
            raise RetryableError("synthetic offline", 503, "not a date")
        with pytest.raises(RetryableError):
            retry(failure, attempts=4, seed=seed, sleep=waits.append)
        return waits
    first = run(7)
    assert first == run(7)
    assert first != run(8)
    assert len(first) == 3
    assert 1 <= first[0] <= 1.25
    assert 2 <= first[1] <= 2.5
    assert 4 <= first[2] <= 5


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_failures_not_retried(status):
    waits = []
    def failure():
        raise RetryableError("synthetic permanent error", status)
    with pytest.raises(RetryableError):
        retry(failure, sleep=waits.append)
    assert waits == []


def test_unknown_exception_not_retried():
    waits = []
    def failure():
        raise ValueError("synthetic bug")
    with pytest.raises(ValueError):
        retry(failure, sleep=waits.append)
    assert waits == []


@pytest.mark.parametrize("header", ["garbage", "NaN", "Infinity", -4, None])
def test_bad_retry_after_falls_back_to_backoff(header):
    waits = []
    def failure():
        raise RetryableError("synthetic rate limit", 429, header)
    with pytest.raises(RetryableError):
        retry(failure, attempts=2, jitter=0, sleep=waits.append)
    assert waits == [1]


def test_circuit_closed_open_half_open_closed():
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=10, clock=lambda: now[0])
    assert breaker.state("synthetic_a") == "closed"
    breaker.record_failure("synthetic_a")
    assert breaker.health("synthetic_a").state == "degraded"
    breaker.record_failure("synthetic_a")
    assert breaker.state("synthetic_a") == "open"
    assert breaker.health("synthetic_a").state == "down"
    assert breaker.state("synthetic_b") == "closed"
    with pytest.raises(CircuitOpenError):
        breaker.before_call("synthetic_a")
    now[0] = 9.999
    assert breaker.state("synthetic_a") == "open"
    now[0] = 10
    assert breaker.state("synthetic_a") == "half-open"
    breaker.before_call("synthetic_a")
    with pytest.raises(CircuitOpenError):
        breaker.before_call("synthetic_a")
    breaker.record_success("synthetic_a")
    assert breaker.state("synthetic_a") == "closed"
    assert breaker.health("synthetic_a").state == "healthy"


def test_failed_half_open_probe_reopens():
    now = [0.0]
    breaker = CircuitBreaker(1, 10, clock=lambda: now[0])
    breaker.record_failure("synthetic")
    now[0] = 10
    def failure():
        raise OSError("synthetic outage")
    with pytest.raises(OSError):
        breaker.call("synthetic", failure)
    assert breaker.state("synthetic") == "open"
    now[0] = 20
    assert breaker.call("synthetic", lambda: "recovered") == "recovered"
    assert breaker.state("synthetic") == "closed"


def test_checkpoint_resumes_after_simulated_processing_crash(tmp_path):
    path = tmp_path / "synthetic_checkpoint.json"
    store = CheckpointStore(path)
    assert store.resume("synthetic") is None
    store.save("synthetic", "item_1", {"processed": ["item_1"]})
    with pytest.raises(RuntimeError):
        # Work on item_2 crashes before commit: the old cursor remains valid.
        raise RuntimeError("simulated process crash on item_2")
    restarted = CheckpointStore(path)
    assert restarted.resume("synthetic") == "item_1"
    restarted.save("synthetic", "item_2", {"processed": ["item_1", "item_2"]})
    assert CheckpointStore(path).resume("synthetic") == "item_2"
    assert restarted.load()["sources"]["synthetic"]["state"]["processed"] == ["item_1", "item_2"]


def test_checkpoint_atomic_replace_failure_preserves_previous(tmp_path, monkeypatch):
    path = tmp_path / "synthetic_checkpoint.json"
    store = CheckpointStore(path)
    store.save("synthetic_a", "item_1")
    def crash(*args):
        raise OSError("synthetic crash before atomic rename")
    monkeypatch.setattr(resilience.os, "replace", crash)
    with pytest.raises(OSError):
        store.save("synthetic_a", "item_2")
    assert CheckpointStore(path).resume("synthetic_a") == "item_1"
    assert list(tmp_path.glob("*.tmp")) == []


def test_checkpoint_keeps_per_source_progress(tmp_path):
    store = CheckpointStore(tmp_path / "synthetic_checkpoint.json")
    store.save("synthetic_a", "item_3", {"note": "synthetic"})
    store.save("synthetic_b", "item_7")
    assert store.resume("synthetic_a") == "item_3"
    assert store.resume("synthetic_b") == "item_7"
    assert store.load()["sources"]["synthetic_a"]["state"] == {"note": "synthetic"}


def test_checkpoint_corruption_is_explicit(tmp_path):
    path = tmp_path / "synthetic_checkpoint.json"
    store = CheckpointStore(path)
    store.save("synthetic", "item_1")
    envelope = json.loads(path.read_text())
    envelope["payload"]["sources"]["synthetic"]["last_processed_item"] = "tampered"
    path.write_text(json.dumps(envelope))
    with pytest.raises(CheckpointError):
        CheckpointStore(path).resume("synthetic")
    path.write_text("{incomplete")
    with pytest.raises(CheckpointError):
        store.load()


def test_checkpoint_serialization_failure_preserves_previous(tmp_path):
    store = CheckpointStore(tmp_path / "synthetic_checkpoint.json")
    store.save("synthetic", "item_1")
    with pytest.raises(ValueError):
        store.save("synthetic", "item_2", {"bad": float("nan")})
    assert store.resume("synthetic") == "item_1"
