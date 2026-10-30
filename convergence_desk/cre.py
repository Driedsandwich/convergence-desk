"""Opt-in CRE export/attachment. Never participates in decision evaluation."""
from datetime import timedelta
from decimal import Decimal
import hashlib
from html import escape
import json
from pathlib import Path
import re

from .core.trail import content_hash
from .sources.common import dt, iso
from .sources.market import SYMBOLS

THRESHOLDS = ('market_min_return', 'cross_venue_max_spread', 'max_market_age_hours',
              'market_min_volume_z', 'volume_lookback')
BEGIN = '<!-- convergence-desk-cre:start -->'
END = '<!-- convergence-desk-cre:end -->'


def read_json(path):
    def invalid(value):
        raise ValueError('non-finite JSON value: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=invalid)


def workflow_config(record_path):
    """Use the same ranking, frozen window and effective rules as runtime.evaluate."""
    record_path = Path(record_path)
    record = read_json(record_path)
    snapshot = read_json(record_path.with_name('snapshot.json'))
    if record.get('schema_version') != 1 or record.get('runtime_version') != '1':
        raise ValueError('expected a CLI record.json (schema/runtime 1)')
    if content_hash({k: v for k, v in record.items() if k != 'decision_hash'}) != record.get('decision_hash'):
        raise ValueError('record decision_hash mismatch')
    if content_hash({k: v for k, v in snapshot.items() if k != 'expected_decision_hash'}) != record.get('snapshot_hash'):
        raise ValueError('record and sibling snapshot.json do not match')
    if dt(snapshot['as_of']) != dt(record['as_of']):
        raise ValueError('record and snapshot observation times differ')
    candidates = [o['narrative'] for o in record['outcomes'] if o['narrative']['converged']]
    if not candidates:
        raise ValueError('no converged narrative; no CRE config written')
    top = sorted(candidates, key=lambda n: (-n['total_weight'], -n['distinct_voices'], n['token'], n['direction']))[0]
    if top['token'] not in SYMBOLS or top['direction'] not in ('bullish', 'bearish'):
        raise ValueError('top converged narrative has an unsupported token/direction')
    rules = snapshot['rules']
    hours = rules['window_hours']
    if not 1 <= hours <= 240:
        raise ValueError('CRE candle window must be 1..240 hours')
    end = dt(record['as_of'])
    config = dict(schema_version=1, record_decision_hash=record['decision_hash'],
                  synthetic_for_tests=bool(record.get('recorded_test_fixture', False)),
                  token=top['token'], direction=top['direction'],
                  window_start=iso(end - timedelta(hours=hours)), window_end=iso(end))
    # These originate in default_rules.json, with any run-specific overrides
    # preserved in the snapshot. record.json alone does not contain the window.
    config.update({key: snapshot['source_rules'][key] if key == 'cross_venue_max_spread'
                   else rules[key] for key in THRESHOLDS})
    return config


def export_config(record_path, out):
    from .cli import write_json
    config = workflow_config(record_path)
    out = Path(out)
    if out.resolve() in {Path(record_path).resolve(), Path(record_path).with_name('snapshot.json').resolve(),
                         Path(record_path).with_name('report.html').resolve()}:
        raise ValueError('--out must not overwrite run artifacts')
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, config)
    print(json.dumps({'config': str(out), 'token': config['token'], 'direction': config['direction']}))
    return 0


def result_payload(result):
    """Hash this result format, not the core's distinct float canonicalization."""
    payload = {k: v for k, v in result.items() if k != 'sha256'}
    def check(value):
        if value is None or isinstance(value, (str, bool)) or type(value) is int:
            return
        if isinstance(value, list):
            for item in value:
                check(item)
        elif isinstance(value, dict):
            for item in value.values():
                check(item)
        else:
            raise ValueError('CRE measurements must be decimal strings, not floats')
    check(payload)
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    if hashlib.sha256(raw.encode('utf-8')).hexdigest() != result.get('sha256'):
        raise ValueError('CRE result sha256 mismatch')
    return payload


