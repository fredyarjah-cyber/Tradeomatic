import os, asyncio
os.environ['DATABASE_URL']='sqlite://'
os.environ['ADMIN_TOKEN']='a'*40
os.environ['DATA_MODE']='demo'
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine
from backend import db
# Same in-memory database across TestClient threads.
db.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
from backend.engine import *
from backend.provider import market_open, fetch
from backend.worker import scan_once
from backend.app import app
from fastapi.testclient import TestClient
import pytest
from datetime import datetime, timezone

def test_risk_budget_and_allocation_caps():
    r=position_size(10000,10000,1,100,98)
    assert r['units']==50 and r['risk_usd']==100 and r['reward_usd']==200
    r=position_size(10000,1000,1,100,98)
    assert r['units']==10 and r['notional_usd']==1000
    r=position_size(10000,10000,1,150,149,1/150)
    assert r['risk_usd']<=100

@pytest.mark.parametrize('values',[(0,1,1,1,2),(100,101,1,1,2),(100,10,1,1,1),(float('nan'),10,1,1,2)])
def test_bad_risk(values):
    with pytest.raises(ValueError): position_size(*values)

def test_no_false_probability_and_flat_data():
    bars=[{'open':1,'high':1,'low':1,'close':1}]*100
    r=analyze(bars)
    assert r['decision']=='NO TRADE' and r['confidence'] is None and r['rsi']==50
    assert analyze(bars[:10])['decision']=='NO TRADE'

def test_calendar_holiday_and_forex_weekend():
    assert not market_open('AAPL',datetime(2026,12,25,16,tzinfo=timezone.utc))
    assert not market_open('EUR/USD',datetime(2026,11,14,16,tzinfo=timezone.utc))
    assert market_open('AAPL',datetime(2026,11,12,16,tzinfo=timezone.utc))

def test_scanner_dedup_stop_and_auth():
    with TestClient(app) as c:
        assert c.get('/api/snapshot').status_code==401
        h={'Authorization':'Bearer '+'a'*40}
        assert c.post('/api/scanner',headers=h,json={'enabled':True,'symbols':['EUR/USD'],'intervals':['1h']}).status_code==200
        asyncio.run(scan_once()); first=len(db.listing('signals')); asyncio.run(scan_once())
        assert len(db.listing('signals'))==first
        data=c.get('/api/snapshot',headers=h).json()
        assert data['quotes'][0]['mode']=='SIMULATED' and data['worker']['heartbeat']
        assert c.post('/api/scanner',headers=h,json={'enabled':False,'symbols':['EUR/USD'],'intervals':['1h']}).status_code==200
        prior=db.listing('quotes'); asyncio.run(scan_once()); assert prior==db.listing('quotes')
        assert c.post('/api/orders',headers=h).status_code==403
        assert c.post('/api/scanner',headers=h,json={'enabled':True,'symbols':['BAD'],'intervals':['1h']}).status_code==422
        assert c.post('/api/journal',headers=h,json={'symbol':'EUR/USD','direction':'BUY','notes':'Test','pnl':5}).status_code==200
        assert c.get('/api/snapshot',headers=h).json()['journal'][0]['pnl']==5

def test_provider_approval_gate(monkeypatch):
    monkeypatch.setenv('DATA_MODE','provider');monkeypatch.setenv('PROVIDER_APPROVED','false')
    with pytest.raises(RuntimeError,match='approval'): asyncio.run(fetch('EUR/USD','1h'))

def test_stale_worker_suppresses_provider_recommendations():
    from backend.app import current_quotes
    db.init()
    db.put('health','worker',{'heartbeat':'2020-01-01T00:00:00+00:00'})
    db.put('quotes','AAPL:1h',{'symbol':'AAPL','interval':'1h','mode':'DELAYED','status':'ok','decision':'BUY','entry':100,'stop':99,'target':102,'bars':[]})
    row=next(r for r in current_quotes() if r['symbol']=='AAPL')
    assert row['decision']=='NO TRADE' and row['entry'] is None and row['status']=='stale'

def test_provider_closed_candle_filter(monkeypatch):
    import httpx
    from unittest.mock import AsyncMock
    monkeypatch.setenv('DATA_MODE','provider');monkeypatch.setenv('PROVIDER_APPROVED','true');monkeypatch.setenv('TWELVEDATA_API_KEY','not-real');monkeypatch.setenv('DATA_ENTITLEMENT','delayed')
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    recent=datetime.fromtimestamp(now.timestamp()-3600,timezone.utc)
    response=httpx.Response(200,json={'values':[{'datetime':t.strftime('%Y-%m-%d %H:%M:%S'),'open':'1','high':'1.1','low':'.9','close':'1','volume':None} for t in [now,recent]]},request=httpx.Request('GET','https://api.twelvedata.com/time_series'))
    monkeypatch.setattr(httpx.AsyncClient,'get',AsyncMock(return_value=response))
    bars,mode=asyncio.run(fetch('EUR/USD','1h'))
    assert len(bars)==1 and bars[0]['time']==int(recent.timestamp()) and mode=='DELAYED'
