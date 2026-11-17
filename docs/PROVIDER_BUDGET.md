# Twelve Data request limits

This release adds a persistent, shared limit for the app's single-symbol `/time_series` requests. Each request reserves one credit before transport. Failed requests count and are not retried automatically inside the provider adapter. Demo mode makes no provider requests.

Defaults are 700 credits per UTC day and six requests per rolling 60 seconds. Configure `PROVIDER_DAILY_CREDITS` (1–800) and `PROVIDER_MINUTE_CREDITS` (1–8) on both API and monitor consistently. Invalid configuration blocks requests. Limits apply across processes sharing the database and survive restart. The day resets at midnight UTC. The ledger is installation-wide; changing keys does not reset it.

This is a local counter, not the provider's account quota. Requests made in other apps, manual Shell diagnostics and prior usage are excluded. Provider entitlement and account quota can still reject requests before these local limits are reached. This limit covers the current one-credit time-series endpoint only, not future endpoints with other weights.

Successful candle sets are cached per credential fingerprint, symbol, interval and entitlement until the next expected candle close, with existing stale-data limits preserved. Approval and entitlement checks still run on cache hits. No credential values are persisted in the cache or exposed in the authenticated snapshot. Cached prices are completed candle prices, not live ticks.

The authenticated snapshot adds `provider_budget`. The Market scanner shows reserved/remaining credits. When a request is blocked by a local limit, discovery displays NO TRADE with a budget reason and missing updates are not fabricated. The same shared cap also covers requests needed by paper-position monitoring; exhausting it can interrupt that monitoring, so start with a small discovery selection and do not rely on this app for live protective orders.

Suggested first acceptance test after deployment: keep orders disabled, choose EUR/USD on 1h, verify owner-approved account access, then enable provider mode for that small selection. Confirm real candle timestamps and that usage grows only on actual requests. Full-catalog operation may exhaust the Basic allowance and is not enabled by this change. Provider mode, approval flags, entitlements and all hosted settings remain unchanged by this source update.

Source: Twelve Data credit accounting documentation: https://support.twelvedata.com/en/articles/5615854-credits
