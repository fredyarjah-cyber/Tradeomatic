import React,{useState} from 'react';
export function OandaCommissionReview({api,notify,signedIn,state,onSaved,symbol}){
 const[ack,A]=useState(false),[days,D]=useState('7'),[busy,B]=useState(false);
 const review=state?.commission_review;
 async function save(revoke=false){
  B(true);try{
   await api('v3/market-data/oanda/commission-review'+(revoke?'/revoke':''),revoke?{symbol:'EUR/USD'}:{symbol:'EUR/USD',confirmed:ack,review_days:Number(days)});
   A(false);onSaved(await api('v3/market-data/oanda'));
  }catch(e){notify(e.message)}finally{B(false)}
 }
 if(symbol!=='EUR/USD'||!signedIn)return null;
 return <section><h3>Record demo commission confirmation</h3>
 <p>Only for the currently configured OANDA practice account and EUR/USD. Record zero commission only after OANDA support confirms spread-only pricing for this account. The app does not infer this from missing API fields.</p>
 <p>Review status: {review?.status||'unrecorded'}{review?.source?' · '+review.source:''}{review?.expires_at?' · Review expires '+new Date(review.expires_at*1000).toLocaleString():''}.</p>
 {review?.status==='active'&&<p>Owner-recorded support confirmation: USD $0 per unit and USD $0 minimum per fill. Full costs remain unvalidated.</p>}
 {review?.status==='conflict'&&<p role="alert">OANDA has reported commission values that conflict with the saved confirmation. Reconfirm the pricing plan with support; this confirmation is not applicable.</p>}
 <label><input type="checkbox" checked={ack} disabled={busy} onChange={e=>A(e.target.checked)}/> OANDA support confirmed that this configured USD demo account uses spread-only pricing and EUR/USD has zero separate commission and zero minimum commission per fill.</label>
 <label>Review again within<select disabled={busy} value={days} onChange={e=>D(e.target.value)}><option value="7">7 days</option><option value="30">30 days</option></select></label>
 <button className="button outline" disabled={busy||!ack||!state?.configured||state?.environment!=='practice'} onClick={()=>save(false)}>Save support confirmation</button>
 {['active','conflict'].includes(review?.status)&&<button className="button outline" disabled={busy} onClick={()=>save(true)}>Revoke confirmation</button>}
 <p>Changing the configured account or switching to live makes this evidence inapplicable. No trade permissions or validated-cost settings change.</p>
 </section>
}
