"""Canonical snapshots and content-addressed records; no clock or I/O in replay."""

from dataclasses import asdict, is_dataclass, replace
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
from typing import Mapping, Union

from .counterfactual import counterfactuals
from .models import (ChainEvent, DecisionRecord, InputReference, MarketBar, Post,
                     PracticePosition, RiskLimits, RuleCheck, Rules, Snapshot,
                     SourceHealth, Voice, utc)
from .pipeline import evaluate, health_notes


SCHEMA_VERSION = 1
ENGINE_VERSION = "1"


def canonical_json(value) -> str:
    """Sorted keys, UTF-8 text, UTC microseconds and fixed-point float notation.

    Decimal(str(float)) preserves round-trip precision without exponent notation
    or rounding tiny token quantities to zero. NaN and infinity are forbidden.
    """
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, datetime):
        utc(value)
        return json.dumps(value.isoformat(timespec="microseconds").replace("+00:00", "Z"))
    if value is None or isinstance(value, (str, bool, int)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite numbers cannot be hashed")
        encoded = format(Decimal(str(value)), "f")
        # Keep a decimal point so JSON reload preserves float type, including
        # large integral floats and signed zero used in explanatory strings.
        return encoded if "." in encoded else encoded + ".0"
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical object keys must be strings")
        return "{" + ",".join(canonical_json(key) + ":" + canonical_json(value[key]) for key in sorted(value)) + "}"
    if isinstance(value, (tuple, list)):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    raise TypeError(f"unsupported canonical type: {type(value).__name__}")


def content_hash(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def snapshot_to_json(snapshot: Snapshot) -> str:
    return canonical_json({"schema_version": SCHEMA_VERSION, "engine_version": ENGINE_VERSION, "snapshot": snapshot})


def _datetime(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value


def _position(value):
    data = dict(value)
    data.pop("kind", None)
    for key in ("entry_time", "time_stop", "opened_at"):
        data[key] = _datetime(data[key])
    data["rule_chain"] = tuple(RuleCheck(**check) for check in data["rule_chain"])
    return PracticePosition(**data)


def snapshot_from_json(payload: Union[str, Mapping]) -> Snapshot:
    """Load a versioned snapshot, validating the same contracts as live inputs."""
    envelope = json.loads(payload) if isinstance(payload, str) else dict(payload)
    if envelope.get("schema_version") != SCHEMA_VERSION or envelope.get("engine_version") != ENGINE_VERSION:
        raise ValueError("unsupported snapshot schema or engine version")
    data = dict(envelope["snapshot"])
    data["as_of"] = _datetime(data["as_of"])
    data["posts"] = tuple(Post(**{**p, "created_at": _datetime(p["created_at"])}) for p in data["posts"])
    data["voices"] = tuple(Voice(**v) for v in data["voices"])
    data["market_bars"] = tuple(MarketBar(**{**b, "start": _datetime(b["start"]),
                                           "end": _datetime(b["end"]) if b.get("end") else None}) for b in data["market_bars"])
    data["chain_events"] = tuple(ChainEvent(**{**e, "occurred_at": _datetime(e["occurred_at"]) if e.get("occurred_at") else None}) for e in data.get("chain_events", ()))
    data["risk_limits"] = RiskLimits(**data["risk_limits"])
    data["rules"] = Rules(**data["rules"])
    data["source_health"] = tuple(SourceHealth(**h) for h in data.get("source_health", ()))
    data["open_positions"] = tuple(_position(p) for p in data.get("open_positions", ()))
    return Snapshot(**data)


def _input_references(snapshot):
    references = []
    for post in snapshot.posts:
        references.append(InputReference("post", post.source, post.uri, post.content_sha256))
    for voice in snapshot.voices:
        references.append(InputReference("voice", voice.source, voice.id, content_hash(voice)))
    for bar in snapshot.market_bars:
        references.append(InputReference("market_bar", bar.source, f"{bar.symbol}:{bar.start.isoformat()}", content_hash(bar)))
    for event in snapshot.chain_events:
        references.append(InputReference("chain_event", event.source,
                                         f"{event.chain}:{event.tx_hash}:{event.event_index}", content_hash(event)))
    for index, position in enumerate(snapshot.open_positions):
        references.append(InputReference("open_position", "practice_ledger", str(index), content_hash(position)))
    for health in snapshot.source_health:
        references.append(InputReference("source_health", health.source, health.source, content_hash(health)))
    for name in ("as_of", "risk_limits", "rules", "realized_loss_today", "degraded_notes"):
        references.append(InputReference(name, "user_snapshot", name, content_hash(getattr(snapshot, name))))
    return tuple(sorted(references, key=lambda ref: (ref.kind, ref.source, ref.identity, ref.content_sha256)))


def decision_hash(record: DecisionRecord) -> str:
    """Hash the full record except its own digest field."""
    data = asdict(record)
    data.pop("decision_hash")
    return content_hash(data)


def replay(snapshot: Union[Snapshot, str, Mapping]) -> DecisionRecord:
    """Recompute decisions and all interventions from supplied inputs alone."""
    if not isinstance(snapshot, Snapshot):
        snapshot = snapshot_from_json(snapshot)
    outcomes = evaluate(snapshot)
    snapshot_digest = hashlib.sha256(snapshot_to_json(snapshot).encode("utf-8")).hexdigest()
    record = DecisionRecord(SCHEMA_VERSION, snapshot.as_of, snapshot_digest, _input_references(snapshot),
                            outcomes, counterfactuals(snapshot, outcomes), snapshot.source_health, health_notes(snapshot))
    return replace(record, decision_hash=decision_hash(record))
