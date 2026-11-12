"""Deterministic paper ledger and conservative completed-OHLC execution model."""
import copy, uuid
from datetime import datetime, timezone
from .intelligence import iso, timestamp, size_position, RiskSettings
from .engine import INTERVALS
ACTIVE=('PENDING_ENTRY','OPEN','PARTIAL')

def portfolio_summary(trades,now):
    day=datetime.fromtimestamp(now,timezone.utc).date()
    active=[t for t in trades if t['status'] in ACTIVE]
    realized_losses=0;unrealized_losses=0
    for t in trades:
        for leg in t.get('fills',[]):
            if leg['kind']=='exit' and datetime.fromtimestamp(leg['time'],timezone.utc).date()==day:realized_losses+=max(0,-leg['pnl'])
        if t['status'] in ('OPEN','PARTIAL'):unrealized_losses+=max(0,-t.get('unrealized_pnl',0))
    return {'open_count':len(active),'exposure':sum(t.get('notional_usd',0)*(t.get('remaining_units',t['units'])/t['units']) for t in active),'open_risk':sum(t.get('risk_usd',0)*(t.get('remaining_units',t['units'])/t['units']) for t in active),'margin':sum(t.get('margin_usd',0)*(t.get('remaining_units',t['units'])/t['units']) for t in active),'daily_loss':realized_losses+unrealized_losses}

def approve(signal,settings,trades,now):
    if signal.get('recommendation')!='YES' or signal.get('provisional'):raise ValueError('Only confirmed YES signals may be approved for paper trading')
    if now>=timestamp(signal['expires_at']):raise ValueError('Signal expired')
    if any(t['signal_id']==signal['id'] for t in trades):raise ValueError('Signal has already been approved')
    if any(t['symbol']==signal['symbol'] and t['status'] in ACTIVE for t in trades):raise ValueError('An active paper position already exists for this instrument')
    sizing=size_position(signal['symbol'],signal['entry'],signal['stop'],settings,signal['costs'],signal['quote_to_usd'],portfolio_summary(trades,now))
    if not sizing['accepted']:raise ValueError('; '.join(sizing['rejections']))
    t={'id':str(uuid.uuid4()),'signal_id':signal['id'],'symbol':signal['symbol'],'interval':signal['interval'],'direction':signal['decision'],'status':'PENDING_ENTRY','approved_at':now,'expires_at':signal['expires_at'],'stop':signal['stop'],'initial_stop':signal['stop'],'target1':signal['target1'],'target2':signal['target2'],'entry_reference':signal['entry'],'entry_zone':signal['entry_zone'],'quote_to_usd':signal['quote_to_usd'],'costs':signal['costs'],'settings':copy.deepcopy(settings),'data_mode':signal.get('mode','UNKNOWN'),'units':sizing['units'],'remaining_units':sizing['units'],'risk_usd':sizing['risk_usd'],'notional_usd':sizing['notional_usd'],'margin_usd':sizing['margin_usd'],'fills':[],'pnl':0,'unrealized_pnl':0,'last_bar':None,'exit_recommendation':'HOLD','exit_reason':'Approved for paper only; waiting for a subsequent bar open within the entry zone','events':[{'time':now,'action':'APPROVED_PAPER_ONLY'}]}
    return t

def friction(t,price):return price*(t['costs']['spread_bps']/2+t['costs']['slippage_bps'])/10000

def close_leg(t,price,units,at,reason):
    sign=1 if t['direction']=='BUY' else -1
    fill=price-sign*friction(t,price);q=t['quote_to_usd'];fee=units*t['costs']['commission_per_unit']
    # Allocate entry commission to each exit leg; metrics include both sides.
    pnl=sign*(fill-t['entry_fill'])*units*q-fee-units*t['costs']['commission_per_unit']
    t['fills'].append({'kind':'exit','time':at,'price':fill,'mid':price,'units':units,'pnl':pnl,'reason':reason,'fee_usd':fee})
    t['pnl']+=pnl;t['remaining_units']=max(0,t['remaining_units']-units)
    t['events'].append({'time':at,'action':reason})
    if t['remaining_units']<=1e-9:t.update(status='CLOSED',closed_at=at,unrealized_pnl=0,exit_recommendation='CLOSE',exit_reason=reason)
    else:t['status']='PARTIAL'

