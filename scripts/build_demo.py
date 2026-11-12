"""Build explicitly synthetic browser fixtures using the actual Python engine."""
import json
from pathlib import Path
from datetime import datetime,timezone
from backend.engine import demo_bars,SYMBOLS,INTERVALS
from backend.intelligence import recommend,HIGHER,rank_signals,DEFAULT_SETTINGS
from backend.service import context
from backend.backtest import walk_forward
NOW=int(datetime.now(timezone.utc).timestamp()//3600)*3600
out={}
Path('src/default-settings.json').write_text(json.dumps(DEFAULT_SETTINGS))
for interval in INTERVALS:
    rows=[]
    for symbol in SYMBOLS:
        dt=datetime.fromtimestamp(NOW,timezone.utc);bars=demo_bars(symbol,interval,dt);htf=HIGHER[interval]
        h=demo_bars(symbol,htf,dt) if htf else []
        r=recommend(symbol,interval,bars,h,context=context(symbol,'SIMULATED',NOW),now=NOW)
        rows.append({**r,'bars':bars,'price':bars[-1]['close'],'status':'ok'})
    out[interval]=rank_signals(rows)
Path('src/fixtures.json').write_text(json.dumps(out,separators=(',',':')))
bars=demo_bars('USD/JPY','1h',datetime.fromtimestamp(NOW,timezone.utc),count=1000)
ctx=context('USD/JPY','SIMULATED',NOW);ctx['costs'].update(asof=0,valid_until=NOW+86400)
report=walk_forward(bars,'USD/JPY','1h',context=ctx,train_bars=200,test_bars=140)
report.update(id='synthetic-walk-forward-v2',created_at=NOW)
Path('src/sample-report.json').write_text(json.dumps(report,separators=(',',':')))
Path('reports/synthetic-walk-forward.json').write_text(json.dumps(report,indent=2))
Path('dist/sample-history.json').write_text(json.dumps({'symbol':'USD/JPY','interval':'1h','bars':bars,'context':{k:v for k,v in ctx.items() if k not in ('market_status','data_mode')},'data_source':'SIMULATED','train_bars':200,'test_bars':140},separators=(',',':')))
print('Synthetic fixtures:',len(out),'timeframes; sample report folds:',len(report['folds']),'closed trades:',report['metrics']['closed_trades'])
