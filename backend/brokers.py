"""Paper endpoints only. Live endpoints are intentionally absent."""
import os, re, time, hashlib
from decimal import Decimal
from datetime import datetime,timezone
from urllib.parse import quote
import httpx

class BrokerBlocked(ValueError):pass

def enabled(name):
    prefix={'OANDA_PRACTICE':'OANDA','ALPACA_PAPER':'ALPACA'}.get(name)
    return bool(prefix and os.getenv(prefix+'_PAPER_APPROVED')=='true' and os.getenv(prefix+'_ELIGIBILITY_VERIFIED')=='true')

def status():
    return [{'id':'LOCAL_PAPER','name':'Internal paper ledger','configured':True,'approved':True,'live':False},
      {'id':'OANDA_PRACTICE','name':'OANDA v20 Practice','configured':bool(os.getenv('OANDA_TOKEN') and os.getenv('OANDA_ACCOUNT_ID')),'approved':enabled('OANDA_PRACTICE'),'live':False},
      {'id':'ALPACA_PAPER','name':'Alpaca US stocks Paper','configured':bool(os.getenv('ALPACA_KEY_ID') and os.getenv('ALPACA_SECRET_KEY')),'approved':enabled('ALPACA_PAPER'),'live':False},
      {'id':'IBKR','name':'Interactive Brokers','configured':False,'approved':False,'live':False,'reason':'Account, session and paper permissions require separate verification; adapter disabled'}]

class PaperHTTP:
    async def request(self,method,path,body=None,params=None):
        if not enabled(self.name):raise BrokerBlocked('Paper broker approval and eligibility verification required')
        async with httpx.AsyncClient(timeout=15,follow_redirects=False) as c:
            r=await c.request(method,self.base+path,headers=self.headers,json=body,params=params)
        if r.status_code==404:return None
        if r.status_code>=400:raise BrokerBlocked('Broker rejected request; inspect broker portal (response redacted)')
        if r.status_code in (301,302,307,308):raise BrokerBlocked('Broker redirects are prohibited')
        return r.json() if r.content else {}

class OandaPractice(PaperHTTP):
    name='OANDA_PRACTICE';base='https://api-fxpractice.oanda.com'
    def __init__(self):
        self.account=os.getenv('OANDA_ACCOUNT_ID','')
        if not re.fullmatch(r'[0-9-]{6,64}',self.account):raise BrokerBlocked('Configure a valid practice account ID on the server')
        if os.getenv('OANDA_MT4_LINKED','unknown')!='false':raise BrokerBlocked('Verify that the practice account is not linked to MT4 before using client IDs')
        self.headers={'Authorization':'Bearer '+os.getenv('OANDA_TOKEN',''),'Content-Type':'application/json'}
    async def snapshot(self):
        account=(await self.request('GET',f'/v3/accounts/{self.account}/summary'))['account']
        if account['currency']!='USD':raise BrokerBlocked('Only USD broker accounts supported by this adapter')
        trades=(await self.request('GET',f'/v3/accounts/{self.account}/openTrades'))['trades']
        orders=(await self.request('GET',f'/v3/accounts/{self.account}/pendingOrders'))['orders']
        return {'currency':'USD','equity':float(account['NAV']),'buying_power':float(account.get('marginAvailable',0)),'positions':[{'symbol':t['instrument'].replace('_','/'),'units':float(t['currentUnits']),'unrealized_pnl':float(t.get('unrealizedPL',0)),'trade_id':t['id'],'protected':bool(t.get('stopLossOrder')) and t['stopLossOrder'].get('state')=='PENDING'} for t in trades],'open_orders':orders,'asof':time.time()}
    async def market(self,symbol):
        if not re.fullmatch(r'[A-Z]{3}/[A-Z]{3}',symbol):raise BrokerBlocked('OANDA adapter accepts FX only')
        instrument=symbol.replace('/','_')
        items=(await self.request('GET',f'/v3/accounts/{self.account}/instruments',params={'instruments':instrument}))['instruments']
        if len(items)!=1:raise BrokerBlocked('Instrument permission unavailable')
        meta=items[0]
        p=(await self.request('GET',f'/v3/accounts/{self.account}/pricing',params={'instruments':instrument,'includeHomeConversions':'true'}))
        price=p['prices'][0]
        if price.get('status')!='tradeable':raise BrokerBlocked('Instrument is not tradeable')
        at=datetime.fromisoformat(price['time'].replace('Z','+00:00')).timestamp()
        if time.time()-at>10 or at>time.time()+2:raise BrokerBlocked('Broker quote stale or clock skewed')
        bid=float(price['bids'][0]['price']);ask=float(price['asks'][0]['price']);q=1 if symbol.endswith('/USD') else 1/((bid+ask)/2) if symbol.startswith('USD/') else None
        if q is None:
            for x in p.get('homeConversions',[]):
                if x['currency']==symbol[-3:]:q=float(x['positionValue'])
        if not q:raise BrokerBlocked('Home currency conversion unavailable')
        return {'bid':bid,'ask':ask,'time':at,'source':self.name,'quote_to_usd':q,'min_units':float(meta['minimumTradeSize']),'unit_step':10**-int(meta['tradeUnitsPrecision']),'price_decimals':int(meta['displayPrecision']),'margin_rate':float(meta['marginRate']),'max_units':float(meta['maximumOrderUnits'])}
    def payload(self,d,client_id):
        if '/' not in d['symbol']:raise BrokerBlocked('FX required')
        return {'order':{'type':'LIMIT','instrument':d['symbol'].replace('/','_'),'units':str(Decimal(str(d['units']))*(1 if d['direction']=='BUY' else -1)),'price':d['broker_entry'],'timeInForce':'GTD','gtdTime':datetime.fromtimestamp(d['expires_at'],timezone.utc).isoformat().replace('+00:00','Z'),'positionFill':'DEFAULT','clientExtensions':{'id':client_id,'tag':'tradeomatic-paper'},'stopLossOnFill':{'price':d['broker_stop'],'timeInForce':'GTC'},'takeProfitOnFill':{'price':d['broker_target2'],'timeInForce':'GTC'}}}
    async def submit(self,d,client_id):return await self.request('POST',f'/v3/accounts/{self.account}/orders',self.payload(d,client_id))
    async def lookup(self,client_id):return await self.request('GET',f'/v3/accounts/{self.account}/orders/@{quote(client_id,safe="")}')

