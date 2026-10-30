"""Shared decision path for normal runs, replay and controlled interventions."""

from dataclasses import replace
from typing import Tuple

from .converge import converge
from .decide import decide
from .evidence import check_evidence
from .extract import extract
from .models import Outcome, PracticePosition, RuleCheck, Snapshot


def health_notes(snapshot: Snapshot) -> Tuple[str, ...]:
    """Report the actual available denominator without lowering quorum."""
    down = {h.source for h in snapshot.source_health if h.state == "down"}
    available = sum(v.source not in down for v in snapshot.voices)
    notes = list(snapshot.degraded_notes)
    if down:
        notes.append(f"quorum computed over {available} of {len(snapshot.voices)} voices because source(s) {', '.join(sorted(down))} were down; thresholds unchanged")
    notes.extend(f"source {h.source} {h.state}: {h.detail}" for h in sorted(snapshot.source_health, key=lambda h: h.source)
                 if h.state != "healthy")
    selected = {(v.source, v.id) for v in snapshot.voices}
    ignored = sum((p.source, p.author_id) not in selected for p in snapshot.posts)
    if ignored:
        notes.append(f"ignored {ignored} posts from unselected voices")
    return tuple(notes)


def evaluate(snapshot: Snapshot) -> Tuple[Outcome, ...]:
    """Allocate sequentially by weight, voice count, token and direction.

    Down sources contribute neither votes nor evidence. Their mentions remain
    visible as rejected candidates. Opposing convergent directions both reject.
    """
    down = {h.source for h in snapshot.source_health if h.state == "down"}
    signals = tuple(signal for post in snapshot.posts for signal in extract(post))
    active = tuple(s for s in signals if s.post.source not in down)
    narratives = converge(active, snapshot.voices, snapshot.rules, snapshot.as_of)
    existing = {(n.token, n.direction) for n in narratives}
    all_candidates = converge(signals, snapshot.voices, snapshot.rules, snapshot.as_of)
    missing = []
    for candidate in all_candidates:
        if (candidate.token, candidate.direction) not in existing:
            checks = (RuleCheck("source_available", False, 0, ">= 1"),
                      RuleCheck("quorum_weight", 0 >= snapshot.rules.quorum_weight, 0, snapshot.rules.quorum_weight),
                      RuleCheck("min_distinct_voices", False, 0, snapshot.rules.min_distinct_voices))
            missing.append(replace(candidate, voice_weights=(), total_weight=0.0, distinct_voices=0,
                                   converged=False, checks=checks))
    narratives = tuple(narratives) + tuple(missing)
    ordered = sorted(narratives, key=lambda n: (-n.total_weight, -n.distinct_voices, n.token, n.direction))
    positions = list(snapshot.open_positions)
    outcomes = []
    for narrative in ordered:
        conflict = narrative.converged and any(n.converged and n.token == narrative.token and n.direction != narrative.direction for n in narratives)
        evidence = check_evidence(narrative, (b for b in snapshot.market_bars if b.source not in down),
                                  snapshot.rules, snapshot.as_of,
                                  (e for e in snapshot.chain_events if e.source not in down))
        decision = decide(narrative, evidence, snapshot.risk_limits, snapshot.rules, positions,
                          snapshot.realized_loss_today, snapshot.as_of, conflicting_direction=conflict)
        outcomes.append(Outcome(narrative, evidence, decision))
        if isinstance(decision, PracticePosition):
            positions.append(decision)
    return tuple(outcomes)
