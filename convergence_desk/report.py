"""Single-file, escaped HTML report, readable offline and in print."""
from html import escape
import json


def esc(value):
    return escape(str(value))


def number(value):
    return 'unavailable' if value is None else f'{value:,.6g}' if isinstance(value,(float,int)) else str(value)


def table(headers, rows):
    return '<div class="table"><table><thead><tr>' + ''.join('<th>'+esc(h)+'</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows) + '</tbody></table></div>'


def checks(rows):
    return table(['Rule','Result','Actual','Required','Detail'], [(esc(c['rule']), 'PASS' if c['passed'] else '<b class="fail">FAIL</b>', esc(number(c['actual'])), esc(number(c['expected'])), esc(c['detail'])) for c in rows])


def render(snapshot, record):
    counts = record['counts']
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Convergence Desk — practice report</title><style>body{font:15px/1.5 system-ui,sans-serif;color:#172330;background:#f5f7f9;margin:0}main{max-width:1180px;margin:auto;padding:28px}h1,h2,h3{line-height:1.2}section{background:white;border:1px solid #dce2e7;border-radius:10px;padding:20px;margin:20px 0}h2{margin-top:0}.table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:8px;border-bottom:1px solid #dce2e7;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#edf2f6}code{overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}summary{cursor:pointer;font-weight:600;padding:10px 0}.fail{color:#9d2434}.badge{display:inline-block;background:#e5edf6;padding:6px 12px;border-radius:6px}a{color:#165e9b}small{color:#4e5e6d}@media print{body{background:white;font-size:11px}main{max-width:none;padding:0}section{break-inside:auto;border:0;padding:8px 0}details{display:block}details>*{display:block}table{font-size:10px}.table{overflow:visible}h2,h3{break-after:avoid}}</style><main>']
    parts.append('<h1>Convergence Desk</h1><p class="badge">PRACTICE ONLY · No real orders · '+esc(record['as_of'])+'</p>')
    if record['recorded_test_fixture']:
        parts.append('<p class="fail">RECORDED TEST FIXTURES — not live demo data. Publisher text has been removed.</p>')
    parts.append('<section><h2>Decision summary</h2><p>'+esc(f"{counts['posts']} posts; {counts['converged_narratives']} converged narratives; {counts['practice_positions']} practice positions; {counts['rejections']} rejected token/direction candidates.")+'</p>')
    accepted = [o for o in record['outcomes'] if o['decision']['kind']=='practice_position']
    rows=[]
    for outcome in accepted:
        p=outcome['decision']; n=outcome['narrative']
        rows.append((esc(p['token']+' '+p['direction']), esc(number(p['entry_price'])), esc(f"{p['units']:.6g} units / ${p['notional']:.2f}"), esc(number(p['stop'])), esc(number(p['take_profit'])),esc(p['time_stop']),esc(f"{n['distinct_voices']} voices, weight {n['total_weight']:.2f}; market confirmed; stop risk ${p['risk_amount']:.2f}.")))
    parts.append(table(['Practice position','Entry USD','Size','Stop','Take profit','Time stop UTC','Reason'],rows) if rows else '<p><b>No practice position opened.</b> The rules and failed checks below explain why.</p>')
    parts.append('<p>State: '+('degraded; thresholds unchanged' if record['degraded'] else 'completed')+'. Headlines are imperfect lexical evidence, not calibrated predictions. Position entry uses the latest completed candle close as a practice reference.</p></section>')
    parts.append('<section><h2>Why</h2><p>Posts → one vote per publisher → directional convergence → completed-candle return and volume → cross-venue agreement → risk sizing. Trust weights are explicit configuration choices. RSS and Bluesky from the same publisher share one vote.</p>')
    for o in record['outcomes']:
        n=o['narrative']; ev=o['evidence']; p=o['decision']; cross=o['cross_venue']
        parts.append('<details><summary>'+esc(f"{n['token']} {n['direction']} — {n['distinct_voices']} voices, weight {n['total_weight']:.2f}; market {ev['status']}; venues {cross['status']}")+'</summary>')
        parts.append('<p>Post evidence (all contributing feature records):</p>')
        parts.append(table(['Voice','URI','Sentiment','Conviction','Extraction rules'],[(esc(m['voice_id']),'<a href="'+esc(m['uri'])+'">'+esc(m['uri'])+'</a>',esc(number(m['sentiment']['value'])),esc(number(m['conviction']['value'])),esc('; '.join(m['token_rules']+m['sentiment']['fired']+m['conviction']['fired']))) for m in n['members']]))
        parts.append('<h3>Convergence and risk rules</h3>'+checks(p['rule_chain']))
        parts.append('<h3>Market check</h3>'+checks(ev['checks']))
        parts.append(table(['Venue','Window return','Volume z','Completed reference','Status'],[(esc(s),esc(number(e['return_fraction'])),esc(number(e['volume_z'])),esc(e['entry_time']),esc(e['status'])) for s,e in cross['venue_evidence'].items()]))
        parts.append('<p>'+esc(f"Cross-venue {cross['status']}: common completed endpoint {cross['common_completed_endpoint']}; close spread {cross['relative_close_spread']}; maximum {cross['max_spread']}.")+'</p><p>'+esc(' '.join(ev['notes']))+'</p></details>')
    parts.append('<h3>Market-wide liquidity</h3><p>USDC/USDT mint, burn and large-transfer observations describe market-wide liquidity. They are not a buy/sell signal for any token and do not vote in its decision.</p><pre>'+esc(json.dumps(record['liquidity'],indent=2))+'</pre>')
    parts.append('<p>Coverage: '+esc(json.dumps(record['coverage']))+'</p></section>')
    parts.append('<section><h2>Cause and effect</h2><p>Each intervention reruns convergence, market checks and portfolio allocation. “Pivotal” means removing that voice flips acceptance. Convergence-only pivotal voices are shown separately. No listed flip means none in the tested steps, not proof of global insensitivity.</p>')
    parts.append(table(['Candidate','Decision-pivotal voices','Convergence-pivotal voices','Thresholds that flip acceptance'],[(esc(c['token']+' '+c['direction']),esc(', '.join(c['pivotal_voices']) or 'none'),esc(', '.join(c['convergence_pivotal_voices']) or 'none'),esc(json.dumps(c['sensitive_thresholds']) if c['sensitive_thresholds'] else 'none in tested steps')) for c in record['counterfactuals']]))
    parts.append('<details><summary>All intervention values and results</summary><pre>'+esc(json.dumps(record['counterfactuals'],indent=2))+'</pre></details></section>')
    parts.append('<section><h2>Rejection ledger</h2>')
    parts.append(table(['Token / direction','Failed rules (actual → required)'],[(esc(o['decision']['token']+' '+o['decision']['direction']),'<br>'.join(esc(f"{c['rule']}: {number(c['actual'])} → {number(c['expected'])}") for c in o['decision']['failed_rules'])) for o in record['outcomes'] if o['decision']['kind']=='rejection']))
    parts.append('</section><section><h2>Source health and provenance</h2>')
    parts.append(table(['Source','State','Detail','Posts in window'],[(esc(h['source']),esc(h['state']),esc(h['detail']),esc(counts['posts_by_source'].get(h['source'],'—'))) for h in record['source_health']]))
    # Aggregate identical response hashes; every item reference remains in snapshot and record.
    seen={}
    for p in record['provenance']:
        key=(p['source'],p['endpoint'],p.get('response_sha256',''),p['fetch_time'])
        seen[key]=p
    parts.append(table(['Source / endpoint','Fetched UTC','HTTP','Response SHA-256'],[(esc(p['source'])+'<br><small>'+esc(p['endpoint'])+'</small>',esc(p['fetch_time']),esc(p['http_status']),'<code>'+esc(p.get('response_sha256','unavailable'))+'</code>') for p in seen.values()]))
    parts.append('<p>Per-item content hashes and RPC request ranges are in snapshot.json and record.json. Response hashes identify the original HTTP bytes; full post/article text is discarded. Excerpts are limited to 140 characters.</p></section>')
    parts.append('<section><h2>Replay</h2><p>From the repository root, run:</p><pre>python3 -m convergence_desk.cli replay '+esc(snapshot['run_path'])+'/snapshot.json</pre><p>Replay reads only the snapshot, including saved extracted features; it performs no network requests and does not change the practice ledger.</p><p>Decision SHA-256: <code>'+esc(record['decision_hash'])+'</code></p><p>Snapshot SHA-256: <code>'+esc(record['snapshot_hash'])+'</code></p></section></main></html>')
    return ''.join(parts)
