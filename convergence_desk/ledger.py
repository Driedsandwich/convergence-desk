"""Append-only practice ledger. No orders. Stop wins ambiguous same-bar exits."""
from pathlib import Path
from datetime import timedelta
import json
from .sources.common import dt
from .core.trail import content_hash


def read(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def append(path, events):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {e['event_id'] for e in read(path)}
    with path.open('a') as handle:
        for event in events:
            if event['event_id'] not in existing:
                handle.write(json.dumps(event, sort_keys=True) + '\n')
                existing.add(event['event_id'])


def evaluate(path, bars, as_of):
    events = read(path)
    closed = {e['position_id'] for e in events if e['event'] == 'close'}
    opens = [e for e in events if e['event'] == 'open' and e['position_id'] not in closed]
    remaining, new_events, notes = [], [], []
    for event in opens:
        position = event['position']
        series_by_source = {}
        for bar in bars:
            if bar.symbol == position['token'] and bar.start >= dt(position['opened_at']) and bar.available_at <= as_of:
                series_by_source.setdefault(bar.source, []).append(bar)
        # Keep a single venue for the entire exit path, prefer original entry venue.
        preferred = event.get('market_source')
        source = preferred if preferred in series_by_source else next((s for s in ('coinbase','kraken','binance') if s in series_by_source), None)
        series = sorted(series_by_source.get(source, []), key=lambda b:b.start)
        exit_data = None
        opened_at = dt(position['opened_at'])
        prior_end = opened_at.replace(minute=0, second=0, microsecond=0)
        if prior_end < opened_at:
            prior_end += timedelta(hours=1)
        for bar in series:
            if bar.start > prior_end:
                notes.append('Missing bars for practice position ' + event['position_id'] + '; exit evaluation deferred.')
                break
            long = position['direction'] == 'bullish'
            if bar.start >= dt(position['time_stop']):
                exit_data = ('time_stop', bar.open, bar.start)
            elif (bar.low <= position['stop'] if long else bar.high >= position['stop']):
                # Adverse gaps fill at open; stop precedes target when both touch.
                price = min(bar.open, position['stop']) if long else max(bar.open, position['stop'])
                exit_data = ('stop', price, bar.available_at)
            elif (bar.high >= position['take_profit'] if long else bar.low <= position['take_profit']):
                exit_data = ('take_profit', position['take_profit'], bar.available_at)
            elif bar.available_at >= dt(position['time_stop']):
                exit_data = ('time_stop', bar.close, bar.available_at)
            if exit_data:
                break
            prior_end = bar.available_at
        if exit_data:
            reason, price, when = exit_data
            pnl = (price-position['entry_price']) * position['units'] * (1 if position['direction']=='bullish' else -1)
            close = dict(event='close', practice_only=True, position_id=event['position_id'], reason=reason,
                         exit_price=price, evaluated_at=as_of.isoformat(), closed_at=when.isoformat(), pnl=pnl,
                         market_source=source, assumption='Completed hourly bars; first partial entry bar excluded; stop wins if both exits touch.')
            close['event_id'] = content_hash(close)
            new_events.append(close)
        else:
            remaining.append(position)
    losses = sum(max(0,-e['pnl']) for e in events+new_events
                 if e['event']=='close' and dt(e['closed_at']).date()==as_of.date())
    return remaining, losses, new_events, notes


def openings(record):
    events = []
    for outcome in record['outcomes']:
        position = outcome['decision']
        if position['kind'] != 'practice_position':
            continue
        identity = content_hash({'decision_hash':record['decision_hash'], 'position':position})
        events.append(dict(event='open', event_id=identity, position_id=identity, practice_only=True,
                           decision_hash=record['decision_hash'], position=position, market_source=outcome['evidence']['market_source']))
    return events
