"""Run three independent services in one always-on worker; restart crashed children."""
import os,sys,time,signal,subprocess
from . import db
MODULES=('backend.worker','backend.assistant','backend.notifications')

def main():
    db.init();stopping=False;children={};backoff={m:1 for m in MODULES};next_start={m:0 for m in MODULES}
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        while not stopping:
            for module in MODULES:
                item=children.get(module)
                if item and item['process'].poll() is not None:
                    lived=time.monotonic()-item['started'];backoff[module]=1 if lived>60 else min(30,backoff[module]*2);next_start[module]=time.monotonic()+backoff[module];children.pop(module)
                if module not in children and time.monotonic()>=next_start[module]:
                    children[module]={'process':subprocess.Popen([sys.executable,'-m',module]),'started':time.monotonic()}
            db.put('health','supervisor',{'heartbeat':time.time(),'children':{m:item['process'].pid for m,item in children.items()}})
            time.sleep(.5)
    finally:
        for item in children.values():
            if item['process'].poll() is None:item['process'].terminate()
        for item in children.values():
            try:item['process'].wait(timeout=20)
            except subprocess.TimeoutExpired:item['process'].kill();item['process'].wait()
if __name__=='__main__':main()
