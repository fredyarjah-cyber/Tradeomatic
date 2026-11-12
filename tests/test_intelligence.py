import copy, time
from datetime import datetime, timezone
import pytest
from backend import db, service
from backend.engine import demo_bars, SYMBOLS
from backend.intelligence import *
from backend.paper import approve, advance, request_exit, portfolio_summary, performance
from backend.backtest import aggregate, replay, walk_forward
from backend.app import app
from fastapi.testclient import TestClient

NOW=datetime(2026,11,12,15,tzinfo=timezone.utc).timestamp()

def yes_signal():
    for symbol in SYMBOLS:
        b=demo_bars(symbol,now=datetime.fromtimestamp(NOW,timezone.utc));h=demo_bars(symbol,'4h',datetime.fromtimestamp(NOW,timezone.utc))
        r=recommend(symbol,'1h',b,h,context=service.context(symbol,'SIMULATED',NOW),now=NOW)
        if r['recommendation']=='YES':
            r['costs']['min_units']=1;r['costs']['unit_step']=1
            return r,b,h
    raise AssertionError('Synthetic fixture should provide a controlled YES case')

def later_bar(s,**changes):
    p=s['entry'];b={'time':int(NOW),'open':p,'high':p*1.0001,'low':p*.9999,'close':p,'volume':100000};b.update(changes);return b

def test_signal_complete_fields_and_net_rr():
    s,b,h=yes_signal()
    for field in ['recommendation','entry_zone','stop','target1','target2','sizing','generated_at','expires_at','market_status','data_age_seconds','score','reasons']:assert field in s
    assert s['confidence'] is None and s['target1']!=s['target2']
    sign=1 if s['decision']=='BUY' else -1;c=s['costs'];p=s['entry'];q=s['quote_to_usd']
    friction=2*p*(c['spread_bps']/2+c['slippage_bps'])/10000+2*c['commission_per_unit']/q
    assert (sign*(s['target1']-p)-friction)/(abs(p-s['stop'])+friction)==pytest.approx(2)

def test_no_future_data_or_incomplete_higher_candle():
    s,b,h=yes_signal();symbol=s['symbol'];ctx=service.context(symbol,'SIMULATED',NOW)
    future={**h[-1],'time':NOW+3600,'close':h[-1]['close']*50,'high':h[-1]['high']*60}
    a=recommend(symbol,'1h',b,h,context=ctx,now=NOW)
    z=recommend(symbol,'1h',b+[{'time':NOW+3600,'open':1,'high':2,'low':.5,'close':1}],h+[future],context=ctx,now=NOW)
    assert a==z
    x=recommend(symbol,'1h',b,[],context=ctx,now=NOW)
    assert x['recommendation']=='NO' and 'higher-timeframe' in x['reason']

def test_missing_events_blackout_costs_and_stale_data_block():
    s,b,h=yes_signal();ctx=service.context(s['symbol'],'SIMULATED',NOW)
    for changed in [{**ctx,'events':{}},{**ctx,'costs':{**ctx['costs'],'validated':False}},{**ctx,'data_mode':'DELAYED'},{**ctx,'market_status':'closed'}]:
        assert recommend(s['symbol'],'1h',b,h,context=changed,now=NOW)['recommendation']=='NO'
    ctx['events']['items']=[{'title':'CPI','time':NOW+100,'known_at':NOW-1000,'importance':'high'}]
    r=recommend(s['symbol'],'1h',b,h,context=ctx,now=NOW);assert r['recommendation']=='NO' and 'CPI' in r['reason']
    assert recommend(s['symbol'],'1h',b,h,context=ctx,now=NOW+10000)['recommendation']=='NO'

def test_intrabar_cannot_be_approved():
    s,b,h=yes_signal();r=recommend(s['symbol'],'1h',b,h,context=service.context(s['symbol'],'SIMULATED',NOW),now=NOW,alert_mode='intrabar')
    assert r['provisional']
    with pytest.raises(ValueError,match='confirmed'):approve(r,DEFAULT_SETTINGS,[],NOW)

