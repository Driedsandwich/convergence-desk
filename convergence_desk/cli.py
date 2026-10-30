"""Zero-configuration live research and offline replay. Practice only."""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sys

from .core.models import Rules, RiskLimits, Voice, SourceHealth
from .core.trail import content_hash
from .sources import rss, bluesky, coinbase, kraken, binance, coingecko, publicnode
from .sources.common import Client, dt, iso
from .sources.market import SYMBOLS
from .runtime import make_record, plain
from .report import render
from . import ledger

CONFIG = Path(__file__).parent/'config'
SOURCE_DEFAULTS = dict(cross_venue_max_spread=.02, chain_blocks=20, chain_chunk_size=10,
                       chain_confirmations=12, large_transfer_threshold=1_000_000)


def write_json(path, data):
    # All serializers here receive privacy-safe values only.
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(plain(data),indent=2,ensure_ascii=False)+'\n')
    temporary.replace(path)


def load_config(args):
    voices = json.loads(Path(args.voices or CONFIG/'default_voices.json').read_text())
    voices = voices['voices'] if isinstance(voices,dict) else voices
    if not 1 <= len(voices) <= 20 or len({v['voice_id'] for v in voices}) != len(voices):
        raise ValueError('configure 1..20 unique voice_id entries; combine RSS/Bluesky in the same entry')
    for voice in voices:
        Voice(voice['voice_id'], voice['label'], 'voices', voice['trust_weight'])
        if not (voice.get('rss') or voice.get('bluesky')):
            raise ValueError('each voice requires rss or bluesky')
    raw = json.loads(Path(args.rules or CONFIG/'default_rules.json').read_text())
    source_rules = {k:raw.pop(k,default) for k,default in SOURCE_DEFAULTS.items()}
    rules = asdict(Rules(**{**raw,'window_hours':float(args.hours)}))
    risk = asdict(RiskLimits(**json.loads(Path(args.risk or CONFIG/'default_risk.json').read_text())))
    if not 1 <= args.hours <= 240:
        raise ValueError('--hours must be in 1..240 (bounded public candle history)')
    if not 0 < source_rules['cross_venue_max_spread'] <= .2:
        raise ValueError('cross_venue_max_spread must be >0 and <=0.2')
    for key, lower, upper in (('chain_blocks',1,100),('chain_chunk_size',1,10),('chain_confirmations',1,1000)):
        if not isinstance(source_rules[key],int) or not lower <= source_rules[key] <= upper:
            raise ValueError(f'{key} must be an integer in {lower}..{upper}')
    if not math.isfinite(source_rules['large_transfer_threshold']) or source_rules['large_transfer_threshold'] <= 0:
        raise ValueError('large_transfer_threshold must be positive and finite')
    return voices,rules,risk,source_rules


