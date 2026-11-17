// Indicative US annual-rate/365 scenario only; never an approval input.
export function financingScenario(value,{units,direction,day}){
 const fail=message=>{throw new Error(message)};
 const finite=x=>typeof x==='number'&&Number.isFinite(x);
 if(!value||value.financing?.status!=='reported')fail('Refresh an observation with reported financing first.');
 const details=value.financing.details;
 if(!details||!['BUY','SELL'].includes(direction))fail('Choose a long or short scenario.');
 if(!finite(units)||units<=0)fail('Enter a positive number of units.');
 const {bid,ask,quote_to_usd:q,min_units:min,max_units:max,unit_step:step}=value;
 if(![bid,ask,q,min,max,step].every(x=>finite(x)&&x>0)||ask<bid||max<min)fail('Saved price, conversion or instrument limits are invalid. Refresh the observation.');
 if(units<min||units>max)fail('Units must stay within the reported instrument limits.');
 const rounded=Math.round(units/step)*step;
 if(!Number.isSafeInteger(Math.round(units/step))||Math.abs(rounded-units)>Math.max(1,Math.abs(units))*1e-10)fail('Units must match the reported increment.');
 const matches=Array.isArray(details.schedule)?details.schedule.filter(row=>row.day===day):[];
 if(matches.length!==1)fail('Choose a day from the provider schedule.');
 const days=matches[0].days_charged;
 if(!Number.isSafeInteger(days)||days<0||days>31)fail('The charge-day count is unsupported by this scenario.');
 const rate=direction==='BUY'?details.long_rate:details.short_rate;
 if(!finite(rate))fail('The selected financing rate is unavailable.');
 const notional=units*((bid+ask)/2)*q;
 const amount=notional*rate*days/365;
 if(!finite(notional)||!finite(amount))fail('Scenario exceeds supported numeric limits.');
 return {notional_usd:notional,rate,days_charged:days,amount_usd:amount,basis:'INDICATIVE_US_ANNUAL_RATE_365',costs_validated:false};
}