def alpaca_protected(position,orders):
    needed=abs(float(position['qty']));exit_side='sell' if float(position['qty'])>0 else 'buy'
    for parent in orders:
        if parent.get('symbol')!=position['symbol']:continue
        for order in [parent]+(parent.get('legs') or []):
            if order.get('type') not in ('stop','stop_limit') or order.get('side')!=exit_side:continue
            if order.get('status') not in ('new','accepted','partially_filled'):continue
            remaining=float(order.get('qty',0))-float(order.get('filled_qty',0))
            if remaining>=needed:return True
    return False

class AlpacaPaper(PaperHTTP):
    name='ALPACA_PAPER';base='https://paper-api.alpaca.markets'
    def __init__(self):self.headers={'APCA-API-KEY-ID':os.getenv('ALPACA_KEY_ID',''),'APCA-API-SECRET-KEY':os.getenv('ALPACA_SECRET_KEY',''),'Content-Type':'application/json'}
    async def snapshot(self):
        a=await self.request('GET','/v2/account')
        if a.get('currency')!='USD' or a.get('trading_blocked') or a.get('account_blocked') or a.get('status')!='ACTIVE':raise BrokerBlocked('Account is not active, permitted or USD-denominated')
        positions=await self.request('GET','/v2/positions');orders=await self.request('GET','/v2/orders',params={'status':'open','nested':'true','limit':500})
        return {'currency':'USD','equity':float(a['equity']),'buying_power':float(a['buying_power']),'positions':[{'symbol':p['symbol'],'units':float(p['qty']),'current_price':float(p.get('current_price',0)),'unrealized_pnl':float(p.get('unrealized_pl',0)),'protected':alpaca_protected(p,orders)} for p in positions],'open_orders':orders,'asof':time.time()}
    async def market(self,symbol):
        if not re.fullmatch(r'[A-Z]{1,8}',symbol):raise BrokerBlocked('US equities symbol required')
        a=await self.request('GET','/v2/assets/'+symbol)
        if not a.get('tradable') or a.get('status')!='active':raise BrokerBlocked('Asset is not tradeable')
        async with httpx.AsyncClient(timeout=15,follow_redirects=False) as c:
            r=await c.get('https://data.alpaca.markets/v2/stocks/'+symbol+'/quotes/latest',headers=self.headers,params={'feed':'iex'})
        if r.status_code!=200:raise BrokerBlocked('IEX quote unavailable; data entitlement must be verified')
        p=r.json()['quote'];at=datetime.fromisoformat(p['t'].replace('Z','+00:00')).timestamp()
        if time.time()-at>10 or at>time.time()+2:raise BrokerBlocked('Broker quote stale or clock skewed')
        return {'bid':float(p['bp']),'ask':float(p['ap']),'time':at,'source':self.name+' IEX (not consolidated NBBO)','quote_to_usd':1,'min_units':1,'unit_step':1,'price_decimals':2,'margin_rate':1,'max_units':1e9,'shortable':bool(a.get('shortable') and a.get('easy_to_borrow'))}
    def payload(self,d,client_id):
        if '/' in d['symbol'] or d['units']%1:raise BrokerBlocked('Whole stock shares required')
        return {'symbol':d['symbol'],'side':d['direction'].lower(),'type':'limit','qty':str(int(d['units'])),'limit_price':d['broker_entry'],'time_in_force':'day','order_class':'bracket','take_profit':{'limit_price':d['broker_target2']},'stop_loss':{'stop_price':d['broker_stop']},'client_order_id':client_id,'extended_hours':False}
    async def submit(self,d,client_id):return await self.request('POST','/v2/orders',self.payload(d,client_id))
    async def lookup(self,client_id):return await self.request('GET','/v2/orders:by_client_order_id',params={'client_order_id':client_id,'nested':'true'})

def adapter(name):
    if not enabled(name):raise BrokerBlocked('Paper connection is not approved/configured; no network call made')
    if name=='OANDA_PRACTICE':return OandaPractice()
    if name=='ALPACA_PAPER':return AlpacaPaper()
    raise BrokerBlocked('Unsupported or live broker; execution locked')