def test_broker_lots_conversion_leverage_and_portfolio_rejections():
    c=assumptions('EUR/USD',True,NOW);settings={**DEFAULT_SETTINGS,'allocation':10000,'leverage':10,'max_exposure_pct':200}
    result=size_position('EUR/USD',1.1,1.09,settings,c,1)
    assert result['accepted'] and result['units']%1000==0 and result['lots']==result['units']/100000 and result['risk_usd']<=100
    for p in [{'open_count':3},{'exposure':20000},{'daily_loss':300},{'open_risk':300},{'margin':10000}]:assert not size_position('EUR/USD',1.1,1.09,settings,c,1,p)['accepted']
    assert not size_position('EUR/USD',1.1,1.09,{**settings,'emergency_stop':True},c,1)['accepted']
    assert conversion('EUR/JPY',160,{},NOW) is None
    assert conversion('USD/JPY',150,{},NOW)==pytest.approx(1/150)
    with pytest.raises(ValueError):RiskSettings(risk_pct=float('nan'))

def test_approval_expiry_duplicate_and_no_same_bar_fill():
    s,_,_=yes_signal();t=approve(s,DEFAULT_SETTINGS,[],NOW)
    assert t['status']=='PENDING_ENTRY'
    with pytest.raises(ValueError,match='already'):approve(s,DEFAULT_SETTINGS,[t],NOW)
    with pytest.raises(ValueError,match='expired'):approve(s,DEFAULT_SETTINGS,[],timestamp(s['expires_at']))
    before=advance(t,[later_bar(s,time=int(NOW)-3600)],NOW)
    assert before['status']=='PENDING_ENTRY' and not before['fills']
    after=advance(t,[later_bar(s)],NOW+3600)
    assert after['status']=='OPEN' and len(after['fills'])==1
    assert advance(after,[later_bar(s)],NOW+3600)==after

def test_ambiguous_bar_uses_stop_and_gap_is_adverse():
    s,_,_=yes_signal();t=approve(s,DEFAULT_SETTINGS,[],NOW)
    hi=max(s['entry'],s['target2'],s['stop'])*1.001;lo=min(s['entry'],s['target2'],s['stop'])*.999
    result=advance(t,[later_bar(s,high=hi,low=lo)],NOW+3600)
    assert result['status']=='CLOSED' and result['pnl']<0 and 'stop-first' in result['fills'][-1]['reason']
    assert t['status']=='PENDING_ENTRY' # No mutation.

def test_partial_exit_adjustment_requires_approval_and_emergency_stop():
    s,_,_=yes_signal();sign=1 if s['decision']=='BUY' else -1;t=approve(s,DEFAULT_SETTINGS,[],NOW)
    bar=later_bar(s,high=max(s['entry'],s['target1']),low=min(s['entry'],s['target1']),close=s['target1'])
    result=advance(t,[bar],NOW+3600)
    assert result['status']=='PARTIAL' and result['remaining_units']<result['units'] and result['stop']==s['stop']
    assert result['exit_recommendation']=='ADJUST STOP LOSS'
    adjusted=request_exit(result,'adjust_stop',NOW+3600,s['entry'])
    assert adjusted['pending_stop']['price']==s['entry'] and adjusted['stop']==s['stop'] and result['stop']==s['stop']
    with pytest.raises(ValueError):request_exit(result,'adjust_stop',NOW+3600,s['stop']-sign)
    killed=advance(t,[later_bar(s)],NOW+3600,{**DEFAULT_SETTINGS,'emergency_stop':True})
    assert killed['status']=='CANCELLED'

def test_immutable_signal_insert_and_settings_preserve_phase1():
    db.init();s,_,_=yes_signal();db.put('config','phase1_sentinel',{'unchanged':True})
    db.put_once('signals',s['id'],s);db.put_once('signals',s['id'],{**s,'decision':'SELL'})
    assert db.get('signals',s['id'])['decision']==s['decision']
    with TestClient(app) as c:
        h={'Authorization':'Bearer '+'a'*40}
        assert c.get('/api/v2/state').status_code==401
        assert c.patch('/api/v2/settings',headers=h,json={'risk_pct':.5}).status_code==200
        assert db.get('config','phase1_sentinel')['unchanged']
        assert c.patch('/api/v2/settings',headers=h,json={'nonsense':3}).status_code==422
        service.save_settings(DEFAULT_SETTINGS)

