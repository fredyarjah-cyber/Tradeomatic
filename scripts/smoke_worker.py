import tempfile, subprocess, sys, os, time, json, sqlite3
from pathlib import Path
with tempfile.TemporaryDirectory() as temp:
    path=Path(temp)/'smoke.db'
    env={**os.environ,'DATABASE_URL':'sqlite:///'+str(path),'DATA_MODE':'demo','SCAN_SECONDS':'0.1'}
    init="from backend import db; db.init(); db.put('config','scanner',{'enabled':True,'symbols':['USD/JPY','NVDA'],'intervals':['1h']})"
    subprocess.run([sys.executable,'-c',init],env=env,check=True)
    worker=subprocess.Popen([sys.executable,'-m','backend.worker'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            with sqlite3.connect(path) as c:
                count=c.execute("SELECT count(*) FROM records WHERE kind='quotes'").fetchone()[0]
                signals=c.execute("SELECT count(*) FROM records WHERE kind='signals'").fetchone()[0]
            if count==2:break
            time.sleep(.1)
        assert count==2,'Independent scanner did not persist instrument snapshots'
        assert signals>=2,'Every instrument decision must be persisted'
        print('Independent process smoke passed: 2 instruments, persisted signals, no browser or API process required.')
    finally:
        worker.terminate();worker.wait(timeout=10)
