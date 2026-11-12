"""Durable push outbox. Notification actions never place or approve an order."""
import os,time,hashlib,json,base64,secrets
from urllib.parse import urlsplit
from pydantic import BaseModel,ConfigDict,Field
from . import db
from .security import encrypt,decrypt

class Preferences(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:bool=False
    opportunities:bool=True
    no_trade:bool=False
    entries:bool=True
    exits:bool=True
    health:bool=True
    details_on_lock_screen:bool=True
    snooze_minutes:int=Field(30,ge=1,le=1440)

def preferences():return {**Preferences().model_dump(),**db.get('config','notifications',{})}
def pref_save(changes):
    s=Preferences(**{**preferences(),**changes}).model_dump();db.put('config','notifications',s);return s

def validate_subscription(s):
    u=urlsplit(s.get('endpoint',''));host=(u.hostname or '').lower()
    approved=host in ('fcm.googleapis.com','updates.push.services.mozilla.com','updates-autopush.stage.mozaws.net') or host.endswith('.push.apple.com') or host.endswith('.notify.windows.com')
    if u.scheme!='https' or not approved or u.username or u.password or u.fragment or u.port not in (None,443):raise ValueError('Unsupported push-service endpoint')
    for key,length in [('p256dh',65),('auth',16)]:
        raw=s.get('keys',{}).get(key,'')
        try:data=base64.urlsafe_b64decode(raw+'='*(-len(raw)%4))
        except Exception:raise ValueError('Invalid push encryption key')
        if len(data)!=length:raise ValueError('Invalid push encryption key length')
    if len(s['endpoint'])>3000:raise ValueError('Push endpoint too long')
    return {'endpoint':s['endpoint'],'keys':{k:s['keys'][k] for k in ('p256dh','auth')}}

def subscribe(subscription,label):
    s=validate_subscription(subscription);id=hashlib.sha256(s['endpoint'].encode()).hexdigest()
    db.put('push_devices',id,{'id':id,'label':label[:60],'subscription':encrypt(s),'enabled':True,'created_at':time.time()});db.audit('PUSH_DEVICE_REGISTERED',id[:12]);return id

def enqueue(kind,key,details,tx=None):
    id=hashlib.sha256((kind+':'+key).encode()).hexdigest()
    row={'id':id,'kind':kind,'details':details,'created_at':time.time(),'status':'QUEUED'}
    if tx:
        if not tx.get('notifications',id):tx.put('notifications',id,row)
    else:db.put_once('notifications',id,row)
    return id

def signal_details(s):
    return {'signal_id':s.get('id'),'instrument':s.get('symbol'),'market':'Forex' if '/' in s.get('symbol','') else 'US stock / ETF','recommendation':s.get('recommendation','NO'),'direction':s.get('decision','NO TRADE'),'price':s.get('price',s.get('entry')),'price_time':s.get('price_time',s.get('time')),'entry':s.get('entry'),'stop':s.get('stop'),'target1':s.get('target1'),'target2':s.get('target2'),'units':(s.get('sizing') or {}).get('units'),'lots':(s.get('sizing') or {}).get('lots'),'risk_usd':(s.get('sizing') or {}).get('risk_usd'),'rr':s.get('rr'),'reason':s.get('reason',''),'mode':s.get('mode','UNKNOWN'),'expires_at':s.get('expires_at')}

def observe_signal(s,now):
    p=preferences();symbol=s['symbol'];key=symbol+':'+s['interval'];old=db.get('alert_state',key,{})
    d=signal_details(s)
    fingerprint=hashlib.sha256(json.dumps({k:d[k] for k in ('recommendation','direction','entry','stop','target1','target2','units','reason')},sort_keys=True).encode()).hexdigest()
    if p['opportunities'] and s.get('recommendation')=='YES' and old.get('fingerprint')!=fingerprint:enqueue('OPPORTUNITY',key+':'+fingerprint,d)
    if p['no_trade'] and s.get('recommendation')!='YES' and old.get('fingerprint')!=fingerprint:enqueue('NO_TRADE',key+':'+fingerprint,d)
    if old.get('recommendation')=='YES' and s.get('recommendation')!='YES':enqueue('INVALIDATED',old.get('signal_id',key),{**d,'reason':'Previous opportunity is no longer valid: '+d['reason']})
    if p['entries'] and s.get('entry_zone') and s.get('price') is not None:
        inside=s['entry_zone'][0]<=s['price']<=s['entry_zone'][1]
        if inside and old.get('entry_alert_for')!=s['id']:
            enqueue('ENTRY_ZONE',s['id'],{**d,'reason':'Latest completed candle reached the entry zone. Open review to obtain a fresh quote before approval.'})
            old['entry_alert_for']=s['id']
    db.put('alert_state',key,{**old,'signal_id':s['id'],'fingerprint':fingerprint,'recommendation':s['recommendation'],'details':d,'expires_at':s.get('expires_at')})

def expire_signals(now):
    from .intelligence import timestamp
    for state in db.listing('alert_state'):
        if state.get('recommendation')=='YES' and state.get('expires_at') and timestamp(state['expires_at'])<=now:
            enqueue('EXPIRED',state['signal_id'],{**state['details'],'recommendation':'NO','reason':'Recommendation expired. A new quote and approval are required.'})

def payload(event,p):
    d=event['details'];title=f"Tradeomatic · {event['kind'].replace('_',' ')} · {d.get('instrument','Service')}"
    value=lambda k:'—' if d.get(k) is None else str(round(d[k],5)) if isinstance(d[k],(float,int)) else str(d[k])
    body=(f"{value('market')} · {value('recommendation')} {value('direction')}\nPrice {value('price')} @ {value('price_time')}\nEntry {value('entry')} · SL {value('stop')}\nTP1 {value('target1')} · TP2 {value('target2')}\nSize {value('units')} units · Risk ${value('risk_usd')} · RR {value('rr')}:1\n{d.get('reason','')[:180]} · U/P&L ${value('unrealized_pnl')} · {d.get('mode','')}" if p['details_on_lock_screen'] else 'A trading research update is ready. Sign in to view the details.')
    return {'id':event['id'],'title':title,'body':body,'tag':event['id'],'data':{'event_id':event['id'],'signal_id':d.get('signal_id'),'details':d},'actions':[{'action':'approve','title':'YES — APPROVE TRADE'},{'action':'reject','title':'NO — REJECT TRADE'},{'action':'view','title':'VIEW ANALYSIS'},{'action':'snooze','title':'SNOOZE SIGNAL'}]}

def deliver_once(now=None,sender=None):
    now=now or time.time();p=preferences()
    if not p['enabled'] or os.getenv('PUSH_ENABLED')!='true':return
    if not os.getenv('VAPID_PRIVATE_KEY') or not os.getenv('VAPID_SUBJECT'):return
    if sender is None:
        from pywebpush import webpush
        def sender(s,data):webpush(subscription_info=s,data=json.dumps(data,separators=(',',':')),vapid_private_key=os.environ['VAPID_PRIVATE_KEY'],vapid_claims={'sub':os.environ['VAPID_SUBJECT']},timeout=15,ttl=120)
    for event in sorted(db.listing('notifications'),key=lambda e:e['created_at'])[-500:]:
        if now-event['created_at']>86400:continue
        if db.get('signal_decisions',event['details'].get('signal_id',''),{}).get('decision')=='REJECT' and event['kind'] not in ('EXPIRED','INVALIDATED','HEALTH'):continue
        if event['kind'] in ('OPPORTUNITY','ENTRY_ZONE') and event['details'].get('expires_at'):
            from .intelligence import timestamp
            if timestamp(event['details']['expires_at'])<=now:continue
        snooze=db.get('snoozes',event['details'].get('signal_id',''),{})
        if snooze.get('until',0)>now:continue
        if event['kind'] in ('EXIT','POSITION') and not p['exits']:continue
        if event['kind']=='HEALTH' and not p['health']:continue
        for device in db.listing('push_devices'):
            if not device['enabled']:continue
            key=event['id']+':'+device['id'];claim=secrets.token_hex(12)
            with db.atomic() as tx:
                job=tx.get('push_delivery',key,{'attempts':0,'status':'QUEUED','next_attempt':0})
                if job['status'] in ('SENT','GONE','FAILED') or job['next_attempt']>now:continue
                if job.get('lease_until',0)>now:continue
                job.update(status='SENDING',lease_until=now+60,claim=claim,attempts=job['attempts']+1);tx.put('push_delivery',key,job)
            try:
                sender(decrypt(device['subscription']),payload(event,p));status='SENT';error=None
            except Exception as e:
                code=getattr(getattr(e,'response',None),'status_code',None)
                status='GONE' if code in (404,410) else 'FAILED' if job['attempts']>=5 else 'RETRY';error='Push endpoint expired' if status=='GONE' else 'Push delivery failed; transport detail redacted'
            with db.atomic() as tx:
                current=tx.get('push_delivery',key,{})
                if current.get('claim')!=claim:continue
                current.update(status=status,last_error=error,lease_until=0,next_attempt=now+min(3600,30*2**job['attempts']));tx.put('push_delivery',key,current)
                if status=='GONE':device['enabled']=False;tx.put('push_devices',device['id'],device)

async def main():
    import asyncio
    db.init()
    while True:
        try:expire_signals(time.time());deliver_once();db.put('health','notifications',{'heartbeat':time.time()})
        except Exception:pass  # No credential-bearing network exceptions in logs.
        await asyncio.sleep(5)
if __name__=='__main__':
    import asyncio
    asyncio.run(main())
