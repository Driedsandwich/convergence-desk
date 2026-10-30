"""Coinbase Exchange hourly candles: time, low, high, open, close, volume."""
from urllib.parse import urlencode
from .common import json_parser, iso
from .market import bars


def fetch(client, symbol, start, as_of):
    endpoint = f'https://api.exchange.coinbase.com/products/{symbol}-USD/candles?' + urlencode(dict(granularity=3600, start=iso(start), end=iso(as_of)))
    result = client.fetch('coinbase', endpoint, json_parser)
    return bars(symbol, 'coinbase', result['data'], result['provenance'], as_of, start,
                lambda r: (r[0], r[3], r[2], r[1], r[4], r[5]))