def validate_result(result, config):
    if not isinstance(result, dict):
        raise ValueError('expected the workflow result JSON object, not simulator logs')
    payload = result_payload(result)
    if payload.get('schema_version') != 1 or payload.get('check') != 'chainlink-cre-market-evidence':
        raise ValueError('unsupported CRE result schema')
    for key in ('record_decision_hash', 'synthetic_for_tests', 'token', 'direction', 'window_start', 'window_end'):
        if payload.get(key) != config[key]:
            raise ValueError(f'CRE result does not match this run: {key}')
    for key in THRESHOLDS:
        if Decimal(payload['thresholds'][key]) != Decimal(str(config[key])):
            raise ValueError(f'CRE threshold mismatch: {key}')
    if payload.get('verdict') not in ('confirm', 'contradict', 'inconclusive'):
        raise ValueError('invalid CRE verdict')
    if payload.get('cross_venue_status') not in ('agreement', 'disagreement', 'unavailable'):
        raise ValueError('invalid CRE cross-venue status')
    dt(payload['observed_at'])
    chain = payload['onchain']
    if (chain['chain'] != 'ethereum-mainnet' or
        chain['contract'] != '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48' or
        chain['function'] != 'totalSupply()' or chain['block_reference'] != 'finalized' or
        chain['decimals'] != '6' or not re.fullmatch(r'\d+', chain['value'])):
        raise ValueError('invalid USDC on-chain context')
    dt(chain['read_at'])
    for venue in ('coinbase', 'kraken'):
        value = payload['venues'][venue]['return_fraction']
        if value is not None and not Decimal(value).is_finite():
            raise ValueError('invalid venue return')
    if payload['spread'] is not None and (not Decimal(payload['spread']).is_finite() or Decimal(payload['spread']) < 0):
        raise ValueError('invalid spread')
    return payload


def attach_result(run_dir, result_path):
    run_dir = Path(run_dir)
    config = workflow_config(run_dir / 'record.json')
    result_path = Path(result_path)
    result = read_json(result_path)
    payload = validate_result(result, config)
    report_path = run_dir / 'report.html'
    report = report_path.read_text(encoding='utf-8')
    if '</body>' not in report:
        raise ValueError('report.html has no closing body')
    if (BEGIN in report) != (END in report):
        raise ValueError('incomplete existing CRE report section')
    synthetic = '<p><strong>SYNTHETIC TEST INPUTS — not live simulation evidence.</strong></p>' if payload['synthetic_for_tests'] else ''
    fields = {key: payload[key] for key in ('token', 'direction', 'verdict', 'spread', 'window_start', 'window_end', 'observed_at')}
    fields['coinbase_return'] = payload['venues']['coinbase']['return_fraction']
    fields['kraken_return'] = payload['venues']['kraken']['return_fraction']
    fields['USDC_total_supply_raw'] = payload['onchain']['value']
    section = (BEGIN + '\n<section id="chainlink-cre"><h2>Chainlink CRE check</h2>' + synthetic +
               '<p>Independent second check; the original decision is unchanged. '
               'Imported workflow output; SHA-256 checks local integrity, not network attestation.</p><dl>' +
               ''.join(f'<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>' for k, v in fields.items()) +
               '</dl><p>SHA-256: <code>' + escape(result['sha256']) +
               '</code></p><p><a href="cre_result.json">Workflow result JSON</a></p></section>\n' + END)
    if BEGIN in report:
        start, stop = report.index(BEGIN), report.index(END) + len(END)
        report = report[:start] + section + report[stop:]
    else:
        report = report.replace('</body>', section + '\n</body>', 1)
    # Validate everything before writes. Each file uses an atomic replacement;
    # rerunning attachment repairs an interruption between the two replacements.
    result_tmp = run_dir / 'cre_result.json.tmp'
    result_tmp.write_bytes(result_path.read_bytes())
    report_tmp = run_dir / 'report.html.cre.tmp'
    report_tmp.write_text(report, encoding='utf-8')
    result_tmp.replace(run_dir / 'cre_result.json')
    report_tmp.replace(report_path)
    print(json.dumps({'cre_result': str(run_dir / 'cre_result.json'), 'verdict': payload['verdict'], 'decision_changed': False}))
    return 0
