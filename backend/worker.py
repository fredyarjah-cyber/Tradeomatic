"""One independent scanner process; paper monitoring continues when discovery is paused."""
import asyncio, os, logging, hashlib, signal
from datetime import datetime, timezone
from . import db, service, controls, notifications
from .engine import SYMBOLS, INTERVALS
from .provider import fetch, market_open
from .intelligence import recommend, HIGHER, iso, trend_features
from .paper import ACTIVE, portfolio_summary
from .approvals import portfolio as reserved_portfolio
from .scanner_lock import ScannerLock, OwnershipLost
log=logging.getLogger('scanner')

TRANSIENT_REASONS={
    'Data unavailable; recommendation suppressed',
    'Daily market-data budget reached; requests paused until next UTC day',
    'Market-data rate limit reached; request deferred',
    'Invalid provider credit limits; requests blocked',
}

def save_confirmed_result(signal):
    existing=db.get('signals',signal['id'])
    if existing and not existing.get('features') and existing.get('reason') in TRANSIENT_REASONS:
        # Preserve the legacy outage record and its ID, while allowing recovery.
        signal={**signal,'id':'recovered:'+signal['id']}
    db.put_once('signals',signal['id'],signal)
    return db.get('signals',signal['id'],signal)


def worker_health():
    return {'heartbeat':datetime.now(timezone.utc).isoformat(),
            'status':'active','commit':os.getenv('RENDER_GIT_COMMIT','unknown'),
            'instance':os.getenv('RENDER_INSTANCE_ID','local'),'pid':os.getpid()}


async def scan_once(ensure_owner=None):
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
        if ensure_owner:ensure_owner()
        now=datetime.now(timezone.utc).timestamp();key=f'{symbol}:{interval}';mode='SIMULATED' if os.getenv('DATA_MODE','demo')=='demo' else os.getenv('DATA_ENTITLEMENT','UNKNOWN').upper()
        db.put('health','worker',worker_health())
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
                if ensure_owner:ensure_owner()
                now=datetime.now(timezone.utc).timestamp()
                service.monitor(symbol,interval,bars,now,trend_features(bars) if len(bars)>=60 else {})
                if not discovering:continue
                higher=[]
                try:
                    if HIGHER[interval]:higher,_=await get_bars(symbol,HIGHER[interval])
                except Exception:pass  # Missing higher timeframe explicitly produces NO TRADE.
                if ensure_owner:ensure_owner()
                now=datetime.now(timezone.utc).timestamp()
                ctx=service.context(symbol,mode,now);ctx['market_status']='open' if mode=='SIMULATED' or market_open(symbol) else 'closed'
                signal=recommend(symbol,interval,bars,higher,service.settings(),ctx,reserved_portfolio(db,now),now)
                row={**signal,'status':'ok','price':bars[-1]['close'],'price_time':bars[-1]['time']+INTERVALS[interval],'bars':bars,'higher_bars':higher}
                # Monitor once more with point-in-time trend features; duplicate candles never refill.
                service.monitor(symbol,interval,bars,now,signal.get('features'))
            if discovering:
                immutable=save_confirmed_result(signal)
                row['last_checked_at']=iso(now)
                row.update({k:v for k,v in immutable.items() if k not in ('rank','status')})
                row['signal_status']=immutable.get('status')
                db.put('quotes',key,row)
                notifications.observe_signal(row,now)
        except OwnershipLost:
            raise
        except Exception as exc:
            from .provider_budget import ProviderLimit
            reason=str(exc) if isinstance(exc,ProviderLimit) else 'Data unavailable; recommendation suppressed'
            signal=recommend(symbol,interval,[],[],service.settings(),{'market_status':'unknown','data_mode':mode},now=now)
            signal.update(id='data-error:'+signal['id'],reason=reason,reasons=[reason],data_error=True)
            db.put_once('signals',signal['id'],signal)
            db.put('quotes',key,{**signal,'status':'error'})
            db.audit('scanner_error',key)  # Never log URLs/secrets from provider exceptions.
        db.put('health','worker',worker_health())
    db.put('health','worker',worker_health())

async def wait_or_stop(stop, seconds):
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass

async def run_owned(stop, lock):
    while not stop.is_set():
        lock.check()
        db.put('health','worker',worker_health())
        scan=asyncio.create_task(scan_once(lock.check))
        stopped=asyncio.create_task(stop.wait())
        try:
            done,_=await asyncio.wait((scan,stopped),return_when=asyncio.FIRST_COMPLETED)
            if stopped in done:
                return
            try:
                await scan
            except OwnershipLost:
                raise
            except Exception:
                log.error('Scan failed; retrying next cycle')
        finally:
            for task in (scan,stopped):
                if not task.done():task.cancel()
            await asyncio.gather(scan,stopped,return_exceptions=True)
        await wait_or_stop(stop,float(os.getenv('SCAN_SECONDS','60')))

async def serve(stop):
    while not stop.is_set():
        lock=ScannerLock()
        try:
            if not lock.acquire():
                db.put('health','worker_standby',{**worker_health(),'status':'standby'})
                await wait_or_stop(stop,5)
                continue
            await run_owned(stop,lock)
        except OwnershipLost:
            log.warning('Scanner ownership changed; returning to standby')
        except Exception:
            log.error('Scanner startup failed; retrying without exposing connection details')
        finally:
            lock.close()
        if not stop.is_set():await wait_or_stop(stop,5)

async def main():
    db.init();stop=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT):
        loop.add_signal_handler(sig,stop.set)
    try:
        await serve(stop)
    finally:
        for sig in (signal.SIGTERM,signal.SIGINT):loop.remove_signal_handler(sig)

if __name__=='__main__':asyncio.run(main())
