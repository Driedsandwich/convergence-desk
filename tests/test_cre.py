"""SYNTHETIC ONLY: CRE export/import and Python oracle; no recorded/live inputs."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from convergence_desk import cli
from convergence_desk.cre import THRESHOLDS, workflow_config
from convergence_desk.core.extract import extract
from convergence_desk.core.models import MarketBar, Rules
from convergence_desk.core.trail import content_hash
from convergence_desk.runtime import make_record, plain, venue_evidence
from convergence_desk.report import render


@pytest.fixture
def synthetic_run(tmp_path, snapshot):
    posts = []
    for post in snapshot.posts:
        features = []
        for signal in extract(post):
            feature = asdict(signal)
            del feature['post']
            features.append(feature)
        posts.append(dict(author_id=post.author_id, author_label=post.author_label, uri=post.uri,
                          created_at=post.created_at, excerpt=post.text, features=features))
    data = plain(dict(schema_version=1, runtime_version='1', as_of=snapshot.as_of,
        run_path=str(tmp_path), voices=[dict(voice_id=v.id, label=v.label, trust_weight=v.trust_weight) for v in snapshot.voices],
        posts=posts, rules=asdict(snapshot.rules), risk_limits=asdict(snapshot.risk_limits),
        source_rules={'cross_venue_max_spread': .02},
        market_bars=[asdict(replace(b, source=v, end=b.available_at)) for v in ('coinbase', 'kraken') for b in snapshot.market_bars],
        chain_events=[], source_health=[], provenance=[], liquidity={'available': False},
        coverage={'unsupported_tokens': []}, post_counts={'synthetic': len(posts)}, recorded_test_fixture=True))
    record = make_record(data)
    data['expected_decision_hash'] = record['decision_hash']
    cli.write_json(tmp_path / 'snapshot.json', data)
    cli.write_json(tmp_path / 'record.json', record)
    (tmp_path / 'report.html').write_text(render(data, record))
    return tmp_path


def signed(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return {**payload, 'sha256': hashlib.sha256(raw.encode()).hexdigest()}


def synthetic_result(run):
    c = workflow_config(run / 'record.json')
    payload = {k: v for k, v in c.items() if k not in THRESHOLDS}
    payload.update(check='chainlink-cre-market-evidence',
        thresholds={k: str(c[k]) for k in THRESHOLDS},
        observed_at=c['window_end'], verdict='confirm', cross_venue_status='agreement',
        spread='0', same_return_direction=True, common_completed_endpoint=c['window_end'],
        venues={v: dict(return_fraction='0.1', close='110', volume_z='2',
                       anchor_at=c['window_start'], endpoint_at=c['window_end'], fresh=True,
                       verdict='confirm') for v in ('coinbase', 'kraken')},
        onchain=dict(chain='ethereum-mainnet', contract='0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                     function='totalSupply()', value='123000000', decimals='6',
                     block_reference='finalized', read_at=c['window_end'],
                     scope='SYNTHETIC invented value, never a live observation.'))
    return signed(payload)


def test_config_uses_run_window_thresholds_and_top_converged(synthetic_run, monkeypatch):
    monkeypatch.chdir(synthetic_run)
    assert cli.main(['cre-config', 'record.json']) == 0
    c = json.loads(Path('cre/config.json').read_text())
    assert (c['token'], c['direction'], c['synthetic_for_tests']) == ('SOL', 'bullish', True)
    assert c['window_start'] == '2026-01-01T12:00:00Z'
    assert c['market_min_return'] == .01 and c['cross_venue_max_spread'] == .02
    assert c['volume_lookback'] == 5
    assert cli.main(['cre-config', 'record.json', '--out', 'record.json']) == 1


def test_ranking_overrides_and_no_convergence(synthetic_run):
    record = json.loads((synthetic_run / 'record.json').read_text())
    snapshot = json.loads((synthetic_run / 'snapshot.json').read_text())
    snapshot['rules']['market_min_return'] = .025
    snapshot['source_rules']['cross_venue_max_spread'] = .015
    cli.write_json(synthetic_run / 'snapshot.json', snapshot)
    record['snapshot_hash'] = content_hash({k: v for k, v in snapshot.items() if k != 'expected_decision_hash'})
    n = next(o['narrative'] for o in record['outcomes'] if o['narrative']['converged'])
    heavier = deepcopy(n); heavier.update(token='ETH', total_weight=2.0)
    record['outcomes'].append({'narrative': heavier})
    def save():
        record['decision_hash'] = content_hash({k: v for k, v in record.items() if k != 'decision_hash'})
        cli.write_json(synthetic_run / 'record.json', record)
    save()
    c = workflow_config(synthetic_run / 'record.json')
    assert c['token'] == 'ETH' and c['market_min_return'] == .025 and c['cross_venue_max_spread'] == .015
    for o in record['outcomes']:
        o['narrative']['converged'] = False
    save()
    out = synthetic_run / 'not-created.json'
    assert cli.main(['cre-config', str(synthetic_run / 'record.json'), '--out', str(out)]) == 1
    assert not out.exists()


def test_attach_preserves_decision_replay_and_is_idempotent(synthetic_run):
    before = {name: (synthetic_run / name).read_bytes() for name in ('record.json', 'snapshot.json')}
    result = synthetic_result(synthetic_run)
    path = synthetic_run / 'simulate_output.json'
    path.write_text(json.dumps(result, indent=2))
    args = ['cre-attach', str(synthetic_run), str(path)]
    assert cli.main(args) == 0
    assert (synthetic_run / 'cre_result.json').read_bytes() == path.read_bytes()
    html = (synthetic_run / 'report.html').read_text()
    assert 'Chainlink CRE check' in html and 'SYNTHETIC TEST INPUTS' in html
    assert 'original decision is unchanged' in html
    assert cli.main(args) == 0
    assert (synthetic_run / 'report.html').read_text() == html
    assert all((synthetic_run / name).read_bytes() == value for name, value in before.items())
    assert cli.main(['replay', str(synthetic_run / 'snapshot.json')]) == 0


@pytest.mark.parametrize('change,resign', [
    (lambda x: x.update(verdict='contradict'), False),
    (lambda x: x.update(record_decision_hash='b' * 64), True),
    (lambda x: x.update(token='BTC'), True),
    (lambda x: x.update(window_start='2026-01-01T00:00:00Z'), True),
    (lambda x: x['thresholds'].update(market_min_return='0.9'), True),
    (lambda x: x['onchain'].update(value='NaN'), True),
    (lambda x: x.update(verdict='<script>alert(1)</script>'), True),
])
def test_invalid_attachment_is_rejected_before_writes(synthetic_run, change, resign):
    result = synthetic_result(synthetic_run)
    change(result)
    if resign:
        result = signed({k: v for k, v in result.items() if k != 'sha256'})
    path = synthetic_run / 'bad.json'; path.write_text(json.dumps(result))
    before = (synthetic_run / 'report.html').read_bytes()
    assert cli.main(['cre-attach', str(synthetic_run), str(path)]) == 1
    assert not (synthetic_run / 'cre_result.json').exists()
    assert (synthetic_run / 'report.html').read_bytes() == before


def test_extract_cli_result_and_reject_failed_simulation(synthetic_run):
    extract_result = runpy.run_path(str(Path(__file__).parents[1] / 'cre/extract_result.py'))['extract']
    result = synthetic_result(synthetic_run)
    log = 'Workflow compiled\nWorkflow Simulation Result:\n' + json.dumps(json.dumps(result)) + '\nExecution finished'
    assert extract_result(log) == result
    with pytest.raises(ValueError):
        extract_result('Authentication required: not logged in')


CASES = json.loads((Path(__file__).parent / 'fixtures/synthetic_cre_cases.json').read_text())['cases']


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_typescript_fixture_expected_values_match_python(case):
    c = case['config']
    end, start = datetime.fromisoformat(c['window_end']), datetime.fromisoformat(c['window_start'])
    rules = Rules(window_hours=(end - start).total_seconds()/3600,
                  **{k: c[k] for k in THRESHOLDS if k != 'cross_venue_max_spread'})
    bars = [MarketBar(c['token'], datetime.fromtimestamp(b['start']/1000, timezone.utc),
                      b['close'], b['close'], b['close'], b['close'], b['volume'], venue,
                      datetime.fromtimestamp(b['end']/1000, timezone.utc))
            for venue in ('coinbase', 'kraken') for b in case[venue]]
    e, d = venue_evidence(SimpleNamespace(token=c['token'], direction=c['direction']), bars, rules, end, c['cross_venue_max_spread'])
    assert e.status == case['expected']['verdict']
    assert d['status'] == case['expected']['cross_venue_status']
    assert d['relative_close_spread'] == case['expected']['spread']
    for venue in ('coinbase', 'kraken'):
        assert d['venue_evidence'].get(venue, {}).get('return_fraction') == case['expected']['returns'][venue]
