"""Manual owner-only calendar preview. No database or recommendation writes."""
import math
import os
import time
from datetime import datetime, timezone, timedelta
import httpx

ENDPOINT='https://financialmodelingprep.com/stable/economic-calendar'

class CalendarError(ValueError):
    pass

def readiness():
    key=os.getenv('FMP_API_KEY','').strip()
    return {'configured':bool(key and not any(c.isspace() for c in key)),
            'enabled':os.getenv('FMP_CALENDAR_READS_APPROVED')=='true',
            'coverage':'unknown','timing_precision':'unknown','retention':'response_only',
            'pilot_symbol':'EUR/USD','orders_enabled':False}

def review(items,now,retrieved_at,*,incomplete=False):
    """Research review only. Unknown release timing cannot certify paper approval."""
    if not all(type(v) in (int,float) and math.isfinite(v) for v in (now,retrieved_at)):
        raise CalendarError('Invalid calendar review timestamp')
    age=now-retrieved_at
    fresh=0<=age<=300
    blocks=[]
    for event in items:
        # UTC-day caution avoids treating an unconfirmed clock time as exact.
        if event['importance'] in ('high','unknown') and int(event['time']//86400)==int(now//86400):
            blocks.append({'title':event['title'],'currency':event['currency'],
                           'reason':'High or unknown impact with unverified timing on this UTC date'})
    issues=['Release-time status is unavailable; exact event timing cannot be verified',
            'Snapshot completeness and update cadence are not verified']
    if not fresh:issues.append('Calendar review is stale or future-dated')
    if incomplete:issues.append('Some rows are missing currency or the preview is truncated')
    return {'fresh':fresh,'expires_at':retrieved_at+300,'paper_approval_ready':False,
            'potential_blocks':blocks,'issues':issues,
            'scope':'Research review only; scanner and order checks are unchanged'}

def normalize(rows,now,start,end):
    if not isinstance(rows,list) or len(rows)>1000:
        raise CalendarError('FMP calendar response is unavailable or exceeds the preview limit')
    items=[];unknown_currency=0;excluded=0
    try:
        for row in rows:
            if not isinstance(row,dict):raise ValueError()
            title=row.get('event')
            if not isinstance(title,str) or not title.strip():raise ValueError()
            raw=row.get('date')
            if not isinstance(raw,str) or len(raw)>64:raise ValueError()
            at=datetime.fromisoformat(raw.replace('Z','+00:00'))
            # FMP documents calendar timestamps in UTC, including timezone-free strings.
            if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
            stamp=at.timestamp()
            if not math.isfinite(stamp):raise ValueError()
            currency=row.get('currency')
            if not isinstance(currency,str) or not currency.strip():
                unknown_currency+=1;continue
            currency=currency.strip().upper()
            if currency not in ('EUR','USD'):
                excluded+=1;continue
            impact=row.get('impact')
            impact=impact.strip().lower() if isinstance(impact,str) else 'unknown'
            if impact not in ('high','medium','low'):impact='unknown'
            country=row.get('country')
            country=country[:12] if isinstance(country,str) else 'unknown'
            items.append({'title':title[:120],'time':stamp,'currency':currency,'country':country,
                          'importance':impact,'time_precision':'unknown'})
    except (ValueError,TypeError,KeyError,OverflowError):
        raise CalendarError('FMP returned incomplete or invalid calendar fields; details withheld') from None
    items.sort(key=lambda event:event['time'])
    result={'source':'FMP economic calendar','requested_symbol':'EUR/USD','retrieved_at':now,
            'requested_from':start,'requested_to':end,'coverage':'unknown','covered_symbols':[],
            'research_only':True,'retention':'response_only','received_count':len(rows),
            'unknown_currency_count':unknown_currency,'excluded_other_currency_count':excluded,
            'matching_count':len(items),'preview_truncated':len(items)>100,'preview_items':items[:100],
            'pending_checks':['Release-time status unavailable from this provider',
                              'Snapshot completeness and update cadence verification'],
            'note':'Preview only; estimate/actual economic figures do not confirm release timestamps. No scanner or order changes.'}
    result['review']=review(items,now,now,incomplete=bool(unknown_currency or len(items)>100))
    return result

def contains_key(value,key):
    if isinstance(value,str):return key in value
    if isinstance(value,dict):return any(contains_key(v,key) for v in value.values())
    if isinstance(value,list):return any(contains_key(v,key) for v in value)
    return False

async def preview(symbol,transport=None):
    if symbol!='EUR/USD':raise CalendarError('The calendar preview pilot supports EUR/USD only')
    state=readiness()
    if not state['enabled']:raise CalendarError('FMP calendar reads are not enabled')
    if not state['configured']:raise CalendarError('Configure a valid server-held FMP key')
    key=os.environ['FMP_API_KEY'].strip()
    now=time.time()
    day=datetime.fromtimestamp(now,timezone.utc).date()
    start=(day-timedelta(days=1)).isoformat();end=(day+timedelta(days=1)).isoformat()
    try:
        async with httpx.AsyncClient(timeout=20,follow_redirects=False,transport=transport) as client:
            response=await client.get(ENDPOINT,params={'from':start,'to':end,'apikey':key})
        if response.status_code in (401,403):
            raise CalendarError(f'FMP calendar access denied (HTTP {response.status_code}); verify the server key and calendar plan entitlement')
        if response.status_code==402:
            raise CalendarError('FMP calendar access requires an eligible subscription (HTTP 402); confirm calendar entitlement with FMP')
        if response.status_code==404:
            raise CalendarError('FMP calendar endpoint not found (HTTP 404); report this error for connector review')
        if response.status_code==429:raise CalendarError('FMP request limit reached (HTTP 429); retry later')
        if response.status_code!=200:raise CalendarError(f'FMP calendar request failed (HTTP {response.status_code}); report this status for diagnosis')
        if len(response.content)>2000000:raise CalendarError('FMP calendar response exceeds the preview size limit')
        result=normalize(response.json(),now,start,end)
        if contains_key(result,key):raise CalendarError('FMP response withheld to protect credentials')
        return result
    except CalendarError:
        raise
    except Exception:
        raise CalendarError('FMP calendar request failed; credential and transport details withheld') from None
