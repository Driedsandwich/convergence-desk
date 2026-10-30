"""Kraken hourly OHLC: time, open, high, low, close, vwap, volume, count."""
from urllib.parse import urlencode
from .common import json_parser
from .market import bars


def fetch(client, symbol, start, as_of):
    pair = ('XBT' if symbol == 'BTC' else 'XDG' if symbol == 'DOGE' else symbol) + 'USD'
    endpoint = 'https://api.kraken.com/0/public/OHLC?' + urlencode(dict(pair=pair, interval=60, since=int(start.timestamp())))
    result = client.fetch('kraken', endpoint, json_parser)
    raw = result['data']['result']
    rows = next((v for k, v in raw.items() if k != 'last'), [])
    return bars(symbol, 'kraken', rows, result['provenance'], as_of, start,
                lambda r: (r[0], r[1], r[2], r[3], r[4], r[6]))
