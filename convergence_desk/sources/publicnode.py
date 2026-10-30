"""Confirmed Ethereum USDC/USDT transfers; market-wide liquidity only."""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from convergence_desk.core.models import ChainEvent
from convergence_desk.core.resilience import CheckpointStore
from .common import Batch, json_parser, item_provenance

ENDPOINT = 'https://ethereum-rpc.publicnode.com'
TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
TOKENS = {'USDC': '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', 'USDT': '0xdac17f958d2ee523a2206206994597c13d831ec7'}
ZERO = '0x' + '0'*40


def fetch(client, *, blocks=20, chunk_size=10, confirmations=12, threshold=1_000_000, decimals_cache=None):
    if not 1 <= chunk_size <= 10 or not 1 <= blocks <= 100 or confirmations < 1 or threshold <= 0:
        raise ValueError('chain limits: chunk 1..10, blocks 1..100, confirmations >=1, threshold >0')
    def rpc(method, params):
        result = client.fetch('publicnode', ENDPOINT, json_parser,
                              {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
        if 'result' not in result['data']:
            raise ValueError('RPC response missing result')
        return result['data']['result'], result['provenance']
    head, _ = rpc('eth_blockNumber', [])
    last = int(head, 16) - confirmations
    first = last - blocks + 1
    times = {}
    items, refs = [], []
    cache = CheckpointStore(decimals_cache) if decimals_cache else None
    decimals_seen = {}
    for token, address in TOKENS.items():
        saved = cache.load()['sources'].get(address) if cache else None
        if saved:
            decimals, decimals_prov = saved['state']['decimals'], saved['state']['provenance']
        else:
            raw, decimals_prov = rpc('eth_call', [{'to': address, 'data': '0x313ce567'}, 'latest'])
            decimals = int(raw, 16)
            if not 0 <= decimals <= 36:
                raise ValueError('invalid token decimals')
            if cache:
                cache.save(address, address, {'decimals': decimals, 'provenance': decimals_prov})
        decimals_seen[token] = {'decimals': decimals, 'provenance': decimals_prov}
        for begin in range(first, last+1, chunk_size):
            end = min(begin+chunk_size-1, last)
            logs, provenance = rpc('eth_getLogs', [{'address': address, 'topics': [TRANSFER], 'fromBlock': hex(begin), 'toBlock': hex(end)}])
            for log in logs:
                if log.get('removed') or log['address'].lower() != address or log['topics'][0].lower() != TRANSFER:
                    continue
                block = int(log['blockNumber'], 16)
                if not begin <= block <= end:
                    raise ValueError('RPC returned log outside requested chunk')
                amount = float(Decimal(int(log['data'], 16)) / Decimal(10)**decimals)
                origin, destination = '0x'+log['topics'][1][-40:].lower(), '0x'+log['topics'][2][-40:].lower()
                label = 'mint' if origin == ZERO else 'burn' if destination == ZERO else 'transfer'
                # Retain only events used by the liquidity summary, to bound disk and RPC work.
                if label == 'transfer' and amount <= threshold:
                    continue
                if block not in times:
                    header, _ = rpc('eth_getBlockByNumber', [hex(block), False])
                    times[block] = datetime.fromtimestamp(int(header['timestamp'], 16), timezone.utc)
                event = ChainEvent('ethereum', log['transactionHash'], block, token, origin, destination,
                                   amount, label, times[block], 'publicnode', int(log['logIndex'], 16))
                items.append(event)
                refs.append(item_provenance(provenance, event.tx_hash + ':' + str(event.event_index), asdict(event)))
    unique = {(e.tx_hash, e.event_index): (e,p) for e,p in zip(items,refs)}
    values = list(unique.values())
    summary = {'first_block': first, 'last_block': last, 'chunk_size': chunk_size,
               'confirmations': confirmations, 'large_transfer_threshold': threshold,
               'decimals': decimals_seen, 'scope': 'Market-wide stablecoin liquidity; not a token buy/sell signal.',
               'tokens': {}}
    for token in TOKENS:
        events = [e for e,p in values if e.token == token]
        def total(selected):
            return float(sum((Decimal(str(e.amount)) for e in selected), Decimal(0)))
        summary['tokens'][token] = dict(mint_total=total(e for e in events if e.from_addr == ZERO),
            burn_total=total(e for e in events if e.to_addr == ZERO),
            large_transfer_count=sum(e.amount > threshold for e in events),
            large_transfer_total=total(e for e in events if e.amount > threshold))
    return Batch(tuple(e for e,p in values), tuple(p for e,p in values), metadata=summary)
