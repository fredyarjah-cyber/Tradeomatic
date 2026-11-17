# OANDA market-data connection

This optional connection performs GET requests only. It is separate from the existing OANDA paper-order adapter and does not enable order permissions. It adds an authenticated market-data panel under Broker connections with a manual connection-test button.

Before activation, confirm whether the owner's OANDA account is Practice or Live and whether v20 access is supported for that account. Configure server secrets `OANDA_TOKEN` and `OANDA_ACCOUNT_ID` privately; never paste credentials into chat or frontend inputs. Set `OANDA_MARKET_ENV` to exactly `practice` or `live`, then enable `OANDA_MARKET_DATA_APPROVED=true` only when the owner authorizes that connection. Default is disabled with no external requests. Existing paper/live trading flags remain unchanged. A personal token may carry broader account privileges; this code's GET-only behavior does not make the token itself permission-restricted.

Each manual refresh makes three OANDA GET requests: account summary (only its currency is used), permitted instrument metadata and current pricing with home conversions. It accepts supported Forex pairs, requires a USD account, matching instrument metadata and tradeable positive-liquidity prices, rejects crossed/nonfinite quotes, and requires timestamps no older than 10 seconds with at most two seconds of future skew. Account balances and account IDs are not returned or persisted in observations.

Observed data includes bid/ask, spread in basis points, minimum/increment/maximum units, available top-level liquidity and quote-to-USD conversion. The instrument commission schedule is reported when supplied; a missing schedule remains unknown rather than assuming zero commission. Minimum per-fill commissions are explicitly flagged because the current linear per-unit cost model cannot fully represent them.

Observations are stored separately in `market_observations`. Saved quote times remain visible, so an old observation is not presented as a current executable quote. This connection does not write `context`, `price_ticks`, orders or risk settings. It never marks full trading costs validated: slippage, financing/holding costs, any minimum-commission handling, economic-event coverage and source/account suitability remain separate acceptance work. No background OANDA polling is activated in this release.

Official references reviewed:
- https://developer.oanda.com/rest-live-v20/authentication/
- https://developer.oanda.com/rest-live-v20/account-ep/
- https://developer.oanda.com/rest-live-v20/pricing-ep/
- https://developer.oanda.com/rest-live-v20/primitives-df/
