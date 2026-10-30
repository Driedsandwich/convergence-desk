"""Keyless OHLC fallback. No per-bar volume is supplied; never invent it.

MarketBar volume=0 is an explicit unavailable sentinel; the integration never
uses this source for a volume-confirmed entry. Only cross-venue price context.
"""
from datetime import datetime, timezone
from convergence_desk.core.models import MarketBar
from .common import Batch, json_parser, item_provenance

IDS = {'BTC': 'bitcoin', 'ETH': 'ethereum', 'SOL': 'solana', 'XRP': 'ripple', 'ADA': 'cardano', 'DOGE': 'dogecoin', 'AVAX': 'avalanche-2', 'LINK': 'chainlink', 'LTC': 'litecoin', 'SUI': 'sui'}


def fetch(client, symbol, start, as_of):
    if symbol not in IDS:
        raise ValueError('CoinGecko ID not configured for ' + symbol)
    endpoint = f'https://api.coingecko.com/api/v3/coins/{IDS[symbol]}/ohlc?vs_currency=usd&days=7'
    result = client.fetch('coingecko', endpoint, json_parser)
    items, refs = [], []
    rows = sorted(result['data'])
    # The API explicitly defines these timestamps as candle close times:
    # https://docs.coingecko.com/reference/coins-id-ohlc
    # A returned row is usable once its close time is at or before as_of.
    for previous, row in zip(rows, rows[1:]):
        end = datetime.fromtimestamp(row[0]/1000, timezone.utc)
        begin = datetime.fromtimestamp(previous[0]/1000, timezone.utc)
        if not start <= end <= as_of:
            continue
        bar = MarketBar(symbol, begin, *map(float, row[1:5]), 0.0, 'coingecko', end)
        items.append(bar)
        refs.append({**item_provenance(result['provenance'], symbol + ':' + begin.isoformat(), row), 'volume_available': False})
    return Batch(tuple(items), tuple(refs))
