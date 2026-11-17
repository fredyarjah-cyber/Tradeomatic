import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from backend import db, oanda_commission as oc, oanda_market as om

BODY={'symbol':'EUR/USD','confirmed':True,'review_days':7}

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    old=db.engine
    db.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    db.init()
    monkeypatch.setenv('OANDA_ACCOUNT_ID','123-456-789')
    monkeypatch.setenv('OANDA_TOKEN','private-test-token')
    monkeypatch.setenv('OANDA_MARKET_ENV','practice')
    yield
    db.engine.dispose();db.engine=old

def test_recorded_confirmation_has_source_expiry_and_no_execution_changes():
    assert oc.review(1000)['status']=='unrecorded'
    result=oc.save(BODY,1000)
    assert result['status']=='active' and result['per_unit']==result['minimum_per_fill']==0
    assert result['source']=='OANDA support confirmation, recorded by owner'
    assert result['expires_at']==1000+7*86400 and result['costs_validated'] is False
    assert '123-456-789' not in json.dumps(result) and 'private-test-token' not in json.dumps(result)
    assert len(db.listing('audit'))==1
    for kind in ['context','price_ticks','paper','broker_orders','config']:
        assert not db.listing(kind)

def test_evidence_expires_and_future_recording_is_inapplicable():
    oc.save(BODY,1000)
    assert oc.review(999)['status']=='expired'
    assert oc.review(1000+7*86400)['status']=='expired'

def test_account_and_environment_are_bound(monkeypatch):
    oc.save(BODY,1000)
    monkeypatch.setenv('OANDA_ACCOUNT_ID','123-456-999')
    assert oc.review(1001)['status']=='unrecorded'
    monkeypatch.setenv('OANDA_MARKET_ENV','live')
    assert oc.review(1001)['status']=='unavailable'
    with pytest.raises(om.MarketDataError):oc.save(BODY,1001)

@pytest.mark.parametrize('body',[
    {**BODY,'confirmed':False},{**BODY,'confirmed':1},{**BODY,'symbol':'GBP/USD'},
    {**BODY,'review_days':0},{**BODY,'review_days':31},{**BODY,'review_days':True},
    {**BODY,'review_days':1.5},{**BODY,'per_unit':0},{'symbol':'EUR/USD'}])
def test_invalid_evidence_is_not_saved(body):
    with pytest.raises(om.MarketDataError):oc.save(body,1000)
    assert not db.listing('commission_reviews')

def test_revoke_retains_record_and_removes_applicability():
    oc.save(BODY,1000)
    assert oc.revoke({'symbol':'EUR/USD'},1001)['status']=='revoked'
    assert len(db.listing('commission_reviews'))==1

def test_provider_conflict_is_not_overridden():
    oc.save(BODY,1000)
    db.put('market_observations','OANDA:EUR/USD',{'_account_binding':oc.binding(),'commission':{'currency':'USD','per_unit':.001,'minimum_per_fill':0}})
    assert oc.review(1001)['status']=='conflict'
    assert oc.save(BODY,1002)['status']=='conflict'
    assert not db.listing('context')

def test_old_account_quote_cannot_invalidate_current_review():
    oc.save(BODY,1000)
    db.put('market_observations','OANDA:EUR/USD',{'_account_binding':'different','commission':{'currency':'USD','per_unit':.001,'minimum_per_fill':0}})
    assert oc.review(1001)['status']=='active'

def test_private_observation_binding_is_not_returned():
    assert om.public_observation({'symbol':'EUR/USD','_account_binding':'private'})=={'symbol':'EUR/USD'}
