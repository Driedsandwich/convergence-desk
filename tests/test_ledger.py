"""Synthetic lifecycle boundary tests; never written into live/demo inputs."""
from dataclasses import asdict, replace
from datetime import timedelta
import pytest
from convergence_desk import ledger
from convergence_desk.core.pipeline import evaluate
from convergence_desk.core.models import MarketBar, PracticePosition
from convergence_desk.runtime import plain


@pytest.fixture
def position(snapshot):
    return next(o.decision for o in evaluate(snapshot) if isinstance(o.decision,PracticePosition))


def setup_ledger(tmp_path,position):
    path=tmp_path/'practice.jsonl'
    event=dict(event='open',event_id='test-open',position_id='test-open',practice_only=True,
               market_source='coinbase',position=plain(position))
    ledger.append(path,[event,event])
    assert len(ledger.read(path))==1
    return path


@pytest.mark.parametrize('reason', ['stop','take_profit','both','time_stop'])
def test_practice_exits_and_gross_loss(tmp_path,position,reason):
    if reason=='time_stop':
        position=replace(position,time_stop=position.opened_at+timedelta(hours=1))
    path=setup_ledger(tmp_path,position)
    high=position.entry_price+1
    low=position.entry_price-1
    if reason in ('stop','both'): low=position.stop-1
    if reason in ('take_profit','both'): high=position.take_profit+1
    bar=MarketBar(position.token,position.opened_at,position.entry_price,high,low,position.entry_price,
                  100,'coinbase',position.opened_at+timedelta(hours=1))
    remaining,loss,closes,notes=ledger.evaluate(path,[bar],bar.end)
    assert not remaining and len(closes)==1 and not notes
    assert closes[0]['reason']==('stop' if reason=='both' else reason)
    assert loss==pytest.approx(position.risk_amount if reason in ('stop','both') else 0)
    ledger.append(path,closes)
    again,again_loss,duplicate,_=ledger.evaluate(path,[bar],bar.end)
    assert not again and not duplicate and again_loss==loss


def test_unobservable_gap_never_invents_exit(tmp_path,position):
    path=setup_ledger(tmp_path,position)
    begin=position.opened_at+timedelta(hours=5)
    bar=MarketBar(position.token,begin,position.entry_price,position.entry_price+1,position.stop-1,
                  position.entry_price,100,'coinbase',begin+timedelta(hours=1))
    remaining,_,closes,notes=ledger.evaluate(path,[bar],bar.end)
    assert len(remaining)==1 and not closes and notes


def test_adverse_gap_fills_at_open(tmp_path,position):
    path=setup_ledger(tmp_path,position)
    price=position.stop-2
    bar=MarketBar(position.token,position.opened_at,price,price+1,price-1,price,100,'coinbase',position.opened_at+timedelta(hours=1))
    _,loss,closes,_=ledger.evaluate(path,[bar],bar.end)
    assert closes[0]['exit_price']==price
    assert loss>position.risk_amount


def test_one_missing_hour_defers_exit(tmp_path,position):
    path=setup_ledger(tmp_path,position)
    # The first full hour is missing. A later stop touch cannot establish when
    # the position exited or whether an earlier target was hit.
    begin=position.opened_at+timedelta(hours=1)
    bar=MarketBar(position.token,begin,position.entry_price,position.entry_price+1,position.stop-1,
                  position.entry_price,100,'coinbase',begin+timedelta(hours=1))
    remaining,_,closes,notes=ledger.evaluate(path,[bar],bar.end)
    assert len(remaining)==1 and not closes and notes
