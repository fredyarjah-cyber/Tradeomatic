"""Single-owner MFA sessions, CSRF binding and encrypted server-side secrets."""
import os, time, secrets, hashlib, json
from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from cryptography.fernet import Fernet, InvalidToken
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
import pyotp
from . import db
HASHER=PasswordHasher()

def cipher():
    key=os.getenv('ENCRYPTION_KEY','')
    if not key:raise ValueError('Server encryption key is not configured')
    return Fernet(key.encode())
def encrypt(value):return cipher().encrypt(json.dumps(value,separators=(',',':')).encode()).decode()
def decrypt(value):return json.loads(cipher().decrypt(value.encode()).decode())
def digest(value):return hashlib.sha256(value.encode()).hexdigest()

def origin_check(request):
    origin=request.headers.get('origin')
    expected=os.getenv('PUBLIC_ORIGIN','').rstrip('/')
    if origin and origin.rstrip('/')!=(expected or str(request.base_url).rstrip('/')):raise HTTPException(403,'Origin mismatch')

def login(username,password,otp,peer,now=None):
    now=now or time.time();key=digest(peer+':'+username)
    with db.atomic() as tx:
        limit=tx.get('login_limits',key,{'start':now,'failures':0})
        if now-limit['start']>=300:limit={'start':now,'failures':0}
        if limit['failures']>=5:raise ValueError('Sign-in temporarily limited; retry after five minutes')
        owner=tx.get('auth','owner');valid=False;counter=None
        if owner and secrets.compare_digest(username,owner['username']):
            try:
                HASHER.verify(owner['password_hash'],password)
                totp=pyotp.TOTP(decrypt(owner['totp_secret']));counter=int(now)//30
                valid=totp.verify(otp,for_time=now,valid_window=0) and counter>owner.get('last_totp_counter',-1)
            except (VerificationError,InvalidToken,ValueError):valid=False
        if not valid:
            limit['failures']+=1;tx.put('login_limits',key,limit)
            # Commit rate-limit state; raising inside the transaction would roll it back.
            result=None
        else:
            owner['last_totp_counter']=counter;tx.put('auth','owner',owner)
            token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
            session={'user':'owner','csrf':csrf,'created_at':now,'mfa_at':now,'expires_at':now+3600}
            tx.put('sessions',digest(token),session);tx.put('login_limits',key,{'start':now,'failures':0})
            tx.put('audit',secrets.token_hex(16),{'time':now,'action':'MFA_LOGIN','details':'owner'})
            result={'token':token,**session}
    if not result:raise ValueError('Invalid sign-in details or reused authenticator code')
    return result

def session(request,mutating=True):
    token=request.cookies.get('tradeomatic_session','');s=db.get('sessions',digest(token)) if token else None
    if not s or s['expires_at']<=time.time():raise HTTPException(401,'Sign in with password and authenticator code')
    if mutating and request.method not in ('GET','HEAD','OPTIONS'):
        origin_check(request)
        if not secrets.compare_digest(request.headers.get('x-csrf-token',''),s['csrf']):raise HTTPException(403,'CSRF verification failed')
    return s

def fresh_session(request):
    s=session(request)
    if time.time()-s['mfa_at']>900:raise HTTPException(401,'Reauthenticate for trade approval (15-minute limit)')
    return s

def readiness():return {'owner_configured':bool(db.get('auth','owner')),'encryption_configured':bool(os.getenv('ENCRYPTION_KEY')),'live_execution':'LOCKED','automated_mode':'LOCKED'}
