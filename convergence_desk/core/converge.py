"""Windowed, distinct-voice voting; frequency never increases a voice's weight."""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Iterable, Tuple

from .models import Narrative, RuleCheck, Rules, Signal, Voice, utc


def converge(signals: Iterable[Signal], voices: Iterable[Voice], rules: Rules,
             as_of: datetime) -> Tuple[Narrative, ...]:
    """Keep all mentioned candidates, including neutral or nonconvergent ones.

    Only members meeting min_conviction contribute; trust is summed once per
    (source, author). Boundary times and both quorum thresholds are inclusive.
    """
    utc(as_of)
    selected = {(v.source, v.id): v for v in voices}
    start = as_of - timedelta(hours=rules.window_hours)
    groups = defaultdict(list)
    for signal in signals:
        post = signal.post
        if (post.source, post.author_id) in selected and start <= post.created_at <= as_of:
            groups[(signal.token, signal.direction)].append(signal)
    narratives = []
    for (token, direction), members in sorted(groups.items()):
        members.sort(key=lambda s: (s.post.created_at, s.post.source, s.post.author_id,
                                    s.post.uri, s.conviction.value, s.token_rules))
        voters = sorted({(s.post.source, s.post.author_id) for s in members
                         if s.conviction.value >= rules.min_conviction})
        weights = tuple((source, author, selected[(source, author)].trust_weight)
                        for source, author in voters)
        # Decimal text preserves intended boundaries such as 0.7 + 0.1 == 0.8.
        with localcontext() as context:
            context.prec = 400
            exact_total = sum((Decimal(str(weight)) for _, _, weight in weights), Decimal(0))
        total = float(exact_total)
        checks = (
            RuleCheck("directional_narrative", direction != "neutral", direction, "bullish or bearish"),
            RuleCheck("min_conviction", bool(voters), max(s.conviction.value for s in members), rules.min_conviction,
                      "only qualifying voices vote; each voice counted once"),
            RuleCheck("quorum_weight", exact_total >= Decimal(str(rules.quorum_weight)), total, rules.quorum_weight),
            RuleCheck("min_distinct_voices", len(voters) >= rules.min_distinct_voices, len(voters), rules.min_distinct_voices),
        )
        narratives.append(Narrative(token, direction, tuple(members), members[0].post.created_at,
                                    members[-1].post.created_at, weights, total, len(voters),
                                    all(check.passed for check in checks), checks))
    return tuple(narratives)
