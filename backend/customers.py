"""Invite-only customer preview. Billing is a local simulator; never charges money."""
import os,time,secrets,calendar
from datetime import datetime,timezone
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel,Field,ConfigDict
from argon2.exceptions import VerificationError
import pyotp
from . import db,security

COOKIE='tradeomatic_customer'
class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Signup(Strict):
    username:str=Field(pattern=r'^[a-zA-Z0-9_-]{3,40}$')
    password:str=Field(min_length=14,max_length=200)
    invitation:str=Field(min_length=20,max_length=200)
class Verify(Strict):
    enrollment:str=Field(min_length=32,max_length=200)
    otp:str=Field(pattern=r'^\d{6}$')
class Login(Strict):
    username:str=Field(max_length=40)
    password:str=Field(max_length=200)
    otp:str=Field(pattern=r'^\d{6}$')
class Purchase(Strict):
    checkout_id:str=Field(max_length=80)
    outcome:str=Field(pattern=r'^(success|decline)$')
class Settings(Strict):
    watchlist:list[str]=Field(default_factory=list,max_length=50)
    equity:float=Field(default=10000,gt=0,le=100000000,allow_inf_nan=False)
    risk_percent:float=Field(default=1,gt=0,le=5,allow_inf_nan=False)
    reward_risk:float=Field(default=2,ge=1,le=10,allow_inf_nan=False)

def enabled():
    if os.getenv('CUSTOMER_PREVIEW_ENABLED')!='true':raise HTTPException(404,'Customer preview is not enabled')

def throttle(request,operation,limit=10):
    key=security.digest(operation+':'+request.client.host);now=time.time()
    with db.atomic() as tx:
        s=tx.get('customer_limits',key,{'start':now,'count':0})
        if now-s['start']>300:s={'start':now,'count':0}
        allowed=s['count']<limit;s['count']+=1;tx.put('customer_limits',key,s)
    if not allowed:raise HTTPException(429,'Please wait five minutes before retrying')

def session(request:Request):
    enabled();token=request.cookies.get(COOKIE,'');s=db.get('customer_sessions',security.digest(token)) if token else None
    if not s or s['expires_at']<=time.time():raise HTTPException(401,'Customer sign-in required')
    if request.method not in ('GET','HEAD','OPTIONS'):
        security.origin_check(request)
        if not secrets.compare_digest(request.headers.get('x-csrf-token',''),s['csrf']):raise HTTPException(403,'CSRF verification failed')
    return s

def audit(tx,user,action,details=None):
    tx.put('customer_audit',secrets.token_hex(16),{'customer':user,'action':action,'time':time.time(),'details':details or {}})

def month_after(now):
    d=datetime.fromtimestamp(now,timezone.utc);year=d.year+(d.month==12);month=1 if d.month==12 else d.month+1
    return d.replace(year=year,month=month,day=min(d.day,calendar.monthrange(year,month)[1])).timestamp()

