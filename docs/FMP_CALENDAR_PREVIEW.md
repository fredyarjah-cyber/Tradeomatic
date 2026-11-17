# FMP owner-only calendar preview

This is an independently gated connection test, not an event-coverage integration for trading decisions.

Server configuration:
- FMP_API_KEY: keep in the API service secret manager only.
- FMP_CALENDAR_READS_APPROVED=false by default. Set true only after confirming plan entitlement and usage rights. Saving a key does not purchase or upgrade a subscription.

Broker connections contains Economic calendar preview. A signed-in owner manually requests EUR/USD. Each click makes exactly one GET to the fixed stable/economic-calendar endpoint, using UTC yesterday through tomorrow dates. Redirects are disabled. Authorization, rate-limit and transport failures return generic errors without URLs, response bodies or credentials.

The preview returns only event title, time, currency, country, impact and unknown timing precision. Estimate and actual figures are omitted. Undocumented precision flags are not trusted. Currency matches are only a display filter; they do not verify U.S./euro-area coverage. Missing currencies, excluded currencies and truncation are counted. At most 100 of 1000 permitted response rows are displayed. Empty results never establish no-event coverage.

All results retain unknown coverage, empty covered_symbols and research-only status. No scanner context, recommendations, price ticks or orders are modified. No provider data is stored in the database or audit records. Responses use Cache-Control: no-store. The panel keeps preview data only in memory, clears it after five minutes, on sign-out or explicit Clear preview, and ignores requests completing after sign-out/unmount. No automatic polling is added.

An entitlement may still deny this endpoint on a free plan. No real provider request is made during tests. Before any integration into recommendations, confirm future U.S./euro-area coverage, time precision, update/completeness semantics and the applicable licensing scope. Public/customer access needs its own approval and licensing.

References:
- https://site.financialmodelingprep.com/developer/docs/stable/economics-calendar
- https://site.financialmodelingprep.com/faqs (calendar timestamps in UTC)
- https://site.financialmodelingprep.com/terms-of-service

The response-only design avoids adding a persistent provider-data store. It is not a substitute for reviewing all applicable data-retention and subscription terms.

## Calendar review

The manual response now includes a five-minute freshness review, potential full UTC-day cautions for high or unknown impact events, and explicit unresolved checks. Review uses all normalized matching rows before the 100-row display limit. Missing currencies and truncation are flagged. Exact event timing and snapshot completeness remain unverified; no empty response or economic actual value certifies approval.

This review remains response-only research. It does not save calendar data, populate validated context, change scanner configuration, or enable orders. The existing event-coverage and approval gates remain in force. A calendar-to-scanner integration still requires a verified coverage/update policy and treatment of unavailable release-time status.
