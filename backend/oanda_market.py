"""OANDA market observations. External requests are GET-only; no order methods."""
import math
import os
import re
import time
from datetime import datetime
import httpx
from .engine import FOREX
from . import db

HOSTS={'practice':'https://api-fxpractice.oanda.com','live':'https://api-fxtrade.oanda.com'}

class MarketDataError(ValueError):
    pass


def readiness():
    environment=os.getenv('OANDA_MARKET_ENV','')
    token=os.getenv('OANDA_TOKEN','').strip()
    account=os.getenv('OANDA_ACCOUNT_ID','').strip()
    return {'environment':environment if environment in HOSTS else 'not_selected',
            'configured':bool(token and re.fullmatch(r'[0-9-]{6,64}',account) and environment in HOSTS),
            'enabled':os.getenv('OANDA_MARKET_DATA_APPROVED')=='true',
            'access':'market-data reads only', 'order_permissions_changed':False}


def number(value, positive=False):
    try:
        result=float(value)
        if not math.isfinite(result) or (result<=0 if positive else result<0):raise ValueError()
        return result
    except (ValueError,TypeError,OverflowError):
        raise MarketDataError('OANDA returned invalid market values') from None


def financing_observation(meta):
    """Optional provider evidence only. Invalid/missing data never means free financing."""
    raw=meta.get('financing')
    if raw is None:return {'status':'unavailable','details':None}
    try:
        def rate(value):
            if isinstance(value,bool):raise ValueError()
            result=float(value)
            if not math.isfinite(result):raise ValueError()
            return result
        long_rate=rate(raw['longRate']);short_rate=rate(raw['shortRate'])
        schedule=raw['financingDaysOfWeek']
        days={'MONDAY','TUESDAY','WEDNESDAY','THURSDAY','FRIDAY','SATURDAY','SUNDAY'}
        if not isinstance(schedule,list) or not 1<=len(schedule)<=7:raise ValueError()
        seen=set();normalized=[]
        for item in schedule:
            day=item['dayOfWeek'];count=item['daysCharged']
            if day not in days or day in seen or type(count) is not int or count<0:raise ValueError()
            seen.add(day);normalized.append({'day':day,'days_charged':count})
        return {'status':'reported','details':{'long_rate':long_rate,'short_rate':short_rate,'schedule':normalized}}
    except (KeyError,TypeError,ValueError,OverflowError):
        return {'status':'invalid','details':None}


