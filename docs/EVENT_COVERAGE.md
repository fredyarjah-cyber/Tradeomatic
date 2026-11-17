# Timestamped event coverage requirements

Real-time, delayed, historical and unknown-mode calendar snapshots no longer pass solely because coverage is labelled complete. Non-simulated snapshots must declare a nonempty source, include the requested instrument in covered_symbols, carry finite asof/valid_until timestamps valid at review time, and be no older than 900 seconds. The declared window must cover 24 hours before and after review, matching the largest supported event blackout.

Events require finite time/known_at, a recognized importance and an integer blackout from 0 to 86400 seconds. Non-simulated high-impact events must explicitly have exact time precision. Estimated, date-only and unknown high-impact timing leave coverage incomplete. Future knowledge or knowledge dated later than the snapshot is rejected. A known high-impact blackout still blocks recommendations when other coverage evidence is incomplete.

The authenticated context schema preserves source, covered_symbols, window_start/window_end and per-event time_precision. Legacy contexts may still be loaded but cannot establish non-simulated coverage without these fields. Synthetic fixtures retain their explicit simulation behavior.

The signal includes event_coverage_review for diagnostics, and the engine version advances to confluence-v2.2. Existing settings continue to govern whether complete coverage is required; known blackouts remain enforced. No existing context is rewritten, no provider subscription or network connection is created, and no order permissions change.

This validates the consistency of declared evidence, not provider licensing, entitlement, source completeness, or delivery guarantees. A verified calendar source is still needed. Economic calendar coverage alone also does not establish corporate earnings or unscheduled-news coverage for stocks.

Validation includes scope, age, horizon boundaries, malformed fields, estimated times, future knowledge, blackouts and compatibility. Production approvals re-run the same recommendation check.
