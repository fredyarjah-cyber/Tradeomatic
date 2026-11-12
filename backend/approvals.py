"""Exact-detail, one-use trade review envelopes. Paper targets only."""
import hashlib,json,time,uuid,math
from decimal import Decimal,ROUND_DOWN,ROUND_HALF_UP
from . import db,service,controls
from .intelligence import DEFAULT_SETTINGS,size_position,recommend,timestamp
from .engine import INTERVALS
from .paper import portfolio_summary,approve,ACTIVE
from .notifications import enqueue
TARGETS=('LOCAL_PAPER','OANDA_PRACTICE','ALPACA_PAPER')

def canonical(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def portfolio(tx,now,exclude_order=None,exclude_paper=None):
    p=portfolio_summary([t for t in tx.listing('paper') if t['id']!=exclude_paper],now)
    for o in tx.listing('broker_orders'):
        if o['id']==exclude_order or o['status'] not in ('READY','SUBMITTING','UNKNOWN','ACCEPTED','PARTIAL','FILLED'):continue
        d=o['details'];p['open_count']+=1;p['exposure']+=d['notional_usd'];p['open_risk']+=d['risk_usd'];p['margin']+=d['margin_usd']
    return p

def details(tx,signal_id,allocation,target,now,exclude_order=None):
    if target not in TARGETS:raise ValueError('Live and unsupported execution targets are locked')
    if not math.isfinite(allocation) or allocation<=0:raise ValueError('Positive finite allocation required')
    if tx.get('signal_decisions',signal_id,{}).get('decision')=='REJECT':raise ValueError('This signal was rejected')
    signal=tx.get('signals',signal_id)
    if not signal or signal.get('recommendation')!='YES' or signal.get('provisional'):raise ValueError('Confirmed YES signal required')
    if now>=timestamp(signal['expires_at']):raise ValueError('Signal expired')
    cfg={**DEFAULT_SETTINGS,**tx.get('config','risk_v2',{}),'allocation':allocation}
    if cfg['emergency_stop']:raise ValueError('Emergency stop enabled')
    latest=tx.get('quotes',signal['symbol']+':'+signal['interval'],{})
    if latest.get('id')!=signal_id or latest.get('status')!='ok':raise ValueError('Signal superseded or current data unavailable')
    if any(o['id']!=exclude_order and o['status'] in ('UNKNOWN','SUBMITTING') for o in tx.listing('broker_orders')):raise ValueError('Unresolved broker submission blocks new approvals until reconciliation')
    p=portfolio(tx,now,exclude_order);context=service.context(signal['symbol'],'SIMULATED',now) if signal['mode']=='SIMULATED' else {'market_status':'open','data_mode':signal['mode'],**tx.get('context',signal['symbol'],{})}
    if signal['mode']!='SIMULATED':
        heartbeat=tx.get('health','worker',{})
        try:age=now-timestamp(heartbeat['heartbeat'])
        except (KeyError,ValueError):age=1e9
        if age>180:raise ValueError('Scanner heartbeat stale')
        from .provider import market_open
        if not market_open(signal['symbol']):raise ValueError('Market closed')
        checked=recommend(signal['symbol'],signal['interval'],latest.get('bars',[]),latest.get('higher_bars',[]),cfg,context,p,now)
        if checked['recommendation']!='YES':raise ValueError('Fresh signal check failed: '+checked['reason'])
    costs=dict(signal['costs'] if signal['mode']=='SIMULATED' else context.get('costs',signal['costs']));q=signal['quote_to_usd'];entry=signal['entry'];stop=signal['stop'];t1=signal['target1'];t2=signal['target2'];meta={};state={}
    if target!='LOCAL_PAPER':
        from .brokers import enabled
        if not enabled(target):raise ValueError('Broker paper account is not approved/verified')
        if signal['mode']!='REAL-TIME':raise ValueError('Broker paper orders require verified real-time, nonsimulated signal data')
        state=tx.get('broker_state',target,{})
        if now-state.get('asof',0)>30 or state.get('blocked') or not state.get('reconciled'):raise ValueError('Fresh broker reconciliation required')
        meta=tx.get('price_ticks',target+':'+signal['symbol'],{})
        if now-meta.get('time',0)>10 or meta.get('time',now)>now+2:raise ValueError('Fresh bid/ask broker quote required')
        if meta.get('bid',0)<=0 or meta.get('ask',0)<meta['bid']:raise ValueError('Invalid broker bid/ask')
        if signal['decision']=='SELL' and target=='ALPACA_PAPER' and not meta.get('shortable'):raise ValueError('Stock short/borrow permission unavailable')
        entry=meta['ask'] if signal['decision']=='BUY' else meta['bid'];q=meta['quote_to_usd']
        cfg['equity']=min(cfg['equity'],state['equity']);cfg['leverage']=min(cfg['leverage'],1/meta['margin_rate'])
        decimals=meta['price_decimals'];quant=Decimal('1').scaleb(-decimals)
        rounding=lambda v:float(Decimal(str(v)).quantize(quant,rounding=ROUND_HALF_UP))
        entry,stop,t1,t2=map(rounding,(entry,stop,t1,t2))
        mid=(meta['ask']+meta['bid'])/2
        costs.update(spread_bps=(meta['ask']-meta['bid'])/mid*10000,min_units=meta['min_units'],unit_step=meta['unit_step'])
    elif signal['mode']=='SIMULATED':
        # Completed-candle simulation, never mislabeled a live price.
        meta={'time':latest['bars'][-1]['time']+INTERVALS[signal['interval']],'source':'SIMULATED completed candle'}
        entry=latest['bars'][-1]['close']
    else:
        meta=tx.get('price_ticks','MARKET:'+signal['symbol'],{})
        if now-meta.get('time',0)>10:raise ValueError('Fresh licensed bid/ask update required; a closed candle is not a current executable quote')
        entry=meta['ask'] if signal['decision']=='BUY' else meta['bid'];q=meta['quote_to_usd']
    if not signal['entry_zone'][0]<=entry<=signal['entry_zone'][1]:raise ValueError('Current price is outside the approved entry zone')
    sign=1 if signal['decision']=='BUY' else -1
    if sign*(entry-stop)<=0 or sign*(t1-entry)<=0:raise ValueError('Protective levels invalid at current price')
    sized=size_position(signal['symbol'],entry,stop,cfg,costs,q,p)
    if not sized['accepted']:raise ValueError('; '.join(sized['rejections']))
    if meta.get('max_units') and sized['units']>meta['max_units']:raise ValueError('Quantity exceeds broker maximum')
    if target!='LOCAL_PAPER' and sized['margin_usd']>state.get('buying_power',0):raise ValueError('Broker buying power insufficient')
    per_risk=abs(entry-stop)*q+sized['round_trip_cost_per_unit_usd'];net_reward=sign*(t1-entry)*q-sized['round_trip_cost_per_unit_usd'];net_rr=net_reward/per_risk
    if net_rr<cfg['rr']*.999:raise ValueError('Fresh price/costs no longer meet minimum net reward/risk')
    expires=min(timestamp(signal['expires_at']),now+60)
    d={'signal_id':signal_id,'symbol':signal['symbol'],'market':'Forex' if '/' in signal['symbol'] else 'US stock / ETF','interval':signal['interval'],'recommendation':'YES','direction':signal['decision'],'target':target,'mode':signal['mode'],'current_price':entry,'price_time':meta.get('time'),'price_source':meta.get('source','licensed feed'),'entry':entry,'entry_zone':signal['entry_zone'],'stop':stop,'target1':t1,'target2':t2,'allocation':allocation,'units':sized['units'],'lots':sized['lots'],'shares':sized['shares'],'risk_usd':sized['risk_usd'],'notional_usd':sized['notional_usd'],'margin_usd':sized['margin_usd'],'potential_profit_usd':net_reward*sized['units'],'round_trip_cost_usd':sized['round_trip_cost_per_unit_usd']*sized['units'],'rr':net_rr,'costs':costs,'quote_to_usd':q,'settings':cfg,'reason':signal['reason'],'expires_at':expires,'broker_entry':str(entry),'broker_stop':str(stop),'broker_target2':str(t2),'working_order_policy':'Internal paper model' if target=='LOCAL_PAPER' else 'Broker GTD entry; native stop and target 2' if target=='OANDA_PRACTICE' else 'Paper DAY bracket entry; target 1 alerts only; native stop and target 2. Not live-approved.'}
    # Price timestamps/TTL are freshness checks; unchanged prices do not invalidate by timestamp alone.
    financial={k:v for k,v in d.items() if k not in ('price_time','expires_at')}
    guard={'financial':financial,'portfolio':p,'controls':controls.get(tx),'context':context,'broker_equity':state.get('equity'),'broker_buying_power':state.get('buying_power')}
    # Synthetic context validity clocks are generated at request time, not new economic information.
    if signal['mode']=='SIMULATED':guard['context']={'synthetic':True}
    return d,canonical(guard)

def create(signal_id,allocation,target,owner,now=None):
    now=now or time.time()
    with db.atomic() as tx:
        d,binding=details(tx,signal_id,allocation,target,now)
        row={'id':str(uuid.uuid4()),'owner':owner,'details':d,'digest':binding,'status':'REVIEW','created_at':now,'expires_at':d['expires_at']}
        tx.put('intents',row['id'],row);tx.put('audit',row['id'],{'time':now,'action':'TRADE_REVIEW_CREATED','details':binding})
    return row

def decide(id,binding,decision,owner,now=None):
    now=now or time.time();error=None;result=None
    with db.atomic() as tx:
        row=tx.get('intents',id)
        if not row or row['owner']!=owner:raise ValueError('Trade review not found')
        if row['status']!='REVIEW':raise ValueError('Review already consumed or invalidated')
        if binding!=row['digest']:raise ValueError('Displayed trade digest does not match')
        if decision=='reject':row.update(status='REJECTED',decided_at=now);result=row
        else:
            try:
                controls.allow_new(tx)
                if row['expires_at']<=now:raise ValueError('Trade review expired')
                fresh,new_binding=details(tx,row['details']['signal_id'],row['details']['allocation'],row['details']['target'],now)
                if new_binding!=binding:raise ValueError('Price, quantity, costs, portfolio, risk or controls changed. Review a new quote.')
                if any(o.get('details',{}).get('signal_id')==fresh['signal_id'] and o['status'] not in ('REJECTED','CANCELLED_BEFORE_SUBMISSION','INVALIDATED') for o in tx.listing('broker_orders')):raise ValueError('This signal already has a broker paper order')
                if fresh['target']=='LOCAL_PAPER':
                    s=tx.get('signals',fresh['signal_id']);s={**s,'entry':fresh['entry'],'stop':fresh['stop'],'target1':fresh['target1'],'target2':fresh['target2'],'costs':fresh['costs'],'quote_to_usd':fresh['quote_to_usd']}
                    trade=approve(s,fresh['settings'],tx.listing('paper'),now)
                    trade.update(units=fresh['units'],remaining_units=fresh['units'],risk_usd=fresh['risk_usd'],notional_usd=fresh['notional_usd'],margin_usd=fresh['margin_usd'])
                    trade['approval_binding']={'entry':fresh['entry'],'units':fresh['units'],'max_price_drift_bps':0}
                    tx.put('paper',trade['id'],trade);row['paper_id']=trade['id']
                else:
                    client_id='ta-'+hashlib.sha256(id.encode()).hexdigest()[:28]
                    tx.put('broker_orders',id,{'id':id,'client_id':client_id,'details':{**fresh,'expires_at':row['expires_at']},'status':'READY','digest':binding,'created_at':now})
                row.update(status='APPROVED_PAPER',decided_at=now);result=row
            except ValueError as e:row.update(status='INVALIDATED',reason=str(e));error=str(e)
        tx.put('intents',id,row);tx.put('audit',str(uuid.uuid4()),{'time':now,'action':'REVIEW_'+row['status'],'details':id})
        if error:enqueue('INVALIDATED',id,{'instrument':row['details']['symbol'],'recommendation':'NO','reason':error,'mode':row['details']['mode'],'signal_id':row['details']['signal_id']},tx)
    if error:raise ValueError(error)
    return result
