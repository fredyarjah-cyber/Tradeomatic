"""Independent supervisor: paper broker outbox, reconciliation and health events."""
import asyncio,time,logging
from datetime import datetime,timezone
from . import db,brokers,controls,approvals
from .notifications import enqueue,expire_signals
log=logging.getLogger('assistant')

async def refresh_broker(name,symbol=None,client=None):
    client=client or brokers.adapter(name)
    snapshot=await client.snapshot();tracked=[o for o in db.listing('broker_orders') if o['details']['target']==name and o['status'] in ('ACCEPTED','PARTIAL','FILLED')]
    unknown=[p for p in snapshot['positions'] if abs(p['units'])>sum(o['details']['units'] for o in tracked if o['details']['symbol']==p['symbol'])+1e-9]
    unprotected=[p for p in snapshot['positions'] if not p['protected']]
    # Do not assume costs, stop risk or account data for untracked positions.
    snapshot.update(reconciled=True,blocked=bool(unknown or unprotected),reason='Untracked or unprotected positions require broker review' if unknown or unprotected else None)
    db.put('broker_state',name,snapshot)
    if snapshot['blocked']:
        enqueue('HEALTH',name+':unprotected',{'instrument':name,'reason':snapshot['reason'],'recommendation':'NO','mode':'PAPER'})
    if controls.get()['positions_monitoring']:
        for position in snapshot['positions']:
            matching=next((o for o in tracked if o['details']['symbol']==position['symbol']),None)
            if not matching:continue
            d=matching['details'];tick=await client.market(position['symbol']);db.put('price_ticks',name+':'+position['symbol'],tick)
            price=tick['bid'] if position['units']>0 else tick['ask'];sign=1 if position['units']>0 else -1
            latest=db.get('quotes',position['symbol']+':'+d['interval'],{});features=latest.get('features',{})
            action='HOLD';reason='Broker position is open; protective orders remain broker-managed.'
            if db.get('config','risk_v2',{}).get('emergency_stop'):action='CLOSE';reason='Emergency stop: review closing this paper position in the broker portal.'
            elif sign*(price-d['target1'])>=0:action='PARTIAL CLOSE';reason='Target 1 reached. Partial exit and protective-order adjustment require broker review.'
            elif features.get('ema20') and sign*(price-features['ema20'])<0 and sign*features.get('macd_histogram',0)<0:action='CLOSE';reason='Confirmed price/momentum weakening. Review exit; no live order was changed.'
            elif sign*(price-d['entry'])>abs(d['entry']-d['stop']):action='ADJUST STOP';reason='Price advanced over one initial risk unit. Review a tighter broker stop.'
            position.update(current_price=price,price_time=tick['time'],exit_recommendation=action,exit_reason=reason)
            if action!='HOLD':enqueue('EXIT',name+':'+position['symbol']+':'+action,{'instrument':position['symbol'],'market':d['market'],'recommendation':action,'direction':d['direction'],'price':price,'price_time':tick['time'],'entry':d['entry'],'stop':d['stop'],'target1':d['target1'],'target2':d['target2'],'units':abs(position['units']),'rr':d['rr'],'unrealized_pnl':position.get('unrealized_pnl'),'reason':reason,'mode':'PAPER'})
        db.put('broker_state',name,snapshot)
    if symbol:
        tick=await client.market(symbol);db.put('price_ticks',name+':'+symbol,tick)
    return snapshot

async def submit_ready(order,now=None,client=None):
    now=now or time.time();id=order['id'];d=order['details'];client=client or brokers.adapter(d['target'])
    # Refreshes are reads; unknown write outcomes are never retried with another POST.
    await refresh_broker(d['target'],d['symbol'],client)
    with db.atomic() as tx:
        row=tx.get('broker_orders',id)
        if not row or row['status']!='READY':return
        try:
            controls.allow_new(tx)
            if d['expires_at']<=now:raise ValueError('Approval expired before submission')
            fresh,binding=approvals.details(tx,d['signal_id'],d['allocation'],d['target'],time.time(),exclude_order=id)
            if binding!=row['digest']:raise ValueError('Trade details changed before submission; new approval required')
        except ValueError as e:
            row.update(status='INVALIDATED',reason=str(e));tx.put('broker_orders',id,row);enqueue('INVALIDATED',id,{'instrument':d['symbol'],'reason':str(e),'recommendation':'NO','mode':'PAPER'},tx);return
        row.update(status='SUBMITTING',submitted_at=time.time());tx.put('broker_orders',id,row)
    try:
        receipt=await client.submit(d,row['client_id'])
        if not receipt:raise ValueError('No broker acknowledgment')
        state='REJECTED' if receipt.get('orderRejectTransaction') or receipt.get('orderCancelTransaction') else 'ACCEPTED'
        if receipt.get('orderFillTransaction'):state='FILLED'
        reason=None
    except Exception:
        receipt=None;state='UNKNOWN';reason='Submission outcome unknown. Reconciliation required; no automatic POST retry.'
    with db.atomic() as tx:
        row=tx.get('broker_orders',id);row.update(status=state,receipt=receipt,reason=reason);tx.put('broker_orders',id,row)
        tx.put('audit',id+':submission',{'time':time.time(),'action':'PAPER_BROKER_'+state,'details':row['client_id']})
        enqueue('ORDER',id+':'+state,{'instrument':d['symbol'],'reason':reason or 'Paper broker acknowledged the order','recommendation':'NO' if state in ('UNKNOWN','REJECTED') else 'YES','mode':'PAPER'},tx)

