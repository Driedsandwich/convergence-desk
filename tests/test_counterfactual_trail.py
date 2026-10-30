"""Synthetic interventions, complete input provenance and repeatable replay."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from convergence_desk.core import (PracticePosition, SourceHealth, canonical_json,
                                   counterfactuals, decision_hash, evaluate, replay,
                                   snapshot_from_json, snapshot_to_json)


def sol_report(snapshot):
    return next(report for report in counterfactuals(snapshot) if report.token == "SOL")


def test_pivotal_voices_and_quorum_sensitivity(snapshot):
    report = sol_report(snapshot)
    assert report.pivotal_voices == (("synthetic_social", "alpha"), ("synthetic_social", "beta"))
    assert "quorum_weight_up" in report.sensitive_thresholds
    assert "quorum_weight_down" not in report.sensitive_thresholds
    assert len(report.trials) == len(snapshot.voices) + 5
    gamma = next(t for t in report.trials if t.value == "synthetic_social:gamma")
    assert not gamma.flipped
    alpha = next(t for t in report.trials if t.value == "synthetic_social:alpha")
    assert "quorum_weight" in alpha.failed_rules


def test_conviction_step_changes_decision(snapshot):
    posts = tuple(replace(p, text="Buy $SOL", content_sha256="") for p in snapshot.posts[:2])
    report = sol_report(replace(snapshot, posts=posts))
    assert "min_conviction_up" in report.sensitive_thresholds
    assert "min_conviction_down" not in report.sensitive_thresholds


def test_lowering_quorum_can_turn_rejection_into_position(snapshot):
    changed = replace(snapshot, rules=replace(snapshot.rules, quorum_weight=1.6))
    report = sol_report(changed)
    trial = next(t for t in report.trials if t.change == "quorum_weight_down")
    assert not trial.baseline_accepted and trial.alternative_accepted and trial.flipped


def test_dropping_evidence_flips_contradiction_but_preserves_risk(snapshot):
    last = replace(snapshot.market_bars[-1], open=90, close=90, high=91, low=89)
    changed = replace(snapshot, market_bars=snapshot.market_bars[:-1] + (last,))
    trial = next(t for t in sol_report(changed).trials if t.change == "drop_market_evidence")
    assert trial.flipped and trial.alternative_accepted
    stopped = replace(changed, realized_loss_today=300)
    trial = next(t for t in sol_report(stopped).trials if t.change == "drop_market_evidence")
    assert not trial.flipped and not trial.alternative_accepted


def test_disappearing_candidate_is_a_rejection(snapshot):
    changed = replace(snapshot, posts=(snapshot.posts[0],), voices=(snapshot.voices[0],),
                      rules=replace(snapshot.rules, quorum_weight=0.8, min_distinct_voices=1))
    report = sol_report(changed)
    assert report.pivotal_voices == (("synthetic_social", "alpha"),)
    assert report.trials[0].failed_rules == ("no_candidate_after_intervention",)


def test_replay_has_identical_hash_and_snapshot_roundtrip(snapshot):
    encoded = snapshot_to_json(snapshot)
    first = replay(snapshot)
    second = replay(encoded)
    assert first == second
    assert first.decision_hash == second.decision_hash == decision_hash(first)
    assert first.snapshot_hash == hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    assert canonical_json(first) == canonical_json(second)
    assert snapshot_to_json(snapshot_from_json(encoded)) == encoded


def test_all_inputs_have_hash_and_source(snapshot):
    record = replay(snapshot)
    assert all(len(ref.content_sha256) == 64 and ref.source for ref in record.inputs)
    post_refs = [ref for ref in record.inputs if ref.kind == "post"]
    assert {ref.content_sha256 for ref in post_refs} == {p.content_sha256 for p in snapshot.posts}
    assert len(record.inputs) == len(snapshot.posts) + len(snapshot.voices) + len(snapshot.market_bars) + 5
    assert {ref.kind for ref in record.inputs} >= {"rules", "risk_limits", "realized_loss_today", "as_of"}


def test_modified_input_changes_snapshot_and_decision_hash(snapshot):
    first = replay(snapshot)
    changed = replay(replace(snapshot, realized_loss_today=1.0))
    assert first.snapshot_hash != changed.snapshot_hash
    assert first.decision_hash != changed.decision_hash
    changed_post = replace(snapshot.posts[0], text="Confident bearish $SOL now", content_sha256="")
    altered = replace(snapshot, posts=(changed_post,) + snapshot.posts[1:])
    assert replay(altered).decision_hash != first.decision_hash


def test_input_order_does_not_change_evaluation(snapshot):
    reordered = replace(snapshot, posts=tuple(reversed(snapshot.posts)), voices=tuple(reversed(snapshot.voices)),
                        market_bars=tuple(reversed(snapshot.market_bars)))
    assert evaluate(reordered) == evaluate(snapshot)
    assert counterfactuals(reordered) == counterfactuals(snapshot)


def test_open_positions_and_source_health_survive_json(snapshot):
    position = next(o.decision for o in evaluate(snapshot) if isinstance(o.decision, PracticePosition))
    changed = replace(snapshot, open_positions=(position,), source_health=(SourceHealth("synthetic_social", "degraded", "rate limited"),),
                      degraded_notes=("synthetic restart checkpoint restored",))
    assert replay(snapshot_to_json(changed)) == replay(changed)
    assert any(ref.kind == "open_position" for ref in replay(changed).inputs)


def test_down_voice_source_preserves_rejections_and_health(snapshot):
    voice = replace(snapshot.voices[1], source="synthetic_down")
    post = replace(snapshot.posts[1], source="synthetic_down")
    changed = replace(snapshot, voices=(snapshot.voices[0], voice, snapshot.voices[2]),
                      posts=(snapshot.posts[0], post, snapshot.posts[2]),
                      source_health=(SourceHealth("synthetic_down", "down", "429; breaker open"),))
    record = replay(changed)
    assert any("2 of 3 voices" in note for note in record.degraded_notes)
    result = next(o for o in record.outcomes if o.narrative.token == "SOL")
    assert result.narrative.total_weight == 0.8
    assert result.decision.kind == "rejection"
    all_down = replay(replace(snapshot, source_health=(SourceHealth("synthetic_social", "down"),)))
    assert {o.narrative.token for o in all_down.outcomes} == {"SOL", "BTC"}
    assert all(o.decision.kind == "rejection" for o in all_down.outcomes)
    assert any("0 of 3 voices" in note for note in all_down.degraded_notes)


def test_canonical_float_format_and_sorted_keys():
    assert canonical_json({"z": 1e-20, "a": -0.0}) == '{"a":-0.0,"z":0.00000000000000000001}'
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            canonical_json({"value": bad})


def test_replay_preserves_large_float_types_and_signed_zero(snapshot):
    bars = tuple(replace(bar, volume=bar.volume * 1e20) for bar in snapshot.market_bars)
    changed = replace(snapshot, market_bars=bars, realized_loss_today=-0.0,
                      risk_limits=replace(snapshot.risk_limits, account_size=1e20))
    assert replay(changed) == replay(snapshot_to_json(changed))
    assert isinstance(json.loads(canonical_json(1e20)), float)


def test_version_and_tampered_post_rejected(snapshot):
    envelope = json.loads(snapshot_to_json(snapshot))
    envelope["schema_version"] = 999
    with pytest.raises(ValueError, match="version"):
        snapshot_from_json(envelope)
    envelope = json.loads(snapshot_to_json(snapshot))
    envelope["snapshot"]["posts"][0]["text"] = "tampered"
    with pytest.raises(ValueError, match="content_sha256"):
        snapshot_from_json(envelope)


def test_replay_hash_stable_in_fresh_processes(snapshot):
    fixture = Path(__file__).parent / "fixtures" / "synthetic_test_engine_inputs.json"
    script = (
        "import sys; from convergence_desk.core import replay; "
        "print(replay(sys.stdin.read()).decision_hash)"
    )
    hashes = []
    for seed in ("1", "987"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-c", script], input=fixture.read_text(),
                                text=True, capture_output=True, check=True, env=env)
        hashes.append(result.stdout.strip())
    assert hashes[0] == hashes[1] == replay(snapshot).decision_hash


def test_empty_snapshot_is_a_repeatable_empty_record(snapshot):
    empty = replace(snapshot, posts=(), voices=(), market_bars=())
    record = replay(empty)
    assert record.outcomes == () and record.counterfactuals == ()
    assert replay(snapshot_to_json(empty)).decision_hash == record.decision_hash
