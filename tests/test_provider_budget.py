import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import create_engine
from backend import db
from backend.provider_budget import reserve, status, ProviderLimit
from backend.provider import fetch


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch, tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'budget.db'))
    monkeypatch.setattr(db, 'engine', engine)
    monkeypatch.setenv('PROVIDER_DAILY_CREDITS', '700')
    monkeypatch.setenv('PROVIDER_MINUTE_CREDITS', '6')
    db.init()
    yield
    engine.dispose()


def test_daily_cap_persists_and_resets_at_utc_midnight():
    start = datetime(2026, 11, 17, tzinfo=timezone.utc).timestamp()
    for i in range(700):
        reserve(start + i * 61)
    assert status(start + 700 * 61)['credits_remaining'] == 0
    with pytest.raises(ProviderLimit, match='Daily'):
        reserve(start + 700 * 61)
    reserve(start + 86400)
    assert status(start + 86400)['credits_reserved'] == 1


def test_sliding_window_cannot_burst_across_minute_boundary():
    for i in range(6):
        reserve(59 + i * .01)
    with pytest.raises(ProviderLimit, match='rate limit'):
        reserve(60)
    reserve(120)
    assert status(120)['credits_reserved'] == 7


def test_atomic_reservations_do_not_exceed_cap(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv('PROVIDER_DAILY_CREDITS', '3')
    def attempt(_):
        try:
            reserve(100)
            return True
        except ProviderLimit:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(12))) == 3
    assert status(100)['credits_reserved'] == 3


@pytest.mark.parametrize('name,value', [('PROVIDER_DAILY_CREDITS','801'), ('PROVIDER_MINUTE_CREDITS','9'), ('PROVIDER_DAILY_CREDITS','bad')])
def test_invalid_limits_block_requests(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ProviderLimit, match='Invalid'):
        reserve(100)
    assert db.get('provider_usage','twelvedata') is None


def provider_setup(monkeypatch):
    monkeypatch.setenv('DATA_MODE', 'provider')
    monkeypatch.setenv('PROVIDER_APPROVED', 'true')
    monkeypatch.setenv('DATA_ENTITLEMENT', 'real-time')
    monkeypatch.setenv('TWELVEDATA_API_KEY', 'private-mock-value')
    now = datetime.now(timezone.utc).timestamp()
    close = int(now // 3600) * 3600
    candle = {'datetime':datetime.fromtimestamp(close - 3600, timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
              'open':'1.1','high':'1.2','low':'1','close':'1.15'}
    response = httpx.Response(200, json={'values':[candle]}, request=httpx.Request('GET','https://api.twelvedata.com/time_series'))
    mock = AsyncMock(return_value=response)
    monkeypatch.setattr(httpx.AsyncClient, 'get', mock)
    return mock, now


def test_cache_avoids_duplicate_credits_and_gates_still_apply(monkeypatch):
    mock, now = provider_setup(monkeypatch)
    first = asyncio.run(fetch('EUR/USD', '1h'))
    assert asyncio.run(fetch('EUR/USD', '1h')) == first
    assert mock.await_count == 1 and status(now)['credits_reserved'] == 1
    assert 'private-mock-value' not in str(db.listing('provider_cache'))
    monkeypatch.setenv('PROVIDER_APPROVED','false')
    with pytest.raises(RuntimeError, match='approval'):
        asyncio.run(fetch('EUR/USD','1h'))
    assert mock.await_count == 1


def test_failed_transport_is_counted_without_retry(monkeypatch):
    mock, now = provider_setup(monkeypatch)
    mock.side_effect = httpx.ConnectError('mock failure')
    with pytest.raises(httpx.ConnectError):
        asyncio.run(fetch('EUR/USD','1h'))
    assert mock.await_count == 1 and status(now)['credits_reserved'] == 1


def test_cap_blocks_network_call(monkeypatch):
    mock, now = provider_setup(monkeypatch)
    monkeypatch.setenv('PROVIDER_DAILY_CREDITS', '1')
    reserve(now)
    with pytest.raises(ProviderLimit):
        asyncio.run(fetch('EUR/USD','1h'))
    assert mock.await_count == 0


def test_expired_cache_requires_another_counted_request(monkeypatch):
    mock, now = provider_setup(monkeypatch)
    asyncio.run(fetch('EUR/USD','1h'))
    from sqlalchemy import select
    with db.engine.connect() as connection:
        key = connection.execute(select(db.records.c.id).where(db.records.c.kind=='provider_cache')).scalar_one()
    cached = db.get('provider_cache', key)
    cached['refresh_at'] = now - 1
    db.put('provider_cache', key, cached)
    asyncio.run(fetch('EUR/USD','1h'))
    assert mock.await_count == 2 and status(now)['credits_reserved'] == 2


def test_invalid_numeric_candles_are_not_cached(monkeypatch):
    mock, now = provider_setup(monkeypatch)
    data = mock.return_value.json()
    data['values'][0]['high'] = 'Infinity'
    mock.return_value = httpx.Response(200,json=data,request=httpx.Request('GET','https://api.twelvedata.com/time_series'))
    with pytest.raises(RuntimeError,match='Invalid OHLC'):
        asyncio.run(fetch('EUR/USD','1h'))
    assert db.listing('provider_cache') == []
    assert status(now)['credits_reserved'] == 1
