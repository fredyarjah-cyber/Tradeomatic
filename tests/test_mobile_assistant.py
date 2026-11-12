import os,time,asyncio,copy,base64
from datetime import datetime,timezone
from unittest.mock import AsyncMock
import pytest,httpx,pyotp
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from backend import db,security,approvals,controls,notifications,assistant,brokers
from backend.intelligence import DEFAULT_SETTINGS
from backend.app import app
from test_intelligence import yes_signal,NOW,later_bar
from backend.paper import advance

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    old=db.engine;db.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool);db.init()
    monkeypatch.setenv('ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.delenv('PUBLIC_ORIGIN',raising=False);monkeypatch.setenv('DATA_MODE','demo')
    yield
    db.engine.dispose();db.engine=old

def setup_signal():
    s,b,h=yes_signal();db.put('signals',s['id'],s);db.put('quotes',s['symbol']+':1h',{**s,'status':'ok','bars':b,'higher_bars':h});controls.save({'mode':'approval_required','new_orders_paused':False});return s

def owner():
    secret=pyotp.random_base32();db.put('auth','owner',{'username':'test-owner','password_hash':security.HASHER.hash('a-local-test-password'),'totp_secret':security.encrypt(secret),'last_totp_counter':-1});return secret

def test_mfa_cookie_csrf_and_totp_replay(monkeypatch):
    secret=owner();monkeypatch.setenv('PUBLIC_ORIGIN','https://testserver')
    with TestClient(app,base_url='https://testserver') as c:
        assert c.get('/api/v3/state').status_code==401
        r=c.post('/api/v3/login',json={'username':'test-owner','password':'a-local-test-password','otp':pyotp.TOTP(secret).now()},headers={'Origin':'https://testserver'})
        assert r.status_code==200,r.text
        assert 'httponly' in r.headers['set-cookie'].lower() and 'secure' in r.headers['set-cookie'].lower()
        assert 'token' not in r.json()
        assert c.get('/api/v3/state').status_code==200
        assert c.patch('/api/v3/controls?mutating=false',json={'global_pause':True}).status_code==403
        csrf=r.json()['csrf']
        assert c.patch('/api/v3/controls',json={'global_pause':True},headers={'X-CSRF-Token':csrf,'Origin':'https://evil.example'}).status_code==403
        assert c.patch('/api/v3/controls',json={'global_pause':True},headers={'X-CSRF-Token':csrf,'Origin':'https://testserver'}).status_code==200
        replay=c.post('/api/v3/login',json={'username':'test-owner','password':'a-local-test-password','otp':pyotp.TOTP(secret).now()})
        assert replay.status_code==401

def test_failed_login_limits_are_persisted():
    for i in range(5):
        with pytest.raises(ValueError):security.login('nobody','bad','000000','peer',now=1000)
    with pytest.raises(ValueError,match='limited'):security.login('nobody','bad','000000','peer',now=1001)

def test_exact_quote_one_use_and_no_silent_quantity_change():
    s=setup_signal();r=approvals.create(s['id'],1000,'LOCAL_PAPER','owner',NOW)
    approved=approvals.decide(r['id'],r['digest'],'approve','owner',NOW+1)
    assert approved['status']=='APPROVED_PAPER' and len(db.listing('paper'))==1
    with pytest.raises(ValueError,match='consumed'):approvals.decide(r['id'],r['digest'],'approve','owner',NOW+2)
    trade=db.listing('paper')[0]
    shifted=later_bar(s,time=int(NOW)+3600,open=s['entry']*1.000001,high=s['entry']*1.0002,low=s['entry']*.9999)
    assert advance(trade,[shifted],NOW+7200)['status']=='INVALIDATED'

def test_changed_risk_invalidates_persistently_and_expiry_blocks():
    s=setup_signal();r=approvals.create(s['id'],1000,'LOCAL_PAPER','owner',NOW)
    db.put('config','risk_v2',{**DEFAULT_SETTINGS,'risk_pct':.5})
    with pytest.raises(ValueError,match='changed'):approvals.decide(r['id'],r['digest'],'approve','owner',NOW+1)
    assert db.get('intents',r['id'])['status']=='INVALIDATED' and not db.listing('paper')
    r=approvals.create(s['id'],1000,'LOCAL_PAPER','owner',NOW)
    with pytest.raises(ValueError,match='expired'):approvals.decide(r['id'],r['digest'],'approve','owner',NOW+61)

def test_tamper_other_owner_and_reject():
    s=setup_signal();r=approvals.create(s['id'],1000,'LOCAL_PAPER','owner',NOW)
    for who,binding in [('other',r['digest']),('owner','0'*64)]:
        with pytest.raises(ValueError):approvals.decide(r['id'],binding,'approve',who,NOW+1)
    assert approvals.decide(r['id'],r['digest'],'reject','owner',NOW+1)['status']=='REJECTED'
    assert not db.listing('paper')

def test_control_separation_and_automation_lock():
    db.put('config','scanner',{'enabled':True,'symbols':['EUR/USD'],'intervals':['1h']})
    db.put('paper','active',{'status':'OPEN','stop':99,'target1':102})
    controls.save({'global_pause':True})
    assert not db.get('config','scanner')['enabled'] and controls.get()['positions_monitoring']
    assert db.get('paper','active')['stop']==99
    with pytest.raises(ValueError,match='acknowledgment'):controls.save({'positions_monitoring':False})
    assert not controls.save({'positions_monitoring':False},True)['positions_monitoring']
    with pytest.raises(ValueError,match='locked'):controls.save({'mode':'automated'})

def subscription():
    enc=lambda x:base64.urlsafe_b64encode(x).decode().rstrip('=')
    return {'endpoint':'https://fcm.googleapis.com/fcm/send/test','keys':{'p256dh':enc(b'\x04'+b'a'*64),'auth':enc(b'b'*16)}}

def test_push_endpoint_restrictions_and_at_rest_encryption():
    bad=subscription();bad['endpoint']='https://127.0.0.1/secrets'
    with pytest.raises(ValueError):notifications.subscribe(bad,'bad')
    id=notifications.subscribe(subscription(),'test phone');d=db.get('push_devices',id)
    assert 'fcm.googleapis.com' not in d['subscription']
    assert security.decrypt(d['subscription'])['endpoint']==subscription()['endpoint']

def test_notification_dedup_retry_and_expiry(monkeypatch):
    monkeypatch.setenv('PUSH_ENABLED','true');monkeypatch.setenv('VAPID_PRIVATE_KEY','test-only');monkeypatch.setenv('VAPID_SUBJECT','mailto:test@example.com')
    notifications.pref_save({'enabled':True});notifications.subscribe(subscription(),'test')
    id=notifications.enqueue('TEST','once',{'instrument':'SERVICE','reason':'Test'})
    assert notifications.enqueue('TEST','once',{'reason':'Changed'})==id and len(db.listing('notifications'))==1
    calls=[]
    def failure(s,p):calls.append(p);raise TimeoutError()
    now=time.time();notifications.deliver_once(now,failure);notifications.deliver_once(now+1,failure)
    assert len(calls)==1
    notifications.deliver_once(now+100,lambda s,p:calls.append(p));notifications.deliver_once(now+101,lambda s,p:calls.append(p))
    assert len(calls)==2 and db.listing('push_delivery')[0]['status']=='SENT'
    assert 'APPROVE' in calls[-1]['actions'][0]['title'] and 'token' not in str(calls[-1]).lower()

def test_health_incident_and_recovery_dedup():
    assistant.health_once(1000);assistant.health_once(1001)
    count=len(db.listing('notifications'));assert count==2
    db.put('health','worker',{'heartbeat':1002});db.put('health','notifications',{'heartbeat':1002})
    assistant.health_once(1003);assert len(db.listing('notifications'))==count+2

def test_paper_adapters_are_live_host_proof(monkeypatch):
    for name in ['LIVE','IBKR','https://api-fxtrade.oanda.com']:
        with pytest.raises(ValueError):brokers.adapter(name)
    monkeypatch.setenv('OANDA_ACCOUNT_ID','123-456-789');monkeypatch.setenv('OANDA_MT4_LINKED','false')
    o=brokers.OandaPractice();a=brokers.AlpacaPaper()
    d={'symbol':'EUR/USD','direction':'BUY','units':1000,'broker_entry':'1.1000','broker_stop':'1.0900','broker_target2':'1.1300','expires_at':NOW+60}
    payload=o.payload(d,'same-id')['order'];assert payload['timeInForce']=='GTD' and payload['stopLossOnFill']['price']=='1.0900'
    payload=a.payload({**d,'symbol':'AAPL','units':2},'same-id');assert payload['order_class']=='bracket' and payload['stop_loss']['stop_price']=='1.0900'
    assert o.base=='https://api-fxpractice.oanda.com' and a.base=='https://paper-api.alpaca.markets'

def test_unknown_broker_write_never_posts_twice(monkeypatch):
    controls.save({'mode':'approval_required','new_orders_paused':False})
    d={'symbol':'EUR/USD','signal_id':'s','allocation':1000,'target':'OANDA_PRACTICE','expires_at':time.time()+60}
    row={'id':'order-test','client_id':'same-id','details':d,'status':'READY','digest':'binding'};db.put('broker_orders',row['id'],row)
    client=type('Fake',(),{})();client.snapshot=AsyncMock(return_value={'positions':[],'equity':10000,'buying_power':10000,'asof':time.time()});client.market=AsyncMock(return_value={'bid':1,'ask':1.1,'time':time.time()});client.submit=AsyncMock(side_effect=httpx.ReadTimeout('test'));client.lookup=AsyncMock(return_value=None)
    monkeypatch.setattr(approvals,'details',lambda *args,**kwargs:({},'binding'))
    asyncio.run(assistant.submit_ready(row,client=client));assert db.get('broker_orders',row['id'])['status']=='UNKNOWN'
    asyncio.run(assistant.submit_ready(db.get('broker_orders',row['id']),client=client));asyncio.run(assistant.reconcile_order(db.get('broker_orders',row['id']),client))
    assert client.submit.await_count==1 and db.get('broker_orders',row['id'])['status']=='UNKNOWN'

def test_authenticated_http_trade_review_and_broker_gate(monkeypatch):
    s=setup_signal();s={**s,'expires_at':datetime.fromtimestamp(time.time()+600,timezone.utc).isoformat()};db.put('signals',s['id'],s);row=db.get('quotes',s['symbol']+':1h');row.update({**s,'status':'ok'});db.put('quotes',s['symbol']+':1h',row)
    secret=owner();monkeypatch.setenv('PUBLIC_ORIGIN','https://testserver')
    with TestClient(app,base_url='https://testserver') as c:
        login=c.post('/api/v3/login',json={'username':'test-owner','password':'a-local-test-password','otp':pyotp.TOTP(secret).now()});assert login.status_code==200
        headers={'X-CSRF-Token':login.json()['csrf'],'Origin':'https://testserver'}
        r=c.post('/api/v3/reviews',json={'signal_id':s['id'],'allocation':1000,'target':'LOCAL_PAPER'},headers=headers);assert r.status_code==200,r.text
        review=r.json()
        tampered=c.post('/api/v3/reviews/'+review['id']+'/decision',json={'digest':review['digest'],'action':'approve','units':9999},headers=headers)
        assert tampered.status_code==422 and not db.listing('paper')
        r=c.post('/api/v3/reviews/'+review['id']+'/decision',json={'digest':review['digest'],'action':'approve'},headers=headers);assert r.status_code==200,r.text
        assert r.json()['status']=='APPROVED_PAPER'
        assert c.post('/api/v3/brokers/refresh',json={'broker':'OANDA_PRACTICE','symbol':'EUR/USD'},headers=headers).status_code==422
        assert c.post('/api/v2/paper',json={'signal_id':s['id']},headers=headers).status_code==410
        c.post('/api/v3/logout',json={},headers=headers);assert c.get('/api/v3/state').status_code==401

def test_backup_encryption_and_public_vapid_pair():
    from scripts.encrypted_backup import encode_backup
    from scripts.generate_secrets import generate
    from py_vapid import Vapid
    values=generate();sealed=encode_backup(b'not-a-real-database',values['ENCRYPTION_KEY']);assert b'not-a-real-database' not in sealed
    assert Fernet(values['ENCRYPTION_KEY'].encode()).decrypt(sealed)==b'not-a-real-database'
    assert Vapid.from_string(values['VAPID_PRIVATE_KEY'])
    assert len(base64.urlsafe_b64decode(values['VAPID_PUBLIC_KEY']+'='*(-len(values['VAPID_PUBLIC_KEY'])%4)))==65

def test_scanner_preserves_transport_status_separate_from_signal_status():
    from backend.worker import scan_once
    db.put('config','scanner',{'enabled':True,'symbols':['USD/JPY'],'intervals':['1h']})
    asyncio.run(scan_once());row=db.get('quotes','USD/JPY:1h')
    assert row['status']=='ok' and row['signal_status'] in ('WAITING_FOR_USER_APPROVAL','REJECTED')

def test_protection_requires_active_correct_side_and_sufficient_quantity():
    p={'symbol':'AAPL','qty':'10'};stop={'symbol':'AAPL','type':'stop','side':'sell','qty':'10','filled_qty':'0','status':'new'}
    assert brokers.alpaca_protected(p,[stop])
    for change in [{'status':'held'},{'status':'canceled'},{'side':'buy'},{'qty':'9'}]:assert not brokers.alpaca_protected(p,[{**stop,**change}])
