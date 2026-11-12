"""One independent scanner process; paper monitoring continues when discovery is paused."""
import asyncio, os, logging, hashlib
from datetime import datetime, timezone
from . import db, service, controls, notifications
from .engine import SYMBOLS, INTERVALS
from .provider import fetch, market_open
from .intelligence import recommend, HIGHER, iso, trend_features
from .paper import ACTIVE, portfolio_summary
from .approvals import portfolio as reserved_portfolio
log=logging.getLogger('scanner')

async def scan_once():
    cfg=db.get('config','scanner',{'enabled':False,'symbols':SYMBOLS,'intervals':['1h']})
    assistant_controls=controls.get()
    if assistant_controls['global_pause']:cfg={**cfg,'enabled':False}
    active=[t for t in db.listing('paper') if t['status'] in ACTIVE] if assistant_controls['positions_monitoring'] else []
    tasks={(s,i) for s in cfg['symbols'] for i in cfg['intervals']} if cfg['enabled'] else set()
    tasks|={(t['symbol'],t['interval']) for t in active}
    cache={}
    async def get_bars(symbol,interval):
        key=(symbol,interval)
        if key not in cache:
            if os.getenv('DATA_MODE','demo')!='demo':await asyncio.sleep(float(os.getenv('REQUEST_SPACING_SECONDS','15')))
            cache[key]=await fetch(symbol,interval)
        return cache[key]
    for symbol,interval in sorted(tasks):
        now=datetime.now(timezone.utc).timestamp();key=f'{symbol}:{interval}';mode='SIMULATED' if os.getenv('DATA_MODE','demo')=='demo' else os.getenv('DATA_ENTITLEMENT','UNKNOWN').upper()
        db.put('health','worker',{'heartbeat':iso(now)})
        current=db.get('config','scanner',cfg)
        discovering=current['enabled'] and not controls.get()['global_pause'] and symbol in current['symbols'] and interval in current['intervals']
        if not discovering and not any(t['symbol']==symbol and t['interval']==interval and t['status'] in ACTIVE for t in db.listing('paper')):continue
        try:
            opened=mode=='SIMULATED' or market_open(symbol)
            if not opened:
                service.monitor(symbol,interval,[],now)
                signal=recommend(symbol,interval,[],[],service.settings(),{'market_status':'closed','data_mode':mode},now=now)
                row={**signal,'symbol':symbol,'interval':interval,'mode':mode,'status':'closed'}
            else:
                bars,mode=await get_bars(symbol,interval)
                now=datetime.now(timezone.utc).timestamp()
                service.monitor(symbol,interval,bars,now,trend_features(bars) if len(bars)>=60 else {})
                if not discovering:continue
                higher=[]
                try:
                    if HIGHER[interval]:higher,_=await get_bars(symbol,HIGHER[interval])
                except Exception:pass  # Missing higher timeframe explicitly produces NO TRADE.
                now=datetime.now(timezone.utc).timestamp()
                ctx=service.context(symbol,mode,now);ctx['market_status']='open' if mode=='SIMULATED' or market_open(symbol) else 'closed'
                signal=recommend(symbol,interval,bars,higher,service.settings(),ctx,reserved_portfolio(db,now),now)
                row={**signal,'status':'ok','price':bars[-1]['close'],'price_time':bars[-1]['time']+INTERVALS[interval],'bars':bars,'higher_bars':higher}
                # Monitor once more with point-in-time trend features; duplicate candles never refill.
                service.monitor(symbol,interval,bars,now,signal.get('features'))
            if discovering:
                db.put_once('signals',signal['id'],signal)
                immutable=db.get('signals',signal['id'],signal)
                row.update({k:v for k,v in immutable.items() if k not in ('rank','status')})
                row['signal_status']=immutable.get('status')
                db.put('quotes',key,row)
                notifications.observe_signal(row,now)
        except Exception:
            signal=recommend(symbol,interval,[],[],service.settings(),{'market_status':'unknown','data_mode':mode},now=now)
            signal.update(reason='Data unavailable; recommendation suppressed',reasons=['Data unavailable; recommendation suppressed'])
            db.put_once('signals',signal['id'],signal)
            db.put('quotes',key,{**signal,'status':'error'})
            db.audit('scanner_error',key)  # Never log URLs/secrets from provider exceptions.
        db.put('health','worker',{'heartbeat':datetime.now(timezone.utc).isoformat()})
    db.put('health','worker',{'heartbeat':datetime.now(timezone.utc).isoformat()})

async def main():
    db.init();lock=db.engine.connect()
    if db.engine.dialect.name=='postgresql':
        from sqlalchemy import text
        if not lock.execute(text('SELECT pg_try_advisory_lock(88412091)')).scalar():raise RuntimeError('Scanner already running')
    while True:
        try:
            db.put('health','worker',{'heartbeat':datetime.now(timezone.utc).isoformat()});await scan_once()
        except Exception:log.error('Scan failed; retrying next cycle')
        await asyncio.sleep(float(os.getenv('SCAN_SECONDS','60')))

if __name__=='__main__':asyncio.run(main())
