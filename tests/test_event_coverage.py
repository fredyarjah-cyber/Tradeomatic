import copy
import pytest
from backend.event_coverage import assess, MAX_SNAPSHOT_AGE
from backend.api_v2 import Events
from backend import service
from backend.intelligence import recommend
from test_intelligence import yes_signal, NOW

def snapshot(now=1000000):
    return {'coverage':'complete','asof':now-10,'valid_until':now+300,'source':'TEST CALENDAR',
            'covered_symbols':['EUR/USD'],'window_start':now-86400,'window_end':now+86400,'items':[]}

def test_scoped_empty_snapshot_is_accepted_without_mutation():
    value=snapshot();before=copy.deepcopy(value)
    assert assess('EUR/USD',value,1000000,'REAL-TIME')=={'complete':True,'issues':[],'blackouts':[]}
    assert value==before
    assert not assess('GBP/USD',value,1000000,'REAL-TIME')['complete']

@pytest.mark.parametrize('change',[
    {'coverage':'unknown'},{'source':''},{'source':' '},{'covered_symbols':[]},
    {'window_start':1000000-86399},{'window_end':1000000+86399},
    {'asof':1000001},{'asof':1000000-MAX_SNAPSHOT_AGE-1},
    {'valid_until':999999},{'valid_until':float('inf')},{'window_start':float('nan')},
    {'items':None},{'items':[None]},{'items':[{}]},{'asof':True},{'asof':10**400}
])
def test_incomplete_or_invalid_real_coverage_is_rejected(change):
    assert not assess('EUR/USD',{**snapshot(),**change},1000000,'REAL-TIME')['complete']

def event(now=1000000):
    return {'title':'Test release','time':now+100,'known_at':now-100,'importance':'high','time_precision':'exact','blackout_seconds':1800}

def test_explicit_blackout_survives_incomplete_calendar():
    value=snapshot();value['coverage']='unknown';value['items']=[event()]
    result=assess('EUR/USD',value,1000000,'REAL-TIME')
    assert not result['complete'] and result['blackouts']==['High-impact event blackout: Test release']

@pytest.mark.parametrize('precision',['estimated','date_only','unknown'])
def test_uncertain_high_impact_timing_blocks_complete_claim(precision):
    value=snapshot();value['items']=[{**event(),'time':1000000+10000,'time_precision':precision}]
    assert not assess('EUR/USD',value,1000000,'REAL-TIME')['complete']

def test_future_knowledge_is_not_usable():
    value=snapshot();value['items']=[{**event(),'known_at':1000001}]
    result=assess('EUR/USD',value,1000000,'REAL-TIME')
    assert not result['complete'] and not result['blackouts']
    value['items'][0]['known_at']=999999
    assert not assess('EUR/USD',value,1000000,'REAL-TIME')['complete']

def test_missing_explicit_event_list_is_not_complete():
    value=snapshot();value.pop('items')
    assert not assess('EUR/USD',value,1000000,'REAL-TIME')['complete']

@pytest.mark.parametrize('event_change',[{'time':float('nan')},{'blackout_seconds':-1},{'blackout_seconds':True},{'importance':'unknown'},{'known_at':None}])
def test_bad_event_cannot_crash_or_pass_coverage(event_change):
    value=snapshot();value['items']=[{**event(),**event_change}]
    assert not assess('EUR/USD',value,1000000,'REAL-TIME')['complete']

def test_legacy_complete_flag_does_not_certify_real_data():
    value={'coverage':'complete','asof':0,'valid_until':2000000,'items':[]}
    assert assess('EUR/USD',value,1000000,'SIMULATED')['complete']
    assert not assess('EUR/USD',value,1000000,'REAL-TIME')['complete']

def test_api_model_retains_scope_and_precision_and_rejects_bad_values():
    value=snapshot();value['items']=[event()]
    parsed=Events(**value).model_dump()
    assert parsed['covered_symbols']==['EUR/USD'] and parsed['items'][0]['time_precision']=='exact'
    with pytest.raises(ValueError):Events(**{**value,'window_end':float('nan')})

def test_real_signal_reports_coverage_failures():
    s,b,h=yes_signal();ctx=service.context(s['symbol'],'SIMULATED',NOW)
    ctx['data_mode']='REAL-TIME'
    r=recommend(s['symbol'],'1h',b,h,context=ctx,now=NOW)
    assert r['recommendation']=='NO'
    assert not r['event_coverage_review']['complete']
    assert 'Event source required' in r['reason']

def test_simulated_signal_fixtures_still_work():
    s,b,h=yes_signal()
    assert s['recommendation']=='YES' and s['event_coverage_review']['complete']
