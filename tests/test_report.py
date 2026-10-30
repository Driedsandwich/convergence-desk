"""Offline report checks using synthetic inputs, without recorded HTTP fixtures."""
from copy import deepcopy
from dataclasses import asdict, replace
from html import unescape
from html.parser import HTMLParser
import re

import pytest

from convergence_desk.core.extract import extract
from convergence_desk.report import render
from convergence_desk.runtime import make_record, plain


@pytest.fixture
def report_snapshot(snapshot):
    posts = list(snapshot.posts)
    # A heavier neutral cluster must never bury the directional conclusions.
    for voice in snapshot.voices:
        for token_text in ('Discussing $BTC.', 'Confident buy $ETH.'):
            posts.append(replace(snapshot.posts[0], author_id=voice.id, author_label=voice.label,
                                 uri=f'synthetic://{voice.id}/{len(posts)}',
                                 text=token_text, content_sha256=''))
    rows = []
    for post in posts:
        features = []
        for signal in extract(post):
            feature = asdict(signal)
            del feature['post']
            features.append(feature)
        rows.append(dict(author_id=post.author_id, author_label=post.author_label,
                         uri=post.uri, created_at=post.created_at, excerpt=post.text,
                         features=features))
    return plain(dict(
        schema_version=1, runtime_version='1', as_of=snapshot.as_of,
        run_path='runs/synthetic-report-test',
        voices=[dict(voice_id=v.id, label=v.label, trust_weight=v.trust_weight)
                for v in snapshot.voices],
        posts=rows, rules=asdict(snapshot.rules), risk_limits=asdict(snapshot.risk_limits),
        source_rules={'cross_venue_max_spread': .02},
        market_bars=[asdict(replace(b, source=venue, end=b.available_at)) for venue in ('coinbase', 'kraken')
                     for b in snapshot.market_bars],
        chain_events=[], source_health=[dict(source='synthetic_rpc', state='down', detail='test outage')],
        provenance=[dict(source='synthetic', endpoint='https://example.test/input',
                         fetch_time=snapshot.as_of, http_status=200, response_sha256='c'*64)],
        liquidity=dict(available=True, first_block=123, last_block=142, confirmations=12,
                       large_transfer_threshold=1000000,
                       scope='Market-wide stablecoin liquidity; not a token buy/sell signal.',
                       tokens={'USDC': dict(mint_total=42, burn_total=0,
                                            large_transfer_count=2, large_transfer_total=3000000)}),
        coverage={'unsupported_tokens': ['SYNTHETIC']}, post_counts={'synthetic': len(rows)},
        recorded_test_fixture=True,
    ))


def section(html, anchor):
    return html.split(f'<section id="{anchor}">', 1)[1].split('</section>', 1)[0]


def cards(html):
    return re.findall(r'<article class="conclusion">(.*?)</article>', html, re.S)


def text(html):
    return unescape(re.sub('<[^>]+>', '', html))


def sol(record):
    return next(o for o in record['outcomes'] if o['narrative']['token'] == 'SOL')


def test_conclusions_and_why_order_preserve_all_candidates(report_snapshot):
    record = make_record(report_snapshot)
    before = deepcopy((report_snapshot, record))
    html = render(report_snapshot, record)
    assert (report_snapshot, record) == before
    headings = re.findall(r'<h2>(.*?)</h2>', html)
    assert headings == ['What the agent concluded', 'Decision summary', 'Why', 'Cause and effect',
                        'Rejection ledger', 'Source health and provenance', 'Replay']
    assert [re.search(r'<h3>(.*?)</h3>', card)[1] for card in cards(html)] == ['ETH bullish', 'SOL bullish']
    why = section(html, 'why')
    assert why.index('ETH bullish') < why.index('SOL bullish') < why.index('BTC bullish') < why.index('BTC neutral')
    assert why.count('<details class="neutral-mentions"><summary>Neutral mentions (no direction)</summary>') == 1
    for outcome in record['outcomes']:
        n = outcome['narrative']
        assert why.count(f"{n['token']} {n['direction']} —") == 1
        for member in n['members']:
            assert member['uri'] in why
    for anchor in ('conclusions', 'decision-summary', 'why', 'cause-and-effect', 'rejections', 'sources', 'replay'):
        assert f'href="#{anchor}"' in html
    assert record['decision_hash'] in html and record['snapshot_hash'] in html
    assert 'python3 -m convergence_desk.cli replay runs/synthetic-report-test/snapshot.json' in html
    assert 'degraded source' in section(html, 'sources')
    assert 'https://example.test/input' in html and 'c'*64 in html
    assert 'SYNTHETIC' in why and 'All intervention values and results' in html


