"""An entry, sized exposure and complete exit plan form one practice decision."""

from datetime import datetime, timedelta
import math
from typing import Iterable

from .models import (Decision, Evidence, Narrative, PracticePosition, Rejection,
                     RiskLimits, RuleCheck, Rules, finite, utc)


def decide(narrative: Narrative, evidence: Evidence, limits: RiskLimits, rules: Rules,
           open_positions: Iterable[PracticePosition], realized_loss_today: float,
           as_of: datetime, *, conflicting_direction: bool = False) -> Decision:
    """Reserve open stop risk against the daily budget, then cap gross exposure.

    Size is min(risk budget / stop distance, position cap / entry, remaining
    account exposure / entry). Loss input is gross realized practice loss today.
    """
    utc(as_of)
    finite(realized_loss_today)
    if realized_loss_today < 0:
        raise ValueError("realized practice loss must be nonnegative")
    positions = tuple(open_positions)
    open_risk = math.fsum(p.risk_amount for p in positions)
    daily_cap = limits.account_size * limits.max_daily_loss_pct
    remaining_daily = daily_cap - realized_loss_today - open_risk
    trade_budget = limits.account_size * limits.max_loss_per_trade_pct
    risk_budget = min(trade_budget, remaining_daily)
    budget_resolution = math.ulp(limits.account_size)
    remaining_exposure = limits.account_size - math.fsum(p.notional for p in positions)
    price = evidence.entry_price
    valid_price = price is not None and math.isfinite(price) and price > 0
    age = (as_of - evidence.entry_time).total_seconds() / 3600 if evidence.entry_time else None
    checks = list(narrative.checks) + [
        RuleCheck("narrative_converged", narrative.converged, narrative.converged, True),
        RuleCheck("no_direction_conflict", not conflicting_direction, conflicting_direction, False),
        RuleCheck("market_confirmation", not rules.require_market_evidence or evidence.status == "confirm",
                  evidence.status, "confirm" if rules.require_market_evidence else "bypassed for sensitivity analysis"),
        RuleCheck("entry_price", valid_price, price, "> 0 and finite"),
        RuleCheck("entry_fresh", age is not None and 0 <= age <= rules.max_market_age_hours,
                  age, rules.max_market_age_hours, "reference age in hours; future references disallowed"),
        RuleCheck("max_open_positions", len(positions) < limits.max_open_positions,
                  len(positions), limits.max_open_positions, "strictly below limit before opening"),
        RuleCheck("no_existing_token", not any(p.token == narrative.token for p in positions),
                  sum(p.token == narrative.token for p in positions), 0),
        RuleCheck("daily_loss_stop", realized_loss_today < daily_cap, realized_loss_today, daily_cap),
        RuleCheck("daily_risk_available", remaining_daily > budget_resolution, remaining_daily, f"> {budget_resolution}",
                  f"daily_cap={daily_cap}; realized_loss={realized_loss_today}; reserved_open_risk={open_risk}; sub-ULP budget dust is unusable"),
        RuleCheck("account_exposure_available", remaining_exposure > 0, remaining_exposure, "> 0"),
    ]
    if rules.require_market_evidence:
        checks.extend(evidence.checks)
    failed = tuple(check for check in checks if not check.passed)
    if failed:
        return Rejection(narrative.token, narrative.direction, failed, tuple(checks))
    stop_distance = price * limits.stop_pct
    cap = limits.account_size * limits.max_position_pct
    sign = 1 if narrative.direction == "bullish" else -1
    stop = price - sign * stop_distance
    target = price + sign * stop_distance * limits.take_profit_r
    exits_ordered = stop < price < target if sign == 1 else target < price < stop
    valid_exits = all(math.isfinite(value) and value > 0 for value in (stop, target)) and exits_ordered
    if not valid_exits:
        check = RuleCheck("valid_exit_plan", False, f"stop={stop}; target={target}",
                          "positive finite exits on opposite sides of entry")
        return Rejection(narrative.token, narrative.direction, (check,), tuple(checks) + (check,))
    # Use actual rounded price distance so recorded risk matches the exit exactly.
    actual_distance = abs(price - stop)
    if actual_distance == 0:
        check = RuleCheck("representable_stop", False, actual_distance, "> 0")
        return Rejection(narrative.token, narrative.direction, (check,), tuple(checks) + (check,))
    units = min(risk_budget / actual_distance, cap / price, remaining_exposure / price)
    if not math.isfinite(units) or units <= 0:
        check = RuleCheck("representable_size", False, str(units), "positive finite units")
        return Rejection(narrative.token, narrative.direction, (check,), tuple(checks) + (check,))
    # Division can round one ULP above a cap; round units down, never widen it.
    while units * price > min(cap, remaining_exposure) or units * actual_distance > risk_budget:
        units = math.nextafter(units, 0.0)
    notional, risk_amount = units * price, units * actual_distance
    checks.extend((
        RuleCheck("risk_sizing", risk_amount <= risk_budget, risk_amount, risk_budget,
                  f"units=min({risk_budget}/{actual_distance}, {cap}/{price}, {remaining_exposure}/{price})"),
        RuleCheck("position_cap", notional <= cap, notional, cap),
        RuleCheck("gross_exposure_cap", notional <= remaining_exposure, notional, remaining_exposure),
        RuleCheck("stop_pct", True, limits.stop_pct, limits.stop_pct),
        RuleCheck("take_profit_r", True, limits.take_profit_r, limits.take_profit_r),
        RuleCheck("max_hold_hours", True, limits.max_hold_hours, limits.max_hold_hours),
    ))
    failed = tuple(check for check in checks if not check.passed)
    if failed:
        return Rejection(narrative.token, narrative.direction, failed, tuple(checks))
    return PracticePosition(narrative.token, narrative.direction, price, evidence.entry_time,
                            stop, target, as_of + timedelta(hours=limits.max_hold_hours),
                            units, notional, risk_amount, tuple(checks), as_of)
