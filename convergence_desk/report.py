"""Single-file, escaped HTML report, readable offline and in print."""
from html import escape
import json


STYLE = '''
:root{color-scheme:light;--ink:#182a38;--muted:#4e606f;--line:#d6e0e6}
*{box-sizing:border-box}html{scroll-padding-top:7rem}
body{font:16px/1.6 system-ui,sans-serif;color:var(--ink);background:#f3f6f8;margin:0}
main{max-width:960px;margin:auto;padding:28px 24px 60px}
h1,h2,h3,h4{line-height:1.25;letter-spacing:-.025em}h1{font-size:2.4rem;margin-bottom:12px}
h2{font-size:1.5rem;margin-top:0}h3{font-size:1.15rem}h4{font-size:1rem}
p{margin:12px 0}section{background:white;border:1px solid var(--line);border-radius:12px;padding:24px;margin:24px 0}
.toc{position:sticky;top:0;z-index:1;display:flex;flex-wrap:wrap;gap:4px 16px;padding:12px 16px;background:#f3f6f8;border-bottom:1px solid var(--line);font-size:13px}
.toc a{padding:3px 0;text-decoration:none;font-weight:600}.toc a:hover{text-decoration:underline}
.conclusion{border:1px solid var(--line);border-left:4px solid #34778a;border-radius:8px;padding:20px;margin-top:20px}
.conclusion h3{font-size:1.3rem;margin:0 0 10px}.conclusion p{font-size:15px}
.tag{display:inline-block;font-size:11px;line-height:1.5;font-weight:700;letter-spacing:.03em;padding:3px 8px;border-radius:20px;margin:0 4px 4px 0;vertical-align:middle;background:#e8edf2;color:#344956}
.converged{background:#deedf7;color:#174b70}.rejected{background:#fbe7e8;color:#8e2233}
.practice{background:#ddf3e8;color:#155b40}.degraded{background:#fff0cf;color:#79520c}
.change{border-top:1px solid var(--line);padding-top:12px}.failed-rules{font-size:14px;padding-left:22px}
.failed-rules li{margin:6px 0;overflow-wrap:anywhere}.table{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
td,th{padding:9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;overflow-wrap:anywhere}
th{background:#edf2f6}code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}
pre{white-space:pre-wrap;font-size:12px;background:#f5f7f9;padding:14px;border-radius:6px}
details{border-top:1px solid var(--line);padding:4px 0}summary{cursor:pointer;font-weight:600;padding:12px 0}
summary:focus-visible,a:focus-visible{outline:3px solid #34778a;outline-offset:3px}
.fail{color:#9d2434}.badge{display:inline-block;background:#e5edf6;padding:6px 12px;border-radius:6px;font-size:13px}
a{color:#165e9b}small{color:var(--muted)}.empty{color:var(--muted)}
@media(max-width:600px){main{padding:16px 12px}section{padding:16px}.conclusion{padding:14px}.toc{gap:2px 12px}h1{font-size:2rem}}
@media print{body{background:white;font-size:11px}main{max-width:none;padding:0}.toc{display:none}
section{break-inside:auto;border:0;padding:8px 0;margin:12px 0}.conclusion{break-inside:avoid;padding:12px}
.conclusion p{font-size:11px}.failed-rules{font-size:10px}details,details>*{display:block}
details::details-content{display:block;content-visibility:visible}table{font-size:10px}.table{overflow:visible}
h2,h3,h4,summary{break-after:avoid}pre{font-size:9px}a{color:inherit}.tag{border:1px solid var(--line)}}
'''

SECTIONS = (
    ('conclusions', 'Conclusions'), ('decision-summary', 'Summary'), ('why', 'Why'),
    ('cause-and-effect', 'Cause & effect'), ('rejections', 'Rejections'),
    ('sources', 'Sources'), ('replay', 'Replay'),
)


def esc(value):
    return escape('not available' if value is None else str(value))


def number(value):
    if value is None:
        return 'not available'
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f'{value:,}'
    if isinstance(value, float):
        return f'{value:,.6f}'.rstrip('0').rstrip('.') if abs(value) >= 1 else f'{value:.6g}'
    return str(value)


def percent(value):
    return 'not available' if value is None else f'{value * 100:+.6g}%'


