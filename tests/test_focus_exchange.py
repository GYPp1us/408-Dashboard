from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pytest

from app.focus_exchange import BookInput,ExchangeParameters,PriceBook,_BOOKS
from app.focus_kline import build_focus_klines,build_cached_focus_klines,build_live_focus_kline
from app.db import FOCUS_EXCHANGE_EFFECTIVE_KEY,connect,init_db,ensure_site_owner

DAY=datetime(2026,10,15,8,tzinfo=ZoneInfo('Asia/Shanghai'))
START=int(DAY.timestamp()*1000)

def inputs(ms):
    minute=(ms-START)/60000
    return BookInput(True,'morning',10<=minute<25,100,100,90,110)

def test_executions_are_actual_single_ticks_at_least_100ms_apart_and_replay_is_identical():
    book=PriceBook(START,100,42,record_trades=True)
    book.advance(START+20*60000,inputs)
    prefix=list(book.all_trades)
    book.advance(START+40*60000,inputs)
    rebuilt=PriceBook(START,100,42,record_trades=True).advance(START+40*60000,inputs)
    assert rebuilt.snapshot()==book.snapshot()
    assert rebuilt.all_trades[:len(prefix)]==prefix
    assert len(book.all_trades)>100
    previous=100
    for trade in book.all_trades:
        assert abs(trade['price']-previous)==pytest.approx(.001)
        previous=trade['price']
    assert all(b['timestamp_ms']-a['timestamp_ms']>=100 for a,b in zip(book.all_trades,book.all_trades[1:]))

def test_switch_pressure_releases_over_eight_minutes_and_opposing_toggles_cannot_stack():
    p=ExchangeParameters(noise_volatility=0)
    book=PriceBook(START,100,42,p)
    book.advance(START+15*60000,inputs)
    assert 0<book.pending_switch<p.switch_return
    book.advance(START+19*60000,inputs)
    assert book.pending_switch==pytest.approx(0,abs=1e-12)
    def toggles(ms):
        return BookInput(True,'morning',int((ms-START)/60000)%2==1,100,100,90,110)
    book=PriceBook(START,100,42,p)
    for minute in range(1,41):
        book.advance(START+minute*60000,toggles)
        assert abs(book.pending_switch)<=p.switch_return+1e-12


@pytest.mark.parametrize('side',[1,-1])
def test_value_zones_allow_outward_executions_and_add_opposing_momentum(side):
    def market(ms):
        return BookInput(True,'morning',side>0,100,100,90,110)
    p=ExchangeParameters(noise_volatility=0)
    book=PriceBook(START,100,42,p,record_trades=True)
    book.momentum=side*.04
    book.advance(START+45*60000,market)
    # Real orders keep moving outward past the configured 1.2% threshold.
    assert any(side*(t['price']-100)>1.3 and t['direction']==side for t in book.all_trades)
    assert side*book.reversion_momentum<0
    unopposed=PriceBook(START,100,42,ExchangeParameters(noise_volatility=0,reversion_strength=0))
    unopposed.momentum=side*.04
    unopposed.advance(START+45*60000,market)
    assert side*(book.price-100)<side*(unopposed.price-100)


def test_value_counterpressure_builds_and_decays_gradually_as_value_moves():
    value=100
    def market(ms):
        return BookInput(True,'morning',True,value,100,90,110)
    book=PriceBook(START,102.4,42,ExchangeParameters(noise_volatility=0))
    book.momentum=.04
    book.advance(START+1000,market)
    initial=book.reversion_momentum
    book.advance(START+119900,market)
    established=book.reversion_momentum
    assert established<initial<0
    # The new value puts the quote inside the zone; accumulated momentum
    # dissipates rather than reversing instantly or rewriting the quote.
    value=book.price
    previous_price=book.price
    book.advance(START+120000,market)
    assert established<book.reversion_momentum<0
    assert abs(book.price-previous_price)<=.001+1e-9

def test_no_execution_during_break_or_outside_limits():
    def market(ms):
        minute=(ms-START)/60000
        active=minute<5 or minute>=7
        return BookInput(active,'am' if minute<5 else 'pm',True,100,100,99.995,100.005)
    book=PriceBook(START,100,77,record_trades=True).advance(START+10*60000,market)
    assert all(99.995<=t['price']<=100.005 for t in book.all_trades)
    assert not any(START+5*60000<=t['timestamp_ms']<START+7*60000 for t in book.all_trades)

