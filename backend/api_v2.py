import time, uuid, os
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from fastapi import APIRouter, Depends, HTTPException
from . import db, service
from .engine import SYMBOLS, INTERVALS
from .intelligence import RiskSettings, ExecutionAssumptions, recommend, HIGHER, rank_signals
from .paper import portfolio_summary, performance
from .backtest import walk_forward

class Bar(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    time:int=Field(ge=0);open:float=Field(gt=0);high:float=Field(gt=0);low:float=Field(gt=0);close:float=Field(gt=0);volume:float|None=Field(None,ge=0)
class Approval(BaseModel):signal_id:str=Field(max_length=400)
class PaperAction(BaseModel):
    action:Literal['close','cancel','adjust_stop'];new_stop:float|None=Field(None,gt=0,allow_inf_nan=False)
class Event(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    title:str=Field(max_length=120);time:float;known_at:float;importance:Literal['high','medium','low'];blackout_seconds:int=Field(1800,ge=0,le=86400)
class Events(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    coverage:Literal['complete','unknown']='unknown';asof:float=0;valid_until:float=0;items:list[Event]=Field(default_factory=list,max_length=100)
class Conversion(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    quote_to_usd:float=Field(gt=0);asof:float;valid_until:float
class Context(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    costs:ExecutionAssumptions;cost_source:str=Field(max_length=160);events:Events;conversion:Conversion|None=None
class ContextRequest(Context):symbol:str
class Update(BaseModel):
    symbol:str;interval:str;bars:list[Bar]=Field(min_length=1,max_length=500);higher_bars:list[Bar]=Field(default_factory=list,max_length=500)
    alert_mode:Literal['intrabar','close']='intrabar'
    data_mode:Literal['SIMULATED','REAL-TIME','DELAYED']='SIMULATED'
class BacktestRequest(BaseModel):
    symbol:str='EUR/USD';interval:str='1h';bars:list[Bar]=Field(min_length=300,max_length=3000)
    higher_bars:list[Bar]|None=Field(None,max_length=3000)
    settings:RiskSettings=Field(default_factory=RiskSettings)
    context:Context
    data_source:Literal['SIMULATED','HISTORICAL']='HISTORICAL'
    train_bars:int=Field(200,ge=100,le=1000);test_bars:int=Field(120,ge=60,le=500)

def register(app,authorize):
    router=APIRouter(prefix='/api/v2',dependencies=[Depends(authorize)])
    @router.get('/state')
    def state():
        t=db.listing('paper');s=service.settings()
        return {'settings':s,'paper':t,'portfolio':portfolio_summary(t,time.time()),'performance':performance(t,s['equity']),'reports':db.listing('backtests'),'events':db.listing('paper_events'),'provisional':db.listing('provisional')}
    @router.patch('/settings')
    def config(changes:dict):
        try:return service.save_settings({**service.settings(),**changes})
        except ValueError as e:raise HTTPException(422,str(e))
    @router.post('/context')
    def context(body:ContextRequest):
        if body.symbol not in SYMBOLS:raise HTTPException(422,'Unsupported symbol')
        db.put('context',body.symbol,body.model_dump(exclude={'symbol'},exclude_none=True));db.audit('CONTEXT_UPDATED',body.symbol);return {'saved':True,'symbol':body.symbol}
    @router.post('/paper')
    def approve(body:Approval):
        if os.getenv('PUBLIC_ORIGIN') and os.getenv('ALLOW_LEGACY_RESEARCH_APPROVALS','false')!='true':raise HTTPException(410,'Use the authenticated exact-quote review workflow in /api/v3/reviews')
        try:return service.approve_paper(body.signal_id,time.time())
        except ValueError as e:raise HTTPException(422,str(e))
    @router.post('/paper/{id}/action')
    def action(id:str,body:PaperAction):
        try:return service.paper_action(id,body.action,time.time(),body.new_stop)
        except ValueError as e:raise HTTPException(422,str(e))
    @router.post('/updates')
    def update(body:Update):
        if body.symbol not in SYMBOLS or body.interval not in INTERVALS:raise HTTPException(422,'Unsupported instrument/timeframe')
        now=time.time()
        try:
            ctx=service.context(body.symbol,body.data_mode,now)
            if body.data_mode!='SIMULATED':
                from .provider import market_open
                ctx['market_status']='open' if market_open(body.symbol) else 'closed'
            s=recommend(body.symbol,body.interval,[b.model_dump() for b in body.bars],[b.model_dump() for b in body.higher_bars],service.settings(),ctx,portfolio_summary(db.listing('paper'),now),now,body.alert_mode)
            if body.alert_mode=='close':
                # Closed external updates are immutable too; they never become provider quotes implicitly.
                db.put_once('signals',s['id'],s)
            else:db.put_once('provisional',s['id'],s)
            return s
        except ValueError as e:raise HTTPException(422,str(e))
    @router.post('/backtests')
    def backtest(body:BacktestRequest):
        if body.symbol not in SYMBOLS or body.interval not in INTERVALS:raise HTTPException(422,'Unsupported instrument/timeframe')
        if any(b.time+INTERVALS[body.interval]>time.time() for b in body.bars):raise HTTPException(422,'Future or incomplete historical bars are not accepted')
        try:
            ctx={**body.context.model_dump(exclude_none=True),'data_mode':body.data_source,'market_status':'open'}
            report=walk_forward([b.model_dump() for b in body.bars],body.symbol,body.interval,body.settings.model_dump(),ctx,body.train_bars,body.test_bars,[b.model_dump() for b in body.higher_bars] if body.higher_bars else None)
            report.update(id=str(uuid.uuid4()),created_at=time.time());db.put('backtests',report['id'],report);db.audit('BACKTEST_COMPLETED',report['id']);return report
        except ValueError as e:raise HTTPException(422,str(e))
    app.include_router(router)
