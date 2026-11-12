import os, secrets, asyncio, uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, HTTPException, Depends, Header, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import db
from .engine import SYMBOLS, INTERVALS, position_size
from .intelligence import rank_signals, timestamp, size_position
from . import service
from .paper import portfolio_summary

def current_quotes():
    rows=db.listing('quotes'); heartbeat=db.get('health','worker',{})
    try: fresh=(datetime.now(timezone.utc)-datetime.fromisoformat(heartbeat['heartbeat'])).total_seconds()<180
    except (KeyError,ValueError): fresh=False
    from .approvals import portfolio as reserved_portfolio
    risk_settings=service.settings();portfolio=reserved_portfolio(db,datetime.now(timezone.utc).timestamp())
    for row in rows:
        expired=row.get('expires_at') and datetime.now(timezone.utc).timestamp()>=timestamp(row['expires_at'])
        if expired:row.update(decision='NO TRADE',recommendation='NO',entry=None,stop=None,target=None,target1=None,target2=None,sizing=None,status='stale',reason='Signal expired; waiting for a new candle')
        if row.get('mode')!='SIMULATED' and row.get('status')=='ok':
            bars=row.get('bars',[]); step=INTERVALS.get(row.get('interval'),3600)
            candle_fresh=bool(bars) and datetime.now(timezone.utc).timestamp()-(bars[-1]['time']+step)<2*step
            if not fresh or not candle_fresh or (row.get('expires_at') and datetime.now(timezone.utc).timestamp()>=timestamp(row['expires_at'])):
                row.update(decision='NO TRADE',recommendation='NO',entry=None,stop=None,target=None,target1=None,target2=None,sizing=None,status='stale',reason='Worker or candles stale; recommendation suppressed')
        if row.get('recommendation')=='YES' and row.get('sizing'):
            current_size=size_position(row['symbol'],row['entry'],row['stop'],risk_settings,row['costs'],row['quote_to_usd'],portfolio)
            if not current_size['accepted']:row.update(recommendation='NO',decision='NO TRADE',sizing=current_size,reason='Current portfolio guardrail: '+'; '.join(current_size['rejections']))
    return rank_signals(rows)

@asynccontextmanager
async def lifespan(app):
    db.init(); yield
app=FastAPI(title='Tradeomatic AI',lifespan=lifespan)

@app.middleware('http')
async def security_headers(request:Request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
    if os.getenv('PUBLIC_ORIGIN','').startswith('https://'):response.headers['Strict-Transport-Security']='max-age=15552000'
    return response


def authorize(request:Request,authorization: str=Header(default='')):
    if request.cookies.get('tradeomatic_session'):
        from .security import session
        return session(request)
    if os.getenv('PUBLIC_ORIGIN') and os.getenv('LEGACY_ADMIN_ENABLED','false')!='true':raise HTTPException(401,'MFA session required')
    token=os.getenv('ADMIN_TOKEN','')
    if len(token)<32: raise HTTPException(503,'Set a random ADMIN_TOKEN of at least 32 characters')
    if not secrets.compare_digest(authorization,'Bearer '+token): raise HTTPException(401,'Unauthorized')

@app.get('/api/health')
def health(): return {'status':'ok','execution':'disabled','worker':db.get('health','worker'), 'mode':os.getenv('DATA_MODE','demo')}

@app.get('/api/snapshot',dependencies=[Depends(authorize)])
def snapshot(): return {'quotes':current_quotes(),'signals':db.listing('signals'),'journal':db.listing('journal'),'scanner':db.get('config','scanner',{'enabled':False,'symbols':SYMBOLS,'intervals':['1h']}),'worker':db.get('health','worker'),'mode':os.getenv('DATA_MODE','demo'),'engine_settings':service.settings(),'paper':db.listing('paper'),'backtests':db.listing('backtests')}

class ScanConfig(BaseModel):
    enabled: bool
    symbols: list[str]=Field(default=SYMBOLS,min_length=1,max_length=100)
    intervals: list[str]=Field(default=['1h'],min_length=1,max_length=6)

@app.post('/api/scanner',dependencies=[Depends(authorize)])
def scanner(body:ScanConfig):
    from .controls import get as get_controls
    if body.enabled and get_controls()['global_pause']:raise HTTPException(409,'Release global pause before starting discovery')
    if any(x not in SYMBOLS for x in body.symbols) or any(x not in INTERVALS for x in body.intervals): raise HTTPException(422,'Unsupported symbol or interval')
    db.put('config','scanner',body.model_dump()); db.audit('scanner_config',str(body.enabled)); return body

class Risk(BaseModel):
    equity:float; allocation:float; risk_pct:float=1; entry:float; stop:float; quote_to_usd:float=1; rr:float=2
@app.post('/api/risk',dependencies=[Depends(authorize)])
def risk(body:Risk):
    try: return position_size(**body.model_dump())
    except ValueError as e: raise HTTPException(422,str(e))

class Journal(BaseModel):
    symbol: str=Field(max_length=20)
    direction:Literal['BUY','SELL']
    notes:str=Field(max_length=2000)
    pnl:float=Field(allow_inf_nan=False)
@app.post('/api/journal',dependencies=[Depends(authorize)])
def journal(body:Journal):
    item={'id':str(uuid.uuid4()),**body.model_dump()}; db.put('journal',item['id'],item); db.audit('journal_created',item['id']); return item

@app.get('/api/audit',dependencies=[Depends(authorize)])
def audit(): return db.listing('audit')

@app.websocket('/api/ws')
async def ws(socket:WebSocket):
    await socket.accept()
    try:
        supplied=await asyncio.wait_for(socket.receive_text(),timeout=10)
        if socket.cookies.get('tradeomatic_session'):
            from .security import session
            s=session(socket,False)
            expected=os.getenv('PUBLIC_ORIGIN','')
            if (expected and socket.headers.get('origin')!=expected) or not secrets.compare_digest(supplied,s['csrf']):await socket.close(code=1008);return
        else:
            token=os.getenv('ADMIN_TOKEN','')
            if (os.getenv('PUBLIC_ORIGIN') and os.getenv('LEGACY_ADMIN_ENABLED','false')!='true') or len(token)<32 or not secrets.compare_digest(supplied,token):await socket.close(code=1008);return
        while True:
            if socket.cookies.get('tradeomatic_session'):
                from .security import session
                session(socket,False)
            await socket.send_json({'quotes':current_quotes(),'worker':db.get('health','worker')}); await asyncio.sleep(5)
    except (WebSocketDisconnect,asyncio.TimeoutError,HTTPException): pass

@app.post('/api/orders',dependencies=[Depends(authorize)])
def orders(): raise HTTPException(403,'Live execution is not implemented or authorized')

from .api_v2 import register
register(app,authorize)

from .api_v3 import register as register_v3
register_v3(app)

app.mount('/',StaticFiles(directory='dist',html=True),name='dashboard')
