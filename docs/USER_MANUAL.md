# Tradeomatic AI user manual

Version 3.0 · Owner-operated paper research release · Authoritative status: no live trading enabled.

## 1. Understand the three environments

| Environment | What works | What it does not mean |
|---|---|---|
| Private Sites preview | Dashboard, ranked synthetic examples, browser journal, notification examples, amount-review walkthrough and controls | No Python cloud worker, real push delivery or broker connection runs here |
| Deployed backend in demo mode | Persistent scanner, server ledger, MFA, queued Web Push and all safeguards using synthetic data | Synthetic returns do not validate a strategy |
| Approved real-time data + broker paper account | Real-time paper workflow after account/data verification and deployment acceptance | Paper fills and protections do not establish live execution quality or profitability |

The app never silently replaces a failed real feed with simulated prices. Data labels are displayed on charts, recommendations and notifications. A price from the last completed candle is not an executable bid/ask quote.

## 2. Open the app on your phone

After the backend is deployed, use its exact HTTPS address, not the static demonstration address. On iPhone/iPad, open in Safari, choose Share → Add to Home Screen, then launch the installed app. Web Push requires a supported Home Screen web app and user permission. On Android, use a browser supporting Push and Notifications APIs and optionally install the PWA from its menu.

The bottom navigation provides Overview, Intelligence, Positions, Inbox and Controls. Use the menu button for watchlist, scanner, backtesting, journal, history, risk and broker connections. Desktop retains the full sidebar. App Store/Play Store binaries are not included; this release is a responsive installable web app.

## 3. Sign in securely

Your owner account is created interactively on the backend host with `python -m scripts.setup_owner`. The script asks for a username, a password of at least 14 characters, and a current code from your authenticator. Do not enter broker credentials, private API keys or recovery secrets in chat.

Open Notifications and enter your username, password and six-digit authenticator code. Sessions use an HTTP-only, SameSite Strict secure cookie. The browser does not store the password, authenticator seed or broker keys. State-changing requests require a CSRF token. A session lasts one hour; trade review/approval requires MFA within the last 15 minutes. Reauthenticate with a new authenticator code when prompted. Reusing a consumed code is rejected.

Repeated failed sign-in attempts are temporarily limited. For a lost authenticator or encryption key, pause new orders and use your controlled backup/recovery process. There is no insecure email-based bypass. Keep the encryption key separate from encrypted database backups.

## 4. Enable and verify phone notifications

1. Confirm the server has persistent VAPID keys, a valid contact URI and PUSH_ENABLED=true after owner approval.
2. Sign in from the installed phone app.
3. Choose Notifications → Enable push on this device.
4. Grant the browser/OS notification permission yourself.
5. Choose Send test alert, close the app and verify delivery on the phone.
6. Record this device acceptance check; a queued message is not proof of delivery.

The server stores push subscriptions encrypted at rest. Push services also encrypt the transport payload. If a subscription expires, it is disabled after the push service reports it gone. Delivery failures retry with a lease and exponential backoff; permanent failure is recorded. Delivery is at-least-once, not mathematically exactly-once. Stable event tags and service-worker deduplication reduce repeated display. Device OS settings, Focus, battery policies and connectivity can delay or suppress notifications.

A notification contains its instrument/market, YES or NO, direction, price and timestamp, entry, stop, two targets, quantity, estimated risk, reward/risk and explanation where those fields are applicable. NO TRADE and service events do not invent trade levels. If lock-screen privacy is enabled, the visible text is generic and details remain in the encrypted payload/authenticated analysis. Browser/OS presentation may truncate text or show fewer action buttons; the app always exposes all four actions.

- **YES — APPROVE TRADE** opens the review flow. It never submits an order from the lock screen.
- **NO — REJECT TRADE** records rejection after authenticated interaction in the app.
- **VIEW ANALYSIS** opens the explanation and full levels.
- **SNOOZE SIGNAL** defers that signal's deliveries for the configured period.

A notification link contains only an opaque event ID and intended action, not credentials or an approval capability. After sign-in, select the exact notification; obsolete signals cannot be approved.

Preferences include opportunities, NO TRADE, entry, exit and health alerts, and lock-screen detail visibility. NO TRADE alerts default off to avoid overwhelming the inbox.

## 5. Start research without placing orders

Use Overview → Start scanning to enable discovery. Choose timeframes and inspect the scanner. Recommendation-only mode remains the default. Review the Intelligence page's technical evidence, score, source, timestamp, expiry and rejection reasons.

A score measures rule agreement, not probability of success. Confirmed signals wait for candle completion. Higher-timeframe, market-calendar, freshness, cost, event and portfolio checks can produce NO TRADE even with a high score. No economic/news/earnings feed is connected by default; missing required coverage blocks nonsimulated entries.

Start/stop discovery is independent of active-position monitoring. Do not stop a cloud process or uninstall the phone app as a risk-management action. Native broker protective orders, when acknowledged, remain with the broker; their execution is still subject to broker and market conditions.

## 6. Choose your own trade amount

Open Notifications → Review your trade amount, or choose Approve paper setup from Intelligence.

