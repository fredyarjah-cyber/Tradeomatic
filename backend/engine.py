"""Closed-candle research rules. No execution and no uncalibrated probabilities."""
import math
from datetime import datetime, timezone

FOREX = ['EUR/USD','GBP/USD','AUD/USD','NZD/USD','USD/JPY','USD/CHF','USD/CAD','EUR/GBP','EUR/JPY','EUR/CHF','EUR/CAD','EUR/AUD','EUR/NZD','GBP/JPY','GBP/CHF','GBP/CAD','GBP/AUD','GBP/NZD','AUD/JPY','AUD/CHF','AUD/CAD','AUD/NZD','CAD/JPY','CAD/CHF','CHF/JPY','NZD/JPY','NZD/CHF','NZD/CAD']
SYMBOLS = FOREX + ['AAPL','MSFT','NVDA','AMZN','GOOGL','META','SPY','QQQ','DIA','IWM']
INTERVALS = {'5min':300,'15min':900,'30min':1800,'1h':3600,'4h':14400,'1day':86400}

def ema(values, length):
    out = [values[0]]
    for x in values[1:]: out.append(out[-1]+2/(length+1)*(x-out[-1]))
    return out

def analyze(bars, rr=2):
    if len(bars)<60: return {'decision':'NO TRADE','reason':'At least 60 completed candles required','confidence':None}
    c=[b['close'] for b in bars]; e20=ema(c,20); e50=ema(c,50)
    delta=[c[i]-c[i-1] for i in range(1,len(c))]
    gains=sum(max(x,0) for x in delta[:14])/14; losses=sum(max(-x,0) for x in delta[:14])/14
    for d in delta[14:]: gains=(gains*13+max(d,0))/14; losses=(losses*13+max(-d,0))/14
    rsi=100-100/(1+gains/losses) if losses else (100 if gains else 50)
    tr=[max(bars[i]['high']-bars[i]['low'],abs(bars[i]['high']-c[i-1]),abs(bars[i]['low']-c[i-1])) for i in range(1,len(c))]
    atr=sum(tr[:14])/14
    for x in tr[14:]: atr=(atr*13+x)/14
    macd=[a-b for a,b in zip(ema(c,12),ema(c,26))]; hist=macd[-1]-ema(macd,9)[-1]
    buy=c[-1]>e20[-1]>e50[-1] and 45<rsi<70 and hist>0
    sell=c[-1]<e20[-1]<e50[-1] and 30<rsi<55 and hist<0
    direction='BUY' if buy else 'SELL' if sell else 'NO TRADE'; sign=1 if buy else -1
    actionable=direction!='NO TRADE' and atr>0
    return {'decision':direction if actionable else 'NO TRADE','entry':c[-1] if actionable else None,'stop':c[-1]-sign*1.5*atr if actionable else None,'target':c[-1]+sign*rr*1.5*atr if actionable else None,'rr':rr,'confidence':None,'confidence_note':'Uncalibrated rule set; no success probability available','rsi':round(rsi,1),'atr':atr,'ema20':e20[-1],'ema50':e50[-1],'macd_histogram':hist,'support':min(b['low'] for b in bars[-20:]),'resistance':max(b['high'] for b in bars[-20:]),'reason':'Trend, momentum and RSI agree on completed candles' if actionable else 'Trend, momentum or RSI filters do not agree'}

def position_size(equity, allocation, risk_pct, entry, stop, quote_to_usd=1, rr=2):
    vals=[equity,allocation,risk_pct,entry,stop,quote_to_usd,rr]
    if not all(math.isfinite(v) and v>0 for v in vals) or risk_pct>100 or allocation>equity or entry==stop: raise ValueError('Positive finite values, distinct stop, allocation <= equity and risk <= 100 required')
    budget=equity*risk_pct/100
    risk_units=budget/(abs(entry-stop)*quote_to_usd)
    allocation_units=allocation/(entry*quote_to_usd)
    units=min(risk_units,allocation_units)
    return {'units':units,'risk_usd':units*abs(entry-stop)*quote_to_usd,'risk_budget':budget,'notional_usd':units*entry*quote_to_usd,'reward_usd':units*abs(entry-stop)*quote_to_usd*rr,'note':'Unleveraged notional cap; quote currency conversion must be current. Fees, spread and slippage excluded.'}

def demo_bars(symbol, interval='1h', now=None, count=100):
    """Synthetic deterministic candles; identical history across repeated scans."""
    import hashlib
    now=now or datetime.now(timezone.utc); step=INTERVALS[interval]; bucket=int(now.timestamp())//step
    seed=int(hashlib.sha256(symbol.encode()).hexdigest()[:8],16)
    base=150 if 'JPY' in symbol else 1.08 if '/' in symbol else 220
    def price(t):
        k=t/3600+seed%1000
        return base*(1+.025*math.sin(k/160)+.003*math.sin(k/5)+.001*math.sin(k*1.7))
    out=[]
    for k in range(bucket-count,bucket):
        t=k*step;o=price(t);c=price(t+step);w=base*.00065
        out.append({'time':t,'open':o,'high':max(o,c)+w,'low':min(o,c)-w,'close':c,'volume':None if '/' in symbol else 10000+int(abs(math.sin(k))*50000)})
    return out
