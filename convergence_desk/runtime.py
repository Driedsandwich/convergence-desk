"""Privacy-preserving engine integration, including a two-venue evidence gate.

Full source text is extracted in memory by adapters. Replay uses those stored
features, not excerpts. The immutable core is unchanged.
"""
from dataclasses import asdict, replace
import json
from convergence_desk.core.models import (Post, Voice, Signal, Score, Rules, RiskLimits,
    MarketBar, PracticePosition, RuleCheck, Outcome)
from convergence_desk.core.converge import converge
from convergence_desk.core.evidence import check_evidence
from convergence_desk.core.decide import decide
from convergence_desk.core.trail import canonical_json, content_hash, _position
from .sources.common import dt


def plain(value):
    return json.loads(canonical_json(value))


def inputs(snapshot, rules_override=None, excluded_voice=None):
    rules = Rules(**(rules_override or snapshot['rules']))
    voices = tuple(Voice(v['voice_id'], v['label'], 'voices', v['trust_weight'])
                   for v in snapshot['voices'] if v['voice_id'] != excluded_voice)
    signals = []
    for row in snapshot['posts']:
        post = Post('voices', row['author_id'], row['author_label'], row['uri'], dt(row['created_at']), row['excerpt'])
        for feature in row['features']:
            value = dict(feature)
            for key in ('sentiment', 'conviction', 'urgency'):
                value[key] = Score(value[key]['value'], tuple(value[key]['fired']))
            value['token_rules'] = tuple(value['token_rules'])
            signals.append(Signal(post=post, **value))
    bars = tuple(MarketBar(**{**b, 'start': dt(b['start']), 'end': dt(b['end'])}) for b in snapshot['market_bars'])
    return rules, voices, tuple(signals), bars


def venue_evidence(narrative, bars, rules, as_of, max_spread):
    """Compare completed closes at the same endpoint and window return signs.

    Prefer the two primary venues. Do not average venue volumes. CoinGecko is
    price-only context; Binance uses a USDT quote, explicitly disclosed.
    """
    sources = [s for s in ('coinbase', 'kraken', 'binance', 'coingecko')
               if any(b.symbol == narrative.token and b.source == s for b in bars)]
    selected = sources[:2]
    relevant = [b for b in bars if b.symbol == narrative.token]
    common = set.intersection(*({b.available_at for b in relevant if b.source == s} for s in selected)) if len(selected) == 2 else set()
    endpoint = max(common) if common else None
    checks = {}
    for source in selected:
        series = [b for b in relevant if b.source == source and (endpoint is None or b.available_at <= endpoint)]
        checks[source] = check_evidence(narrative, series, rules, as_of)
    primary = checks[selected[0]] if selected else check_evidence(narrative, (), rules, as_of)
    spread = None
    aligned = False
    fresh = False
    if len(selected) == 2 and endpoint is not None:
        left, right = (checks[s] for s in selected)
        if left.entry_price and right.entry_price:
            spread = abs(left.entry_price-right.entry_price) / min(left.entry_price,right.entry_price)
        if left.return_fraction is not None and right.return_fraction is not None:
            aligned = (left.return_fraction > 0) == (right.return_fraction > 0) and (left.return_fraction < 0) == (right.return_fraction < 0)
        fresh = all(all(c.passed for c in e.checks if c.rule in ('market_fresh','window_anchor','window_endpoint')) for e in (left,right))
    agreement = endpoint is not None and fresh and aligned and spread is not None and spread <= max_spread
    status = 'agreement' if agreement else 'disagreement' if endpoint and fresh and spread is not None else 'unavailable'
    details = dict(status=status, venues=selected, common_completed_endpoint=endpoint,
                   relative_close_spread=spread, max_spread=max_spread, same_return_direction=aligned,
                   venue_evidence={s: asdict(e) for s,e in checks.items()})
    extra = (RuleCheck('two_venues', len(selected)==2, len(selected), 2),
             RuleCheck('cross_venue_agreement', agreement, status, 'agreement',
                       f'spread={spread}; max={max_spread}; aligned_return_sign={aligned}; common_endpoint={endpoint}'))
    notes = list(primary.notes)
    notes.append('Cross-venue check: ' + status + '; venues=' + ', '.join(selected))
    if 'binance' in selected:
        notes.append('Binance is quoted in USDT; USD/USDT basis is included in the spread tolerance.')
    if 'coingecko' in selected:
        notes.append('CoinGecko OHLC has no per-bar volume; used for price context only.')
    result_status = primary.status if agreement else 'contradict' if status == 'disagreement' else 'inconclusive'
    return replace(primary, status=result_status, checks=primary.checks+extra, notes=tuple(notes)), details


