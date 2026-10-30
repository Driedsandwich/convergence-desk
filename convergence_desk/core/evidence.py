"""Observable price/volume confirmation, with optional exchange-flow context."""

from collections import defaultdict
from datetime import datetime, timedelta
import math
import statistics
from typing import Iterable

from .models import ChainEvent, Evidence, MarketBar, Narrative, RuleCheck, Rules, utc


STABLECOINS = {"USDT", "USDC", "DAI"}


def _chain(narrative, events, start, as_of):
    totals = defaultdict(list)
    notes = []
    seen = set()
    for event in sorted(events, key=lambda e: (e.chain, e.tx_hash, e.event_index)):
        key = (event.chain, event.tx_hash, event.event_index)
        if key in seen:
            continue
        seen.add(key)
        if event.token not in STABLECOINS | {narrative.token}:
            continue
        if event.occurred_at is None:
            notes.append(f"ignored untimed chain event {event.chain}:{event.tx_hash}:{event.event_index}")
            continue
        if start <= event.occurred_at <= as_of and event.label in ("exchange_inflow", "exchange_outflow"):
            totals[(event.token, event.label)].append(event.amount)
    amounts = {key: math.fsum(values) for key, values in totals.items()}
    biases = set()
    for token in sorted({key[0] for key in amounts}):
        net = amounts.get((token, "exchange_inflow"), 0) - amounts.get((token, "exchange_outflow"), 0)
        if net:
            bullish = net > 0 if token in STABLECOINS else net < 0
            biases.add("bullish" if bullish else "bearish")
    bias = next(iter(biases)) if len(biases) == 1 else "inconclusive"
    return tuple((token, label, amount) for (token, label), amount in sorted(amounts.items())), bias, notes


def check_evidence(narrative: Narrative, bars: Iterable[MarketBar], rules: Rules,
                   as_of: datetime, chain_events: Iterable[ChainEvent] = ()) -> Evidence:
    """Require aligned window return and an elevated latest-bar volume z-score.

    Use one venue, selected by latest available timestamp then source name.
    Prior lookback volumes use population standard deviation; zero variance is
    inconclusive. Opposing exchange flows can veto, but never replace, prices.
    """
    utc(as_of)
    start = as_of - timedelta(hours=rules.window_hours)
    by_source = defaultdict(list)
    for bar in bars:
        if bar.symbol == narrative.token and bar.available_at <= as_of:
            by_source[bar.source].append(bar)
    totals, bias, notes = _chain(narrative, chain_events, start, as_of)
    chain_opposes = bias not in ("inconclusive", narrative.direction) and narrative.direction != "neutral"
    if not by_source:
        return Evidence("contradict" if chain_opposes else "inconclusive", None, None, None, None, None,
                        (RuleCheck("market_bars_present", False, 0, ">= 1"),), totals, bias,
                        tuple(notes + ["no observable market bars"]))
    source = sorted(by_source, key=lambda name: (-max(b.available_at.timestamp() for b in by_source[name]), name))[0]
    series = sorted(by_source[source], key=lambda b: (b.available_at, b.start))
    latest = series[-1]
    anchors = [b for b in series if b.available_at <= start]
    anchor = anchors[-1] if anchors else None
    return_fraction = latest.close / anchor.close - 1 if anchor and latest.available_at > start else None
    previous = [b.volume for b in series if b.available_at < latest.available_at][-rules.volume_lookback:]
    mean = statistics.fmean(previous) if previous else None
    std = statistics.pstdev(previous) if len(previous) >= 2 else None
    volume_z = (latest.volume - mean) / std if len(previous) == rules.volume_lookback and std and std > 0 else None
    age = (as_of - latest.available_at).total_seconds() / 3600
    anchor_age = (start - anchor.available_at).total_seconds() / 3600 if anchor else None
    signed_return = return_fraction * (1 if narrative.direction == "bullish" else -1) if return_fraction is not None else None
    checks = (
        RuleCheck("market_fresh", age <= rules.max_market_age_hours, age, rules.max_market_age_hours),
        RuleCheck("window_anchor", anchor_age is not None and anchor_age <= rules.max_market_age_hours,
                  anchor_age, rules.max_market_age_hours, "hours between window start and baseline close"),
        RuleCheck("window_endpoint", latest.available_at > start, latest.available_at.isoformat(), f"> {start.isoformat()}"),
        RuleCheck("volume_lookback", len(previous) == rules.volume_lookback, len(previous), rules.volume_lookback),
        RuleCheck("volume_variance", std is not None and std > 0, std, "> 0"),
        RuleCheck("return_aligned", signed_return is not None and signed_return >= rules.market_min_return,
                  signed_return, rules.market_min_return),
        RuleCheck("volume_z", volume_z is not None and volume_z >= rules.market_min_volume_z, volume_z, rules.market_min_volume_z,
                  f"latest_volume={latest.volume}; baseline_mean={mean}; baseline_std={std}"),
        RuleCheck("chain_not_opposed", not chain_opposes, bias, narrative.direction + " or inconclusive"),
    )
    observable_return = all(c.passed for c in checks[:3])
    if chain_opposes or (observable_return and signed_return is not None and signed_return <= -rules.market_min_return):
        status = "contradict"
    elif narrative.direction != "neutral" and all(c.passed for c in checks):
        status = "confirm"
    else:
        status = "inconclusive"
    if len(by_source) > 1:
        notes.append(f"used market source {source}; sources are never mixed")
    if std == 0:
        notes.append("volume baseline has zero variance; z-score is undefined")
    return Evidence(status, return_fraction, volume_z, latest.close, latest.available_at, source,
                    checks, totals, bias, tuple(notes))