def tag(label, style=''):
    return '<span class="tag '+esc(style)+'">'+esc(label)+'</span>'


def decision_tag(decision):
    kind = decision.get('kind')
    if kind == 'practice_position':
        return tag('practice position', 'practice')
    if kind == 'rejection':
        return tag('rejected', 'rejected')
    return tag('not available')


def narrative_order(outcome):
    n = outcome['narrative']
    return (-(n.get('total_weight') or 0), -(n.get('distinct_voices') or 0),
            n.get('token', ''), n.get('direction', ''))


def voice_name(voice_id, labels):
    # Labels live in the paired snapshot; only recorded qualifying voters are listed.
    return f'{labels.get(voice_id) or "not available"} ({voice_id})'


def counterfactual_line(counterfactual, labels):
    if counterfactual is None or counterfactual.get('trials') is None:
        return 'Counterfactual trials: not available.'
    flipped = [trial for trial in counterfactual['trials'] if trial.get('flipped') is True]
    if not flipped:
        return 'No tested counterfactual trial flipped this decision.'
    sentences = []
    for trial in flipped:
        change, value = trial.get('change'), trial.get('value')
        if change == 'leave_out_voice':
            condition = f'Without {voice_name(value, labels)}'
        elif change == 'drop_market_evidence' and value is True:
            condition = 'Without the market-confirmation step'
        else:
            condition = f'With {number(change)} set to {number(value)}'
        accepted = trial.get('alternative_accepted')
        result = ('a practice position would have opened' if accepted is True else
                  'the practice position would be rejected' if accepted is False else
                  'the alternative decision is not available')
        failures = trial.get('failed_rules') or []
        if change == 'leave_out_voice' and accepted is False and any(
                rule in failures for rule in ('quorum_weight', 'min_distinct_voices')):
            result = 'the quorum would fail and ' + result
        sentences.append(f'{condition}, {result}.')
        if failures:
            sentences.append('Alternative failed rules: '+', '.join(failures)+'.')
    return ' '.join(sentences)


def liquidity_sentences(liquidity):
    liquidity = liquidity or {}
    if liquidity.get('available') is not True:
        text = 'On-chain liquidity context: not available.'
        if liquidity.get('error'):
            text += ' Source detail: '+str(liquidity['error'])+'.'
    else:
        text = (f"On-chain liquidity was sampled from blocks {number(liquidity.get('first_block'))} "
                f"through {number(liquidity.get('last_block'))}, with {number(liquidity.get('confirmations'))} confirmations.")
        tokens = liquidity.get('tokens') or {}
        if not tokens:
            text += ' Token liquidity totals: not available.'
        for token, totals in tokens.items():
            text += (f" {token}: minted {number(totals.get('mint_total'))} and burned {number(totals.get('burn_total'))}; "
                     f"{number(totals.get('large_transfer_count'))} transfers above {number(liquidity.get('large_transfer_threshold'))} "
                     f"totaled {number(totals.get('large_transfer_total'))} {token}.")
    return text + ' Scope: ' + str(liquidity.get('scope') or 'not available')


