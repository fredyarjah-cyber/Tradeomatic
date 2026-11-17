import test from 'node:test';
import assert from 'node:assert/strict';
import {financingScenario} from '../src/financing-scenario.mjs';
const observation=()=>({symbol:'EUR/USD',bid:1.1,ask:1.1002,quote_to_usd:1,min_units:1,max_units:1000000,unit_step:1,financing:{status:'reported',details:{long_rate:-.0247,short_rate:.0045,schedule:[{day:'MONDAY',days_charged:1},{day:'WEDNESDAY',days_charged:3},{day:'SATURDAY',days_charged:0}]}}});
const args={units:1000,direction:'BUY',day:'MONDAY'};
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-10);
test('long debit and short credit use signed rate and snapshot midpoint',()=>{
 const v=observation(),before=structuredClone(v);
 const long=financingScenario(v,args),short=financingScenario(v,{...args,direction:'SELL'});
 near(long.amount_usd,1000*1.1001*-.0247/365);
 near(short.amount_usd,1000*1.1001*.0045/365);
 assert.equal(long.costs_validated,false);assert.deepEqual(v,before);
});
test('Wednesday uses provider triple charge, weekend is explicit zero',()=>{
 const one=financingScenario(observation(),args);
 near(financingScenario(observation(),{...args,day:'WEDNESDAY'}).amount_usd,one.amount_usd*3);
 assert.equal(Math.abs(financingScenario(observation(),{...args,day:'SATURDAY'}).amount_usd),0);
});
test('USD conversion is applied to cross-currency notional',()=>{
 const v=observation();v.quote_to_usd=1.25;
 near(financingScenario(v,args).amount_usd,financingScenario(observation(),args).amount_usd*1.25);
});
test('missing financing and unsupported charge day fail',()=>{
 assert.throws(()=>financingScenario({...observation(),financing:null},args));
 assert.throws(()=>financingScenario(observation(),{...args,day:'UNKNOWN'}));
});
test('invalid quantity, direction and fractional step fail',()=>{
 for(const units of [0,-1,NaN,Infinity,true,'1000',.5,1000001,1.5])assert.throws(()=>financingScenario(observation(),{...args,units}));
 assert.throws(()=>financingScenario(observation(),{...args,direction:'LONG'}));
});
test('decimal unit increments work without accepting half steps',()=>{
 const v=observation();v.unit_step=.01;v.min_units=.01;
 assert.ok(Number.isFinite(financingScenario(v,{...args,units:.03}).amount_usd));
 assert.throws(()=>financingScenario(v,{...args,units:.035}));
});
test('invalid snapshots cannot produce misleading estimates',()=>{
 for(const [key,val] of [['quote_to_usd',0],['bid',NaN],['ask',.9],['unit_step',0],['max_units',0]])assert.throws(()=>financingScenario({...observation(),[key]:val},args));
 const v=observation();v.financing.details.long_rate=NaN;
 assert.throws(()=>financingScenario(v,args));
});
test('malformed and duplicate schedule rows fail',()=>{
 for(const count of [-1,1.5,true,Infinity,32]){
 const v=observation();v.financing.details.schedule[0].days_charged=count;
 assert.throws(()=>financingScenario(v,args));}
 const v=observation();v.financing.details.schedule.push(v.financing.details.schedule[0]);
 assert.throws(()=>financingScenario(v,args));
});
