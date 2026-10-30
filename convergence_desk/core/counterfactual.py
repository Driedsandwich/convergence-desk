"""Controlled interventions re-use the complete deterministic decision path."""

from dataclasses import replace
from typing import Optional, Tuple

from .models import (CounterfactualReport, CounterfactualTrial, Outcome,
                     PracticePosition, Rejection, Snapshot)
from .pipeline import evaluate


def counterfactuals(snapshot: Snapshot, baseline: Optional[Tuple[Outcome, ...]] = None) -> Tuple[CounterfactualReport, ...]:
    """A flip means acceptance changes, including a candidate disappearing.

    Portfolio allocation is rerun too. Disabling confirmation still requires a
    fresh entry price and every risk constraint; it cannot invent an entry.
    """
    baseline = evaluate(snapshot) if baseline is None else baseline
    variants = []
    for voice in sorted(snapshot.voices, key=lambda v: (v.source, v.id)):
        remaining = tuple(v for v in snapshot.voices if (v.source, v.id) != (voice.source, voice.id))
        variants.append(("leave_out_voice", voice.source + ":" + voice.id,
                         replace(snapshot, voices=remaining), (voice.source, voice.id)))
    for name, step, minimum, maximum in (("quorum_weight", snapshot.rules.quorum_step, 0.0, None),
                                         ("min_conviction", snapshot.rules.conviction_step, 0.0, 1.0)):
        for label, sign in (("down", -1), ("up", 1)):
            value = max(minimum, round(getattr(snapshot.rules, name) + sign * step, 10))
            if maximum is not None:
                value = min(maximum, value)
            variants.append((name + "_" + label, value,
                             replace(snapshot, rules=replace(snapshot.rules, **{name: value})), None))
    variants.append(("drop_market_evidence", "confirmation disabled",
                     replace(snapshot, rules=replace(snapshot.rules, require_market_evidence=False)), None))
    alternatives = [(change, value, {(o.narrative.token, o.narrative.direction): o for o in evaluate(variant)}, voice)
                    for change, value, variant, voice in variants]
    reports = []
    for outcome in baseline:
        key = (outcome.narrative.token, outcome.narrative.direction)
        accepted = isinstance(outcome.decision, PracticePosition)
        trials, pivotal, sensitive = [], [], []
        for change, value, alternatives_by_key, voice in alternatives:
            alternative = alternatives_by_key.get(key)
            alternative_accepted = alternative is not None and isinstance(alternative.decision, PracticePosition)
            if alternative is None:
                failures = ("no_candidate_after_intervention",)
            elif isinstance(alternative.decision, Rejection):
                failures = tuple(check.rule for check in alternative.decision.failed_rules)
            else:
                failures = ()
            flipped = accepted != alternative_accepted
            trials.append(CounterfactualTrial(change, value, accepted, alternative_accepted, flipped, failures))
            if flipped and voice is not None:
                pivotal.append(voice)
            if flipped and change.startswith(("quorum_weight_", "min_conviction_")):
                sensitive.append(change)
        reports.append(CounterfactualReport(*key, tuple(pivotal), tuple(sensitive), tuple(trials)))
    return tuple(reports)