def conclusion_card(outcome, record, labels):
    n = outcome['narrative']
    decision = outcome.get('decision') or {}
    evidence = outcome.get('evidence') or {}
    cross = outcome.get('cross_venue') or {}
    rules = {c['rule']: c for c in n.get('checks') or []}
    voters = ', '.join(voice_name(v[1], labels) for v in n.get('voice_weights') or []) or 'not available'
    parts = ['<article class="conclusion"><h3>'+esc(n.get('token'))+' '+esc(n.get('direction'))+'</h3>',
             tag('converged', 'converged'), decision_tag(decision)]
    parts.append('<p><strong>Voices.</strong> '+esc(
        f"{voters} converged: {number(n.get('distinct_voices'))} qualifying voices "
        f"against a minimum of {number(rules.get('min_distinct_voices', {}).get('expected'))}, "
        f"with weight {number(n.get('total_weight'))} against quorum {number(rules.get('quorum_weight', {}).get('expected'))}.")+'</p>')
    market = []
    venue_evidence = cross.get('venue_evidence') or {}
    venues = list(dict.fromkeys([*(cross.get('venues') or []), *venue_evidence]))
    for venue in venues:
        ev = venue_evidence.get(venue) or {}
        status = {'confirm': 'confirmed this direction', 'contradict': 'contradicted this direction',
                  'inconclusive': 'was inconclusive'}.get(ev.get('status'), 'was not available')
        market.append(f"On {venue}, the window return was {percent(ev.get('return_fraction'))} "
                      f"and volume z-score was {number(ev.get('volume_z'))}; the evidence {status}.")
    if not venues:
        market.append('Per-venue market evidence: not available.')
    market.append(f"Cross-venue status was {number(cross.get('status'))}, with close spread "
                  f"{percent(cross.get('relative_close_spread'))} against a maximum of {percent(cross.get('max_spread'))}; "
                  f"the common completed endpoint was {number(cross.get('common_completed_endpoint'))}.")
    market.extend(evidence.get('notes') or [])
    parts.append('<p><strong>Market.</strong> '+esc(' '.join(market))+'</p>')
    parts.append('<p><strong>Liquidity.</strong> '+esc(liquidity_sentences(record.get('liquidity')))+'</p>')
    if decision.get('kind') == 'practice_position':
        result = (f"A practice position opened at {number(decision.get('entry_price'))} USD, "
                  f"sized at {number(decision.get('units'))} units / {number(decision.get('notional'))} USD, "
                  f"with stop {number(decision.get('stop'))} USD, target {number(decision.get('take_profit'))} USD, "
                  f"and time stop {number(decision.get('time_stop'))}; stop risk was {number(decision.get('risk_amount'))} USD.")
    elif decision.get('kind') == 'rejection':
        result = 'This narrative was rejected; no practice position opened.'
        failures = decision.get('failed_rules') or []
        if any(c.get('rule') == 'no_direction_conflict' and c.get('actual') is True for c in failures):
            result += ' A converged narrative in the opposite direction conflicted with this one.'
    else:
        result = 'Decision: not available.'
    parts.append('<p><strong>Decision.</strong> '+esc(result)+'</p>')
    failures = decision.get('failed_rules')
    if failures is None and decision.get('rule_chain') is not None:
        failures = [c for c in decision['rule_chain'] if c.get('passed') is False]
    if failures:
        parts.append('<p><strong>Exact failed rules</strong> (recorded values):</p><ul class="failed-rules">')
        for check in failures:
            # Preserve full precision here: rounded values can hide a threshold failure.
            parts.append('<li><code>'+esc(check.get('rule'))+'</code>: actual '+esc(check.get('actual'))+
                         '; required '+esc(check.get('expected'))+'. '+esc(check.get('detail', ''))+'</li>')
        parts.append('</ul>')
    else:
        parts.append('<p>Failed rules: '+('not available' if failures is None else 'none')+'.</p>')
    cf = next((c for c in record.get('counterfactuals', [])
               if (c.get('token'), c.get('direction')) == (n.get('token'), n.get('direction'))), None)
    parts.append('<p class="change"><strong>What would change this decision:</strong> '+
                 esc(counterfactual_line(cf, labels))+'</p></article>')
    return ''.join(parts)


