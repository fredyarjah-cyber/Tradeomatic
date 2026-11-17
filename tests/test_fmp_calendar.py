import asyncio
import copy
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from backend import fmp_calendar as fmp, db

ROW={'date':'2026-11-17 13:30:00','country':'US','event':'Test release',
     'currency':'USD','estimate':1.2,'actual':1.3,'impact':'High'}

@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('FMP_API_KEY','private-calendar-test-key')
    monkeypatch.setenv('FMP_CALENDAR_READS_APPROVED','true')

def test_single_get_keeps_data_unverified_and_never_persists(configured,monkeypatch):
    requests=[]
    def respond(request):
        requests.append(request)
        assert request.method=='GET'
        assert request.url.host=='financialmodelingprep.com'
        assert request.url.path=='/stable/economic-calendar'
        assert request.url.params['apikey']=='private-calendar-test-key'
        assert request.url.params['from']<request.url.params['to']
        return httpx.Response(200,json=[ROW])
    def fail(*args,**kwargs):raise AssertionError('No database writes allowed')
    monkeypatch.setattr(db,'put',fail);monkeypatch.setattr(db,'put_once',fail)
    result=asyncio.run(fmp.preview('EUR/USD',httpx.MockTransport(respond)))
    assert len(requests)==1 and result['coverage']=='unknown' and result['covered_symbols']==[]
    assert result['preview_items'][0]['time_precision']=='unknown'
    assert result['research_only'] is True and result['retention']=='response_only'
    assert 'actual' not in result['preview_items'][0] and 'estimate' not in result['preview_items'][0]
    assert 'private-calendar-test-key' not in json.dumps(result)

def test_disabled_gate_prevents_network(configured,monkeypatch):
    monkeypatch.setenv('FMP_CALENDAR_READS_APPROVED','false')
    def fail(request):raise AssertionError('No network')
    with pytest.raises(fmp.CalendarError,match='not enabled'):
        asyncio.run(fmp.preview('EUR/USD',httpx.MockTransport(fail)))

@pytest.mark.parametrize('key',['','bad key','bad\nkey'])
def test_missing_or_malformed_keys_block_requests(configured,monkeypatch,key):
    monkeypatch.setenv('FMP_API_KEY',key)
    with pytest.raises(fmp.CalendarError,match='server-held'):
        asyncio.run(fmp.preview('EUR/USD'))

def test_only_pilot_symbol_allowed(configured):
    with pytest.raises(fmp.CalendarError,match='EUR/USD'):
        asyncio.run(fmp.preview('GBP/USD'))

@pytest.mark.parametrize('status',[301,401,403,429,500])
def test_provider_errors_redact_body_and_key(configured,status):
    def respond(request):return httpx.Response(status,json={'error':'private-calendar-test-key'},headers={'Location':'https://other.example'})
    with pytest.raises(fmp.CalendarError) as e:
        asyncio.run(fmp.preview('EUR/USD',httpx.MockTransport(respond)))
    assert 'private-calendar-test-key' not in str(e.value)

def test_transport_error_redacts_query(configured):
    def respond(request):raise RuntimeError(str(request.url))
    with pytest.raises(fmp.CalendarError) as e:
        asyncio.run(fmp.preview('EUR/USD',httpx.MockTransport(respond)))
    assert 'private-calendar-test-key' not in str(e.value) and 'apikey' not in str(e.value)

@pytest.mark.parametrize('row',[None,{}, {**ROW,'date':'bad date'},{**ROW,'event':None}])
def test_invalid_event_fields_are_rejected(row):
    with pytest.raises(fmp.CalendarError):fmp.normalize([row],1,'2026-11-16','2026-11-18')

def test_currency_filter_reports_uncertain_rows_without_inference():
    rows=[ROW,{**ROW,'currency':'EUR','country':'DE'},{**ROW,'currency':None},
          {**ROW,'currency':'JPY','country':'JP'}]
    result=fmp.normalize(rows,1,'2026-11-16','2026-11-18')
    assert result['matching_count']==2 and result['unknown_currency_count']==1
    assert result['excluded_other_currency_count']==1 and result['coverage']=='unknown'

