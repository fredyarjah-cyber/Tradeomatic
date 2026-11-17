# Expanded stock selection

The catalog includes 28 Forex pairs and 24 US stocks/ETFs. New stocks: TSLA, AMD, NFLX, AVGO, ORCL, CRM, JPM, BAC, V, MA, WMT, COST, XOM, CVX.

On Market scanner, expand **Choose scan instruments**. Stop discovery before changing instruments. Select individual checkboxes or **Use watchlist**, choose the timeframe, then start scanning to apply the selection to the background worker. Empty selections cannot start discovery. Existing server selections are loaded when the dashboard connects. These controls change discovery only; existing position monitoring continues independently.

The expanded catalog does not grant provider access or activate a feed. Availability remains subject to the account's symbol entitlements. The existing provider approval and data entitlement gates remain in place.

Basic-plan activation remains pending. The current worker polls each selected instrument and its higher timeframe every cycle; it does not enforce a daily provider-credit budget. Do not enable the full catalog on a limited plan. A stock list update alone does not establish that provider coverage, transaction-cost context, event coverage, or currency conversions are ready for actionable recommendations.

The Docker build regenerates synthetic fixtures for every supported symbol. Existing routes, watchlist storage, Forex symbols, authentication and execution gates are preserved.