def normalize(symbol, summary, instruments, pricing, now, environment):
    try:
        if summary['account']['currency']!='USD':raise MarketDataError('Only USD account cost conversion is supported')
        name=symbol.replace('/','_')
        meta=[x for x in instruments['instruments'] if x.get('name')==name]
        prices=[x for x in pricing['prices'] if x.get('instrument')==name]
        if len(meta)!=1 or len(prices)!=1:raise MarketDataError('Requested OANDA instrument is unavailable')
        meta,price=meta[0],prices[0]
        if price.get('status')!='tradeable':raise MarketDataError('OANDA instrument is not tradeable')
        stamp=datetime.fromisoformat(price['time'].replace('Z','+00:00'))
        if stamp.tzinfo is None:raise MarketDataError('OANDA quote timestamp has no timezone')
        at=stamp.timestamp()
        if at>now+2 or now-at>10:raise MarketDataError('OANDA quote is stale or clock is skewed')
        bids,asks=price['bids'],price['asks']
        # Only positive-liquidity levels represent available bid/ask volume.
        bids=[(number(x['price'],True),number(x['liquidity'])) for x in bids]
        asks=[(number(x['price'],True),number(x['liquidity'])) for x in asks]
        bids=[x for x in bids if x[1]>0];asks=[x for x in asks if x[1]>0]
        if not bids or not asks:raise MarketDataError('OANDA quote has no available liquidity')
        bid,bid_liquidity=max(bids);ask,ask_liquidity=min(asks)
        if ask<bid:raise MarketDataError('OANDA bid/ask spread is invalid')
        precision=int(meta['tradeUnitsPrecision'])
        if not 0<=precision<=8:raise MarketDataError('Unsupported OANDA unit precision')
        q=1.0 if symbol.endswith('/USD') else None
        if q is None:
            conversion=next((x for x in pricing.get('homeConversions',[]) if x.get('currency')==symbol[-3:]),None)
            if conversion:q=number(conversion['positionValue'],True)
        if q is None:raise MarketDataError('OANDA quote currency conversion is unavailable')
        commission=None
        if meta.get('commission') is not None:
            c=meta['commission']
            amount=number(c['commission']);units=number(c['unitsTraded'],True);minimum=number(c['minimumCommission'])
            commission={'currency':'USD','per_unit':amount/units,'minimum_per_fill':minimum}
        return {'symbol':symbol,'source':'OANDA '+environment.upper()+' market data',
                'environment':environment,'bid':bid,'ask':ask,'time':at,'observed_at':now,
                'spread_bps':(ask-bid)/((bid+ask)/2)*10000,
                'bid_liquidity_units':bid_liquidity,'ask_liquidity_units':ask_liquidity,
                'quote_to_usd':q,'min_units':number(meta['minimumTradeSize'],True),
                'unit_step':10**-precision,'max_units':number(meta['maximumOrderUnits'],True),
                'commission':commission,'financing':financing_observation(meta),'costs_validated':False,
                'pending_checks':['Slippage model review','Financing/holding-cost review','Economic-event coverage']+
                    (['Commission schedule unavailable'] if commission is None else ['Minimum-commission model review'] if commission['minimum_per_fill']>0 else [])}
    except MarketDataError:
        raise
    except (KeyError,IndexError,TypeError,ValueError,OverflowError):
        raise MarketDataError('OANDA market response is incomplete or invalid') from None


async def observe(symbol, transport=None):
    state=readiness()
    if not state['enabled']:raise MarketDataError('OANDA market-data reads are not enabled')
    if not state['configured']:raise MarketDataError('Configure the OANDA environment and server credentials')
    if symbol not in FOREX:raise MarketDataError('OANDA market-data pilot accepts supported Forex pairs only')
    account=os.environ['OANDA_ACCOUNT_ID'].strip();token=os.environ['OANDA_TOKEN'].strip()
    if any(c.isspace() for c in token):raise MarketDataError('OANDA token contains whitespace')
    base=HOSTS[state['environment']]
    try:
        async with httpx.AsyncClient(timeout=15,follow_redirects=False,transport=transport) as client:
            async def get(stage,path,params=None):
                response=await client.get(base+path,params=params,headers={'Authorization':'Bearer '+token,'Accept-Datetime-Format':'RFC3339'})
                if response.status_code != 200:
                    raise MarketDataError(f'OANDA {stage} request failed (HTTP {response.status_code})')
                return response.json()
            summary=await get('account summary','/v3/accounts/'+account+'/summary')
            instruments=await get('instrument details','/v3/accounts/'+account+'/instruments',{'instruments':symbol.replace('/','_')})
            pricing=await get('pricing','/v3/accounts/'+account+'/pricing',{'instruments':symbol.replace('/','_'),'includeHomeConversions':'true'})
        return normalize(symbol,summary,instruments,pricing,time.time(),state['environment'])
    except MarketDataError:
        raise
    except Exception:
        raise MarketDataError('OANDA market-data connection unavailable; credentials and transport details withheld') from None


def public_observation(value):
    return {k:v for k,v in value.items() if not k.startswith('_')}

async def refresh(symbol):
    value=await observe(symbol)
    from . import oanda_commission
    if value.get('environment')=='practice':value['_account_binding']=oanda_commission.binding()
    # Observation evidence only: do not mark execution assumptions validated,
    # modify price_ticks/order inputs, or fabricate complete event coverage.
    db.put('market_observations','OANDA:'+symbol,value)
    db.audit('OANDA_MARKET_OBSERVATION',symbol)
    return public_observation(value)
