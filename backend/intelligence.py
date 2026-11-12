"""Point-in-time, deterministic multi-factor research. No LLM or paid inference."""
import math, hashlib, json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pydantic import BaseModel, Field, ConfigDict
from .engine import analyze, ema, INTERVALS

VERSION='confluence-v2.0'
HIGHER={'5min':'15min','15min':'1h','30min':'4h','1h':'4h','4h':'1day','1day':None}

def iso(t): return datetime.fromtimestamp(t,timezone.utc).isoformat()
def timestamp(s): return datetime.fromisoformat(s).timestamp()

class RiskSettings(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    equity:float=Field(10000,gt=0)
    allocation:float=Field(1000,gt=0)
    risk_pct:float=Field(1,gt=0,le=10)
    rr:float=Field(2,ge=1,le=10)
    leverage:float=Field(1,ge=1,le=50)
    max_open_positions:int=Field(3,ge=1,le=100)
    max_exposure_pct:float=Field(100,gt=0,le=500)
    max_portfolio_risk_pct:float=Field(3,gt=0,le=25)
    daily_loss_pct:float=Field(3,gt=0,le=25)
    emergency_stop:bool=False
    signal_ttl_bars:int=Field(2,ge=1,le=6)
    min_score:int=Field(65,ge=0,le=100)
    max_cost_risk_ratio:float=Field(.2,gt=0,le=1)
    max_atr_pct:float=Field(5,gt=0,le=30)
    require_event_coverage:bool=True
    allow_short:bool=True

class ExecutionAssumptions(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    spread_bps:float=Field(1.5,ge=0,le=500)
    slippage_bps:float=Field(1,ge=0,le=500)
    commission_per_unit:float=Field(.005,ge=0,le=100)
    min_units:float=Field(1,gt=0)
    unit_step:float=Field(1,gt=0)
    lot_units:float=Field(1,gt=0)
    min_volume:float=Field(1000,ge=0)
    validated:bool=False
    asof:float=0
    valid_until:float=0

DEFAULT_SETTINGS=RiskSettings().model_dump()

def assumptions(symbol,simulated=False,now=0):
    fx='/' in symbol
    return ExecutionAssumptions(spread_bps=1.2 if fx else 2,slippage_bps=.5 if fx else 1,commission_per_unit=.000035 if fx else .005,min_units=1000 if fx else 1,unit_step=1000 if fx else 1,lot_units=100000 if fx else 1,min_volume=0 if fx else 1000,validated=simulated,asof=now,valid_until=now+86400).model_dump()

def validate_bars(bars):
    prev=-1
    for b in bars:
        vals=[b[k] for k in ('time','open','high','low','close')]
        if not all(math.isfinite(v) for v in vals) or b['time']<=prev or b['low']<=0 or not b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high']: raise ValueError('Invalid, unsorted or duplicate OHLC bars')
        if b.get('volume') is not None and (not math.isfinite(b['volume']) or b['volume']<0): raise ValueError('Invalid volume')
        prev=b['time']

def conversion(symbol,price,context,asof):
    if '/' not in symbol or symbol.endswith('/USD'): return 1.0
    if symbol.startswith('USD/'): return 1/price
    item=context.get('conversion',{})
    value=item.get('quote_to_usd')
    if not value or not math.isfinite(value) or value<=0 or item.get('asof',float('inf'))>asof or item.get('valid_until',0)<asof: return None
    return value

def size_position(symbol,entry,stop,settings,costs,quote_to_usd,portfolio=None):
    s=RiskSettings(**settings); c=ExecutionAssumptions(**costs); p=portfolio or {}
    if not all(math.isfinite(v) and v>0 for v in (entry,stop,quote_to_usd)) or entry==stop: raise ValueError('Invalid prices or currency conversion')
    reasons=[]
    if s.emergency_stop: reasons.append('Emergency stop is enabled')
    if s.allocation>s.equity: reasons.append('Allocation exceeds account equity')
    if p.get('open_count',0)>=s.max_open_positions: reasons.append('Maximum open/pending positions reached')
    if p.get('daily_loss',0)>=s.equity*s.daily_loss_pct/100: reasons.append('Daily loss limit reached (realized losses + unrealized losses)')
    px_cost=entry*(c.spread_bps/2+c.slippage_bps)/10000
    round_cost=2*px_cost*quote_to_usd+2*c.commission_per_unit
    risk_per_unit=abs(entry-stop)*quote_to_usd+round_cost
    risk_budget=s.equity*s.risk_pct/100
    # Allocation is margin capital; leverage multiplies its notional cap.
    exposure_left=max(0,s.equity*s.max_exposure_pct/100-p.get('exposure',0))
    portfolio_left=max(0,s.equity*s.max_portfolio_risk_pct/100-p.get('open_risk',0))
    margin_left=max(0,s.equity-p.get('margin',0))
    raw=min(risk_budget/risk_per_unit,portfolio_left/risk_per_unit,exposure_left/(entry*quote_to_usd),min(s.allocation,margin_left)*s.leverage/(entry*quote_to_usd))
    units=float((Decimal(str(raw))/Decimal(str(c.unit_step))).to_integral_value(rounding=ROUND_FLOOR)*Decimal(str(c.unit_step)))
    if units<c.min_units: reasons.append('Position below broker minimum after risk, margin and exposure limits')
    return {'accepted':not reasons,'units':max(0,units) if not reasons else 0,'lots':max(0,units)/c.lot_units if '/' in symbol and not reasons else None,'shares':max(0,units) if '/' not in symbol and not reasons else None,'risk_usd':units*risk_per_unit if not reasons else 0,'risk_budget':risk_budget,'notional_usd':units*entry*quote_to_usd if not reasons else 0,'margin_usd':units*entry*quote_to_usd/s.leverage if not reasons else 0,'round_trip_cost_per_unit_usd':round_cost,'rejections':reasons}

def trend_features(bars):
    f=analyze(bars)
    if len(bars)<60:return f
    # ADX14 from Wilder smoothing of directional movement and true range.
    trs=[]; plus=[]; minus=[]
    for a,b in zip(bars,bars[1:]):
        up=b['high']-a['high']; down=a['low']-b['low']
        plus.append(up if up>down and up>0 else 0);minus.append(down if down>up and down>0 else 0)
        trs.append(max(b['high']-b['low'],abs(b['high']-a['close']),abs(b['low']-a['close'])))
    tr=sum(trs[:14]);pos=sum(plus[:14]);neg=sum(minus[:14]);dx=[]
    for i in range(14,len(trs)):
        tr=tr-tr/14+trs[i];pos=pos-pos/14+plus[i];neg=neg-neg/14+minus[i]
        dx.append(100*abs(pos-neg)/(pos+neg) if pos+neg else 0)
    adx=sum(dx[:14])/14 if len(dx)>=14 else 0
    for v in dx[14:]:adx=(13*adx+v)/14
    f['adx']=round(adx,2)
    prior=bars[-21:-1];last=bars[-1];res=max(b['high'] for b in prior);sup=min(b['low'] for b in prior)
    f.update(prior_support=sup,prior_resistance=res,structure='bullish break' if last['close']>res else 'bearish break' if last['close']<sup else 'range',supply_zone=[res-f['atr']*.25,res+f['atr']*.25],demand_zone=[sup-f['atr']*.25,sup+f['atr']*.25])
    previous=bars[-2]
    prior_trend=analyze(bars[:-1]) if len(bars)>60 else f
    bullish_reversal=prior_trend['ema20']<prior_trend['ema50'] and last['close']>previous['high'] and last['close']>last['open']
    bearish_reversal=prior_trend['ema20']>prior_trend['ema50'] and last['close']<previous['low'] and last['close']<last['open']
    f['reversal_warning']='possible bullish reversal' if bullish_reversal else 'possible bearish reversal' if bearish_reversal else 'none'
    return f

def recommend(symbol,interval,bars,higher_bars,settings=None,context=None,portfolio=None,now=None,alert_mode='close',strategy='confluence'):
    s=RiskSettings(**(settings or DEFAULT_SETTINGS));ctx=context or {};now=now if now is not None else datetime.now(timezone.utc).timestamp(); step=INTERVALS[interval]
    validate_bars(bars);validate_bars(higher_bars)
    closed=[b for b in bars if b['time']+step<=now]
    provisional=alert_mode=='intrabar'
    visible=[b for b in bars if b['time']<=now] if provisional else closed
    candle=visible[-1]['time'] if visible else int(now//step)*step
    frontier=min(now,candle+step) if not provisional else now
    htf=HIGHER[interval];higher=[b for b in higher_bars if htf and b['time']+INTERVALS[htf]<=frontier]
    f=trend_features(visible) if len(visible)>=60 else {};h=trend_features(higher) if len(higher)>=60 else {}
    expiry=(candle+step*(s.signal_ttl_bars+1)) if not provisional else now+min(step,60)
    costs=ctx.get('costs',assumptions(symbol,False,now));c=ExecutionAssumptions(**costs)
    config_hash=hashlib.sha256(json.dumps({'settings':s.model_dump(),'costs':{k:v for k,v in costs.items() if k not in ('asof','valid_until')},'strategy':strategy},sort_keys=True).encode()).hexdigest()[:12]
    mode=ctx.get('data_mode','UNKNOWN');signal_id=f'{VERSION}:{mode}:{symbol}:{interval}:{int(candle)}:{config_hash}:{int(now*1000) if provisional else "close"}'
    out={'id':signal_id,'engine_version':VERSION,'strategy':strategy,'symbol':symbol,'interval':interval,'higher_timeframe':htf,'decision':'NO TRADE','recommendation':'NO','entry':None,'entry_zone':None,'stop':None,'target':None,'target1':None,'target2':None,'rr':s.rr,'rr2':s.rr*1.5,'confidence':None,'confidence_note':'Score measures rule agreement, not a calibrated success probability','score':0,'rank':None,'reasons':[],'reason':'','generated_at':iso(now),'time':iso(now),'expires_at':iso(expiry),'candle_time':candle,'data_mode':mode,'mode':mode,'market_status':ctx.get('market_status','unknown'),'data_age_seconds':max(0,now-(candle+step)),'alert_mode':alert_mode,'provisional':provisional,'status':'RESEARCH_ONLY' if provisional else 'REJECTED','features':f,'costs':costs,'cost_source':ctx.get('cost_source','assumed'),'sizing':None,'quote_to_usd':None,'settings_snapshot':s.model_dump()}
    reject=[];notes=[]
    if len(visible)<60:reject.append('At least 60 eligible candles required')
    if htf is None:reject.append('No higher timeframe supported for daily confirmation')
    elif len(higher)<60:reject.append('Insufficient completed higher-timeframe candles')
    if not visible:reject.append('No eligible price data')
    if ctx.get('market_status')!='open':reject.append('Market is closed or status is unknown')
    if mode not in ('SIMULATED','REAL-TIME') and not (ctx.get('historical_replay') and mode=='HISTORICAL'):reject.append('Delayed or unknown data is research-only')
    if now>expiry:reject.append('Signal or price data has expired')
    if not c.validated or c.asof>now or c.valid_until<now:reject.append('Current validated cost/liquidity assumptions unavailable')
    news=ctx.get('events',{})
    coverage=news.get('asof',float('inf'))<=now and news.get('valid_until',0)>=now and news.get('coverage')=='complete'
    if s.require_event_coverage and not coverage:reject.append('Economic/news/earnings coverage unavailable or stale')
    for event in news.get('items',[]):
        if event.get('known_at',float('inf'))>now:continue
        if abs(event['time']-now)<=event.get('blackout_seconds',1800) and event.get('importance')=='high':reject.append('High-impact event blackout: '+str(event.get('title','scheduled event'))[:120])
    if f and h:
        price=visible[-1]['close'];atr=f['atr'];vol=atr/price*100;sign=1 if price>f['ema20']>f['ema50'] else -1 if price<f['ema20']<f['ema50'] else 0
        direction='BUY' if sign==1 else 'SELL' if sign==-1 else 'NO TRADE'
        higher_ok=h['ema20']>h['ema50'] if sign==1 else h['ema20']<h['ema50'] if sign==-1 else False
        momentum_ok=f['macd_histogram']*sign>0
        rsi_ok=40<f['rsi']<72 if sign==1 else 28<f['rsi']<60
        structure_ok=f['structure']==('bullish break' if sign==1 else 'bearish break')
        # Continuation requires a recent EMA20 touch and a close back on trend side.
        touch=any(b['low']<=f['ema20']<=b['high'] for b in visible[-6:])
        setup_ok=structure_ok or (strategy=='confluence' and touch and momentum_ok)
        score=20*bool(sign)+20*higher_ok+15*momentum_ok+10*rsi_ok+15*(f['adx']>=18)+10*setup_ok+10*(.01<=vol<=s.max_atr_pct)
        out.update(score=score,price=price,rsi=f['rsi'],atr=atr,adx=f['adx'])
        for ok,label in [(bool(sign),'EMA20/50 trend'),(higher_ok,'Completed higher timeframe agrees'),(momentum_ok,'MACD momentum agrees'),(rsi_ok,'RSI within guardrails'),(f['adx']>=18,'ADX trend strength'),(setup_ok,'Structure break or tested trend continuation')]:
            notes.append(('PASS: ' if ok else 'FAIL: ')+label)
        if not sign or not higher_ok or not momentum_ok or not rsi_ok or not setup_ok or score<s.min_score:reject.append('Conflicting or insufficient technical confirmation')
        if atr<=0 or not .01<=vol<=s.max_atr_pct:reject.append('Volatility outside configured range')
        if direction=='SELL' and not s.allow_short:reject.append('Short positions disabled')
        volume=visible[-1].get('volume')
        if '/' not in symbol and (volume is None or volume<c.min_volume):reject.append('Volume below liquidity threshold or unavailable')
        if '/' in symbol:notes.append('Forex liquidity uses spread proxy; centralized volume/order-book depth unavailable')
        stop=price-sign*max(1.5*atr,abs(price-(f['prior_support'] if sign==1 else f['prior_resistance'])))
        if stop<=0 or not sign:reject.append('Invalid protective stop')
        q=conversion(symbol,price,ctx,frontier)
        if q is None:reject.append('Fresh quote-to-USD conversion required')
        if q and sign and stop>0:
            cost_px=2*price*(c.spread_bps/2+c.slippage_bps)/10000+2*c.commission_per_unit/q
            net_risk=abs(price-stop)+cost_px
            # Net RR includes modeled round-trip friction, not gross distance alone.
            t1=price+sign*(s.rr*net_risk+cost_px);t2=price+sign*(s.rr*1.5*net_risk+cost_px)
            if min(t1,t2)<=0:reject.append('Profit target would be nonpositive')
            if cost_px/max(abs(price-stop),1e-12)>s.max_cost_risk_ratio:reject.append('Transaction costs too large relative to stop distance')
            sizing=size_position(symbol,price,stop,s.model_dump(),costs,q,portfolio)
            reject+=sizing['rejections'];out.update(quote_to_usd=q,sizing=sizing)
            if not reject:out.update(decision=direction,recommendation='YES',entry=price,entry_zone=[price-atr*.1,price+atr*.1],stop=stop,target=t1,target1=t1,target2=t2,status='PROVISIONAL' if provisional else 'WAITING_FOR_USER_APPROVAL')
    if provisional:notes.append('Intrabar preview may change before close; not eligible for paper entry')
    notes.append('Confirmed close signals wait for candle completion; delivery and execution have nonzero latency')
    out['reasons']=reject+notes;out['reason']='; '.join(reject) if reject else 'Higher timeframe, trend, momentum and structure align after cost and risk checks'
    return out

def rank_signals(signals):
    ranked=sorted(signals,key=lambda s:(s.get('recommendation')=='YES',s.get('score',0),s.get('symbol','')),reverse=True)
    for i,s in enumerate(ranked,1):s['rank']=i
    return ranked