def register(app):
    r=APIRouter(prefix='/api/customers',dependencies=[Depends(enabled)])
    @app.get('/customers',response_class=HTMLResponse)
    def page():
        enabled();return HTMLResponse(Path('dist/customers.html').read_text(),headers={'Cache-Control':'no-store'})
    def owner(request:Request):return security.session(request,True)
    @r.post('/admin/invitations')
    def invitation(request:Request,_=Depends(owner)):
        token=secrets.token_urlsafe(32)
        with db.atomic() as tx:
            tx.put('customer_invitations',security.digest(token),{'expires_at':time.time()+86400,'used':False})
            audit(tx,'owner','INVITATION_CREATED')
        return {'invitation':token,'expires_in':86400}
    @app.get('/customer-admin',response_class=HTMLResponse)
    def admin_page():
        enabled();return HTMLResponse(Path('dist/customer-admin.html').read_text(),headers={'Cache-Control':'no-store'})
    @r.get('/status')
    def status():return {'billing':'LOCAL_SIMULATOR','real_payments':False,'market_data':'SIMULATED','registration':'INVITATION_REQUIRED','live_trading':'LOCKED'}
    @r.post('/enroll')
    def enroll(body:Signup,request:Request):
        security.origin_check(request);throttle(request,'enroll',5)
        user=body.username.lower();token=secrets.token_urlsafe(32);secret=pyotp.random_base32()
        with db.atomic() as tx:
            invite=tx.get('customer_invitations',security.digest(body.invitation))
            if not invite or invite['expires_at']<=time.time() or invite.get('used'):raise HTTPException(403,'Valid preview invitation required')
            if tx.get('customers',user):raise HTTPException(409,'Username unavailable')
            tx.put('customer_enrollment',security.digest(token),{'username':user,'password_hash':security.HASHER.hash(body.password),'totp':security.encrypt(secret),'invitation':security.digest(body.invitation),'expires_at':time.time()+600,'attempts':0})
        return {'enrollment':token,'setup_key':secret,'expires_in':600}
    @r.post('/verify')
    def verify(body:Verify,request:Request):
        security.origin_check(request);throttle(request,'verify');key=security.digest(body.enrollment);ok=False
        with db.atomic() as tx:
            e=tx.get('customer_enrollment',key)
            if e and e['expires_at']>time.time() and e['attempts']<5:
                e['attempts']+=1;tx.put('customer_enrollment',key,e)
                invite=tx.get('customer_invitations',e['invitation'],{})
                if invite.get('expires_at',0)>time.time() and not invite.get('used') and pyotp.TOTP(security.decrypt(e['totp'])).verify(body.otp) and not tx.get('customers',e['username']):
                    invite['used']=True;tx.put('customer_invitations',e['invitation'],invite)
                    tx.put('customers',e['username'],{'username':e['username'],'password_hash':e['password_hash'],'totp':e['totp'],'last_counter':int(time.time())//30})
                    e['expires_at']=0;tx.put('customer_enrollment',key,e);audit(tx,e['username'],'REGISTERED');ok=True
        if not ok:raise HTTPException(400,'Invalid, expired or already used enrollment')
        return {'registered':True,'message':'Wait for the next authenticator code to sign in'}
    @r.post('/login')
    def login(body:Login,request:Request,response:Response):
        security.origin_check(request);throttle(request,'login');result=None;now=time.time();user=body.username.lower()
        with db.atomic() as tx:
            c=tx.get('customers',user)
            if c:
                try:
                    security.HASHER.verify(c['password_hash'],body.password);counter=int(now)//30
                    if counter>c['last_counter'] and pyotp.TOTP(security.decrypt(c['totp'])).verify(body.otp,for_time=now):
                        c['last_counter']=counter;tx.put('customers',user,c)
                        token=secrets.token_urlsafe(32);s={'customer':user,'csrf':secrets.token_urlsafe(24),'expires_at':now+3600}
                        tx.put('customer_sessions',security.digest(token),s);result={'token':token,**s};audit(tx,user,'LOGIN')
                except (VerificationError,ValueError):pass
        if not result:raise HTTPException(401,'Invalid sign-in details or reused code')
        response.set_cookie(COOKIE,result.pop('token'),httponly=True,secure=os.getenv('COOKIE_SECURE','true')=='true',samesite='strict',max_age=3600,path='/')
        return result
    @r.post('/logout')
    def logout(request:Request,response:Response,s=Depends(session)):
        s['expires_at']=0;db.put('customer_sessions',security.digest(request.cookies[COOKIE]),s);response.delete_cookie(COOKIE,path='/');return {'signed_out':True}
    @r.get('/account')
    def account(s=Depends(session)):
        user=s['customer'];sub=db.get('customer_subscriptions',user,{'status':'none','test_only':True})
        return {'customer':user,'csrf':s['csrf'],'subscription':sub,'access':sub['status']=='active' and sub.get('period_end',0)>time.time(),'settings':db.get('customer_settings',user,Settings().model_dump()),'billing':'LOCAL_SIMULATOR','real_payments':False}
    @r.patch('/settings')
    def settings(body:Settings,s=Depends(session)):
        from .engine import SYMBOLS
        if any(x not in SYMBOLS for x in body.watchlist):raise HTTPException(422,'Unsupported instrument')
        db.put('customer_settings',s['customer'],body.model_dump());return body.model_dump()
    @r.post('/checkout')
    def checkout(s=Depends(session)):
        if os.getenv('CUSTOMER_BILLING_SIMULATOR_ENABLED')!='true':raise HTTPException(503,'Checkout simulator is disabled')
        now=time.time();row={'id':secrets.token_urlsafe(24),'customer':s['customer'],'state':'pending','created_at':now,'expires_at':now+600,'currency':'USD','amount_due':0,'test_only':True,'interval':'month'}
        db.put('customer_checkouts',row['id'],row);return row
    @r.post('/checkout/complete')
    def complete(body:Purchase,s=Depends(session)):
        if os.getenv('CUSTOMER_BILLING_SIMULATOR_ENABLED')!='true':raise HTTPException(503,'Checkout simulator is disabled')
        with db.atomic() as tx:
            c=tx.get('customer_checkouts',body.checkout_id);user=s['customer'];now=time.time()
            if not c or c['customer']!=user:raise HTTPException(404,'Checkout not found')
            if c['state']!='pending':return {'state':c['state'],'duplicate':True}
            if c['expires_at']<=now:raise HTTPException(409,'Checkout expired')
            c['state']='complete' if body.outcome=='success' else 'declined';tx.put('customer_checkouts',c['id'],c)
            if body.outcome=='success':
                old=tx.get('customer_subscriptions',user,{})
                end=max(now,old.get('period_end',0)) if old.get('status')=='active' else now
                tx.put('customer_subscriptions',user,{'status':'active','period_end':month_after(end),'cancel_at_period_end':False,'test_only':True,'billing':'LOCAL_SIMULATOR'})
            audit(tx,user,'TEST_CHECKOUT_'+c['state'].upper(),{'checkout':c['id']})
            return {'state':c['state'],'charged':0,'test_only':True}
    @r.post('/subscription/cancel')
    def cancel(s=Depends(session)):
        with db.atomic() as tx:
            sub=tx.get('customer_subscriptions',s['customer'])
            if not sub:raise HTTPException(404,'No test subscription')
            sub['cancel_at_period_end']=True;tx.put('customer_subscriptions',s['customer'],sub);audit(tx,s['customer'],'TEST_CANCEL_AT_PERIOD_END')
        return sub
    @r.get('/workspace')
    def workspace(s=Depends(session)):
        sub=db.get('customer_subscriptions',s['customer'],{})
        if sub.get('status')!='active' or sub.get('period_end',0)<=time.time():raise HTTPException(403,'Active test subscription required')
        return {'customer':s['customer'],'data_mode':'SIMULATED','trading':'DISABLED','message':'Customer workspace access verified. Shared owner signals, positions and broker records are not exposed.'}
    app.include_router(r)
