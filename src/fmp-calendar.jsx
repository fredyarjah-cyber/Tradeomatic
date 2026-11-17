import React,{useEffect,useRef,useState} from 'react';
export function FmpCalendarPanel({api,signedIn,notify}){
 const[state,S]=useState(null),[result,R]=useState(null),[busy,B]=useState(false),[clock,C]=useState(Date.now());
 const generation=useRef(0);
 useEffect(()=>{const run=++generation.current;S(null);R(null);B(false);
  if(signedIn)api('v3/calendar/fmp').then(v=>{if(generation.current===run)S(v)}).catch(e=>{if(generation.current===run)notify(e.message)});
  return()=>{generation.current++};
 },[signedIn]);
 useEffect(()=>{if(!result)return;const timer=setTimeout(()=>R(null),300000);return()=>clearTimeout(timer)},[result]);
 useEffect(()=>{if(!result)return;C(Date.now());const timer=setInterval(()=>C(Date.now()),1000);return()=>clearInterval(timer)},[result]);
 async function preview(){const run=generation.current;B(true);R(null);
  try{const value=await api('v3/calendar/fmp/preview',{symbol:'EUR/USD'});if(generation.current===run)R(value)}
  catch(e){if(generation.current===run)notify(e.message)}
  finally{if(generation.current===run)B(false)}
 }
 return <section className="panel settings"><h2>Economic calendar preview</h2>
 <p>FMP calendar connection test for EUR/USD. Snapshot completeness remains UNVERIFIED and event timing remains UNKNOWN. This preview does not update recommendations, validated context or orders.</p>
 <p>{signedIn?(state?.configured&&state?.enabled?'Manual preview enabled':'Server key and explicit calendar-read approval required'):'Sign in to test the calendar connection.'}</p>
 <button className="button outline" disabled={!signedIn||busy||!state?.configured||!state?.enabled} onClick={preview}>{busy?'Reading calendar…':'Fetch calendar preview'}</button>
 {signedIn&&result&&<><button className="button outline" disabled={busy} onClick={()=>R(null)}>Clear preview</button>
 <p>Retrieved {new Date(result.retrieved_at*1000).toISOString()} · Requested UTC dates: {result.requested_from} through {result.requested_to}.</p>
 <p>Received {result.received_count} rows · EUR/USD-currency matches: {result.matching_count} · Missing currency: {result.unknown_currency_count} · Other currencies excluded: {result.excluded_other_currency_count}.</p>
 {result.preview_truncated&&<p>Display limited to 100 rows. This is not complete calendar coverage.</p>}
 {!result.matching_count&&<p>No EUR/USD-currency rows were returned in this preview. This does not prove there are no relevant events.</p>}
 <table><thead><tr><th>Event</th><th>Provider UTC time</th><th>Currency</th><th>Impact</th><th>Timing</th></tr></thead><tbody>{result.preview_items.map((event,i)=><tr key={i}><td>{event.title}</td><td>{new Date(event.time*1000).toISOString()}</td><td>{event.currency}</td><td>{event.importance}</td><td>UNKNOWN</td></tr>)}</tbody></table>
 {result.review&&<div role="status"><h3>Calendar review</h3>
 <p>Freshness: {clock/1000>=result.retrieved_at&&clock/1000<=result.review.expires_at?'Fresh preview (five-minute limit)':'STALE — fetch again'} · Paper approval: BLOCKED.</p>
 <p>High-impact events with unknown release timing receive a full UTC-day caution in this review. Unknown-impact events receive the same caution.</p>
 {result.review.potential_blocks.map((event,i)=><p key={i}>{event.currency}: {event.title} · {event.reason}</p>)}
 {!result.review.potential_blocks.length&&<p>No same-day potential blocks found. This does not certify a safe trading window.</p>}
 <p>{result.review.issues.join('; ')}.</p><p>{result.review.scope}.</p></div>}
 <p>Pending: {result.pending_checks.join('; ')}.</p></>}
 <p>No automatic polling or calendar database storage. Preview data stays in this page's memory and clears after five minutes or sign-out. Use only with the appropriate FMP entitlement and usage rights; no public or customer display is enabled.</p>
 </section>
}