def advance(trade,bars,now,settings=None,portfolio=None,features=None):
    """Immutable input; stop wins ambiguous OHLC bars. Never fill on the signal bar."""
    t=copy.deepcopy(trade);s=RiskSettings(**(settings or t['settings']));step=INTERVALS[t['interval']];sign=1 if t['direction']=='BUY' else -1
    for b in bars:
        at=b['time']
        if at+step>now or at<t['approved_at'] or (t['last_bar'] is not None and at<=t['last_bar']):continue
        if t['status'] not in ACTIVE:break
        t['last_bar']=at
        if t.get('pending_stop') and at>=t['pending_stop']['effective_at']:
            t['stop']=t['pending_stop']['price'];t.pop('pending_stop')
        if t['status']=='PENDING_ENTRY':
            if s.emergency_stop:t.update(status='CANCELLED',exit_reason='Emergency stop cancelled unfilled paper entry');break
            if at>=timestamp(t['expires_at']):t.update(status='EXPIRED',exit_reason='Entry window expired');break
            if not t['entry_zone'][0]<=b['open']<=t['entry_zone'][1]:continue
            if sign*(b['open']-t['stop'])<=0:t.update(status='REJECTED',exit_reason='Opening gap invalidated stop');break
            binding=t.get('approval_binding')
            if binding and (abs(b['open']-binding['entry'])/binding['entry']*10000>binding['max_price_drift_bps']):
                t.update(status='INVALIDATED',exit_reason='Entry price changed after approval; review new quoted details');break
            # The pending trade has already reserved capital; exclude it from portfolio.
            sized=size_position(t['symbol'],b['open'],t['stop'],s.model_dump(),t['costs'],t['quote_to_usd'],portfolio)
            if not sized['accepted']:t.update(status='REJECTED',exit_reason='; '.join(sized['rejections']));break
            if binding and sized['units']!=binding['units']:
                t.update(status='INVALIDATED',exit_reason='Approved quantity no longer passes risk checks; new approval required');break
            t.update(units=min(t['units'],sized['units']),entry_mid=b['open'],entry_fill=b['open']+sign*friction(t,b['open']),entered_at=at,status='OPEN')
            t['remaining_units']=t['units'];t['risk_usd']=sized['risk_usd']*t['units']/sized['units'];t['notional_usd']=t['units']*b['open']*t['quote_to_usd'];t['margin_usd']=t['notional_usd']/s.leverage
            expected_risk=abs(b['open']-t['stop'])+2*friction(t,b['open'])+2*t['costs']['commission_per_unit']/t['quote_to_usd']
            reward=sign*(t['target1']-b['open'])-2*friction(t,b['open'])-2*t['costs']['commission_per_unit']/t['quote_to_usd']
            if reward/expected_risk<s.rr*.999:t.update(status='REJECTED',exit_reason='Entry gap violates minimum net reward/risk');break
            t['fills'].append({'kind':'entry','time':at,'price':t['entry_fill'],'mid':b['open'],'units':t['units'],'fee_usd':t['units']*t['costs']['commission_per_unit']})
        if t.get('close_requested_at') is not None and at>=t['close_requested_at']:
            close_leg(t,b['open'],t['remaining_units'],at,'USER_PAPER_CLOSE');break
        stop_hit=b['low']<=t['stop'] if sign==1 else b['high']>=t['stop']
        if stop_hit:
            stop_price=min(t['stop'],b['open']) if sign==1 else max(t['stop'],b['open'])
            close_leg(t,stop_price,t['remaining_units'],at,'STOP_LOSS (stop-first if OHLC ambiguous)');break
        target1_hit=b['high']>=t['target1'] if sign==1 else b['low']<=t['target1']
        target2_hit=b['high']>=t['target2'] if sign==1 else b['low']<=t['target2']
        if target1_hit and not t.get('target1_reached'):
            t['target1_reached']=True
            # Respect broker step sizes for the partial quantity too.
            step_units=t['costs']['unit_step'];partial=math_floor(t['remaining_units']/2/step_units)*step_units
            if partial>=t['costs']['min_units'] and t['remaining_units']-partial>=t['costs']['min_units']:close_leg(t,t['target1'],partial,at,'TAKE_PROFIT_1')
            t.update(exit_recommendation='PARTIAL EXIT',exit_reason='Target 1 reached; model took half only if broker minimums permit')
        if target2_hit:
            close_leg(t,t['target2'],t['remaining_units'],at,'TAKE_PROFIT_2');break
        t['last_price']=b['close'];t['unrealized_pnl']=sign*(b['close']-sign*friction(t,b['close'])-t['entry_fill'])*t['remaining_units']*t['quote_to_usd']-2*t['remaining_units']*t['costs']['commission_per_unit']
        f=features or {}
        if s.emergency_stop:t.update(exit_recommendation='CLOSE',exit_reason='Emergency stop enabled. Existing paper position remains monitored; approve paper close explicitly.')
        elif f.get('ema20') and sign*(b['close']-f['ema20'])<0 and sign*f.get('macd_histogram',0)<0:t.update(exit_recommendation='CLOSE',exit_reason='Price and momentum moved against the position')
        elif t.get('target1_reached'):t.update(exit_recommendation='ADJUST STOP LOSS',suggested_stop=t['entry_mid'],exit_reason='Target 1 reached. Consider tightening the remaining stop to entry; approval required.')
        else:t.update(exit_recommendation='HOLD',exit_reason='Protective levels intact; no confirmed adverse reversal')
    if t['status']=='PENDING_ENTRY' and now>=timestamp(t['expires_at']):t.update(status='EXPIRED',exit_reason='No eligible entry before expiration')
    return t

