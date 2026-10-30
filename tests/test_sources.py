"""Adapter contracts against captured, prose-redacted HTTP responses."""
from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from convergence_desk.sources import rss, bluesky, coinbase, kraken, binance, coingecko, publicnode
from convergence_desk.sources.common import Client, dt
from convergence_desk.core.models import Post, MarketBar, ChainEvent
from convergence_desk.core.resilience import RetryableError, CircuitOpenError

FIXTURES = Path(__file__).parent/'fixtures'/'recorded'
MANIFEST = json.loads((FIXTURES/'manifest.json').read_text())
AS_OF = dt(MANIFEST['as_of'])
START = (AS_OF-timedelta(hours=51)).replace(minute=0,second=0,microsecond=0)


@pytest.fixture
def client(tmp_path):
    return Client(tmp_path/'checkpoint.json',recordings=FIXTURES)


@pytest.mark.parametrize('voice', MANIFEST['voices'], ids=lambda v:v['voice_id'])
def test_recorded_rss(client, voice):
    result = rss.fetch(client,voice,AS_OF-timedelta(hours=48),AS_OF)
    assert result.items
    assert all(isinstance(p,Post) and len(p.text)<=140 for p in result.items)
    assert len(result.items)==len(result.provenance)
    for reference in result.provenance:
        assert reference['http_status']==200
        assert len(reference['content_sha256'])==64
        assert len(reference['response_sha256'])==64
        assert reference['endpoint']==voice['rss']
    # No prose survives the fixture redaction, but real recorded features do.
    assert all(not p.text for p in result.items)


def test_original_bluesky_and_cross_channel_identity(client):
    voice=next(v for v in MANIFEST['voices'] if v.get('bluesky'))
    social=bluesky.fetch(client,voice,AS_OF-timedelta(hours=48),AS_OF)
    publisher=rss.fetch(client,voice,AS_OF-timedelta(hours=48),AS_OF)
    assert len(social.items)==37
    assert {(p.source,p.author_id) for p in social.items+publisher.items}=={('voices','decrypt')}
    assert all(row['author']=='decrypt.co' for row in social.metadata.values())


@pytest.mark.parametrize('adapter,symbol',[(coinbase,'BTC'),(kraken,'BTC'),(binance,'TRX'),(coingecko,'ETH')])
def test_recorded_market_columns_and_completed_only(client,adapter,symbol):
    result=adapter.fetch(client,symbol,START,AS_OF)
    assert result.items and len(result.items)==len(result.provenance)
    assert all(isinstance(b,MarketBar) and b.end<=AS_OF and b.high>=b.close>=b.low for b in result.items)
    original=next(json.loads(p.read_text()) for p in FIXTURES.glob('*.json')
                  if json.loads(p.read_text()).get('endpoint')==result.provenance[0]['endpoint'])
    raw=json.loads(original['body'])
    first=result.items[0]
    if adapter==coinbase:
        row=next(r for r in raw if r[0]==int(first.start.timestamp()))
        assert (first.low,first.high,first.open,first.close,first.volume)==tuple(map(float,row[1:]))
    elif adapter==kraken:
        rows=next(v for k,v in raw['result'].items() if k!='last')
        row=next(r for r in rows if r[0]==int(first.start.timestamp()))
        assert first.volume==float(row[6]) and first.close==float(row[4])
    elif adapter==binance:
        row=next(r for r in raw if r[0]==int(first.start.timestamp()*1000))
        assert first.volume==float(row[5]) and first.close==float(row[4])
    else:
        assert first.volume==0 and all(p['volume_available'] is False for p in result.provenance)


def test_rpc_decimals_ranges_and_liquidity(client,tmp_path):
    batch=publicnode.fetch(client,decimals_cache=tmp_path/'decimals.json')
    assert batch.items and all(isinstance(e,ChainEvent) for e in batch.items)
    summary=batch.metadata
    assert {v['decimals'] for v in summary['decimals'].values()}=={6}
    assert summary['last_block']-summary['first_block']+1==20
    assert summary['chunk_size']==10
    assert summary['tokens']['USDC']['large_transfer_count']==14
    assert summary['tokens']['USDT']['large_transfer_count']==6
    assert summary['tokens']['USDC']['mint_total']==pytest.approx(16978967.818522)
    log_calls=[p for p in client.requests if p.get('rpc_request',{}).get('method')=='eth_getLogs']
    assert len(log_calls)==4
    for call in log_calls:
        params=call['rpc_request']['params'][0]
        assert int(params['toBlock'],16)-int(params['fromBlock'],16)+1<=10
    # A fresh request checkpoint still reuses the persistent token decimals cache.
    other=Client(tmp_path/'second.json',recordings=FIXTURES)
    publicnode.fetch(other,decimals_cache=tmp_path/'decimals.json')
    assert not any(p.get('rpc_request',{}).get('method')=='eth_call' for p in other.requests)


def test_checkpoint_resume_never_refetches(client,monkeypatch):
    voice=MANIFEST['voices'][0]
    original=rss.fetch(client,voice,AS_OF-timedelta(hours=48),AS_OF)
    def forbidden(*a,**k):
        raise AssertionError('checkpoint resume performed I/O')
    monkeypatch.setattr(client.breaker,'call',forbidden)
    resumed=rss.fetch(client,voice,AS_OF-timedelta(hours=48),AS_OF)
    assert resumed==original


def test_recorded_404_opens_source_circuit(client):
    for _ in range(2):
        with pytest.raises(RetryableError,match='404'):
            coinbase.fetch(client,'TRX',START,AS_OF)
    with pytest.raises(CircuitOpenError):
        coinbase.fetch(client,'TRX',START,AS_OF)
    assert client.breaker.health('coinbase').state=='down'


def test_fixture_privacy():
    for path in FIXTURES.glob('*.json'):
        value=json.loads(path.read_text())
        assert value['recorded_test_fixture'] is True
        if value.get('source','').startswith('rss:'):
            root=ET.fromstring(value['body'])
            assert not any(e.text for e in root.iter('title'))
            assert not list(root.iter('description'))
        elif value.get('source','').startswith('bluesky:'):
            assert all(not p['post']['record']['text'] for p in json.loads(value['body'])['feed'])


def test_long_retry_after_defers_source_without_early_retry(client):
    voice=MANIFEST['voices'][0]
    calls=[]
    def rate_limited(body,provenance):
        # Deliberate fault injection over a recorded response, not demo data.
        calls.append(provenance)
        raise RetryableError('injected rate limit',429,'60')
    with pytest.raises(RuntimeError,match='Retry-After 60s'):
        client.fetch('rss:'+voice['voice_id'],voice['rss'],rate_limited)
    with pytest.raises(RuntimeError,match='interval expires'):
        client.fetch('rss:'+voice['voice_id'],voice['rss'],rate_limited)
    assert len(calls)==1
