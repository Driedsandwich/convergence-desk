"""Synthetic market evidence and complete portfolio-constrained practice plans."""

from dataclasses import replace
from datetime import timedelta

import pytest

from convergence_desk.core import (ChainEvent, PracticePosition, Rejection, SourceHealth,
                                   check_evidence, decide, evaluate)


def sol(snapshot):
    return next(o for o in evaluate(snapshot) if o.narrative.token == "SOL")


def failures(decision):
    return {check.rule for check in decision.failed_rules}


def test_market_numbers_and_entry(snapshot):
    result = sol(snapshot)
    assert result.evidence.status == "confirm"
    assert result.evidence.return_fraction == pytest.approx(0.1)
    assert result.evidence.volume_z == pytest.approx(60 / (200 ** 0.5))
    assert result.evidence.entry_price == 110
    assert result.evidence.entry_time == snapshot.as_of
    assert result.evidence.market_source == "synthetic_market"


def test_risk_size_capped_and_exit_plan(snapshot):
    position = sol(snapshot).decision
    assert isinstance(position, PracticePosition)
    assert position.units == pytest.approx(1000 / 110)
    assert position.notional == pytest.approx(1000)
    assert position.risk_amount == pytest.approx(50)
    assert position.stop == 104.5
    assert position.take_profit == 121
    assert position.time_stop == snapshot.as_of + timedelta(hours=24)
    assert all(c.passed for c in position.rule_chain)


def test_risk_size_without_position_cap(snapshot):
    snapshot = replace(snapshot, risk_limits=replace(snapshot.risk_limits, max_position_pct=0.5))
    position = sol(snapshot).decision
    assert position.units == pytest.approx(100 / 5.5)
    assert position.notional == pytest.approx(2000)
    assert position.risk_amount == pytest.approx(100)


def test_bearish_stop_and_take_profit(snapshot):
    posts = tuple(replace(p, text="Confident sell $SOL now", content_sha256="") for p in snapshot.posts[:2])
    last = replace(snapshot.market_bars[-1], open=90, high=91, low=89, close=90)
    result = sol(replace(snapshot, posts=posts, market_bars=snapshot.market_bars[:-1] + (last,)))
    assert result.evidence.status == "confirm"
    assert result.decision.direction == "bearish"
    assert result.decision.stop == 94.5
    assert result.decision.take_profit == 81


def test_daily_loss_stop_and_every_failed_rule(snapshot):
    snapshot = replace(snapshot, realized_loss_today=300, market_bars=(), rules=replace(snapshot.rules, quorum_weight=2))
    rejected = sol(snapshot).decision
    assert isinstance(rejected, Rejection)
    assert {"daily_loss_stop", "daily_risk_available", "quorum_weight", "market_confirmation", "entry_price", "entry_fresh"} <= failures(rejected)
    assert all(not check.passed for check in rejected.failed_rules)


def test_remaining_daily_budget_reduces_size(snapshot):
    position = sol(replace(snapshot, realized_loss_today=280)).decision
    assert position.risk_amount == pytest.approx(20)
    assert position.units == pytest.approx(20 / 5.5)


def test_open_stop_risk_is_reserved(snapshot):
    existing = replace(sol(snapshot).decision, token="ETH")
    result = sol(replace(snapshot, open_positions=(existing,), realized_loss_today=240)).decision
    assert result.risk_amount == pytest.approx(10)
    rejected = sol(replace(snapshot, open_positions=(existing,), realized_loss_today=250)).decision
    assert "daily_risk_available" in failures(rejected)


def test_position_count_and_duplicate_token(snapshot):
    existing = sol(snapshot).decision
    result = sol(replace(snapshot, open_positions=(existing,), risk_limits=replace(snapshot.risk_limits, max_open_positions=1))).decision
    assert {"no_existing_token", "max_open_positions"} <= failures(result)


def test_mentioned_nonconvergent_token_has_reasons(snapshot):
    rejected = next(o.decision for o in evaluate(snapshot) if o.narrative.token == "BTC")
    assert {"min_conviction", "quorum_weight", "min_distinct_voices", "market_confirmation"} <= failures(rejected)


@pytest.mark.parametrize("change", ["missing", "flat", "insufficient", "stale", "anchor_missing"])
def test_incomplete_market_data_rejects(snapshot, change):
    bars = snapshot.market_bars
    if change == "missing":
        bars = ()
    elif change == "flat":
        bars = tuple(replace(b, volume=100) for b in bars)
    elif change == "insufficient":
        bars = (bars[0], bars[-1])
    elif change == "stale":
        bars = bars[:2]
    elif change == "anchor_missing":
        bars = bars[1:]
    result = sol(replace(snapshot, market_bars=bars))
    assert result.evidence.status == "inconclusive"
    assert "market_confirmation" in failures(result.decision)


def test_opposing_return_is_contradiction(snapshot):
    last = replace(snapshot.market_bars[-1], open=90, high=91, low=89, close=90)
    result = sol(replace(snapshot, market_bars=snapshot.market_bars[:-1] + (last,)))
    assert result.evidence.status == "contradict"
    assert "return_aligned" in failures(result.decision)


def test_future_and_unfinished_bars_cannot_leak(snapshot):
    future = replace(snapshot.market_bars[-1], start=snapshot.as_of + timedelta(hours=1), close=110)
    assert sol(replace(snapshot, market_bars=snapshot.market_bars + (future,))).evidence == sol(snapshot).evidence
    unfinished = replace(snapshot.market_bars[-1], end=snapshot.as_of + timedelta(minutes=1))
    evidence = sol(replace(snapshot, market_bars=snapshot.market_bars[:-1] + (unfinished,))).evidence
    assert evidence.entry_time == snapshot.market_bars[-2].start
    assert evidence.entry_price == 105


