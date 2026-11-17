import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from backend import db, worker
from backend.scanner_lock import ScannerLock, OwnershipLost


def connection(monkeypatch, acquired=True, pid=123):
    c=MagicMock()
    c.invalidated=False
    c.execute.side_effect=[SimpleNamespace(scalar=lambda:acquired),SimpleNamespace(scalar=lambda:pid)]
    engine=MagicMock()
    engine.dialect.name='postgresql'
    engine.connect.return_value=c
    monkeypatch.setattr(db,'engine',engine)
    return c


def test_session_lock_commits_and_releases(monkeypatch):
    c=connection(monkeypatch)
    lock=ScannerLock()
    assert lock.acquire()
    assert lock.backend_pid==123
    c.commit.assert_called_once()
    c.close.assert_not_called()
    c.execute.side_effect=None
    lock.close()
    assert 'pg_advisory_unlock' in str(c.execute.call_args.args[0])
    assert c.commit.call_count==2
    c.close.assert_called_once()


def test_busy_lock_returns_standby_without_leaking_connection(monkeypatch):
    c=connection(monkeypatch,False)
    lock=ScannerLock()
    assert not lock.acquire()
    assert lock.connection is None
    c.commit.assert_called_once()
    c.close.assert_called_once()


@pytest.mark.parametrize('invalidated,new_pid',[(True,123),(False,999)])
def test_lost_session_never_continues_scanning(monkeypatch,invalidated,new_pid):
    c=connection(monkeypatch)
    lock=ScannerLock();assert lock.acquire()
    c.invalidated=invalidated
    c.execute.side_effect=None
    c.execute.return_value.scalar.return_value=new_pid
    with pytest.raises(OwnershipLost):lock.check()
    lock.close()
    c.close.assert_called_once()


def test_stop_cancels_inflight_scan(monkeypatch):
    async def exercise():
        stop=asyncio.Event();entered=asyncio.Event();cancelled=asyncio.Event()
        async def scan(check):
            entered.set()
            try:await asyncio.Event().wait()
            finally:cancelled.set()
        monkeypatch.setattr(worker,'scan_once',scan)
        monkeypatch.setattr(db,'put',lambda *a:None)
        task=asyncio.create_task(worker.run_owned(stop,SimpleNamespace(check=lambda:None)))
        await asyncio.wait_for(entered.wait(),1)
        stop.set()
        await asyncio.wait_for(task,1)
        assert cancelled.is_set()
    asyncio.run(exercise())


def test_standby_takes_over_after_previous_owner_releases(monkeypatch):
    async def exercise():
        stop=asyncio.Event();calls=[];standby=[]
        class Lock:
            def acquire(self):
                calls.append('acquire')
                return calls.count('acquire')>1
            def close(self):calls.append('close')
        async def wait(stop,seconds):pass
        async def owned(stop,lock):calls.append('scan');stop.set()
        monkeypatch.setattr(worker,'ScannerLock',Lock)
        monkeypatch.setattr(worker,'wait_or_stop',wait)
        monkeypatch.setattr(worker,'run_owned',owned)
        monkeypatch.setattr(db,'put',lambda *a:standby.append(a))
        await asyncio.wait_for(worker.serve(stop),1)
        assert calls==['acquire','close','acquire','scan','close']
        assert standby[0][1]=='worker_standby'
        assert standby[0][2]['status']=='standby'
    asyncio.run(exercise())


def test_health_identifies_deployed_commit(monkeypatch):
    monkeypatch.setenv('RENDER_GIT_COMMIT','test-commit')
    monkeypatch.setenv('RENDER_INSTANCE_ID','test-instance')
    health=worker.worker_health()
    assert health['commit']=='test-commit' and health['instance']=='test-instance'
    assert health['status']=='active' and health['pid']>0


def test_failed_acquisition_discards_possibly_locked_session(monkeypatch):
    c=connection(monkeypatch)
    c.commit.side_effect=RuntimeError('commit failed')
    with pytest.raises(RuntimeError):ScannerLock().acquire()
    c.invalidate.assert_called_once()
    c.close.assert_called_once()


def test_unlock_error_discards_session_instead_of_pooling_lock(monkeypatch):
    c=connection(monkeypatch)
    lock=ScannerLock();assert lock.acquire()
    c.execute.side_effect=RuntimeError('transport failed')
    lock.close()
    c.invalidate.assert_called_once()
    c.close.assert_called_once()
