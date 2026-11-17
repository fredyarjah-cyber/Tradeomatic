# Indicative financing scenario

The OANDA observation panel offers a local calculator only when financing evidence is reported. It requires choosing units, direction and a provider charge day, plus an explicit acknowledgement of the U.S. annual-rate/365 scenario basis.

Formula: units × saved bid/ask midpoint × saved quote-to-USD conversion × selected signed decimal rate × days charged / 365. Positive amounts are shown as credits and negative amounts as debits. This is one provider charge-day scenario, not an entry/exit-date forecast. No rollover timezone, holiday adjustment, future rate or account-specific method is inferred.

Inputs must fit provider size limits and increments. Missing, nonfinite or invalid price/conversion/rate/schedule data cannot produce an estimate. Old quote age remains visible in the parent panel. Refreshing the observation resets acknowledgement. No network requests, persistence, cost validation, recommendation inputs or order changes are added.

Reference: https://www.oanda.com/us-en/trading/financing-fees/ . Account applicability and effective rates require independent confirmation.

Validation: `npm run test:financing` exercises signs, charge-day counts, cross-currency conversion, numeric limits, malformed metadata and decimal increments.
