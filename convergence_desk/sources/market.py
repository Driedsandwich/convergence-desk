"""Shared conversion and completed-bar filtering; venue volumes never mix."""
from datetime import datetime, timezone, timedelta
from dataclasses import asdict
from .common import Batch, item_provenance
from convergence_desk.core.models import MarketBar

# Explicit supported demo universe; unsupported mentions remain in the rejection ledger.
SYMBOLS = {'BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'DOGE', 'AVAX', 'LINK', 'LTC', 'BCH', 'DOT', 'UNI', 'AAVE', 'SUI', 'SHIB', 'ATOM', 'ARB', 'OP', 'NEAR', 'PEPE', 'FIL', 'ETC', 'APT', 'INJ', 'TRX', 'XLM'}


def bars(symbol, source, data, provenance, as_of, start, converter, seconds=3600):
    items, refs = {}, {}
    for row in data:
        timestamp, opening, high, low, close, volume = converter(row)
        begin = datetime.fromtimestamp(float(timestamp), timezone.utc)
        end = begin + timedelta(seconds=seconds)
        if end > as_of or end < start:
            continue
        bar = MarketBar(symbol, begin, float(opening), float(high), float(low), float(close), float(volume), source, end)
        identity = symbol + ':' + begin.isoformat()
        items[identity] = bar
        refs[identity] = item_provenance(provenance, identity, asdict(bar))
    ordered = sorted(items)
    return Batch(tuple(items[k] for k in ordered), tuple(refs[k] for k in ordered))
