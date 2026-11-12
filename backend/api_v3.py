import os,time,hashlib
from fastapi import APIRouter,Request,Response,Depends,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from typing import Literal
from . import db,security,controls,approvals,notifications,brokers,assistant

class Login(BaseModel):
    username:str=Field(min_length=1,max_length=80);password:str=Field(max_length=200);otp:str=Field(pattern=r'^\d{6}$')
class Quote(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    signal_id:str=Field(max_length=400);allocation:float=Field(gt=0);target:Literal['LOCAL_PAPER','OANDA_PRACTICE','ALPACA_PAPER']='LOCAL_PAPER'
class Decision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    digest:str=Field(min_length=64,max_length=64);action:Literal['approve','reject']
class Device(BaseModel):subscription:dict;label:str=Field('My phone',max_length=60)
class AlertAction(BaseModel):action:Literal['reject','snooze'];minutes:int=Field(30,ge=1,le=1440)
class Refresh(BaseModel):broker:Literal['OANDA_PRACTICE','ALPACA_PAPER'];symbol:str=Field(max_length=20)

def register(app):
    public=APIRouter(prefix='/api/v3')
    @public.get('/readiness')
    def readiness():return {**security.readiness(),'push_configured':bool(os.getenv('VAPID_PUBLIC_KEY') and os.getenv('VAPID_PRIVATE_KEY')),'push_enabled':os.getenv('PUSH_ENABLED')=='true','vapid_public_key':os.getenv('VAPID_PUBLIC_KEY','')}
    @public.post('/login')
    def login(body:Login,request:Request,response:Response):
        security.origin_check(request)
        try:s=security.login(body.username,body.password,body.otp,request.client.host)
        except ValueError as e:raise HTTPException(401,str(e))
        response.set_cookie('tradeomatic_session',s.pop('token'),secure=os.getenv('COOKIE_SECURE','true')=='true',httponly=True,samesite='strict',max_age=3600,path='/')
        return s
    app.include_router(public)
    def authenticated(request:Request):return security.session(request,True)
    router=APIRouter(prefix='/api/v3',dependencies=[Depends(authenticated)])
    @router.get('/session')
    def session(request:Request):return security.session(request,False)
    @router.post('/logout')
    def logout(request:Request,response:Response):
        token=request.cookies.get('tradeomatic_session','');s=db.get('sessions',security.digest(token),{});s['expires_at']=0;db.put('sessions',security.digest(token),s);response.delete_cookie('tradeomatic_session',path='/');return {'signed_out':True}
    @router.get('/state')
    def state():
        return {'controls':controls.get(),'preferences':notifications.preferences(),'events':sorted(db.listing('notifications'),key=lambda x:x['created_at'],reverse=True)[:200],'devices':[{k:d[k] for k in ('id','label','enabled')} for d in db.listing('push_devices')],'deliveries':[{k:v for k,v in x.items() if k not in ('claim',)} for x in db.listing('push_delivery')],'brokers':brokers.status(),'broker_state':{n:db.get('broker_state',n) for n in ('OANDA_PRACTICE','ALPACA_PAPER')},'orders':db.listing('broker_orders'),'intents':db.listing('intents'),'health':{n:db.get('health',n) for n in ('worker','notifications','assistant')},**security.readiness()}
    @router.patch('/controls')
    def config(body:dict):
        body=dict(body);ack=body.pop('acknowledge_unmonitored',False)
        try:return controls.save(body,ack)
        except ValueError as e:raise HTTPException(422,str(e))
    @router.patch('/preferences')
    def preferences(body:dict):
        try:return notifications.pref_save(body)
        except ValueError as e:raise HTTPException(422,str(e))
    @router.post('/devices')
    def devices(body:Device):
        try:return {'id':notifications.subscribe(body.subscription,body.label)}
        except ValueError as e:raise HTTPException(422,str(e))
    @router.delete('/devices/{id}')
    def disable_device(id:str):
        d=db.get('push_devices',id)
        if not d:raise HTTPException(404,'Device not found')
        d['enabled']=False;db.put('push_devices',id,d);return {'disabled':True}
    @router.post('/notifications/test')
    def test():return {'event_id':notifications.enqueue('TEST',str(time.time()),{'instrument':'SERVICE','reason':'Tradeomatic test notification. No trade or market-data request was made.','mode':'TEST'})}
    @router.post('/notifications/{id}/action')
    def alert_action(id:str,body:AlertAction):
        e=db.get('notifications',id)
        if not e:raise HTTPException(404,'Notification not found')
        signal_id=e['details'].get('signal_id')
        if not signal_id:raise HTTPException(422,'This service notification has no trade action')
        if body.action=='snooze':db.put('snoozes',signal_id,{'until':time.time()+body.minutes*60})
        else:db.put('signal_decisions',signal_id,{'decision':'REJECT','time':time.time()})
        db.audit('NOTIFICATION_'+body.action.upper(),id);return {'recorded':True}
    @router.post('/reviews')
    def quote(body:Quote,request:Request):
        s=security.fresh_session(request)
        try:return approvals.create(body.signal_id,body.allocation,body.target,s['user'])
        except ValueError as e:raise HTTPException(422,str(e))
    @router.post('/reviews/{id}/decision')
    def decide(id:str,body:Decision,request:Request):
        s=security.fresh_session(request)
        try:return approvals.decide(id,body.digest,body.action,s['user'])
        except ValueError as e:raise HTTPException(409,str(e))
    @router.post('/brokers/refresh')
    async def refresh(body:Refresh):
        from .engine import SYMBOLS
        if body.symbol not in SYMBOLS:raise HTTPException(422,'Unsupported instrument')
        try:return await assistant.refresh_broker(body.broker,body.symbol)
        except ValueError as e:raise HTTPException(422,str(e))
        except Exception:raise HTTPException(503,'Broker unavailable; transport details redacted')
    app.include_router(router)