def evaluate(snapshot, *, rules_override=None, excluded_voice=None):
    rules, voices, signals, bars = inputs(snapshot, rules_override, excluded_voice)
    as_of = dt(snapshot['as_of'])
    narratives = converge(signals, voices, rules, as_of)
    ordered = sorted(narratives, key=lambda n: (-n.total_weight, -n.distinct_voices, n.token, n.direction))
    positions = [_position(p) for p in snapshot.get('open_positions', [])]
    outcomes, venue_details = [], {}
    for narrative in ordered:
        conflict = narrative.converged and any(n.converged and n.token == narrative.token and n.direction != narrative.direction for n in narratives)
        evidence, details = venue_evidence(narrative, bars, rules, as_of, snapshot['source_rules']['cross_venue_max_spread'])
        decision = decide(narrative, evidence, RiskLimits(**snapshot['risk_limits']), rules, positions,
                          snapshot.get('realized_loss_today', 0), as_of, conflicting_direction=conflict)
        outcomes.append(Outcome(narrative, evidence, decision))
        venue_details[(narrative.token, narrative.direction)] = details
        if isinstance(decision, PracticePosition):
            positions.append(decision)
    return tuple(outcomes), venue_details


def interventions(snapshot, baseline):
    variants = []
    for voice in sorted(snapshot['voices'], key=lambda v: v['voice_id']):
        variants.append(('leave_out_voice', voice['voice_id'], dict(excluded_voice=voice['voice_id'])))
    rules = snapshot['rules']
    for name, step, minimum, maximum in (
        ('quorum_weight', rules['quorum_step'], 0, None),
        ('min_conviction', rules['conviction_step'], 0, 1),
        ('market_min_return', .005, .000001, None),
        ('market_min_volume_z', .5, 0, None)):
        for sign in (-1, 1):
            value = max(minimum, round(rules[name] + sign*step, 10))
            if maximum is not None:
                value = min(maximum, value)
            variants.append((name, value, dict(rules_override={**rules, name:value})))
    variants.append(('drop_market_evidence', True, dict(rules_override={**rules, 'require_market_evidence': False})))
    reports = {(o.narrative.token,o.narrative.direction): dict(token=o.narrative.token, direction=o.narrative.direction,
                pivotal_voices=[], convergence_pivotal_voices=[], sensitive_thresholds=[], trials=[]) for o in baseline}
    for change, value, kwargs in variants:
        alternatives, _ = evaluate(snapshot, **kwargs)
        mapping = {(o.narrative.token,o.narrative.direction): o for o in alternatives}
        for original in baseline:
            key = (original.narrative.token,original.narrative.direction)
            alternative = mapping.get(key)
            accepted = isinstance(original.decision, PracticePosition)
            alt_accepted = alternative is not None and isinstance(alternative.decision, PracticePosition)
            flipped = accepted != alt_accepted
            report = reports[key]
            report['trials'].append(dict(change=change, value=value, baseline_accepted=accepted,
                alternative_accepted=alt_accepted, flipped=flipped,
                failed_rules=[c.rule for c in alternative.decision.failed_rules] if alternative and not alt_accepted else [] if alternative else ['no_candidate_after_intervention']))
            if change == 'leave_out_voice':
                if flipped:
                    report['pivotal_voices'].append(value)
                if original.narrative.converged and (alternative is None or not alternative.narrative.converged):
                    report['convergence_pivotal_voices'].append(value)
            elif flipped:
                report['sensitive_thresholds'].append({'rule':change, 'value':value})
    return list(reports.values())


def make_record(snapshot):
    if snapshot.get('schema_version') != 1 or snapshot.get('runtime_version') != '1':
        raise ValueError('unsupported snapshot schema/runtime version')
    outcomes, details = evaluate(snapshot)
    encoded = []
    for outcome in outcomes:
        row = asdict(outcome)
        row['narrative']['members'] = [dict(uri=s.post.uri, voice_id=s.post.author_id, token=s.token,
            direction=s.direction, sentiment=asdict(s.sentiment), conviction=asdict(s.conviction),
            urgency=asdict(s.urgency), token_rules=s.token_rules) for s in outcome.narrative.members]
        row['cross_venue'] = details[(outcome.narrative.token, outcome.narrative.direction)]
        encoded.append(row)
    snapshot_inputs = {k:v for k,v in snapshot.items() if k != 'expected_decision_hash'}
    positions = sum(isinstance(o.decision, PracticePosition) for o in outcomes)
    record = dict(schema_version=1, runtime_version='1', as_of=snapshot['as_of'], practice_only=True,
        snapshot_hash=content_hash(snapshot_inputs), outcomes=encoded, counterfactuals=interventions(snapshot,outcomes),
        source_health=snapshot['source_health'], provenance=snapshot['provenance'],
        liquidity=snapshot['liquidity'], coverage=snapshot['coverage'],
        counts=dict(posts_by_source=snapshot['post_counts'], posts=len(snapshot['posts']),
                    converged_narratives=sum(o.narrative.converged for o in outcomes),
                    practice_positions=positions, rejections=len(outcomes)-positions),
        degraded=any(h['state']!='healthy' for h in snapshot['source_health']),
        recorded_test_fixture=snapshot.get('recorded_test_fixture',False))
    record = plain(record)
    record['decision_hash'] = content_hash(record)
    return record
