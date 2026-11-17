import React,{useEffect,useState} from 'react';
export function OandaMarketPanel({api,signedIn,notify}){
 const[state,S]=useState(null),[busy,B]=useState(false),[symbol,U]=useState('EUR/USD'),[observation,O]=useState(null);
 const[now,N]=useState(Date.now());
 useEffect(()=>{let active=true;S(null);O(null);if(signedIn)api('v3/market-data/oanda').then(v=>{if(active)S(v)}).catch(e=>{if(active)notify(e.message)});return()=>{active=false}},[signedIn]);
 useEffect(()=>{const timer=setInterval(()=>N(Date.now()),1000);return()=>clearInterval(timer)},[]);
 async function refresh(){B(true);try{O(await api('v3/market-data/oanda/refresh',{symbol}));N(Date.now())}catch(e){notify(e.message)}finally{B(false)}}
 const value=signedIn?((observation?.symbol===symbol?observation:null)||state?.observations?.find(x=>x.symbol===symbol)):null;
 const age=value?(now/1000-value.time):null;
 const fresh=Number.isFinite(age)&&age>=-2&&age<=10;
 const steps=[
 ['Quote freshness',fresh?'Snapshot within 10 seconds':'Refresh the quote before reviewing current conditions'],
 ['Commission',value?.commission?`Provider reports $${value.commission.per_unit} per unit and $${value.commission.minimum_per_fill} minimum per fill; execution model review required`:'Confirm the commission and minimum charge for this account; missing does not mean zero'],
 ['Slippage','Choose and validate a conservative allowance against observed demo fills'],
 ['Overnight financing',value?.financing?.status==='reported'?'Provider rates and weekly schedule reported below; confirm account rollover rules, rate date and holding period':'Financing data unavailable or invalid; confirm account rates and rollover rules'],
 ['Economic events','Connect a timestamped event source and verify currency coverage']
 ];
 return <section className="panel settings"><h2>OANDA market data</h2><p>Read bid/ask prices and instrument limits using server-held credentials. This connection does not enable orders.</p>
 <p>{signedIn?`Environment: ${state?.environment||'loading'} · ${state?.enabled&&state?.configured?'Ready for a connection test':'Server setup required'}`:'Sign in to check the OANDA data connection.'}</p>
 <label>Forex instrument<input disabled={busy} value={symbol} maxLength="7" onChange={e=>{U(e.target.value.toUpperCase());O(null)}} placeholder="EUR/USD"/></label>
 <button className="button outline" disabled={!signedIn||busy||!state?.configured||!state?.enabled} onClick={refresh}>{busy?'Reading OANDA…':'Read current OANDA quote'}</button>
 {value&&<><p>Source: {value.source} · Quote time: {new Date(value.time*1000).toLocaleString()} (saved observation; refresh to check again)</p><p role="status">{fresh?'Recent snapshot':'Snapshot is stale for execution review'} · {Number.isFinite(age)?Math.max(0,Math.floor(age)):'Unknown'} seconds old. No automatic quote requests.</p><div className="service-row"><span>Bid / Ask</span><b>{value.bid} / {value.ask}</b></div><div className="service-row"><span>Observed spread</span><b>{value.spread_bps.toFixed(2)} basis points</b></div><div className="service-row"><span>Minimum / increment (units)</span><b>{value.min_units} / {value.unit_step}</b></div><p>Full trading costs remain unvalidated. Pending: {value.pending_checks.join('; ')}.</p></>}
 {value&&<><h3>Overnight financing evidence</h3><p>Provider data retrieved with this saved observation. Rate effective date and account rollover rules are not verified.</p>{value.financing?.status==='reported'&&value.financing.details?<><div className="service-row"><span>Long / short rate (decimal)</span><b>{value.financing.details.long_rate} / {value.financing.details.short_rate}</b></div><table><thead><tr><th>Provider charge day</th><th>Days charged</th></tr></thead><tbody>{value.financing.details.schedule.map(row=><tr key={row.day}><td>{row.day}</td><td>{row.days_charged}</td></tr>)}</tbody></table><p>Rates and charge days are provider observations, not a validated holding-cost estimate. Holidays and account-specific terms require review.</p></>:<p>{value.financing?.status==='invalid'?'Provider financing fields were incomplete or invalid.':'Provider financing fields are unavailable in this observation.'} Refresh to request current evidence. Missing data does not mean zero financing.</p>}</>}
 <h3>Paper-trade readiness checklist</h3><p>These items describe evidence still needed. Reading a quote does not validate trading costs or authorize a trade.</p><table><thead><tr><th>Check</th><th>Next step</th></tr></thead><tbody>{steps.map(([label,detail])=><tr key={label}><th scope="row">{label}</th><td>{detail}</td></tr>)}</tbody></table>
 </section>
}