def math_floor(x):
    import math
    return math.floor(x+1e-10)

def request_exit(t,action,now,new_stop=None):
    t=copy.deepcopy(t)
    if t['status'] not in ACTIVE:raise ValueError('Paper trade is not active')
    if action=='cancel' and t['status']=='PENDING_ENTRY':t.update(status='CANCELLED',exit_reason='User cancelled pending paper entry')
    elif action=='close' and t['status'] in ('OPEN','PARTIAL'):t['close_requested_at']=now
    elif action=='adjust_stop' and t['status'] in ('OPEN','PARTIAL'):
        sign=1 if t['direction']=='BUY' else -1
        if new_stop is None or not math_isfinite(new_stop) or new_stop<=0 or sign*(new_stop-t['stop'])<=0 or sign*(t.get('last_price',t['entry_mid'])-new_stop)<=0:raise ValueError('New stop must tighten protection and remain behind current modeled price')
        t['pending_stop']={'price':new_stop,'effective_at':now}
    else:raise ValueError('Action is invalid for this paper state')
    t['events'].append({'time':now,'action':'USER_'+action.upper()});return t

def math_isfinite(x):
    import math
    return math.isfinite(x)

def performance(trades,equity=10000):
    closed=sorted([t for t in trades if t.get('status')=='CLOSED'],key=lambda t:t['closed_at']);p=[t['pnl'] for t in closed]
    profit=sum(max(x,0) for x in p);loss=-sum(min(x,0) for x in p);balance=equity;peak=equity;dd=0;curve=[{'time':None,'equity':equity}]
    for t in closed:
        balance+=t['pnl'];peak=max(peak,balance);dd=max(dd,(peak-balance)/peak if peak>0 else 0);curve.append({'time':t['closed_at'],'equity':balance})
    r=[t['pnl']/t['risk_usd'] for t in closed if t.get('risk_usd',0)>0]
    return {'closed_trades':len(p),'win_rate':sum(x>0 for x in p)/len(p) if p else None,'profit_factor':profit/loss if loss else None,'profit_factor_note':'Undefined when no losing trades' if not loss else None,'max_drawdown_pct':dd*100,'drawdown_basis':'Realized closed-trade equity; intratrade drawdown is not included','average_r_multiple':sum(r)/len(r) if r else None,'net_pnl':sum(p),'equity_curve':curve,'sample_warning':'Research only. No evidence of profitability from this sample alone.','costs_included':True}
