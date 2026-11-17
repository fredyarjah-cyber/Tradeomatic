import React,{useEffect,useState} from 'react';
export function OandaMarketPanel({api,signedIn,notify}){
 const[state,S]=useState(null),[busy,B]=useState(false),[symbol,U]=useState('EUR/USD'),[observation,O]=useState(null);
 useEffect(()=>{if(signedIn)api('v3/market-data/oanda').then(S).catch(e=>notify(e.message))},[signedIn]);
 async function refresh(){B(true);try{O(await api('v3/market-data/oanda/refresh',{symbol}))}catch(e){notify(e.message)}finally{B(false)}}
 const value=observation||state?.observations?.find(x=>x.symbol===symbol);
 return <section className="panel settings"><h2>OANDA market data</h2><p>Read bid/ask prices and instrument limits using server-held credentials. This connection does not enable orders.</p>
 <p>{signedIn?`Environment: ${state?.environment||'loading'} · ${state?.enabled&&state?.configured?'Ready for a connection test':'Server setup required'}`:'Sign in to check the OANDA data connection.'}</p>
 <label>Forex instrument<input value={symbol} maxLength="7" onChange={e=>{U(e.target.value.toUpperCase());O(null)}} placeholder="EUR/USD"/></label>
 <button className="button outline" disabled={!signedIn||busy||!state?.configured||!state?.enabled} onClick={refresh}>{busy?'Reading OANDA…':'Read current OANDA quote'}</button>
 {value&&<><p>Source: {value.source} · Quote time: {new Date(value.time*1000).toLocaleString()} (saved observation; refresh to check again)</p><div className="service-row"><span>Bid / Ask</span><b>{value.bid} / {value.ask}</b></div><div className="service-row"><span>Observed spread</span><b>{value.spread_bps.toFixed(2)} basis points</b></div><div className="service-row"><span>Minimum / increment (units)</span><b>{value.min_units} / {value.unit_step}</b></div><p>Full trading costs remain unvalidated. Pending: {value.pending_checks.join('; ')}.</p></>}
 </section>
}
