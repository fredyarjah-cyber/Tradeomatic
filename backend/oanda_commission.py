"""Owner-recorded support evidence; never validates the full execution model."""
import hashlib
import math
import time
from . import db, oanda_market

SYMBOL='EUR/USD'
SOURCE='OANDA support confirmation, recorded by owner'

def binding():
    import os
    state=oanda_market.readiness()
    if not state['configured'] or state['environment']!='practice':
        raise oanda_market.MarketDataError('Commission confirmation is limited to the configured practice account')
    account=os.environ['OANDA_ACCOUNT_ID'].strip()
    return hashlib.sha256(('oanda-practice:'+account).encode()).hexdigest()

def review(now=None):
    now=time.time() if now is None else now
    try:key=binding()
    except oanda_market.MarketDataError:return {'symbol':SYMBOL,'status':'unavailable'}
    row=db.get('commission_reviews',key+':'+SYMBOL)
    if not row:return {'symbol':SYMBOL,'status':'unrecorded'}
    valid=(row.get('pricing')=='SPREAD_ONLY' and row.get('currency')=='USD'
           and row.get('per_unit')==0 and row.get('minimum_per_fill')==0
           and isinstance(row.get('recorded_at'),(int,float)) and isinstance(row.get('expires_at'),(int,float))
           and math.isfinite(row['recorded_at']) and math.isfinite(row['expires_at'])
           and 0<row['expires_at']-row['recorded_at']<=30*86400)
    status='active' if valid and row['recorded_at']<=now<row['expires_at'] else 'expired'
    if row.get('revoked'):status='revoked'
    observed=db.get('market_observations','OANDA:'+SYMBOL,{})
    provider=observed.get('commission')
    if status=='active' and observed.get('_account_binding')==key and provider is not None:
        if provider.get('currency')!='USD' or provider.get('per_unit')!=0 or provider.get('minimum_per_fill')!=0:
            status='conflict'
    return {**{k:row[k] for k in ('symbol','pricing','currency','per_unit','minimum_per_fill','recorded_at','expires_at','source') if k in row},
            'status':status,'costs_validated':False}

def save(body,now=None):
    if not isinstance(body,dict) or set(body)!={'symbol','confirmed','review_days'}:
        raise oanda_market.MarketDataError('Choose EUR/USD and acknowledge the support confirmation')
    if body['symbol']!=SYMBOL or body['confirmed'] is not True:
        raise oanda_market.MarketDataError('Confirm support verified spread-only pricing for this practice account and EUR/USD')
    days=body['review_days']
    if type(days) is not int or not 1<=days<=30:
        raise oanda_market.MarketDataError('Review validity must be 1 to 30 days')
    key=binding();now=time.time() if now is None else now
    row={'symbol':SYMBOL,'pricing':'SPREAD_ONLY','currency':'USD','per_unit':0.0,
         'minimum_per_fill':0.0,'recorded_at':now,'expires_at':now+days*86400,'source':SOURCE}
    with db.atomic() as tx:
        tx.put('commission_reviews',key+':'+SYMBOL,row)
    db.audit('OANDA_COMMISSION_CONFIRMATION',SYMBOL)
    return review(now)

def revoke(body,now=None):
    if not isinstance(body,dict) or body!={'symbol':SYMBOL}:
        raise oanda_market.MarketDataError('Choose the EUR/USD confirmation')
    key=binding()
    with db.atomic() as tx:
        row=tx.get('commission_reviews',key+':'+SYMBOL)
        if row:
            row['revoked']=True;tx.put('commission_reviews',key+':'+SYMBOL,row)
    db.audit('OANDA_COMMISSION_REVOKED',SYMBOL)
    return review(now)
