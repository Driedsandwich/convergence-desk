"""Binance data-only public klines; USDT quote basis is disclosed in evidence."""
from urllib.parse import urlencode
from .common import json_parser
from .market import bars


def fetch(client, symbol, start, as_of):
    endpoint = 'https://data-api.binance.vision/api/v3/klines?' + urlencode(dict(symbol=symbol+'USDT', interval='1h', startTime=int(start.timestamp()*1000), endTime=int(as_of.timestamp()*1000), limit=300))
    result = client.fetch('binance', endpoint, json_parser)
    return bars(symbol, 'binance', result['data'], result['provenance'], as_of, start,
                lambda r: (r[0]/1000, r[1], r[2], r[3], r[4], r[5]))
