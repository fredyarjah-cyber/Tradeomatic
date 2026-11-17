# Provider result recovery

Previously, a provider failure generated an immutable signal ID using the current time bucket even though it had no candles. A later successful fetch could produce a completed candle with that same ID. The successful quote received status `ok` and current bars, then copied the earlier outage reason, decision and generation time from immutable history.

New provider failures use a `data-error:` ID namespace and remain non-actionable. For pre-existing outage records, successful results use a stable `recovered:` ID only when the conflicting record has no technical features and matches a known internal transient-data reason. Existing valid signal IDs are unchanged. Old history is retained rather than overwritten or deleted, and repeated successful scans of a recovered candle deduplicate normally.

Quotes now include `last_checked_at` independently of the immutable signal's original generation time. Data recovery does not grant provider access, validate costs/news coverage, waive technical/risk checks or create orders.

Regression tests recreate the cross-hour failure/completed-candle collision using the actual recommendation engine, verify both legacy and new-outage recovery, confirm deduplication and existing identity, and check that paper orders are not created. No hosted settings or database migrations are needed. After deployment, inspect EUR/USD `status`, `reason`, `generated_at`, `last_checked_at` and `features` on a new scan to verify hosted recovery.
