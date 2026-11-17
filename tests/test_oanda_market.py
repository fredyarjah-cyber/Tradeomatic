import asyncio
import copy
import json
import time
from datetime import datetime, timezone
import httpx
import pytest
from backend import oanda_market as om


def payloads(now):
    return ({'account':{'currency':'USD','id':'DO_NOT_RETURN','NAV':'12345'}},
            {'instruments':[{'name':'EUR_USD','tradeUnitsPrecision':0,'minimumTradeSize':'1','maximumOrderUnits':'1000000',
              'commission':{'commission':'5','unitsTraded':'100000','minimumCommission':'0'}}]},
            {'prices':[{'instrument':'EUR_USD','status':'tradeable','time':datetime.fromtimestamp(now,timezone.utc).isoformat(),
              'bids':[{'price':'1.1','liquidity':100000}], 'asks':[{'price':'1.1002','liquidity':100000}]}]})


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('OANDA_MARKET_ENV','practice')
    monkeypatch.setenv('OANDA_MARKET_DATA_APPROVED','true')
    monkeypatch.setenv('OANDA_ACCOUNT_ID','123-456-789')
    monkeypatch.setenv('OANDA_TOKEN','private-token-value')


def test_get_only_connection_never_enables_orders(configured,monkeypatch):
    monkeypatch.setenv('OANDA_PAPER_APPROVED','false')
    now=time.time();summary,instruments,pricing=payloads(now);requests=[]
    def respond(request):
        requests.append(request)
        assert request.method=='GET' and request.url.host=='api-fxpractice.oanda.com'
        if request.url.path.endswith('/summary'):data=summary
        elif request.url.path.endswith('/instruments'):data=instruments
        elif request.url.path.endswith('/pricing'):data=pricing
        else:raise AssertionError('Unexpected endpoint')
        return httpx.Response(200,json=data)
    result=asyncio.run(om.observe('EUR/USD',httpx.MockTransport(respond)))
    assert len(requests)==3 and all('/orders' not in r.url.path for r in requests)
    assert result['commission']['per_unit']==.00005
    assert result['spread_bps']>0 and result['quote_to_usd']==1
    assert result['costs_validated'] is False
    assert 'DO_NOT_RETURN' not in json.dumps(result)
    assert 'private-token-value' not in json.dumps(om.readiness())
    from backend.brokers import enabled
    assert not enabled('OANDA_PRACTICE')


def test_gate_blocks_all_network_calls(configured,monkeypatch):
    monkeypatch.setenv('OANDA_MARKET_DATA_APPROVED','false')
    def fail(request):raise AssertionError('Network must not be called')
    with pytest.raises(om.MarketDataError,match='not enabled'):
        asyncio.run(om.observe('EUR/USD',httpx.MockTransport(fail)))


@pytest.mark.parametrize('environment',['','production','https://example.com'])
def test_environment_must_be_explicit(configured,monkeypatch,environment):
    monkeypatch.setenv('OANDA_MARKET_ENV',environment)
    with pytest.raises(om.MarketDataError,match='Configure'):
        asyncio.run(om.observe('EUR/USD'))


def test_authorization_errors_redacted(configured):
    def respond(request):return httpx.Response(401,json={'message':'private-token-value'})
    with pytest.raises(om.MarketDataError) as error:
        asyncio.run(om.observe('EUR/USD',httpx.MockTransport(respond)))
    assert 'private-token-value' not in str(error.value)


@pytest.mark.parametrize('change', ['stale','future','crossed','nonfinite','no_liquidity','missing_commission','minimum_commission','wrong_currency'])
def test_market_validation(change):
    now=time.time();summary,instruments,pricing=payloads(now);price=pricing['prices'][0]
    if change=='stale':price['time']=datetime.fromtimestamp(now-11,timezone.utc).isoformat()
    if change=='future':price['time']=datetime.fromtimestamp(now+3,timezone.utc).isoformat()
    if change=='crossed':price['asks'][0]['price']='1.0'
    if change=='nonfinite':price['bids'][0]['price']='NaN'
    if change=='no_liquidity':price['bids'][0]['liquidity']=0
    if change=='missing_commission':instruments['instruments'][0].pop('commission')
    if change=='minimum_commission':instruments['instruments'][0]['commission']['minimumCommission']='1'
    if change=='wrong_currency':summary['account']['currency']='GBP'
    if change in ('missing_commission','minimum_commission'):
        result=om.normalize('EUR/USD',summary,instruments,pricing,now,'practice')
        assert not result['costs_validated']
        assert any('Commission' in x or 'commission' in x for x in result['pending_checks'])
    else:
        with pytest.raises(om.MarketDataError):om.normalize('EUR/USD',summary,instruments,pricing,now,'practice')


def test_instrument_must_match_requested_symbol():
    now=time.time();summary,instruments,pricing=payloads(now)
    instruments['instruments'][0]['name']='GBP_USD'
    with pytest.raises(om.MarketDataError,match='unavailable'):
        om.normalize('EUR/USD',summary,instruments,pricing,now,'practice')


def test_refresh_does_not_write_executable_quotes_or_context(configured,monkeypatch):
    calls=[]
    async def observe(symbol):return {'symbol':symbol,'costs_validated':False}
    monkeypatch.setattr(om,'observe',observe)
    monkeypatch.setattr(om.db,'put',lambda *args:calls.append(args))
    monkeypatch.setattr(om.db,'audit',lambda *args:None)
    asyncio.run(om.refresh('EUR/USD'))
    assert len(calls)==1 and calls[0][0]=='market_observations'