async def reconcile_order(order,client=None):
    client=client or brokers.adapter(order['details']['target'])
    value=await client.lookup(order['client_id'])
    if value is None:return  # Absence is not proof that an ambiguous write may safely be retried.
    item=value.get('order',value);status=str(item.get('state',item.get('status',''))).upper()
    mapping={'PENDING':'ACCEPTED','NEW':'ACCEPTED','ACCEPTED':'ACCEPTED','PARTIALLY_FILLED':'PARTIAL','FILLED':'FILLED','CANCELLED':'CANCELLED','CANCELED':'CANCELLED','REJECTED':'REJECTED','EXPIRED':'EXPIRED'}
    new=mapping.get(status)
    with db.atomic() as tx:
        current=tx.get('broker_orders',order['id']);old=current['status'];current.update(last_reconciled=time.time(),broker_record=value)
        if new:current['status']=new
        tx.put('broker_orders',order['id'],current)
        if old!=current['status']:
            tx.put('audit',order['id']+':'+current['status'],{'time':time.time(),'action':'BROKER_RECONCILIATION','details':current['status']})
            enqueue('POSITION',order['id']+':'+current['status'],{'instrument':order['details']['symbol'],'reason':'Broker paper status: '+current['status'],'mode':'PAPER'},tx)


def health_once(now=None):
    now=now or time.time()
    for name in ('worker','notifications'):
        h=db.get('health',name,{})
        try:at=h.get('heartbeat',0);at=datetime.fromisoformat(at).timestamp() if isinstance(at,str) else at
        except ValueError:at=0
        failed=now-at>180;previous=db.get('health_state',name,{'failed':False,'incident':0})
        if failed and not previous['failed']:
            previous['incident']+=1;enqueue('HEALTH',name+':'+str(previous['incident']),{'instrument':name,'recommendation':'NO','reason':'Monitoring heartbeat stale. Do not rely on this service for fresh trade decisions. Broker protective orders are unchanged.','mode':'SERVICE'})
        if not failed and previous['failed']:enqueue('HEALTH',name+':recovered:'+str(previous['incident']),{'instrument':name,'reason':'Service heartbeat recovered. Verify data freshness before resuming new activity.','mode':'SERVICE'})
        db.put('health_state',name,{**previous,'failed':failed})
    expire_signals(now)

async def cycle():
    health_once()
    for name in ('OANDA_PRACTICE','ALPACA_PAPER'):
        if not brokers.enabled(name) or not controls.get()['positions_monitoring']:continue
        try:
            await refresh_broker(name)
            for order in db.listing('broker_orders'):
                if order['details']['target']!=name:continue
                if order['status']=='READY':await submit_ready(order)
                elif order['status'] in ('SUBMITTING','UNKNOWN','ACCEPTED','PARTIAL','FILLED'):
                    if order['status']=='SUBMITTING' and time.time()-order.get('submitted_at',0)<60:continue
                    await reconcile_order(order)
        except Exception:
            enqueue('HEALTH',name+':connection:'+str(int(time.time())//300),{'instrument':name,'recommendation':'NO','reason':'Broker connection unavailable. New orders blocked until fresh reconciliation. Existing protective orders were not cancelled.','mode':'PAPER'})
            state=db.get('broker_state',name,{})
            db.put('broker_state',name,{**state,'blocked':True,'reconciled':False})
    db.put('health','assistant',{'heartbeat':time.time()})

async def main():
    db.init()
    while True:
        try:await cycle()
        except Exception:log.error('Assistant cycle failed; transport details redacted')
        await asyncio.sleep(10)
if __name__=='__main__':asyncio.run(main())
