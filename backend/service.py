"""Database boundary for configuration, event context, paper approvals and replay."""
from datetime import datetime, timezone
from . import db
from .intelligence import DEFAULT_SETTINGS, RiskSettings, assumptions, recommend, conversion
from .paper import approve, advance, portfolio_summary, request_exit, performance, ACTIVE

def settings():return {**DEFAULT_SETTINGS,**db.get('config','risk_v2',{})}

def context(symbol,mode,now):
    if mode=='SIMULATED':return {'data_mode':mode,'market_status':'open','costs':{**assumptions(symbol,True,0),'valid_until':now+86400},'cost_source':'SIMULATED ASSUMPTIONS','events':{'coverage':'complete','asof':0,'valid_until':now+86400,'items':[]},'conversion':{'quote_to_usd':1 if symbol.endswith('/USD') else .0065 if symbol.endswith('/JPY') else 1.1,'asof':0,'valid_until':now+86400}}
    return {'data_mode':mode,'market_status':'open',**db.get('context',symbol,{})}

def approve_paper(signal_id,now):
    with db.atomic() as tx:
        if tx.get('config','assistant_v3'):
            from .controls import allow_new
            allow_new(tx)
        signal=tx.get('signals',signal_id)
        if not signal:raise ValueError('Signal not found')
        if signal.get('mode')!='SIMULATED':
            from .provider import market_open
            if not market_open(signal['symbol']):raise ValueError('Market closed')
            heartbeat=tx.get('health','worker',{})
            try:age=now-datetime.fromisoformat(heartbeat['heartbeat']).timestamp()
            except (ValueError,KeyError):age=1e9
            if age>180:raise ValueError('Worker data is stale')
        trades=tx.listing('paper');s={**DEFAULT_SETTINGS,**tx.get('config','risk_v2',{})}
        if signal.get('mode')!='SIMULATED':
            latest=tx.get('quotes',f"{signal['symbol']}:{signal['interval']}",{})
            if latest.get('id')!=signal_id or latest.get('status')!='ok':raise ValueError('Signal superseded or current data unavailable')
            ctx={'data_mode':signal['mode'],'market_status':'open',**tx.get('context',signal['symbol'],{})}
            check=recommend(signal['symbol'],signal['interval'],latest.get('bars',[]),latest.get('higher_bars',[]),s,ctx,portfolio_summary(trades,now),now)
            if check['recommendation']!='YES':raise ValueError('Approval recheck failed: '+check['reason'])
            signal={**signal,'costs':ctx['costs'],'quote_to_usd':conversion(signal['symbol'],signal['entry'],ctx,now)}
        if signal.get('rr',0)<s['rr']:raise ValueError('Signal target is below the current minimum reward/risk; wait for a newly generated signal')
        trade=approve(signal,s,trades,now);tx.put('paper',trade['id'],trade);tx.put('audit',trade['id'],{'time':datetime.fromtimestamp(now,timezone.utc).isoformat(),'action':'APPROVE_PAPER','details':signal_id})
        return trade

def monitor(symbol,interval,bars,now,features=None):
    from .controls import get as get_controls
    if not get_controls()['positions_monitoring']:return
    with db.atomic() as tx:
        trades=tx.listing('paper');s={**DEFAULT_SETTINGS,**tx.get('config','risk_v2',{})}
        for i,t in enumerate(trades):
            if t['symbol']!=symbol or t['interval']!=interval or t['status'] not in ACTIVE:continue
            from .approvals import portfolio as reserved_portfolio
            other=reserved_portfolio(tx,now,exclude_paper=t['id'])
            new=advance(t,bars,now,s,other,features);trades[i]=new;tx.put('paper',t['id'],new)
            # Exit recommendations are append-only changes, not rewritten signals.
            if (new['exit_recommendation'],new['status'])!=(t['exit_recommendation'],t['status']):
                key=f'{t["id"]}:{new.get("last_bar")}:{new["status"]}:{new["exit_recommendation"]}'
                from .notifications import enqueue
                enqueue('EXIT',key,{'instrument':symbol,'recommendation':new['exit_recommendation'],'direction':new['direction'],'price':new.get('last_price'),'price_time':now,'stop':new['stop'],'target1':new['target1'],'target2':new['target2'],'units':new['remaining_units'],'unrealized_pnl':new.get('unrealized_pnl',0),'reason':new['exit_reason'],'mode':new['data_mode']},tx)
                tx.put('paper_events',key,{'trade_id':t['id'],'time':now,'recommendation':new['exit_recommendation'],'reason':new['exit_reason'],'status':new['status']})

def paper_action(id,action,now,new_stop=None):
    with db.atomic() as tx:
        t=tx.get('paper',id)
        if not t:raise ValueError('Paper trade not found')
        result=request_exit(t,action,now,new_stop);tx.put('paper',id,result);tx.put('audit',f'{id}:{now}',{'time':now,'action':'PAPER_'+action,'details':id});return result

def save_settings(s):
    s=RiskSettings(**s).model_dump()
    with db.atomic() as tx:
        tx.put('config','risk_v2',s)
        if s['emergency_stop']:
            for t in tx.listing('paper'):
                if t['status']=='PENDING_ENTRY':t.update(status='CANCELLED',exit_reason='Emergency stop cancelled pending entry');tx.put('paper',t['id'],t)
                elif t['status'] in ('OPEN','PARTIAL'):t.update(exit_recommendation='CLOSE',exit_reason='Emergency stop enabled; explicit paper close approval required');tx.put('paper',t['id'],t)
    db.audit('RISK_CONFIG_UPDATED','Emergency stop='+str(s['emergency_stop']));return s
