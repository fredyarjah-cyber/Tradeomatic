"""Chronological replay with train-only parameter selection and untouched test folds."""
from .intelligence import recommend, HIGHER, DEFAULT_SETTINGS, assumptions, iso, validate_bars
from .engine import INTERVALS
from .paper import approve, advance, close_leg, portfolio_summary, performance, ACTIVE

def aggregate(bars,base_interval,higher_interval):
    if not higher_interval:return []
    base=INTERVALS[base_interval];step=INTERVALS[higher_interval];groups={}
    for b in bars:groups.setdefault(int(b['time']//step)*step,[]).append(b)
    out=[]
    for start,group in sorted(groups.items()):
        if len(group)!=step//base or [b['time'] for b in group]!=list(range(start,start+step,base)):continue
        out.append({'time':start,'open':group[0]['open'],'high':max(b['high'] for b in group),'low':min(b['low'] for b in group),'close':group[-1]['close'],'volume':sum(b['volume'] for b in group) if all(b.get('volume') is not None for b in group) else None})
    return out

def replay(bars,symbol='EUR/USD',interval='1h',settings=None,context=None,start=240,end=None,strategy='confluence',higher_bars=None):
    validate_bars(bars);end=end or len(bars);s={**DEFAULT_SETTINGS,**(settings or {})};step=INTERVALS[interval]
    htf=HIGHER[interval];higher_bars=higher_bars if higher_bars is not None else aggregate(bars,interval,htf)
    trades=[];signals=[];active=None
    for i in range(start,end):
        frontier=bars[i]['time']+step
        history=bars[:i+1]
        if active is not None:
            active=advance(active,[bars[i]],frontier,s,portfolio_summary([t for t in trades if t['id']!=active['id']],frontier))
            trades[-1]=active
            if active['status'] not in ACTIVE:active=None
        # Only information published at this frontier enters the decision.
        ctx=dict(context or {});ctx.setdefault('data_mode','HISTORICAL');ctx.setdefault('market_status','open')
        # HISTORICAL is not a live entitlement. Explicitly label replay source separately.
        ctx['historical_replay']=True
        signal=recommend(symbol,interval,history,higher_bars,s,ctx,portfolio_summary(trades,frontier),frontier,strategy=strategy)
        signal['replay_source']=(context or {}).get('data_mode','HISTORICAL');signals.append(signal)
        if active is None and signal['recommendation']=='YES':
            active=approve(signal,s,trades,frontier);trades.append(active)
    if active and active['status'] in ('OPEN','PARTIAL'):
        close_leg(active,bars[end-1]['close'],active['remaining_units'],bars[end-1]['time']+step,'PREDECLARED_END_OF_TEST_LIQUIDATION');trades[-1]=active
    elif active and active['status']=='PENDING_ENTRY':active['status']='CANCELLED';active['exit_reason']='End of test';trades[-1]=active
    return {'metrics':performance(trades,s['equity']),'trades':trades,'signals':signals}

def walk_forward(bars,symbol='EUR/USD',interval='1h',settings=None,context=None,train_bars=400,test_bars=160,higher_bars=None):
    validate_bars(bars);s={**DEFAULT_SETTINGS,**(settings or {})}
    warmup=max(60,60*INTERVALS[HIGHER[interval]]//INTERVALS[interval]) if HIGHER[interval] else 60
    if len(bars)<warmup+train_bars+test_bars:raise ValueError(f'Need at least {warmup+train_bars+test_bars} chronological bars for warmup, training and one test fold')
    candidates=list(dict.fromkeys([(st,rr) for st,rr in [('confluence',1.5),('confluence',2),('breakout',2),('breakout',3)] if rr>=s['rr']]+[('confluence',s['rr']),('breakout',s['rr'])]))
    folds=[];all_test_trades=[];comparisons=[]
    for test_start in range(warmup+train_bars,len(bars)-test_bars+1,test_bars):
        train_start=test_start-train_bars
        training=[]
        for strategy,rr in candidates:
            result=replay(bars,symbol,interval,{**s,'rr':rr},context,train_start,test_start,strategy,higher_bars)
            m=result['metrics'];training.append({'strategy':strategy,'rr':rr,'metrics':m,'selection_score':m['average_r_multiple'] if m['closed_trades']>=3 else None})
        eligible=[t for t in training if t['selection_score'] is not None]
        selected=max(eligible,key=lambda t:t['selection_score']) if eligible else next(t for t in training if t['strategy']=='confluence' and t['rr']==s['rr'])
        tested=replay(bars,symbol,interval,{**s,'rr':selected['rr']},context,test_start,test_start+test_bars,selected['strategy'],higher_bars)
        # Each fold uses starting equity independently; aggregate metric uses realized net cashflows.
        all_test_trades+=tested['trades'];comparisons.append(training)
        folds.append({'train_start':iso(bars[train_start]['time']),'train_end':iso(bars[test_start-1]['time']+INTERVALS[interval]),'test_start':iso(bars[test_start]['time']),'test_end':iso(bars[test_start+test_bars-1]['time']+INTERVALS[interval]),'selected_strategy':selected['strategy'],'selected_rr':selected['rr'],'selection_basis':'Best train average R with >=3 closed trades' if eligible else 'Default, insufficient training trades','test_metrics':tested['metrics']})
    return {'kind':'WALK_FORWARD_RESEARCH','source':(context or {}).get('data_mode','HISTORICAL'),'symbol':symbol,'interval':interval,'settings':s,'folds':folds,'training_comparisons':comparisons,'metrics':performance(all_test_trades,s['equity']),'trades':all_test_trades,'assumptions':context,'limitations':['No profitability claim. Untested with a licensed historical feed.','Stop-first for ambiguous OHLC; entry only at a subsequent bar open inside entry zone.','Spread, slippage and per-unit commissions modeled on both sides; no borrow fees, financing or market impact.','Daily loss uses UTC day; conversion held at entry snapshot.','Fixed universe has survivorship/selection bias; corporate actions require point-in-time adjusted OHLC.','Realized drawdown excludes intratrade equity moves. Fold capital resets; aggregate cashflow curve is not a compounded portfolio.','No historical events/costs may be inferred from future information. Missing required coverage blocks signals.']}
