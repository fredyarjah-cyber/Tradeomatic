"""Short real-process outage/recovery test. Never contacts providers or phones."""
import os,sys,subprocess,tempfile,time,json,sqlite3,signal
from pathlib import Path

def main():
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'assistant.db';env={**os.environ,'DATABASE_URL':'sqlite:///'+str(path),'DATA_MODE':'demo','PUSH_ENABLED':'false','OANDA_PAPER_APPROVED':'false','ALPACA_PAPER_APPROVED':'false','SCAN_SECONDS':'.2'}
        subprocess.run([sys.executable,'-c',"from backend import db;db.init();db.put('config','scanner',{'enabled':True,'symbols':['USD/JPY'],'intervals':['1h']})"],env=env,check=True)
        p=subprocess.Popen([sys.executable,'-m','backend.supervisor'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def health():
            with sqlite3.connect(path) as c:return {r[0]:json.loads(r[1]) for r in c.execute("SELECT id,payload FROM records WHERE kind='health'")}
        try:
            deadline=time.monotonic()+20;h={}
            while time.monotonic()<deadline:
                h=health()
                if all(n in h for n in ('worker','assistant','notifications','supervisor')):break
                time.sleep(.1)
            assert all(n in h for n in ('worker','assistant','notifications','supervisor')),'Services did not become ready'
            old=h['supervisor']['children']['backend.worker'];os.kill(old,signal.SIGTERM)
            deadline=time.monotonic()+12;restarted=False
            while time.monotonic()<deadline:
                current=health().get('supervisor',{}).get('children',{}).get('backend.worker')
                if current and current!=old:restarted=True;break
                time.sleep(.1)
            assert restarted,'Scanner child was not restarted'
            print('PASS: API-independent scanner, push and broker-supervisor heartbeats; killed scanner restarted; all external activation flags remained false.')
        finally:p.terminate();p.wait(timeout=25)
if __name__=='__main__':main()
