import pytest
from backend.intelligence import ExecutionAssumptions, DEFAULT_SETTINGS, size_position, commission_fee, commission_reserve
from backend.paper import close_leg

@pytest.mark.parametrize('floor',[0,.01,1,40])
@pytest.mark.parametrize('rate',[0,.005])
def test_sizing_reserves_entry_and_partial_exit_fees(floor,rate):
    c=ExecutionAssumptions(spread_bps=0,slippage_bps=0,commission_per_unit=rate,minimum_commission_per_fill=floor).model_dump()
    result=size_position('AAPL',10,9,DEFAULT_SETTINGS,c,1)
    if not result['accepted']:
        assert floor==40
        return
    n=result['units']
    for partial in [0,1,n/2,max(0,n-1)]:
        fees=commission_fee(c,n)+commission_fee(c,partial)+commission_fee(c,n-partial)
        assert n+fees<=result['risk_usd']+1e-9
        assert fees<=commission_reserve(c,n)+1e-9
    assert result['risk_usd']<=result['risk_budget']+1e-9


def test_legacy_zero_floor_preserves_sizing():
    c=ExecutionAssumptions(spread_bps=0,slippage_bps=0,commission_per_unit=.005).model_dump()
    c.pop('minimum_commission_per_fill')
    result=size_position('AAPL',10,9,DEFAULT_SETTINGS,c,1)
    assert result['units']==99
    assert result['risk_usd']==pytest.approx(99*1.01)


def test_partial_exits_charge_minimum_each_and_allocate_entry_once():
    costs={'spread_bps':0,'slippage_bps':0,'commission_per_unit':.001,'minimum_commission_per_fill':1}
    t={'direction':'BUY','costs':costs,'quote_to_usd':1,'entry_fill':10,'units':10,'remaining_units':10,'fills':[],'pnl':0,'events':[]}
    close_leg(t,10,4,1,'PARTIAL')
    close_leg(t,10,6,2,'FINAL')
    assert [f['fee_usd'] for f in t['fills']]==[1,1]
    assert t['pnl']==pytest.approx(-3)
    assert t['status']=='CLOSED'


def test_invalid_floor_is_rejected():
    for value in [-1,float('nan'),float('inf')]:
        with pytest.raises(ValueError):ExecutionAssumptions(minimum_commission_per_fill=value)
