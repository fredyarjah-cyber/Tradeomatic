# Owner-recorded demo commission evidence

This review records an owner's confirmation that OANDA support verified spread-only pricing with zero separate commission and zero minimum commission per fill for the configured USD practice account and EUR/USD. It is not a provider-reported API field.

The owner must explicitly acknowledge the confirmation. Scope is fixed to EUR/USD and practice, with a chosen review expiry of 1–30 days. Records are bound to a hash of the configured account and environment; full account IDs and tokens are not stored in the review or returned by the endpoints. Account changes, live mode, expiry or revocation make the confirmation inapplicable. Token rotation for the same account does not change scope.

New observations carry an internal account binding that is removed from public responses. A provider commission reported for the same bound account that disagrees with zero fees produces a conflict; re-saving the owner's confirmation does not override it. Older unbound observations cannot establish a conflict.

Authenticated, CSRF-protected endpoints save and revoke evidence and audit the actions. The panel labels provenance, expiry and conflicts. Only an active review removes the missing-commission reminder; it does not modify the stored provider observation or validated execution context.

No scanner, paper-order, broker-order, financing, slippage or event-coverage permission changes are made. Commission evidence alone does not establish full trading costs.

Validation: new tests cover account/environment scope, expiration, revocation, provenance, numeric input restrictions, provider conflicts, private-field filtering, MFA and CSRF. GitHub verification runs the Python suite, synthetic build and frontend checks without deployment credentials.
