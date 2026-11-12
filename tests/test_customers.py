import os,time
import pytest,pyotp
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from backend import db,security,customers
from backend.app import app

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    old=db.engine;db.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool);db.init()
    monkeypatch.setenv('ENCRYPTION_KEY',Fernet.generate_key().decode());monkeypatch.setenv('COOKIE_SECURE','false')
    monkeypatch.setenv('CUSTOMER_PREVIEW_ENABLED','true');monkeypatch.setenv('CUSTOMER_BILLING_SIMULATOR_ENABLED','true');monkeypatch.delenv('PUBLIC_ORIGIN',raising=False)
    db.put('customer_invitations',security.digest('t'*40),{'expires_at':time.time()+86400,'used':False})
    yield
    db.engine.dispose();db.engine=old

def client(user):
    secret=pyotp.random_base32();db.put('customers',user,{'username':user,'password_hash':security.HASHER.hash('a-long-test-password'),'totp':security.encrypt(secret),'last_counter':-1})
    c=TestClient(app);r=c.post('/api/customers/login',json={'username':user,'password':'a-long-test-password','otp':pyotp.TOTP(secret).now()});assert r.status_code==200
    c.headers['X-CSRF-Token']=r.json()['csrf'];return c

def test_invitation_and_mfa_enrollment():
    c=TestClient(app);payload={'username':'alice','password':'a-long-test-password','invitation':'t'*40}
    assert c.post('/api/customers/enroll',json={**payload,'invitation':'x'*40}).status_code==403
    a=c.post('/api/customers/enroll',json=payload).json();assert not db.get('customers','alice')
    assert c.post('/api/customers/verify',json={'enrollment':a['enrollment'],'otp':pyotp.TOTP(a['setup_key']).now()}).status_code==200
    assert c.post('/api/customers/verify',json={'enrollment':a['enrollment'],'otp':pyotp.TOTP(a['setup_key']).now()}).status_code==400
    assert db.get('customers','alice') and not db.get('auth','owner')

def test_tenant_isolation_csrf_and_owner_protection():
    a,b=client('alice'),client('bob')
    assert a.get('/api/v3/state').status_code==401
    assert a.patch('/api/customers/settings',headers={'X-CSRF-Token':''},json={'equity':5000}).status_code==403
    assert a.patch('/api/customers/settings',json={'equity':5000,'watchlist':['EUR/USD']}).status_code==200
    assert b.get('/api/customers/account').json()['settings']['equity']==10000
    assert not db.get('config','risk')
    checkout=a.post('/api/customers/checkout',json={}).json()
    assert b.post('/api/customers/checkout/complete',json={'checkout_id':checkout['id'],'outcome':'success'}).status_code==404

def test_checkout_decline_success_duplicate_and_cancellation():
    c=client('alice');assert c.get('/api/customers/workspace').status_code==403
    x=c.post('/api/customers/checkout',json={}).json()
    assert c.post('/api/customers/checkout/complete',json={'checkout_id':x['id'],'outcome':'decline'}).json()['charged']==0
    assert not c.get('/api/customers/account').json()['access']
    x=c.post('/api/customers/checkout',json={}).json();body={'checkout_id':x['id'],'outcome':'success'}
    assert c.post('/api/customers/checkout/complete',json=body).status_code==200
    end=c.get('/api/customers/account').json()['subscription']['period_end']
    assert c.post('/api/customers/checkout/complete',json=body).json()['duplicate']
    assert c.get('/api/customers/account').json()['subscription']['period_end']==end
    assert c.post('/api/customers/subscription/cancel',json={}).json()['cancel_at_period_end']
    assert c.get('/api/customers/workspace').status_code==200
    sub=db.get('customer_subscriptions','alice');sub['period_end']=time.time()-1;db.put('customer_subscriptions','alice',sub)
    assert c.get('/api/customers/workspace').status_code==403

def test_simulator_disabled_and_invalid_prices(monkeypatch):
    c=client('alice');monkeypatch.setenv('CUSTOMER_BILLING_SIMULATOR_ENABLED','false')
    assert c.post('/api/customers/checkout',json={}).status_code==503
    assert c.post('/api/customers/checkout/complete',json={'checkout_id':'fake','outcome':'success','price':1}).status_code==422
    monkeypatch.setenv('CUSTOMER_PREVIEW_ENABLED','false');assert c.get('/customers').status_code==404

def test_expired_checkout_and_session_logout():
    c=client('alice');x=c.post('/api/customers/checkout',json={}).json();x['expires_at']=0;db.put('customer_checkouts',x['id'],x)
    assert c.post('/api/customers/checkout/complete',json={'checkout_id':x['id'],'outcome':'success'}).status_code==409
    assert c.post('/api/customers/logout',json={}).status_code==200
    assert c.get('/api/customers/account').status_code==401

def test_customer_login_limits_and_replay():
    c=client('alice')
    for _ in range(11):r=c.post('/api/customers/login',json={'username':'alice','password':'incorrect','otp':'000000'})
    assert r.status_code==429

def test_month_boundary():
    from datetime import datetime,timezone
    jan=datetime(2026,1,31,tzinfo=timezone.utc).timestamp()
    assert datetime.fromtimestamp(customers.month_after(jan),timezone.utc).day==28


def test_customer_cannot_issue_invitation():
    c=client('alice')
    assert c.post('/api/customers/admin/invitations',json={}).status_code==401

def test_used_invitation_cannot_register_another_account():
    db.put('customer_invitations',security.digest('t'*40),{'expires_at':time.time()+86400,'used':True})
    c=TestClient(app)
    assert c.post('/api/customers/enroll',json={'username':'bob','password':'a-long-test-password','invitation':'t'*40}).status_code==403