def table(headers, rows):
    return '<div class="table"><table><thead><tr>' + ''.join('<th>'+esc(h)+'</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows) + '</tbody></table></div>'


def checks(rows):
    return table(['Rule','Result','Actual','Required','Detail'], [(esc(c.get('rule')), 'PASS' if c.get('passed') is True else '<b class="fail">FAIL</b>' if c.get('passed') is False else 'not available', esc(c.get('actual')), esc(c.get('expected')), esc(c.get('detail'))) for c in rows])



def narrative_details(o):
    parts = []
    n=o['narrative']; ev=o.get('evidence') or {}; p=o['decision']; cross=o.get('cross_venue') or {}
    parts.append('<details><summary>'+esc(f"{n.get('token')} {n.get('direction')} — {number(n.get('distinct_voices'))} voices, weight {number(n.get('total_weight'))}; market {number(ev.get('status'))}; venues {number(cross.get('status'))}")+' '+
                 (tag('converged', 'converged') if n.get('converged') else '')+decision_tag(p)+'</summary>')
    parts.append('<p>Post evidence (all contributing feature records):</p>')
    parts.append(table(['Voice','URI','Sentiment','Conviction','Extraction rules'],[(esc(m['voice_id']),'<a href="'+esc(m['uri'])+'">'+esc(m['uri'])+'</a>',esc(number(m['sentiment']['value'])),esc(number(m['conviction']['value'])),esc('; '.join(m['token_rules']+m['sentiment']['fired']+m['conviction']['fired']))) for m in n['members']]))
    parts.append('<h4>Convergence and risk rules</h4>'+checks(p.get('rule_chain', [])))
    parts.append('<h4>Market check</h4>'+checks(ev.get('checks', [])))
    parts.append(table(['Venue','Window return (fraction)','Volume z','Completed reference','Status'],[(esc(s),esc(number(e.get('return_fraction'))),esc(number(e.get('volume_z'))),esc(e.get('entry_time')),esc(e.get('status'))) for s,e in (cross.get('venue_evidence') or {}).items()]))
    parts.append('<p>'+esc(f"Cross-venue {number(cross.get('status'))}: common completed endpoint {number(cross.get('common_completed_endpoint'))}; close spread {number(cross.get('relative_close_spread'))}; maximum {number(cross.get('max_spread'))}.")+'</p><p>'+esc(' '.join(ev.get('notes') or []))+'</p></details>')
    return "".join(parts)


def render(snapshot, record):
    counts = record['counts']
    outcomes = sorted(record['outcomes'], key=narrative_order)
    directional = [o for o in outcomes if o['narrative'].get('direction') in ('bullish', 'bearish')]
    converged = [o for o in directional if o['narrative'].get('converged') is True]
    candidates = [o for o in directional if o['narrative'].get('converged') is not True]
    neutral = [o for o in outcomes if o not in directional]
    labels = {v['voice_id']: v.get('label') for v in snapshot.get('voices', [])}
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Convergence Desk — practice report</title><style>'+STYLE+'</style></head><body><main>']
    parts.append('<h1>Convergence Desk</h1><p class="badge">PRACTICE ONLY · No real orders · '+esc(record['as_of'])+'</p>')
    if record['recorded_test_fixture']:
        parts.append('<p class="fail">RECORDED TEST FIXTURES — not live demo data. Publisher text has been removed.</p>')
    parts.append('<nav class="toc" aria-label="Report sections">'+''.join(
        '<a href="#'+anchor+'">'+esc(label)+'</a>' for anchor, label in SECTIONS)+'</nav>')
    parts.append('<section id="conclusions"><h2>What the agent concluded</h2>')
    parts.extend(conclusion_card(o, record, labels) for o in converged)
    if not converged:
        parts.append('<p class="empty">No directional narrative converged in this record.</p>')
    parts.append('</section>')
    parts.append('<section id="decision-summary"><h2>Decision summary</h2><p>'+esc(f"{counts['posts']} posts; {counts['converged_narratives']} converged narratives; {counts['practice_positions']} practice positions; {counts['rejections']} rejected token/direction candidates.")+'</p>')
    accepted = [o for o in record['outcomes'] if o['decision']['kind']=='practice_position']
    rows=[]
    for outcome in accepted:
        p=outcome['decision']; n=outcome['narrative']
        rows.append((esc(p['token']+' '+p['direction']), esc(number(p.get('entry_price'))), esc(f"{number(p.get('units'))} units / ${number(p.get('notional'))}"), esc(number(p.get('stop'))), esc(number(p.get('take_profit'))),esc(p.get('time_stop')),esc(f"{number(n.get('distinct_voices'))} voices, weight {number(n.get('total_weight'))}; market {number((outcome.get('evidence') or {}).get('status'))}; stop risk ${number(p.get('risk_amount'))}.")))
    parts.append(table(['Practice position','Entry USD','Size','Stop','Take profit','Time stop UTC','Reason'],rows) if rows else '<p><b>No practice position opened.</b> The rules and failed checks below explain why.</p>')
    parts.append('<p>State: '+('degraded; thresholds unchanged' if record['degraded'] else 'completed')+'. Headlines are imperfect lexical evidence, not calibrated predictions. Position entry uses the latest completed candle close as a practice reference.</p></section>')
    parts.append('<section id="why"><h2>Why</h2><p>Posts → one vote per publisher → directional convergence → completed-candle return and volume → cross-venue agreement → risk sizing. Trust weights are explicit configuration choices. RSS and Bluesky from the same publisher share one vote.</p>')
    for group_title, group, collapsed in (
        ('Converged directional narratives', converged, False),
        ('Directional candidates that did not converge', candidates, False),
        ('Neutral mentions (no direction)', neutral, True),
    ):
        parts.append('<details class="neutral-mentions"><summary>'+group_title+'</summary>' if collapsed else '<h3>'+group_title+'</h3>')
        if not group:
            parts.append('<p class="empty">None in this record.</p>')
        parts.extend(narrative_details(o) for o in group)
        if collapsed:
            parts.append('</details>')
    parts.append('<h3>Market-wide liquidity</h3><p>USDC/USDT mint, burn and large-transfer observations describe market-wide liquidity. They are not a buy/sell signal for any token and do not vote in its decision.</p><pre>'+esc(json.dumps(record['liquidity'],indent=2))+'</pre>')
    parts.append('<p>Coverage: '+esc(json.dumps(record['coverage']))+'</p></section>')
    parts.append('<section id="cause-and-effect"><h2>Cause and effect</h2><p>Each intervention reruns convergence, market checks and portfolio allocation. “Pivotal” means removing that voice flips acceptance. Convergence-only pivotal voices are shown separately. No listed flip means none in the tested steps, not proof of global insensitivity.</p>')
    parts.append(table(['Candidate','Decision-pivotal voices','Convergence-pivotal voices','Thresholds that flip acceptance'],[(esc(c['token']+' '+c['direction']),esc(', '.join(c['pivotal_voices']) or 'none'),esc(', '.join(c['convergence_pivotal_voices']) or 'none'),esc(json.dumps(c['sensitive_thresholds']) if c['sensitive_thresholds'] else 'none in tested steps')) for c in record['counterfactuals']]))
    parts.append('<details><summary>All intervention values and results</summary><pre>'+esc(json.dumps(record['counterfactuals'],indent=2))+'</pre></details></section>')
    parts.append('<section id="rejections"><h2>Rejection ledger</h2>')
    parts.append(table(['Token / direction','Failed rules (actual → required)'],[(esc(o['decision']['token']+' '+o['decision']['direction']),'<br>'.join(esc(f"{c['rule']}: {number(c['actual'])} → {number(c['expected'])}") for c in o['decision']['failed_rules'])) for o in record['outcomes'] if o['decision']['kind']=='rejection']))
    parts.append('</section><section id="sources"><h2>Source health and provenance</h2>')
    parts.append(table(['Source','State','Detail','Posts in window'],[(esc(h['source']),tag('degraded source', 'degraded')+' '+esc(h['state']) if h['state'] != 'healthy' else esc(h['state']),esc(h['detail']),esc(counts['posts_by_source'].get(h['source'],'—'))) for h in record['source_health']]))
    # Aggregate identical response hashes; every item reference remains in snapshot and record.
    seen={}
    for p in record['provenance']:
        key=(p['source'],p['endpoint'],p.get('response_sha256',''),p['fetch_time'])
        seen[key]=p
    parts.append(table(['Source / endpoint','Fetched UTC','HTTP','Response SHA-256'],[(esc(p['source'])+'<br><small>'+esc(p['endpoint'])+'</small>',esc(p['fetch_time']),esc(p['http_status']),'<code>'+esc(p.get('response_sha256','unavailable'))+'</code>') for p in seen.values()]))
    parts.append('<p>Per-item content hashes and RPC request ranges are in snapshot.json and record.json. Response hashes identify the original HTTP bytes; full post/article text is discarded. Excerpts are limited to 140 characters.</p></section>')
    parts.append('<section id="replay"><h2>Replay</h2><p>From the repository root, run:</p><pre>python3 -m convergence_desk.cli replay '+esc(snapshot['run_path'])+'/snapshot.json</pre><p>Replay reads only the snapshot, including saved extracted features; it performs no network requests and does not change the practice ledger.</p><p>Decision SHA-256: <code>'+esc(record['decision_hash'])+'</code></p><p>Snapshot SHA-256: <code>'+esc(record['snapshot_hash'])+'</code></p></section></main></body></html>')
    return ''.join(parts)