def test_cutover_preserves_old_points_and_close_remains_a_separate_value_auction():
    start=DAY+timedelta(hours=1,minutes=15,seconds=20)
    kwargs={'daily_focus_seconds':{DAY.date():3*3600},'daily_segments':{DAY.date():[(DAY,DAY+timedelta(hours=3))]},'user_key':28}
    old=build_focus_klines(now=start,**kwargs)[0]
    enabled=build_focus_klines(now=start,exchange_at=start,**kwargs)[0]
    assert enabled==old
    later=build_focus_klines(now=start+timedelta(minutes=10),exchange_at=start,**kwargs)[0]
    prefix=[p for p in later['intraday'] if datetime.fromisoformat(p['timestamp'])<=start]
    assert prefix==old['intraday']
    close=build_focus_klines(now=DAY.replace(hour=22),exchange_at=start,**kwargs)[0]
    legacy=build_focus_klines(now=DAY.replace(hour=22),**kwargs)[0]
    assert close['close']==legacy['close']
    assert close['intraday'][-1]['closing_auction'] is True

def database(tmp_path):
    db=connect(str(tmp_path/'exchange.sqlite3'));init_db(db)
    owner=ensure_site_owner(db,'owner','owner@example.invalid','unused')
    db.execute('UPDATE settings SET value=? WHERE key=?',(DAY.isoformat(),FOCUS_EXCHANGE_EFFECTIVE_KEY))
    db.execute("INSERT INTO focus_sessions(user_id,subject,mode,planned_minutes,started_at,status) VALUES (?,?,?,0,?,'active')",
               (owner,'数学','专注',(DAY+timedelta(hours=1)).isoformat()))
    db.commit()
    return db,owner

def test_live_and_history_share_the_same_real_quote_and_source_corrections_replay(tmp_path):
    db,owner=database(tmp_path)
    now=DAY+timedelta(hours=1,minutes=30,seconds=.5)
    full=build_cached_focus_klines(db,owner,now=now)[-1]
    live=build_live_focus_kline(db,owner,now=now)
    assert live['index']['current']==full['close']==full['exchange']['price']
    assert live['live_tick']['kind']=='executions' and live['live_tick']['per_second']==0
    assert live['trades'] and live['trades'][-1]['price']==live['index']['current']
    assert all(t['timestamp_ms']<=now.timestamp()*1000 for t in live['trades'])
    db.execute('UPDATE focus_sessions SET started_at=?',((DAY+timedelta(hours=1,minutes=10)).isoformat(),));db.commit()
    corrected=build_live_focus_kline(db,owner,now=now)
    _BOOKS.clear()
    rebuilt=build_live_focus_kline(db,owner,now=now)
    assert corrected==rebuilt
    db.close()


def test_retuned_ordinary_dynamics_invalidate_settled_cache_without_changing_settlement(tmp_path,monkeypatch):
    from app import focus_kline
    db,owner=database(tmp_path)
    db.execute("UPDATE focus_sessions SET ended_at=?,status='completed'",((DAY+timedelta(hours=3)).isoformat(),))
    db.commit()
    earlier=ExchangeParameters(noise_volatility=.003,value_relaxation_seconds=90)
    monkeypatch.setattr(focus_kline,'exchange_parameters_for',lambda *_:earlier)
    kwargs={'now':DAY+timedelta(days=1),'intraday_date':DAY.date()}
    old=build_cached_focus_klines(db,owner,**kwargs)[0]
    old_fingerprint=db.execute('SELECT cache_fingerprint FROM focus_klines').fetchone()[0]
    monkeypatch.setattr(focus_kline,'exchange_parameters_for',lambda *_:ExchangeParameters())
    new=build_cached_focus_klines(db,owner,**kwargs)[0]
    new_fingerprint=db.execute('SELECT cache_fingerprint FROM focus_klines').fetchone()[0]
    assert old_fingerprint!=new_fingerprint
    assert old['intraday']!=new['intraday']
    assert old['close']==new['close']
    assert build_cached_focus_klines(db,owner,**kwargs)[0]==new
    db.close()


@pytest.mark.parametrize('field,value',[('support_percent',0),('resistance_percent',float('nan')),('switch_minutes',2)])
def test_invalid_book_parameters_are_rejected(field,value):
    with pytest.raises(ValueError): ExchangeParameters(**{field:value})