def test_performance_cost_adjusted_metrics_and_no_invented_winrate():
    assert performance([])['win_rate'] is None
    trades=[{'status':'CLOSED','closed_at':i,'pnl':p,'risk_usd':100} for i,p in enumerate([200,-100,50])]
    m=performance(trades)
    assert m['win_rate']==pytest.approx(2/3) and m['profit_factor']==2.5 and m['average_r_multiple']==.5 and m['max_drawdown_pct']>0

def test_aggregate_only_full_higher_bars_and_walkforward_dates():
    bars=demo_bars('USD/JPY',now=datetime.fromtimestamp(NOW,timezone.utc),count=620)
    h=aggregate(bars,'1h','4h');assert all(b['time']%14400==0 for b in h)
    missing=aggregate(bars[:3],'1h','4h');assert not missing
    ctx=service.context('USD/JPY','SIMULATED',NOW);ctx['costs']['valid_until']=NOW+86400
    report=walk_forward(bars,'USD/JPY','1h',context=ctx,train_bars=200,test_bars=80)
    assert len(report['folds'])==2
    for f in report['folds']:assert f['train_end']<=f['test_start']<f['test_end']
    assert report['source']=='SIMULATED' and 'No profitability' in report['limitations'][0]

def test_api_paper_approval_emergency_stop_and_additive_records():
    db.init();s,_,_=yes_signal();s={**s,'id':'test-api-confirmed-v2','expires_at':iso(time.time()+3600)};db.put_once('signals',s['id'],s)
    # Use a clean isolated trade list while preserving unrelated records for this test.
    from sqlalchemy import delete
    with db.engine.begin() as c:c.execute(delete(db.records).where(db.records.c.kind=='paper'))
    with TestClient(app) as c:
        h={'Authorization':'Bearer '+'a'*40}
        response=c.post('/api/v2/paper',headers=h,json={'signal_id':s['id']});assert response.status_code==200,response.text
        t=response.json();assert t['status']=='PENDING_ENTRY'
        assert c.post('/api/v2/paper',headers=h,json={'signal_id':s['id']}).status_code==422
        assert c.patch('/api/v2/settings',headers=h,json={'emergency_stop':True}).status_code==200
        assert db.get('paper',t['id'])['status']=='CANCELLED'
        assert db.get('signals',s['id'])['decision']==s['decision']
        assert c.get('/api/v2/state',headers=h).json()['settings']['emergency_stop']
        service.save_settings(DEFAULT_SETTINGS)

def test_discovery_paused_still_monitors_approved_paper(monkeypatch):
    import asyncio
    from backend.worker import scan_once
    from unittest.mock import AsyncMock
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromtimestamp(NOW+3600,timezone.utc)
    monkeypatch.setattr('backend.worker.datetime',Clock)
    s,_,_=yes_signal();s['id']='paused-monitor';t=approve(s,DEFAULT_SETTINGS,[],NOW)
    db.init();db.put('paper',t['id'],t);db.put('config','scanner',{'enabled':False,'symbols':[s['symbol']],'intervals':['1h']})
    monkeypatch.setattr('backend.worker.fetch',AsyncMock(return_value=([later_bar(s)],'SIMULATED')))
    asyncio.run(scan_once());assert db.get('paper',t['id'])['status']=='OPEN'

def test_exact_indicator_warmup_and_expiration_without_market_bars():
    s,b,h=yes_signal()
    r=recommend(s['symbol'],'1h',b[-60:],h,context=service.context(s['symbol'],'SIMULATED',NOW),now=NOW)
    assert r['recommendation'] in ('YES','NO')
    t=approve(s,DEFAULT_SETTINGS,[],NOW)
    expired=advance(t,[],timestamp(t['expires_at'])+1)
    assert expired['status']=='EXPIRED'
