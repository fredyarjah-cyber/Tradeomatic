import React,{useState} from 'react';
import {financingScenario} from './financing-scenario.mjs';
export function FinancingScenario({value}){
 const[units,U]=useState('1000'),[direction,D]=useState('BUY'),[day,Y]=useState(''),[ack,A]=useState(false);
 const schedule=value.financing?.details?.schedule||[];
 let result=null,error='';
 if(ack){try{result=financingScenario(value,{units:units.trim()?Number(units):NaN,direction,day})}catch(e){error=e.message}}
 return <section><h3>Indicative financing scenario</h3>
 <p>Uses this saved quote midpoint, its USD conversion and the reported financing rate. This is a single charge-day scenario, not a forecast across dates or a confirmed account charge.</p>
 <label>Position units<input type="number" min={value.min_units} max={value.max_units} step={value.unit_step} value={units} onChange={e=>U(e.target.value)}/></label>
 <label>Direction<select value={direction} onChange={e=>D(e.target.value)}><option value="BUY">Long / buy</option><option value="SELL">Short / sell</option></select></label>
 <label>Charge day<select value={day} onChange={e=>Y(e.target.value)}><option value="">Choose a provider charge day</option>{schedule.map(row=><option key={row.day} value={row.day}>{row.day}: {row.days_charged} days charged</option>)}</select></label>
 <label><input type="checkbox" checked={ack} onChange={e=>A(e.target.checked)}/> Use the indicative U.S. annual-rate / 365 formula for this scenario. My account rules and rate date still require confirmation.</label>
 {error&&<p role="alert">{error}</p>}
 {result&&<><div className="service-row"><span>Scenario financing {result.amount_usd<0?'debit':result.amount_usd>0?'credit':'amount'}</span><b>{new Intl.NumberFormat(undefined,{style:'currency',currency:'USD',minimumFractionDigits:4,maximumFractionDigits:4}).format(result.amount_usd)}</b></div><p>Saved midpoint notional: ${result.notional_usd.toFixed(2)} · Rate: {(result.rate*100).toFixed(4)}% · Charge days: {result.days_charged}. Formula: notional × annual decimal rate × charge days / 365.</p></>}
 <p>Rates may change. Rollover timing, holidays and account terms are unverified. Spread, commission and slippage are excluded. This estimate is not saved as validated costs or used for trade approval. <a href="https://www.oanda.com/us-en/trading/financing-fees/" target="_blank" rel="noreferrer">OANDA U.S. financing formula</a></p>
 </section>
}
