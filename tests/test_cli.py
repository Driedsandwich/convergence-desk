"""Recorded end-to-end runs, immutable replay and deliberate failures."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import pytest
from convergence_desk import cli
from convergence_desk.runtime import evaluate, inputs, venue_evidence
from convergence_desk.core.converge import converge
from convergence_desk.sources.common import dt

FIXTURES=Path(__file__).parent/'fixtures'/'recorded'


@pytest.fixture(scope='module')
def recorded_run(tmp_path_factory):
    out=tmp_path_factory.mktemp('recorded_run')
    # A module fixture cannot use the per-test network guard; explicitly make
    # urlopen fail as a second line of defense, including in subprocess-free CLI.
    import urllib.request
    original=urllib.request.urlopen
    def forbidden(*args,**kwargs):
        raise AssertionError('recorded E2E attempted network')
    urllib.request.urlopen=forbidden
    try:
        code=cli.main(['run','--hours','48','--recordings',str(FIXTURES),'--out',str(out)])
    finally:
        urllib.request.urlopen=original
    return out,code


def test_cli_recordings_and_replay(recorded_run,capsys):
    out,code=recorded_run
    # The recorded Coinbase TRX product returned 404 (pair not listed), then Binance succeeded.
    # An unlisted pair is not a source outage, so the run completes without degradation.
    assert code==0
    snapshot=json.loads((out/'snapshot.json').read_text())
    record=json.loads((out/'record.json').read_text())
    assert record['counts']['posts']==434
    assert record['counts']['converged_narratives']==3
    assert record['counts']['rejections']==32
    assert record['counts']['practice_positions']==0
    assert all(len(p['excerpt'])<=140 and 'text' not in p for p in snapshot['posts'])
    assert all(p['content_sha256'] and p['title_sha256'] for p in snapshot['posts'])
    assert cli.main(['replay',str(out/'snapshot.json')])==0
    assert '"replay_match": true' in capsys.readouterr().out
    html=(out/'report.html').read_text()
    sections=['Decision summary','Why','Cause and effect','Rejection ledger','Source health and provenance','Replay']
    assert [html.index('<h2>'+s+'</h2>') for s in sections]==sorted(html.index('<h2>'+s+'</h2>') for s in sections)
    assert '<script' not in html and 'RECORDED TEST FIXTURES' in html
    assert record['decision_hash'] in html


def test_replay_detects_changed_inputs(recorded_run,tmp_path,capsys):
    out,_=recorded_run
    snapshot=json.loads((out/'snapshot.json').read_text())
    snapshot['risk_limits']['account_size']+=100
    target=tmp_path/'changed.json'; target.write_text(json.dumps(snapshot))
    assert cli.main(['replay',str(target)])==1
    assert '"replay_match": false' in capsys.readouterr().out


def test_chaos_continues_and_replays(tmp_path,capsys):
    out=tmp_path/'chaos'
    assert cli.main(['chaos','--kill','publicnode','--recordings',str(FIXTURES),'--out',str(out)])==2
    record=json.loads((out/'record.json').read_text())
    assert record['counts']['posts']==434
    chain=next(h for h in record['source_health'] if h['source']=='publicnode')
    assert chain['state']=='down' and 'deliberate chaos failure' in chain['detail']
    assert record['liquidity']['available'] is False
    assert cli.main(['replay',str(out/'snapshot.json')])==0


def test_exit_zero_when_all_requested_sources_work(tmp_path):
    manifest=json.loads((FIXTURES/'manifest.json').read_text())
    # Coindesk's recorded mentions have no TRX; use a selected public voice.
    voices=tmp_path/'voices.json'
    voices.write_text(json.dumps({'voices':[manifest['voices'][0]]}))
    out=tmp_path/'healthy'
    assert cli.main(['run','--voices',str(voices),'--recordings',str(FIXTURES),'--out',str(out)])==0


def test_invalid_configuration_fails(tmp_path):
    assert cli.main(['run','--hours','500','--out',str(tmp_path/'invalid')])==1
    assert not (tmp_path/'invalid'/'snapshot.json').exists()


def test_completed_resume_is_idempotent(recorded_run):
    out,code=recorded_run
    before=(out/'record.json').read_bytes()
    assert cli.main(['run','--hours','48','--recordings',str(FIXTURES),'--out',str(out)])==code
    assert (out/'record.json').read_bytes()==before


def test_interrupted_commit_resumes_without_fetch(recorded_run,tmp_path,monkeypatch):
    out,_=recorded_run
    import shutil
    target=tmp_path/'interrupted'
    shutil.copytree(out,target)
    (target/'record.json').unlink()
    def forbidden(*a,**k):
        raise AssertionError('resume should not fetch')
    monkeypatch.setattr(cli.Client,'fetch',forbidden)
    assert cli.main(['run','--hours','48','--recordings',str(FIXTURES),'--out',str(target)])==0
    assert json.loads((target/'record.json').read_text())['decision_hash']==json.loads((out/'record.json').read_text())['decision_hash']


def test_venue_disagreement_is_an_explicit_failed_rule(recorded_run):
    out,_=recorded_run
    snapshot=json.loads((out/'snapshot.json').read_text())
    rules,voices,signals,bars=inputs(snapshot)
    narrative=next(n for n in converge(signals,voices,rules,dt(snapshot['as_of'])) if n.token=='BTC' and n.direction=='bearish')
    altered=tuple(replace(b,open=b.open*1.2,high=b.high*1.2,low=b.low*1.2,close=b.close*1.2) if b.source=='kraken' and b.symbol=='BTC' else b for b in bars)
    evidence,details=venue_evidence(narrative,altered,rules,dt(snapshot['as_of']),.02)
    assert details['status']=='disagreement'
    assert evidence.status=='contradict'
    assert any(c.rule=='cross_venue_agreement' and not c.passed for c in evidence.checks)


def test_marketwide_liquidity_does_not_vote(recorded_run):
    out,_=recorded_run
    snapshot=json.loads((out/'snapshot.json').read_text())
    baseline,_=evaluate(snapshot)
    snapshot['chain_events']=[]
    snapshot['liquidity']={'available':False}
    alternative,_=evaluate(snapshot)
    assert [o.decision for o in baseline]==[o.decision for o in alternative]
