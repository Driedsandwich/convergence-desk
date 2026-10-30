"""Synthetic language and voting boundaries, including ambiguous ticker words."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import hashlib

import pytest

from convergence_desk.core import Post, Voice, converge, extract


def changed_post(snapshot, text):
    return replace(snapshot.posts[0], text=text, content_sha256="")


def signals(snapshot):
    return tuple(signal for post in snapshot.posts for signal in extract(post))


def sol(snapshot):
    return next(n for n in converge(signals(snapshot), snapshot.voices, snapshot.rules, snapshot.as_of) if n.token == "SOL")


def test_extraction_scores_have_fired_words(snapshot):
    signal = extract(changed_post(snapshot, "Definitely bullish $SOL, buy now!"))[0]
    assert signal.token == "SOL" and signal.direction == "bullish"
    assert signal.sentiment.value == 0.8
    assert signal.conviction.value == 0.65
    assert signal.urgency.value == 0.25
    assert signal.token_rules == ("cashtag:$SOL",)
    assert "sentiment:bullish:+0.40" in signal.sentiment.fired
    assert "conviction:definitely:+0.15" in signal.conviction.fired
    assert "urgency:now:+0.25" in signal.urgency.fired


def test_hedges_and_negation(snapshot):
    signal = extract(changed_post(snapshot, "Maybe Solana is not bullish, might crash soon."))[0]
    assert signal.direction == "bearish"
    assert signal.sentiment.value == -0.8
    assert signal.conviction.value == 0.1
    assert "sentiment:negated:bullish:-0.40" in signal.sentiment.fired
    assert "conviction:maybe:-0.20" in signal.conviction.fired


def test_per_clause_token_direction(snapshot):
    result = extract(changed_post(snapshot, "Bullish $SOL but bearish $ETH. Bitcoin is interesting."))
    assert [(s.token, s.direction) for s in result] == [("SOL", "bullish"), ("ETH", "bearish"), ("BTC", "neutral")]
    assert result[-1].sentiment.fired == ("sentiment:no_direction_words:0",)


def test_common_words_require_cashtags(snapshot):
    assert extract(changed_post(snapshot, "ONE GAS near the LINK, ETC.")) == ()
    assert {s.token for s in extract(changed_post(snapshot, "Buy $ONE $GAS $NEAR"))} == {"ONE", "GAS", "NEAR"}


def test_long_names_win_and_unknown_cashtags_allowed(snapshot):
    result = extract(changed_post(snapshot, "Buy Bitcoin Cash and Ethereum Classic and $NEWCOIN."))
    assert {s.token for s in result} == {"BCH", "ETC", "NEWCOIN"}


def test_no_substring_hits(snapshot):
    assert extract(changed_post(snapshot, "solid dogged ethically unison")) == ()


def test_scores_clamp_with_traces(snapshot):
    signal = extract(changed_post(snapshot, "$SOL buy bullish long breakout definitely confident will guaranteed now today breaking urgent soon"))[0]
    assert (signal.sentiment.value, signal.conviction.value, signal.urgency.value) == (1.0, 1.0, 1.0)
    assert len(signal.sentiment.fired) == 4


def test_content_digest_and_immutable_post(snapshot):
    post = snapshot.posts[0]
    assert post.content_sha256 == hashlib.sha256(post.text.encode()).hexdigest()
    with pytest.raises(ValueError, match="content_sha256"):
        replace(post, content_sha256="bad")
    with pytest.raises(FrozenInstanceError):
        post.text = "changed"
    with pytest.raises(ValueError, match="UTC"):
        replace(post, created_at=post.created_at.replace(tzinfo=None))


@pytest.mark.parametrize("quorum,converged", [(1.5, True), (1.500001, False), (1.499999, True)])
def test_quorum_boundary(snapshot, quorum, converged):
    candidate = sol(replace(snapshot, rules=replace(snapshot.rules, quorum_weight=quorum)))
    assert candidate.total_weight == 1.5
    assert candidate.converged is converged


def test_repeated_posts_count_voice_once(snapshot):
    copies = tuple(replace(snapshot.posts[0], uri=f"synthetic://repeat/{i}") for i in range(10))
    candidate = sol(replace(snapshot, posts=copies))
    assert candidate.total_weight == 0.8
    assert candidate.distinct_voices == 1
    assert not candidate.converged


def test_conviction_threshold_inclusive(snapshot):
    assert sol(replace(snapshot, rules=replace(snapshot.rules, min_conviction=0.65))).converged
    candidate = sol(replace(snapshot, rules=replace(snapshot.rules, min_conviction=0.650001)))
    assert not candidate.converged and candidate.distinct_voices == 0
    assert len(candidate.members) == 2


def test_window_includes_edges_excludes_future_and_old(snapshot):
    start = snapshot.as_of - timedelta(hours=24)
    posts = (replace(snapshot.posts[0], created_at=start), replace(snapshot.posts[1], created_at=snapshot.as_of))
    assert sol(replace(snapshot, posts=posts)).converged
    for timestamp in (start - timedelta(microseconds=1), snapshot.as_of + timedelta(microseconds=1)):
        assert not sol(replace(snapshot, posts=(replace(posts[0], created_at=timestamp), posts[1]))).converged


def test_unselected_and_wrong_source_voice_cannot_vote(snapshot):
    altered = replace(snapshot.posts[0], source="synthetic_spoof")
    assert not sol(replace(snapshot, posts=(altered, snapshot.posts[1]))).converged


def test_voice_limits_and_distinct_sources(snapshot):
    with pytest.raises(ValueError, match="20"):
        replace(snapshot, voices=tuple(Voice(str(i), str(i), "synthetic", 0.5) for i in range(21)))
    with pytest.raises(ValueError, match="unique"):
        replace(snapshot, voices=(snapshot.voices[0], snapshot.voices[0]))
    with pytest.raises(ValueError):
        Voice("bad", "bad", "synthetic", 1.1)


def test_decimal_weight_boundary(snapshot):
    voices = (replace(snapshot.voices[0], trust_weight=0.7), replace(snapshot.voices[1], trust_weight=0.1))
    candidate = sol(replace(snapshot, voices=voices, rules=replace(snapshot.rules, quorum_weight=0.8)))
    assert candidate.converged