def test_position_card_and_voice_removal_flip(report_snapshot):
    record = make_record(report_snapshot)
    outcome = sol(record)
    assert outcome['decision']['kind'] == 'practice_position'
    card = text(cards(render(report_snapshot, record))[1])
    assert 'Synthetic Alpha (alpha), Synthetic Beta (beta) converged: 2 qualifying voices' in card
    assert 'weight 1.5 against quorum 1.5' in card
    assert 'On coinbase, the window return was +10% and volume z-score was' in card
    assert 'On kraken, the window return was +10%' in card
    assert 'Cross-venue status was agreement' in card
    assert 'minted 42 and burned 0' in card
    assert '2 transfers above 1,000,000 totaled 3,000,000 USDC' in card
    assert 'at 110 USD' in card and 'stop 104.5 USD, target 121 USD' in card
    assert '1,000 USD' in card and outcome['decision']['time_stop'] in card
    assert 'Failed rules: none.' in card
    assert 'What would change this decision:' in card
    assert 'Without Synthetic Alpha (alpha), the quorum would fail and the practice position would be rejected.' in card
    assert 'With quorum_weight set to 1.6, the practice position would be rejected.' in card


def test_market_bypass_flip_and_exact_failed_values(report_snapshot):
    for bar in report_snapshot['market_bars']:
        if bar['close'] == 110:
            bar.update(open=90, high=91, low=89, close=90)
    record = make_record(report_snapshot)
    card = text(cards(render(report_snapshot, record))[1])
    assert 'the evidence contradicted this direction' in card
    assert 'This narrative was rejected; no practice position opened.' in card
    assert 'Without the market-confirmation step, a practice position would have opened.' in card
    for failure in sol(record)['decision']['failed_rules']:
        assert f"{failure['rule']}: actual {failure['actual']}; required {failure['expected']}." in card


def test_conflicting_directions_and_no_flipped_trial(report_snapshot):
    for post in list(report_snapshot['posts'][:2]):
        bearish = deepcopy(post)
        bearish['uri'] += '/bearish'
        for feature in bearish['features']:
            feature['direction'] = 'bearish'
            feature['sentiment']['value'] = -1
        report_snapshot['posts'].append(bearish)
    record = make_record(report_snapshot)
    html = render(report_snapshot, record)
    sol_cards = [text(c) for c in cards(html) if '<h3>SOL ' in c]
    assert len(sol_cards) == 2
    for card in sol_cards:
        assert 'A converged narrative in the opposite direction conflicted with this one.' in card
        assert 'no_direction_conflict: actual True; required False.' in card
        assert 'No tested counterfactual trial flipped this decision.' in card


@pytest.mark.parametrize('missing', ['market', 'liquidity', 'labels', 'quorum', 'position', 'trials'])
def test_missing_card_fields_are_explicit(report_snapshot, missing):
    record = make_record(report_snapshot)
    outcome = sol(record)
    if missing == 'market':
        outcome['cross_venue'] = {'venues': ['coinbase'], 'venue_evidence': {'coinbase': {}}}
        outcome['evidence'] = {}
    elif missing == 'liquidity':
        record['liquidity'] = {'available': False}
    elif missing == 'labels':
        report_snapshot['voices'] = []
    elif missing == 'quorum':
        outcome['narrative']['checks'] = []
    elif missing == 'position':
        for key in ('entry_price', 'units', 'notional', 'stop', 'take_profit', 'time_stop', 'risk_amount'):
            del outcome['decision'][key]
    elif missing == 'trials':
        record['counterfactuals'] = []
    card = text(cards(render(report_snapshot, record))[1])
    assert 'not available' in card
    assert 'None' not in card
    if missing == 'trials':
        assert 'No tested counterfactual trial flipped' not in card
    if missing == 'market':
        assert 'On coinbase, the window return was not available and volume z-score was not available' in card


def test_empty_conclusions(report_snapshot):
    report_snapshot['posts'] = []
    record = make_record(report_snapshot)
    html = render(report_snapshot, record)
    assert not cards(html)
    assert 'No directional narrative converged in this record.' in section(html, 'conclusions')


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_self_contained_html_and_escaped_record_text(report_snapshot):
    report_snapshot['voices'][0]['label'] = '<script src="https://example.test/evil.js">&'
    record = make_record(report_snapshot)
    record['liquidity']['scope'] = '<link rel="stylesheet" href="https://example.test/evil.css">'
    html = render(report_snapshot, record)
    parser = Resources()
    parser.feed(html)
    assert not [tag for tag, attrs in parser.tags if tag in ('script', 'link', 'iframe')]
    assert not re.search(r'@import|url\s*\(', html, re.I)
    assert '&lt;script src=' in html and '&lt;link rel=' in html
    assert '<style>' in html and 'position:sticky' in html and '@media print' in html
