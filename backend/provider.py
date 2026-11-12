import os, asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import httpx
import exchange_calendars as xcals
from .engine import demo_bars, INTERVALS

def market_open(symbol, now=None):
    now=now or datetime.now(timezone.utc)
    if '/' in symbol:
        n=now.astimezone(ZoneInfo('America/New_York'))
        return n.weekday()<4 or (n.weekday()==4 and n.hour<17) or (n.weekday()==6 and n.hour>=17)
    return bool(xcals.get_calendar('XNYS').is_open_on_minute(now.replace(second=0,microsecond=0)))

async def fetch(symbol,interval):
    if os.getenv('DATA_MODE','demo')=='demo': return demo_bars(symbol,interval),'SIMULATED'
    if os.getenv('PROVIDER_APPROVED')!='true': raise RuntimeError('Provider activation requires owner approval')
    if interval=='1day' and '/' not in symbol: raise RuntimeError('Daily equity candles require exchange-session timestamp normalization; use intraday intervals for now')
    key=os.getenv('TWELVEDATA_API_KEY')
    if not key: raise RuntimeError('Provider credentials not configured')
    if os.getenv('DATA_ENTITLEMENT') not in ('real-time','delayed'): raise RuntimeError('Document data entitlement before activation')
    async with httpx.AsyncClient(timeout=20) as client:
        r=await client.get('https://api.twelvedata.com/time_series',params={'symbol':symbol,'interval':interval,'outputsize':110,'timezone':'UTC','apikey':key})
        r.raise_for_status(); data=r.json()
    if 'values' not in data: raise RuntimeError('Provider returned no candles; check quota and symbol entitlement')
    out=[]; now=datetime.now(timezone.utc).timestamp()
    for b in reversed(data['values']):
        t=datetime.fromisoformat(b['datetime']).replace(tzinfo=timezone.utc).timestamp()
        if t+INTERVALS[interval]>now: continue
        row={'time':int(t),**{k:float(b[k]) for k in ('open','high','low','close')},'volume':float(b['volume']) if b.get('volume') else None}
        if row['low']<=min(row['open'],row['close'])<=max(row['open'],row['close'])<=row['high'] and row['low']>0: out.append(row)
        else: raise RuntimeError('Invalid OHLC data')
    if not out or now-(out[-1]['time']+INTERVALS[interval])>INTERVALS[interval]*2: raise RuntimeError('Stale data; recommendation suppressed')
    return out,os.environ['DATA_ENTITLEMENT'].upper()
