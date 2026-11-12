"""Real elapsed-time local/demo soak recorder; does not fabricate a multi-day run."""
import argparse,time,json,os
from pathlib import Path
from backend import db

def main():
    p=argparse.ArgumentParser();p.add_argument('--hours',type=float,default=72);p.add_argument('--report',default='paper-soak-report.json');a=p.parse_args()
    if os.getenv('DATA_MODE','demo')!='demo':raise SystemExit('This runner is demo-only. Use a separate approved live-data forward-test plan.')
    db.init();start=time.time();samples=[]
    try:
        while time.time()-start<a.hours*3600:
            samples.append({'time':time.time(),'worker':db.get('health','worker'),'assistant':db.get('health','assistant'),'notifications':db.get('health','notifications'),'signals':len(db.listing('signals')),'paper':len(db.listing('paper'))});time.sleep(min(30,max(.1,a.hours*3600-(time.time()-start))))
    finally:
        Path(a.report).write_text(json.dumps({'data':'SIMULATED','start':start,'end':time.time(),'requested_hours':a.hours,'elapsed_hours':(time.time()-start)/3600,'samples':samples,'claim':'No real-money, historical profitability or real-time-feed validation implied'},indent=2))
if __name__=='__main__':main()
