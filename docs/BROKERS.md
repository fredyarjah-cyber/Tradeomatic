# Broker compatibility evaluation — checked November 12, 2026

This is API/documentation evaluation, not verification of Alfred's personal account eligibility or permission. Actual division, account status, fees, pricing rights and local restrictions must be checked in the broker account before enabling a connection. No broker account was connected during development.

| Provider | Implemented scope | Conditions before activation | Protection and limits |
|---|---|---|---|
| OANDA v20 Practice | Account read, instrument metadata, current pricing, GTD limit-entry payload, order lookup and paper-only POST | v20-capable division; practice account/token; USD home currency; non-MT4 verification; instrument and data permission; explicit paper approval | stopLossOnFill and takeProfitOnFill at target 2. Target 1 alert only. Ordinary stops are not guaranteed fills. |
| Alpaca Paper | Account/asset read, IEX quote, whole-share DAY limit bracket, client-ID lookup and paper-only POST | Paper keys, active USD account, permitted/tradable asset, IEX entitlement and verified costs; shortable/easy-to-borrow when selling short; explicit paper approval | Native bracket stop and target 2. Target 1 alert only. DAY working order is not GTD; already-accepted entry may remain working after signal expiry. No live approval. |
| Interactive Brokers | Evaluated; no executable adapter | Account/API authentication, account funding/tier requirements, trading/market-data permissions and paper-session behavior must be verified | Kept disabled instead of assuming eligibility or unattended authentication support |

OANDA uses only https://api-fxpractice.oanda.com. Alpaca uses only https://paper-api.alpaca.markets, plus its explicit IEX data endpoint for approved reads. Their live trading hosts are absent from the adapter factory. Redirects are not followed. Broker credentials are server environment secrets; there is no browser key-entry form.

Both implemented connections default off. Required flags are `<BROKER>_PAPER_APPROVED=true` and `<BROKER>_ELIGIBILITY_VERIFIED=true`, plus corresponding credentials. OANDA additionally requires OANDA_MT4_LINKED=false after verification. Flags are deployment gates, not proof that a broker has authorized an account. Do not enable them to bypass account checks.

New broker reviews require fresh reconciliation, valid bid/ask (10-second limit), current validated cost/event context, broker instrument sizing rules, account equity/buying power and all portfolio risk checks. Unknown/unprotected or excess broker positions block new orders. Unresolved writes block new approvals. The broker still has final authority to reject any request.

Paper order POSTs are never automatically retried after an uncertain transport result. SUBMITTING/UNKNOWN records survive restarts; lookups use the original client ID. A missing lookup result is not proof it is safe to send the request again. There is no automatic live fallback.

Reconciliation is conservative: reservations for filled broker parent orders may remain until their lifecycle is explicitly resolved. The current ledger does not infer realized broker profit merely from position absence. Automatic bracket cancellation, broker-side partial exits, broker stop replacement, multi-currency broker equity, financing and stock borrow fees are not implemented. Manage those items in the broker portal during this paper release.

API sources:
- OANDA development endpoints: https://developer.oanda.com/rest-live-v20/development-guide/
- OANDA v20 divisions/account access: https://developer.oanda.com/rest-live-v20/introduction/
- OANDA token scope/security: https://developer.oanda.com/rest-live-v20/authentication/
- OANDA orders and protective details: https://developer.oanda.com/rest-live-v20/order-ep/ and https://developer.oanda.com/rest-live-v20/order-df/
- OANDA pricing/conversion: https://developer.oanda.com/rest-live-v20/pricing-ep/
- Alpaca paper environment and simulation limitations: https://docs.alpaca.markets/us/docs/paper-trading
- Alpaca orders/brackets: https://docs.alpaca.markets/us/docs/orders-at-alpaca
- IBKR Web API: https://www.interactivebrokers.com/docs/web-api/authentication/introduction
- IBKR account requirements: https://ibkrcampus.com/docs/web-api/v1/requirements-limitations/introduction

No API charges were incurred. Official availability does not imply an individual account, jurisdiction or dataset is permitted or free of ancillary fees.
