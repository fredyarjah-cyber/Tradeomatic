import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import create_engine
from backend import db, worker, service
from backend.engine import demo_bars
from backend.intelligence import recommend

NOW=datetime(2026,11,17,4,20,tzinfo=timezone.utc)
EARLIER=datetime(2026,11,17,3,20,tzinfo=timezone.utc)

@pytest.fixture(autouse=True)
def setup(monkeypatch,tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'recovery.db'))
    monkeypatch.setattr(db,'engine',engine)
    monkeypatch.setenv('DATA_MODE','provider')
    monkeypatch.setenv('DATA_ENTITLEMENT','real-time')
    monkeypatch.setenv('REQUEST_SPACING_SECONDS','0')
    class Clock:
        @staticmethod
        def now(tz=None):return NOW
    monkeypatch.setattr(worker,'datetime',Clock)
    monkeypatch.setattr(worker,'market_open',lambda symbol:True)
    db.init()
    db.put('config','scanner',{'enabled':True,'symbols':['EUR/USD'],'intervals':['1h']})
    async def fetch(symbol,interval):return demo_bars(symbol,interval,NOW), 'REAL-TIME'
    monkeypatch.setattr(worker,'fetch',fetch)
    yield
    engine.dispose()


def test_legacy_outage_cannot_poison_later_completed_candle():
    old=recommend('EUR/USD','1h',[],[],service.settings(),{'market_status':'unknown','data_mode':'REAL-TIME'},now=EARLIER.timestamp())
    old.update(reason='Data unavailable; recommendation suppressed',reasons=['Data unavailable; recommendation suppressed'])
    db.put_once('signals',old['id'],old)
    asyncio.run(worker.scan_once())
    row=db.get('quotes','EUR/USD:1h')
    assert row['id']=='recovered:'+old['id']
    assert row['status']=='ok' and row['features']
    assert row['reason']!=old['reason'] and row['generated_at']==NOW.isoformat()
    assert row['last_checked_at']==NOW.isoformat()
    assert db.get('signals',old['id'])==old
    records=len(db.listing('signals'))
    asyncio.run(worker.scan_once())
    assert len(db.listing('signals'))==records
    assert db.get('quotes','EUR/USD:1h')['id']==row['id']
    # Recovery does not bypass the real-data readiness checks.
    assert row['recommendation']=='NO'
    assert 'validated cost' in row['reason'] and 'coverage' in row['reason']


def test_new_outage_uses_separate_id_and_does_not_create_paper_trade(monkeypatch):
    monkeypatch.setattr(worker,'fetch',AsyncMock(side_effect=RuntimeError('private transport detail')))
    asyncio.run(worker.scan_once())
    failure=db.get('quotes','EUR/USD:1h')
    assert failure['id'].startswith('data-error:') and failure['data_error']
    assert failure['status']=='error' and 'private' not in str(failure)
    async def fetch(symbol,interval):return demo_bars(symbol,interval,NOW), 'REAL-TIME'
    monkeypatch.setattr(worker,'fetch',fetch)
    asyncio.run(worker.scan_once())
    row=db.get('quotes','EUR/USD:1h')
    assert not row['id'].startswith('data-error:') and row['status']=='ok'
    assert db.get('signals',failure['id'])['reason']==failure['reason']
    assert db.listing('paper')==[]


def test_existing_confirmed_result_keeps_its_identity():
    asyncio.run(worker.scan_once())
    first=db.get('quotes','EUR/USD:1h')
    asyncio.run(worker.scan_once())
    second=db.get('quotes','EUR/USD:1h')
    assert first['id']==second['id'] and not second['id'].startswith('recovered:')
    assert len(db.listing('signals'))==1
