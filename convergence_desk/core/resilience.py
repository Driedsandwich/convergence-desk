"""Local failure controls; caller-supplied operations are never networked here."""

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
from pathlib import Path
import random
import tempfile
import time
from typing import Callable, Optional, Union

from .models import SourceHealth
from .trail import canonical_json, content_hash


class RetryableError(Exception):
    """Adapters can normalize transient failures into this explicit contract."""

    def __init__(self, message: str, status_code: Optional[int] = None,
                 retry_after: Optional[Union[str, float]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def retry_after_seconds(value, now: Callable[[], datetime]) -> Optional[float]:
    """Accept Retry-After delta seconds or an HTTP date; ignore malformed values."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            target = parsedate_to_datetime(str(value))
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            seconds = (target - now()).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def retry(operation: Callable, *, attempts: int = 3, base_delay: float = 1.0,
          max_delay: float = 60.0, jitter: float = 0.25, seed: int = 0,
          sleep: Callable[[float], None] = time.sleep,
          now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
    """Retry transient errors with bounded exponential delay and seeded jitter.

    Retry-After on 429/503 is a minimum wait, even beyond max_delay. Permanent
    4xx errors and unclassified exceptions propagate immediately.
    """
    if not isinstance(attempts, int) or attempts < 1:
        raise ValueError("attempts must be a positive integer")
    if any(not math.isfinite(v) or v < 0 for v in (base_delay, max_delay, jitter)):
        raise ValueError("delays and jitter must be finite and nonnegative")
    rng = random.Random(seed)
    delay = min(base_delay, max_delay)
    for attempt in range(attempts):
        try:
            return operation()
        except RetryableError as error:
            transient = error.status_code is None or error.status_code in (408, 429) or 500 <= error.status_code <= 599
            if not transient or attempt == attempts - 1:
                raise
            wait = min(max_delay, delay + rng.uniform(0, delay * jitter))
            if error.status_code in (429, 503):
                server_delay = retry_after_seconds(error.retry_after, now)
                if server_delay is not None:
                    wait = max(wait, server_delay)
            sleep(wait)
            delay = min(max_delay, delay * 2)


class CircuitOpenError(RuntimeError):
    pass


@dataclass
class _Circuit:
    state: str = "closed"
    failures: int = 0
    opened_at: float = 0.0
    probe_in_flight: bool = False


class CircuitBreaker:
    """Per-source closed/open/half-open states using an injectable monotonic clock.

    One half-open probe is allowed after cooldown; success closes and failure
    reopens. Intended for synchronous callers, with external locking if shared.
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 60.0,
                 clock: Callable[[], float] = time.monotonic):
        if not isinstance(failure_threshold, int) or failure_threshold < 1:
            raise ValueError("failure_threshold must be a positive integer")
        if not math.isfinite(recovery_timeout) or recovery_timeout <= 0:
            raise ValueError("recovery_timeout must be finite and positive")
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.clock = clock
        self._sources = {}

    def state(self, source: str) -> str:
        circuit = self._sources.setdefault(source, _Circuit())
        if circuit.state == "open" and self.clock() - circuit.opened_at >= self.recovery_timeout:
            circuit.state = "half-open"
        return circuit.state

    def before_call(self, source: str) -> None:
        state = self.state(source)
        circuit = self._sources[source]
        if state == "open" or (state == "half-open" and circuit.probe_in_flight):
            raise CircuitOpenError(f"source {source} circuit is {state}")
        if state == "half-open":
            circuit.probe_in_flight = True

    def record_success(self, source: str) -> None:
        self._sources[source] = _Circuit()

    def record_failure(self, source: str) -> None:
        circuit = self._sources.setdefault(source, _Circuit())
        circuit.failures += 1
        circuit.probe_in_flight = False
        if circuit.state == "half-open" or circuit.failures >= self.failure_threshold:
            circuit.state = "open"
            circuit.opened_at = self.clock()

    def call(self, source: str, operation: Callable):
        self.before_call(source)
        try:
            result = operation()
        except Exception:
            self.record_failure(source)
            raise
        self.record_success(source)
        return result

    def health(self, source: str) -> SourceHealth:
        state = self.state(source)
        circuit = self._sources[source]
        status = "down" if state == "open" else "degraded" if state == "half-open" or circuit.failures else "healthy"
        return SourceHealth(source, status, f"circuit={state}; consecutive_failures={circuit.failures}")


class CheckpointError(RuntimeError):
    pass


class CheckpointStore:
    """Single-writer cursor and result state committed together using os.replace.

    Save after each processed item; replay any uncommitted item after a crash.
    Store its local result in state for atomic cursor/result persistence. External
    side effects need caller idempotency; this is not an exactly-once service.
    """

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return {"schema_version": 1, "sources": {}}
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            payload = envelope["payload"]
            if envelope["sha256"] != content_hash(payload):
                raise ValueError("checkpoint checksum mismatch")
            if payload["schema_version"] != 1 or not isinstance(payload["sources"], dict):
                raise ValueError("unsupported checkpoint format")
            return payload
        except (ValueError, KeyError, TypeError) as error:
            raise CheckpointError(f"invalid checkpoint: {self.path}") from error

    def resume(self, source: str):
        """Return the last committed item id, or None for a new source."""
        entry = self.load()["sources"].get(source)
        return entry["last_processed_item"] if entry else None

    def save(self, source: str, last_processed_item: str, state=None) -> None:
        payload = self.load()
        payload["sources"][source] = {"last_processed_item": last_processed_item, "state": state}
        encoded = canonical_json({"payload": payload, "sha256": content_hash(payload)})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=self.path.name + ".", suffix=".tmp", delete=False) as handle:
                temporary = handle.name
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
            if hasattr(os, "O_DIRECTORY"):
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