def test_sources_are_not_spliced(snapshot):
    other = replace(snapshot.market_bars[-1], source="aaa_synthetic_other")
    result = sol(replace(snapshot, market_bars=snapshot.market_bars + (other,)))
    assert result.evidence.market_source == "aaa_synthetic_other"
    assert result.evidence.status == "inconclusive"
    assert result.evidence.return_fraction is None


def event(snapshot, token="SOL", label="exchange_inflow", **kwargs):
    return ChainEvent("synthetic_chain", "synthetic_tx", 10, token, "synthetic_a", "synthetic_b", 100, label,
                      kwargs.get("occurred_at", snapshot.as_of), "synthetic_chain")


@pytest.mark.parametrize("token,label,bias,status", [
    ("SOL", "exchange_inflow", "bearish", "contradict"),
    ("SOL", "exchange_outflow", "bullish", "confirm"),
    ("USDC", "exchange_inflow", "bullish", "confirm"),
    ("USDC", "exchange_outflow", "bearish", "contradict"),
])
def test_chain_flow_direction_and_numbers(snapshot, token, label, bias, status):
    evidence = sol(replace(snapshot, chain_events=(event(snapshot, token, label),))).evidence
    assert evidence.chain_bias == bias
    assert evidence.status == status
    assert evidence.chain_totals == ((token, label, 100.0),)


def test_untimed_future_chain_events_ignored(snapshot):
    for timestamp in (None, snapshot.as_of + timedelta(seconds=1), snapshot.as_of - timedelta(hours=25)):
        evidence = sol(replace(snapshot, chain_events=(event(snapshot, occurred_at=timestamp),))).evidence
        assert evidence.status == "confirm"
        assert not evidence.chain_totals


def test_no_market_confirmation_bypass_invents_entry(snapshot):
    result = sol(replace(snapshot, market_bars=(), rules=replace(snapshot.rules, require_market_evidence=False)))
    assert "entry_price" in failures(result.decision)


def test_down_market_source_rejects(snapshot):
    result = sol(replace(snapshot, source_health=(SourceHealth("synthetic_market", "down", "dependency unavailable"),)))
    assert "entry_price" in failures(result.decision)


def test_neutral_mentions_rejected(snapshot):
    posts = tuple(replace(p, text="$SOL discussed today", content_sha256="") for p in snapshot.posts[:2])
    result = sol(replace(snapshot, posts=posts))
    assert "directional_narrative" in failures(result.decision)


def test_conflicting_convergence_rejects_both(snapshot):
    opposing = tuple(replace(p, uri=p.uri + "/opposite", text="Confident bearish $SOL", content_sha256="") for p in snapshot.posts[:2])
    results = [o for o in evaluate(replace(snapshot, posts=snapshot.posts + opposing)) if o.narrative.token == "SOL"]
    assert len(results) == 2
    assert all("no_direction_conflict" in failures(o.decision) for o in results)


def test_batch_allocation_respects_shared_risk_and_order(snapshot):
    posts = tuple(replace(p, text="Confident buy $ETH and $SOL", content_sha256="") for p in snapshot.posts[:2])
    bars = snapshot.market_bars + tuple(replace(b, symbol="ETH") for b in snapshot.market_bars)
    results = evaluate(replace(snapshot, posts=posts, market_bars=bars, realized_loss_today=250))
    assert results[0].narrative.token == "ETH"
    assert isinstance(results[0].decision, PracticePosition)
    assert "daily_risk_available" in failures(results[1].decision)


def test_negative_loss_input_rejected(snapshot):
    with pytest.raises(ValueError):
        replace(snapshot, realized_loss_today=-1)


def test_unrepresentable_exit_rejects_instead_of_crashing(snapshot):
    tiny_stop = replace(snapshot.risk_limits, stop_pct=1e-300)
    result = sol(replace(snapshot, risk_limits=tiny_stop))
    assert "valid_exit_plan" in failures(result.decision)


def test_nonpositive_short_target_rejects_but_large_long_target_valid(snapshot):
    limits = replace(snapshot.risk_limits, take_profit_r=30)
    assert isinstance(sol(replace(snapshot, risk_limits=limits)).decision, PracticePosition)
    posts = tuple(replace(p, text="Confident sell $SOL", content_sha256="") for p in snapshot.posts[:2])
    last = replace(snapshot.market_bars[-1], open=90, high=91, low=89, close=90)
    changed = replace(snapshot, risk_limits=limits, posts=posts, market_bars=snapshot.market_bars[:-1] + (last,))
    assert "valid_exit_plan" in failures(sol(changed).decision)


def test_existing_position_token_case_is_normalized(snapshot):
    existing = replace(sol(snapshot).decision, token="sol")
    assert "no_existing_token" in failures(sol(replace(snapshot, open_positions=(existing,))).decision)


@pytest.mark.parametrize("field,value", [("account_size", 0), ("stop_pct", 0), ("stop_pct", 1),
                                         ("max_position_pct", 2), ("take_profit_r", 0), ("max_hold_hours", float("nan"))])
def test_invalid_risk_limits_rejected(snapshot, field, value):
    with pytest.raises(ValueError):
        replace(snapshot.risk_limits, **{field: value})
