"""Fail-closed validation of timestamped, symbol-scoped calendar snapshots."""
import math

MAX_SNAPSHOT_AGE=900
MAX_BLACKOUT=86400

def finite(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except (ValueError,OverflowError):return False

def assess(symbol,news,now,mode):
    issues=[];blackouts=[]
    if not isinstance(news,dict):return {'complete':False,'issues':['Event snapshot missing'],'blackouts':[]}
    simulated=mode=='SIMULATED'
    asof=news.get('asof');until=news.get('valid_until')
    if not (finite(asof) and finite(until) and asof<=now<=until):
        issues.append('Event snapshot missing, expired or future-dated')
    if news.get('coverage')!='complete':issues.append('Event coverage not declared complete')
    if not simulated:
        if finite(asof) and now-asof>MAX_SNAPSHOT_AGE:issues.append('Event snapshot older than 15 minutes')
        source=news.get('source')
        if not isinstance(source,str) or not source.strip() or len(source)>160:issues.append('Event source required')
        scope=news.get('covered_symbols')
        if not isinstance(scope,list) or symbol not in scope:issues.append('Event coverage does not include this instrument')
        start=news.get('window_start');end=news.get('window_end')
        if not (finite(start) and finite(end) and start<=now-MAX_BLACKOUT and end>=now+MAX_BLACKOUT):
            issues.append('Calendar window must cover 24 hours before and after review')
    items=news.get('items',[] if simulated else None)
    if not isinstance(items,list) or len(items)>100:
        return {'complete':False,'issues':issues+['Event list missing or exceeds supported size'],'blackouts':[]}
    for event in items:
        if not isinstance(event,dict):
            issues.append('Malformed event');continue
        at=event.get('time');known=event.get('known_at');importance=event.get('importance')
        blackout=event.get('blackout_seconds',1800)
        if not (finite(at) and finite(known) and type(blackout) is int and 0<=blackout<=MAX_BLACKOUT and importance in ('low','medium','high')):
            issues.append('Invalid event timing, importance or blackout');continue
        if known>now:
            if not simulated:issues.append('Event knowledge timestamp is in the future')
            continue
        if not simulated and finite(asof) and known>asof:issues.append('Event knowledge timestamp is later than snapshot')
        precision=event.get('time_precision','exact' if simulated else 'unknown')
        if precision not in ('exact','estimated','date_only','unknown'):
            issues.append('Invalid event time precision');continue
        if not simulated and importance=='high' and precision!='exact':
            issues.append('High-impact event timing is uncertain')
        # An incomplete calendar must never suppress an explicitly known blackout.
        if importance=='high' and abs(at-now)<=blackout:
            blackouts.append('High-impact event blackout: '+str(event.get('title','scheduled event'))[:120])
    return {'complete':not issues,'issues':list(dict.fromkeys(issues)),'blackouts':blackouts}