1. Select the current YES opportunity.
2. Enter capital allocation in USD.
3. Select Internal paper ledger, OANDA Practice or Alpaca Paper.
4. Choose Prepare exact quote.
5. Review current price and timestamp, price source, units/shares/lots, entry, stop, both targets, estimated loss, net potential profit, spread, slippage and commission assumptions.
6. Check the destination and working-order policy.
7. Choose Confirm PAPER trade or Cancel / reject.

Allocation is capital committed/margin, not maximum loss. Maximum loss is modeled from stop distance, size and costs. Gaps and execution conditions can exceed it. The estimated profit is a target calculation, not an expectation or guarantee.

Reviews expire after at most 60 seconds and no later than the signal expiry. Approval is tied to a one-use digest of the financial details, risk configuration, portfolio reservation, controls and relevant context. A changed price, quantity, protective level, cost, risk setting or available capacity invalidates the review. A later identical-price timestamp alone does not authorize new terms. Requote and confirm; the service does not silently resize an approved V3 trade.

The internal paper model waits for a later eligible completed candle. V3 approves its exact modeled entry/quantity; a changed later opening price invalidates that approval instead of silently filling another amount. Older V2 research simulations retain their historical behavior locally, but the production V2 direct-approval endpoint is disabled by default. The dashboard routes new approvals through V3.

The standalone browser demonstration uses preset synthetic prices and a scripted walkthrough. It cannot approve external orders or prove authenticated phone delivery. Custom backend risk changes may require a fresh deployed quote rather than the preset demo.

## 7. Track entries and exits

Paper trading displays pending/open/partial/closed internal positions, modeled P/L, protective levels and recommendations. The broker screen displays acknowledged broker paper orders and status. Broker snapshots include current positions, broker-reported unrealized P/L and protection status. Broker advisory recommendations are HOLD, CLOSE, PARTIAL CLOSE or ADJUST STOP when fresh inputs justify them.

Internal paper targets/stops follow the conservative OHLC model described in Phase 2. Partial exits respect minimum quantity/steps. Internal discretionary close/stop changes require your action. External paper brokers use their own simulation and native protection; this release does not silently modify broker exits. Follow a broker exit recommendation through its own portal and verify remaining protection.

For external adapters, target 2 is the native full-position take-profit. Target 1 is an alert for discretionary partial exit. Automatic split broker exits, live protective-order management and fully automated trading remain locked/deferred.

An order marked UNKNOWN means a network timeout or crash left submission uncertain. Do not press buttons repeatedly. The same client ID is reconciled; no second POST is sent automatically. New approvals are blocked until ambiguity is resolved. Check the broker portal if its record is still unavailable.

## 8. Use the correct stop control

| Control | Effect | What remains |
|---|---|---|
| Stop scanning | Pauses new opportunity discovery | Existing positions and broker protections |
| Pause new entries | Blocks new submissions/approvals, cancels unfilled internal paper entries and unsent outbox items | Open positions and already-accepted broker orders/protective legs |
| Global pause | Stops discovery and new submissions | Position monitoring and native protection |
| Risk emergency stop | Blocks new entries; recommends CLOSE for open internal paper positions | Broker protection is not cancelled |
| Stop position monitoring | Requires acknowledgment, pauses new entries and stops advisory/position polling | Broker-side orders remain; you must oversee them directly |
| Resume position monitoring | Restarts monitoring/reconciliation | Does not automatically resume new submissions |

Already-accepted broker entry orders can still fill after a global/new-submission pause. Review working orders directly in the broker portal. This release deliberately does not blindly cancel bracket groups, because that can affect protective legs. Never assume a UI pause recalled a broker request already in flight.

## 9. Review history and performance

Signal history includes both YES and NO evaluations without rewriting confirmed historical decisions. Journal records remain available. Backtesting exports assumptions, training comparisons, out-of-sample folds, modeled fills and metrics. Internal and broker paper outcomes are separate; a broker parent marked FILLED does not establish realized profit. No verified live/forward profitability has been established.

The bundled synthetic backtest and browser walkthrough are demonstrations. Use the included real elapsed-time soak recorder on the deployed demo stack, then separately conduct an approved real-data paper trial. Retain outage, recovery, protection and reconciliation evidence before considering any future live implementation.

## 10. Sign out and preserve records

Sign out to invalidate that browser session. Push subscriptions remain registered until disabled; device unsubscription is managed through `/api/v3/devices/{id}` and OS settings. Keep encrypted backups, the application encryption key and backup encryption key in separate controlled locations. Existing private-preview browser watchlist/journal keys remain on their original origin. A new hosting origin has separate browser storage; server records should be migrated with a reviewed database restore rather than reset.

## Verified in this development turn versus pending

Implemented and locally tested: MFA/cookie/CSRF, exact-review binding, expiry, replay rejection, new-order controls, encrypted subscriptions, push retry/deduplication, paper-only endpoint selection, native protective payload construction and ambiguous-submission quarantine.

Pending real acceptance: Render backend deployment, actual device subscription/test, external paper account authorization, licensed feed/event coverage, real PostgreSQL concurrency/restore tests, broker protective-order behavior and a sustained multi-day forward trial. No hosting purchase, paid API subscription or live trade was activated.
