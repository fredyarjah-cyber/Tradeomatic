# OANDA financing observations

The existing three-GET market observation reads optional instrument financing metadata without additional requests. Stored observations contain `financing.status` (`reported`, `unavailable`, or `invalid`) and normalized details only when valid.

Long and short rates are signed finite decimals. The weekly schedule retains provider day names and nonnegative integer charge-day counts, including multi-day and zero-day entries. Duplicate or unknown days, incomplete rates, invalid numbers and missing schedules do not become zero-cost assumptions. Invalid optional metadata does not discard an otherwise valid quote.

The panel displays the rates as decimals and the weekly schedule. The observation retrieval time does not establish the rates' effective date. Older records without financing metadata show unavailable evidence until refreshed.

These observations never validate costs, alter scanner context or enable orders. Account rollover timing, holiday changes, effective rates, holding periods and estimated charges still need review.

Source: https://developer.oanda.com/rest-live-v20/primitives-df/ — InstrumentFinancing and FinancingDayOfWeek.
