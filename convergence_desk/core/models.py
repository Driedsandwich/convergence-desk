"""Immutable contracts for adapters and the deterministic, practice-only engine."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import math
from typing import Optional, Tuple, Union


def utc(value: datetime) -> None:
    """Require aware UTC timestamps; the engine never reads the wall clock."""
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be timezone-aware UTC")


def finite(*values: float) -> None:
    if any(not math.isfinite(value) for value in values):
        raise ValueError("numeric inputs must be finite")


def fraction(value: float, name: str, *, positive: bool = False) -> None:
    finite(value)
    if not 0 <= value <= 1 or (positive and value == 0):
        raise ValueError(f"{name} must be {'> 0 and ' if positive else ''}<= 1 and >= 0")


@dataclass(frozen=True)
class Post:
    source: str
    author_id: str
    author_label: str
    uri: str
    created_at: datetime
    text: str
    content_sha256: str = ""

    def __post_init__(self) -> None:
        utc(self.created_at)
        digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.content_sha256 and self.content_sha256 != digest:
            raise ValueError("post content_sha256 does not match UTF-8 text")
        object.__setattr__(self, "content_sha256", digest)


@dataclass(frozen=True)
class Voice:
    id: str
    label: str
    source: str
    trust_weight: float

    def __post_init__(self) -> None:
        fraction(self.trust_weight, "trust_weight")


@dataclass(frozen=True)
class MarketBar:
    """A completed bar; end is its availability time (start for point samples)."""

    symbol: str
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    end: Optional[datetime] = None

    def __post_init__(self) -> None:
        utc(self.start)
        if self.end is not None:
            utc(self.end)
            if self.end < self.start:
                raise ValueError("bar end precedes start")
        finite(self.open, self.high, self.low, self.close, self.volume)
        if min(self.open, self.high, self.low, self.close) <= 0 or self.volume < 0:
            raise ValueError("prices must be positive and volume nonnegative")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("invalid OHLC bounds")
        object.__setattr__(self, "symbol", self.symbol.upper())

    @property
    def available_at(self) -> datetime:
        return self.end or self.start


@dataclass(frozen=True)
class ChainEvent:
    """Only timestamped events can contribute to time-window evidence."""

    chain: str
    tx_hash: str
    block: int
    token: str
    from_addr: str
    to_addr: str
    amount: float
    label: str
    occurred_at: Optional[datetime] = None
    source: str = "chain"
    event_index: int = 0

    def __post_init__(self) -> None:
        finite(self.amount)
        if self.amount < 0 or self.block < 0 or self.event_index < 0:
            raise ValueError("chain quantities must be nonnegative")
        if self.occurred_at is not None:
            utc(self.occurred_at)
        object.__setattr__(self, "token", self.token.upper())


@dataclass(frozen=True)
class RiskLimits:
    """Percentages are fractions, e.g. 0.01 is one percent of account size."""

    account_size: float
    max_position_pct: float = 0.10
    max_loss_per_trade_pct: float = 0.01
    max_daily_loss_pct: float = 0.03
    max_open_positions: int = 3
    stop_pct: float = 0.05
    take_profit_r: float = 2.0
    max_hold_hours: float = 24.0

    def __post_init__(self) -> None:
        finite(self.account_size, self.take_profit_r, self.max_hold_hours)
        if min(self.account_size, self.take_profit_r, self.max_hold_hours) <= 0:
            raise ValueError("account, reward multiple and holding period must be positive")
        for name in ("max_position_pct", "max_loss_per_trade_pct", "max_daily_loss_pct", "stop_pct"):
            fraction(getattr(self, name), name, positive=True)
        if self.stop_pct >= 1:
            raise ValueError("stop_pct must be less than 1")
        if not isinstance(self.max_open_positions, int) or self.max_open_positions < 1:
            raise ValueError("max_open_positions must be a positive integer")


@dataclass(frozen=True)
class Rules:
    window_hours: float = 24.0
    quorum_weight: float = 1.5
    min_distinct_voices: int = 2
    min_conviction: float = 0.5
    market_min_return: float = 0.01
    market_min_volume_z: float = 1.0
    volume_lookback: int = 5
    max_market_age_hours: float = 2.0
    quorum_step: float = 0.1
    conviction_step: float = 0.1
    require_market_evidence: bool = True

    def __post_init__(self) -> None:
        finite(self.window_hours, self.quorum_weight, self.market_min_return,
               self.market_min_volume_z, self.max_market_age_hours,
               self.quorum_step, self.conviction_step)
        if min(self.window_hours, self.max_market_age_hours, self.quorum_step, self.conviction_step) <= 0:
            raise ValueError("windows and sensitivity steps must be positive")
        if self.quorum_weight < 0 or self.market_min_return <= 0 or self.market_min_volume_z < 0:
            raise ValueError("invalid market/quorum thresholds")
        if not isinstance(self.min_distinct_voices, int) or not 1 <= self.min_distinct_voices <= 20:
            raise ValueError("min_distinct_voices must be in 1..20")
        if not isinstance(self.volume_lookback, int) or self.volume_lookback < 2:
            raise ValueError("volume_lookback must be an integer >= 2")
        fraction(self.min_conviction, "min_conviction")
        fraction(self.conviction_step, "conviction_step", positive=True)


@dataclass(frozen=True)
class RuleCheck:
    rule: str
    passed: bool
    actual: Union[str, float, int, bool, None]
    expected: Union[str, float, int, bool, None]
    detail: str = ""


@dataclass(frozen=True)
class Score:
    value: float
    fired: Tuple[str, ...]


@dataclass(frozen=True)
class Signal:
    post: Post
    token: str
    direction: str
    sentiment: Score
    conviction: Score
    urgency: Score
    token_rules: Tuple[str, ...]


@dataclass(frozen=True)
class Narrative:
    token: str
    direction: str
    members: Tuple[Signal, ...]
    first_post_time: datetime
    last_post_time: datetime
    voice_weights: Tuple[Tuple[str, str, float], ...]
    total_weight: float
    distinct_voices: int
    converged: bool
    checks: Tuple[RuleCheck, ...]


@dataclass(frozen=True)
class Evidence:
    status: str
    return_fraction: Optional[float]
    volume_z: Optional[float]
    entry_price: Optional[float]
    entry_time: Optional[datetime]
    market_source: Optional[str]
    checks: Tuple[RuleCheck, ...]
    chain_totals: Tuple[Tuple[str, str, float], ...] = ()
    chain_bias: str = "inconclusive"
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PracticePosition:
    token: str
    direction: str
    entry_price: float
    entry_time: datetime
    stop: float
    take_profit: float
    time_stop: datetime
    units: float
    notional: float
    risk_amount: float
    rule_chain: Tuple[RuleCheck, ...]
    opened_at: datetime
    kind: str = field(default="practice_position", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", self.token.upper())
        for value in (self.entry_time, self.time_stop, self.opened_at):
            utc(value)
        finite(self.entry_price, self.stop, self.take_profit, self.units, self.notional, self.risk_amount)
        if min(self.entry_price, self.stop, self.take_profit, self.units, self.notional, self.risk_amount) <= 0:
            raise ValueError("position prices, units, notional and risk must be positive")
        if self.direction not in ("bullish", "bearish"):
            raise ValueError("position direction must be bullish or bearish")
        if self.entry_time > self.opened_at or self.time_stop <= self.opened_at:
            raise ValueError("invalid position timestamps")
        ordered = self.stop < self.entry_price < self.take_profit if self.direction == "bullish" else self.take_profit < self.entry_price < self.stop
        if not ordered:
            raise ValueError("stop and target must match position direction")
        if not math.isclose(self.notional, self.units * self.entry_price):
            raise ValueError("notional does not match units times entry")
        if not math.isclose(self.risk_amount, self.units * abs(self.entry_price - self.stop)):
            raise ValueError("risk does not match units times stop distance")


@dataclass(frozen=True)
class Rejection:
    token: str
    direction: str
    failed_rules: Tuple[RuleCheck, ...]
    rule_chain: Tuple[RuleCheck, ...]
    kind: str = field(default="rejection", init=False)


Decision = Union[PracticePosition, Rejection]


@dataclass(frozen=True)
class SourceHealth:
    source: str
    state: str = "healthy"
    detail: str = ""

    def __post_init__(self) -> None:
        if self.state not in ("healthy", "degraded", "down"):
            raise ValueError("health state must be healthy, degraded or down")


@dataclass(frozen=True)
class Snapshot:
    as_of: datetime
    posts: Tuple[Post, ...]
    voices: Tuple[Voice, ...]
    market_bars: Tuple[MarketBar, ...]
    risk_limits: RiskLimits
    rules: Rules = field(default_factory=Rules)
    chain_events: Tuple[ChainEvent, ...] = ()
    open_positions: Tuple[PracticePosition, ...] = ()
    realized_loss_today: float = 0.0
    source_health: Tuple[SourceHealth, ...] = ()
    degraded_notes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        utc(self.as_of)
        finite(self.realized_loss_today)
        if self.realized_loss_today < 0:
            raise ValueError("realized_loss_today is nonnegative gross realized loss in account currency")
        for name in ("posts", "voices", "market_bars", "chain_events", "open_positions", "source_health", "degraded_notes"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if len(self.voices) > 20:
            raise ValueError("at most 20 selected voices")
        if len({(v.source, v.id) for v in self.voices}) != len(self.voices):
            raise ValueError("selected voices must have unique (source, id)")
        if len({h.source for h in self.source_health}) != len(self.source_health):
            raise ValueError("source health must have unique sources")
        if any(p.opened_at > self.as_of for p in self.open_positions):
            raise ValueError("open positions cannot come from the future")
        post_keys = [(p.source, p.uri) for p in self.posts]
        if len(set(post_keys)) != len(post_keys):
            raise ValueError("post (source, uri) must be unique")
        bar_keys = [(b.source, b.symbol, b.start) for b in self.market_bars]
        if len(set(bar_keys)) != len(bar_keys):
            raise ValueError("bar (source, symbol, start) must be unique")
        event_keys = [(e.chain, e.tx_hash, e.event_index) for e in self.chain_events]
        if len(set(event_keys)) != len(event_keys):
            raise ValueError("chain event identities must be unique")


@dataclass(frozen=True)
class Outcome:
    narrative: Narrative
    evidence: Evidence
    decision: Decision


@dataclass(frozen=True)
class CounterfactualTrial:
    change: str
    value: Union[str, float]
    baseline_accepted: bool
    alternative_accepted: bool
    flipped: bool
    failed_rules: Tuple[str, ...]


@dataclass(frozen=True)
class CounterfactualReport:
    token: str
    direction: str
    pivotal_voices: Tuple[Tuple[str, str], ...]
    sensitive_thresholds: Tuple[str, ...]
    trials: Tuple[CounterfactualTrial, ...]


@dataclass(frozen=True)
class InputReference:
    kind: str
    source: str
    identity: str
    content_sha256: str


@dataclass(frozen=True)
class DecisionRecord:
    schema_version: int
    as_of: datetime
    snapshot_hash: str
    inputs: Tuple[InputReference, ...]
    outcomes: Tuple[Outcome, ...]
    counterfactuals: Tuple[CounterfactualReport, ...]
    source_health: Tuple[SourceHealth, ...]
    degraded_notes: Tuple[str, ...]
    decision_hash: str = ""
