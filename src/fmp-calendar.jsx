import React,{useEffect,useRef,useState} from 'react';
export function FmpCalendarPanel({api,signedIn,notify}){
 const[state,S]=useState(null),[result,R]=useState(null),[busy,B]=useState(false);
 const generation=useRef(0);
 useEffect(()=>{const run=++generation.current;S(null);R(null);B(false);
  if(signedIn)api('v3/calendar/fmp').then(v=>{if(generation.current===run)S(v)}).catch(e=>{if(generation.current===run)notify(e.message)});
  return()=>{generation.current++};
 },[signedIn]);
 useEffect(()=>{if(!result)return;const timer=setTimeout(()=>R(null),300000);return()=>clearTimeout(timer)},[result]);
 async function preview(){const run=generation.current;B(true);R(null);
  try{const value=await api('v3/calendar/fmp/preview',{symbol:'EUR/USD'});if(generation.current===run)R(value)}
  catch(e){if(generation.current===run)notify(e.message)}
  finally{if(generation.current===run)B(false)}
 }
 return <section className="panel settings"><h2>Economic calendar preview</h2>
 <p>FMP calendar connection test for EUR/USD. Coverage remains UNVERIFIED and event timing remains UNKNOWN. This preview does not update recommendations, validated context or orders.</p>
 <p>{signedIn?(state?.configured&&state?.enabled?'Manual preview enabled':'Server key and explicit calendar-read approval required'):'Sign in to test the calendar connection.'}</p>
 <button className="button outline" disabled={!signedIn||busy||!state?.configured||!state?.enabled} onClick={preview}>{busy?'Reading calendar…':'Fetch calendar preview'}</button>
 {signedIn&&result&&<><button className="button outline" disabled={busy} onClick={()=>R(null)}>Clear preview</button>
 <p>Retrieved {new Date(result.retrieved_at*1000).toISOString()} · Requested UTC dates: {result.requested_from} through {result.requested_to}.</p>
 <p>Received {result.received_count} rows · EUR/USD-currency matches: {result.matching_count} · Missing currency: {result.unknown_currency_count} · Other currencies excluded: {result.excluded_other_currency_count}.</p>
 {result.preview_truncated&&<p>Display limited to 100 rows. This is not complete calendar coverage.</p>}
 {!result.matching_count&&<p>No EUR/USD-currency rows were returned in this preview. This does not prove there are no relevant events.</p>}
 <table><thead><tr><th>Event</th><th>Provider UTC time</th><th>Currency</th><th>Impact</th><th>Timing</th></tr></thead><tbody>{result.preview_items.map((event,i)=><tr key={i}><td>{event.title}</td><td>{new Date(event.time*1000).toISOString()}</td><td>{event.currency}</td><td>{event.importance}</td><td>UNKNOWN</td></tr>)}</tbody></table>
 <p>Pending: {result.pending_checks.join('; ')}.</p></>}
 <p>No automatic polling or calendar database storage. Preview data stays in this page's memory and clears after five minutes or sign-out. Use only with the appropriate FMP entitlement and usage rights; no public or customer display is enabled.</p>
 </section>
}
