# Customer preview validation

Nine focused automated tests passed for invitation validation, MFA enrollment, invitation reuse rejection, customer/owner isolation, per-customer preferences, CSRF, checkout ownership, declined payments, successful payments, duplicate completion, cancellation and expiry, simulator disablement, checkout expiry, logout, login throttling and calendar-month boundaries.

Billing is an explicitly labeled local simulator, not a payment-provider sandbox. Real payments, live market data, customer execution, account recovery and sustained customer trials are not validated.