def run(args):
    voices,rules,risk,source_rules = load_config(args)
    fixture_manifest = json.loads((Path(args.recordings)/'manifest.json').read_text()) if args.recordings else None
    now = dt(fixture_manifest['as_of']) if fixture_manifest else datetime.now(timezone.utc)
    out = Path(args.out or ('runs/'+now.strftime('%Y%m%dT%H%M%S%fZ')))
    out.mkdir(parents=True,exist_ok=True)
    config_hash = content_hash(dict(voices=voices,rules=rules,risk=risk,source_rules=source_rules,
                                  kill=args.kill or os.environ.get('CONVERGENCE_KILL_SOURCE',''),recordings=args.recordings,
                                  ledger=args.ledger))
    context_file = out/'run_context.json'
    if context_file.exists():
        context = json.loads(context_file.read_text())
        if context['config_hash'] != config_hash:
            raise ValueError('existing --out has different configuration; choose a fresh output directory')
        now = dt(context['as_of'])
        if (out/'record.json').exists():
            record = json.loads((out/'record.json').read_text())
            print(json.dumps({'out':str(out),'resumed_completed_run':True,**record['counts'],'decision_hash':record['decision_hash']}))
            return 2 if record['degraded'] else 0
        if (out/'snapshot.json').exists():
            # Finish a crash between snapshot and record commits without
            # reallocating against positions this run already appended.
            snapshot = json.loads((out/'snapshot.json').read_text())
            record = make_record(snapshot)
            if record['decision_hash'] != snapshot['expected_decision_hash']:
                raise ValueError('incomplete-run snapshot hash mismatch')
            (out/'report.html').write_text(render(snapshot,record))
            ledger.append(snapshot['ledger_path'], snapshot['ledger_close_events']+ledger.openings(record))
            write_json(out/'record.json',record)
            print(json.dumps({'out':str(out),'resumed_commit':True,**record['counts'],'decision_hash':record['decision_hash']}))
            return 2 if record['degraded'] else 0
    else:
        write_json(context_file,dict(as_of=iso(now),config_hash=config_hash))
    if args.record_http:
        Path(args.record_http).mkdir(parents=True,exist_ok=True)
        write_json(Path(args.record_http)/'manifest.json', dict(recorded_test_fixture=True,as_of=iso(now),voices=voices,rules=rules,risk_limits=risk,source_rules=source_rules))
    client = Client(out/'checkpoint.json',kill=args.kill,recordings=args.recordings,record_to=args.record_http)
    start = now-timedelta(hours=args.hours)
    health_rows, posts, counts, provenance, bars = {}, {}, {}, [], []
    def health(source, state, detail):
        old=health_rows.get(source)
        if old:
            states={old['state'],state}
            state='healthy' if states=={'healthy'} else 'down' if states=={'down'} else 'degraded'
            detail=old['detail']+'; '+detail
        health_rows[source]=asdict(SourceHealth(source,state,detail))
    for voice in voices:
        for kind,adapter in (('rss',rss),('bluesky',bluesky)):
            if not voice.get(kind):
                continue
            source=kind+':'+voice['voice_id']
            try:
                batch=adapter.fetch(client,voice,start,now)
                counts[source]=len(batch.items)
                for row in batch.metadata.values():
                    posts[(row['source'],row['uri'])]=row
                provenance.extend(batch.provenance)
                health(source,'healthy' if batch.items else 'degraded',f'{len(batch.items)} original items in requested window; feed history may be shorter than window')
            except Exception as error:
                counts[source]=0
                health(source,'down',str(error)[:300])
            print(f'{source}: {counts[source]} posts',flush=True)
    ledger_path = Path(args.ledger or ('runs/practice_ledger.jsonl' if not args.recordings else out/'practice_ledger.jsonl'))
    prior_ledger=ledger.read(ledger_path)
    closed={e['position_id'] for e in prior_ledger if e['event']=='close'}
    prior_positions=[e['position'] for e in prior_ledger if e['event']=='open' and e['position_id'] not in closed]
    mentioned={f['token'] for row in posts.values() for f in row['features']}
    wanted=sorted((mentioned|{p['token'] for p in prior_positions}) & SYMBOLS)
    # Always probe the two core assets even if this window contains no recognized mentions.
    wanted=sorted(set(wanted)|{'BTC','ETH'})
    bar_start=(start-timedelta(hours=3)).replace(minute=0,second=0,microsecond=0)
    for symbol in wanted:
        successes=[]
        for source,adapter in (('coinbase',coinbase),('kraken',kraken)):
            try:
                batch=adapter.fetch(client,symbol,bar_start,now)
                if not batch.items:
                    raise ValueError('no completed candles in requested window')
                bars.extend(batch.items); provenance.extend(batch.provenance); successes.append(source)
                health(source,'healthy',f'{symbol}: {len(batch.items)} completed hourly bars')
            except Exception as error:
                health(source,'down',f'{symbol}: {str(error)[:200]}')
        if len(successes)<2:
            for source,adapter in (('binance',binance),('coingecko',coingecko)):
                try:
                    batch=adapter.fetch(client,symbol,bar_start,now)
                    if not batch.items:
                        raise ValueError('no completed candles')
                    bars.extend(batch.items); provenance.extend(batch.provenance); successes.append(source)
                    health(source,'healthy',f'{symbol}: {len(batch.items)} fallback bars')
                except Exception as error:
                    health(source,'down',f'{symbol}: {str(error)[:200]}')
                if len(successes)>=2:
                    break
        print(f'market {symbol}: '+(', '.join(successes) or 'unavailable'),flush=True)
    chain_events=[]
    liquidity={'scope':'Market-wide liquidity only; not a token buy/sell signal.','available':False}
    try:
        chain=publicnode.fetch(client,blocks=source_rules['chain_blocks'],chunk_size=source_rules['chain_chunk_size'],
            confirmations=source_rules['chain_confirmations'],threshold=source_rules['large_transfer_threshold'],
            decimals_cache=out/'token_decimals.json' if args.recordings else Path('runs/token_decimals.json'))
        chain_events=list(chain.items); provenance.extend(chain.provenance)
        liquidity={**chain.metadata,'available':True}
        health('publicnode','healthy',f"{len(chain.items)} relevant logs; {source_rules['chain_blocks']} blocks; chunks of {source_rules['chain_chunk_size']}; {source_rules['chain_confirmations']} confirmations")
    except Exception as error:
        health('publicnode','down',str(error)[:300])
        liquidity['error']=str(error)[:300]
    print('on-chain: '+health_rows['publicnode']['state'],flush=True)
    if not posts and not bars and not chain_events:
        write_json(out/'failure.json',dict(source_health=list(health_rows.values()),requests=client.requests))
        raise RuntimeError('no usable inputs from any source; see failure.json')
    open_positions,realized_loss,closes,ledger_notes=ledger.evaluate(ledger_path,bars,now)
    if ledger_notes:
        health('practice_ledger','degraded','; '.join(ledger_notes))
    # Preserve failed-request provenance too, without response bodies.
    provenance.extend(client.requests)
    snapshot=plain(dict(schema_version=1,runtime_version='1',as_of=iso(now),run_path=str(out),
        voices=voices,rules=rules,risk_limits=risk,source_rules=source_rules,
        posts=sorted(posts.values(),key=lambda p:(p['created_at'],p['uri'])),
        market_bars=bars,chain_events=chain_events,source_health=list(health_rows.values()),
        provenance=provenance,liquidity=liquidity,post_counts=counts,
        open_positions=open_positions,realized_loss_today=realized_loss,
        ledger_path=str(ledger_path),ledger_close_events=closes,
        coverage=dict(unsupported_tokens=sorted(mentioned-SYMBOLS),market_symbols=wanted,
                      feed_history='Bounded publisher feeds; requested hours are a filter, not a completeness guarantee.',
                      bluesky_max_pages=5,ledger_notes=ledger_notes),
        recorded_test_fixture=bool(args.recordings)))
    print('evaluating rules and counterfactuals...',flush=True)
    record=make_record(snapshot)
    snapshot['expected_decision_hash']=record['decision_hash']
    write_json(out/'snapshot.json',snapshot)
    (out/'report.html').write_text(render(snapshot,record))
    ledger.append(ledger_path,closes+ledger.openings(record))
    write_json(out/'record.json',record)
    print(json.dumps(dict(out=str(out),**record['counts'],decision_hash=record['decision_hash'],degraded=record['degraded']),indent=2))
    return 2 if record['degraded'] else 0


def replay(path):
    snapshot=json.loads(Path(path).read_text())
    record=make_record(snapshot)
    matches=record['decision_hash']==snapshot.get('expected_decision_hash')
    print(json.dumps(dict(replay_match=matches,decision_hash=record['decision_hash'],expected_decision_hash=snapshot.get('expected_decision_hash')),indent=2))
    return 0 if matches else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description='Convergence Desk: public-source research, practice positions only.')
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ('run','chaos'):
        p=sub.add_parser(command)
        p.add_argument('--hours',type=float,default=48)
        for name in ('voices','rules','risk','out','ledger'):
            p.add_argument('--'+name)
        p.add_argument('--kill',required=command=='chaos',help='Source ID: coinbase, kraken, publicnode, rss, bluesky or rss:coindesk')
        p.add_argument('--recordings',help=argparse.SUPPRESS)
        p.add_argument('--record-http',help=argparse.SUPPRESS)
    p=sub.add_parser('replay'); p.add_argument('snapshot')
    args=parser.parse_args(argv)
    try:
        return replay(args.snapshot) if args.command=='replay' else run(args)
    except (Exception, KeyboardInterrupt) as error:
        print(f'Convergence Desk failed: {type(error).__name__}: {error}',file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
