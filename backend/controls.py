from pydantic import BaseModel,ConfigDict
from typing import Literal
from . import db
class Controls(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode:Literal['recommendation','approval_required','automated']='recommendation'
    new_orders_paused:bool=True
    positions_monitoring:bool=True
    global_pause:bool=False

def get(tx=None):return {**Controls().model_dump(),**((tx.get('config','assistant_v3',{}) if tx else db.get('config','assistant_v3',{})))}

def save(changes,acknowledge_unmonitored=False):
    with db.atomic() as tx:
        s=Controls(**{**get(tx),**changes}).model_dump()
        if s['mode']=='automated':raise ValueError('Automated and live execution are locked pending sustained paper validation and separate authorization')
        if not s['positions_monitoring'] and not acknowledge_unmonitored:raise ValueError('Explicit acknowledgment required before stopping position monitoring; protective broker orders remain unchanged')
        if not s['positions_monitoring']:s['new_orders_paused']=True
        tx.put('config','assistant_v3',s)
        if s['global_pause']:
            cfg=tx.get('config','scanner',{'enabled':False,'symbols':[],'intervals':['1h']});cfg['enabled']=False;tx.put('config','scanner',cfg)
        if s['global_pause'] or s['new_orders_paused']:
            for trade in tx.listing('paper'):
                if trade['status']=='PENDING_ENTRY':trade.update(status='CANCELLED',exit_reason='New entries paused; existing protective positions unchanged');tx.put('paper',trade['id'],trade)
            for order in tx.listing('broker_orders'):
                if order['status']=='READY':order['status']='CANCELLED_BEFORE_SUBMISSION';tx.put('broker_orders',order['id'],order)
    db.audit('ASSISTANT_CONTROLS_UPDATED',str(s));return s

def allow_new(tx):
    c=get(tx)
    if c['mode']!='approval_required' or c['global_pause'] or c['new_orders_paused'] or not c['positions_monitoring']:raise ValueError('New orders are paused or recommendation-only mode is active')