def test_provider_extra_precision_and_actual_values_do_not_certify_timing():
    row={**ROW,'time_precision':'exact','confirmed':True,'actual':7}
    before=copy.deepcopy(row)
    result=fmp.normalize([row],1,'2026-11-16','2026-11-18')
    assert row==before and result['preview_items'][0]['time_precision']=='unknown'

def test_empty_and_truncated_previews_never_claim_complete_coverage():
    result=fmp.normalize([],1,'2026-11-16','2026-11-18')
    assert result['matching_count']==0 and result['coverage']=='unknown'
    result=fmp.normalize([ROW]*101,1,'2026-11-16','2026-11-18')
    assert len(result['preview_items'])==100 and result['preview_truncated']
    assert result['matching_count']==101 and result['coverage']=='unknown'
    with pytest.raises(fmp.CalendarError):fmp.normalize([ROW]*1001,1,'2026-11-16','2026-11-18')

def test_key_echo_in_event_title_is_withheld(configured):
    def respond(request):return httpx.Response(200,json=[{**ROW,'event':'private-calendar-test-key'}])
    with pytest.raises(fmp.CalendarError,match='protect credentials'):
        asyncio.run(fmp.preview('EUR/USD',httpx.MockTransport(respond)))

def test_utc_and_offset_dates_agree_and_unknown_impact_stays_unknown():
    a=fmp.normalize([{**ROW,'date':'2026-11-17 13:30:00'}],1,'a','b')
    b=fmp.normalize([{**ROW,'date':'2026-11-17T14:30:00+01:00','impact':None}],1,'a','b')
    assert a['preview_items'][0]['time']==b['preview_items'][0]['time']
    assert b['preview_items'][0]['importance']=='unknown'

def test_nonlist_error_payload_is_rejected():
    with pytest.raises(fmp.CalendarError):fmp.normalize({'error':'private'},1,'a','b')

def test_escaped_key_echo_is_withheld(configured,monkeypatch):
    key='quote"private-key'
    monkeypatch.setenv('FMP_API_KEY',key)
    def respond(request):return httpx.Response(200,json=[{**ROW,'event':key}])
    with pytest.raises(fmp.CalendarError,match='protect credentials'):
        asyncio.run(fmp.preview('EUR/USD',httpx.MockTransport(respond)))

def test_review_blocks_unknown_time_for_entire_utc_day():
    at=1794922200  # same UTC day is calculated from the normalized event
    item={'title':'Release','currency':'USD','importance':'high','time':at}
    start=int(at//86400)*86400
    for now in (start,start+86399):
        result=fmp.review([item],now,now)
        assert result['fresh'] and not result['paper_approval_ready']
        assert len(result['potential_blocks'])==1
    assert not fmp.review([item],start+86400,start+86400)['potential_blocks']

@pytest.mark.parametrize('impact,expected',[('high',1),('unknown',1),('medium',0),('low',0)])
def test_review_impact_caution(impact,expected):
    item={'title':'Release','currency':'EUR','importance':impact,'time':100000}
    result=fmp.review([item],100000,100000)
    assert len(result['potential_blocks'])==expected
    assert not result['paper_approval_ready']

@pytest.mark.parametrize('now,fresh',[(100,True),(400,True),(401,False),(99,False)])
def test_review_expires_and_rejects_future_snapshot(now,fresh):
    result=fmp.review([],now,100)
    assert result['fresh'] is fresh
    assert result['expires_at']==400 and not result['paper_approval_ready']

def test_review_checks_all_rows_before_display_truncation():
    rows=[{**ROW,'impact':'Low'}]*100+[ROW]
    result=fmp.normalize(rows,1794922200,'2026-11-16','2026-11-18')
    assert result['preview_truncated']
    assert any('truncated' in issue for issue in result['review']['issues'])
    assert result['review']['paper_approval_ready'] is False

@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,None])
def test_review_invalid_clock_rejected(value):
    with pytest.raises(fmp.CalendarError):fmp.review([],value,100)
