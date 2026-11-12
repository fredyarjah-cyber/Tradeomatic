# Phase 2 engine, paper trading and research guide

## What runs where

- `backend/intelligence.py`: pure, deterministic opportunity scoring, explanation, freshness, cost, event, higher-timeframe and risk checks.
- `backend/worker.py`: independent discovery and paper-monitoring loop. One scanner replica. Stop discovery to stop new scans; existing paper trades remain monitored. Emergency stop also cancels pending paper entries.
- `backend/paper.py`: approved paper state machine, cost-adjusted execution, targets, stops, exit recommendations and realized metrics.
- `backend/backtest.py`: chronological replay, training comparisons, rolling walk-forward parameter selection and out-of-sample results.
- `backend/api_v2.py`: authenticated configuration, context ingestion, provisional updates, paper approval/action and replay endpoints.
- `src/phase2.jsx`: Intelligence, Paper trading, Backtesting and Risk controls pages.
- `src/paper-demo.js`: explicitly scripted browser walkthrough, independent from backend forward-test evidence. It is not the production execution model.

The prior scanner config, quote records, signals, journal, audit records, watchlist and routes are preserved. Phase 2 adds record kinds `paper`, `paper_events`, `context`, `backtests`, `provisional` and config ID `risk_v2` to the existing records table. No database reset. Back up PostgreSQL and test upgrade on a copy before deploying. Historical Phase 1 signals remain readable; they lack new metadata and cannot be approved as V2 paper trades.

## Signal rules

Confirmed signals only use candles whose end is at or before the decision frontier. Higher timeframe: 5m→15m, 15m→1h, 30m→4h, 1h→4h, 4h→daily. Daily entry confirmation deliberately returns NO TRADE because no higher interval is currently supported. Provider daily equities remain blocked pending exchange-session normalization.

EMA20/50 trend (20 points), higher-timeframe alignment (20), MACD histogram (15), RSI guardrails (10), ADX14 trend strength (15), structure/continuation setup (10), and volatility guardrail (10) form a 0–100 rule score. Trend, higher timeframe, momentum, RSI and structure are mandatory; a score alone cannot override a failed mandatory check. The score is not a success probability. `confidence` is null until properly calibrated on sufficient out-of-sample observations.

Support/resistance use the previous 20 completed bars, excluding the decision candle. Approximate supply/demand zones extend ±0.25 ATR around those levels; these are technical heuristics, not measured institutional order inventories. Structure breaks are closes outside the previous range. Continuation requires a recent EMA touch with aligned momentum. Possible reversal warnings flag an opposing trend with a close through the previous candle's extreme; a warning alone is not an approved reversal trade.

Stop distance is the larger of 1.5 ATR and the distance to prior support/resistance. Target 1 is calculated to meet the configured **net** reward/risk after modeled round-trip costs; Target 2 uses 1.5 times that ratio. Invalid or nonpositive targets are rejected. Price zones are illustrative execution bounds, not guaranteed fills.

Every confirmed evaluation, including NO TRADE, has a stable ID including version, data mode, symbol, timeframe, candle and configuration hash. Inserts are unique and append-only. Repeated scans do not overwrite historical decisions. Ranking and current freshness overlays can change on the dashboard without rewriting stored signals. Configuration changes can generate a new versioned evaluation on the same candle. A selected signal still undergoes approval and fill-time risk checks.

Default expiration is two full intervals after candle completion. Generation time and candle time are separate. Signals must not be interpreted as actionable after expiration. Confirmed close signals necessarily wait for completion. Polling, provider delivery and execution all add latency; no zero-latency claim is made.

## Context, events, liquidity and conversion

No news, economic or earnings feed has been connected. The authenticated context API accepts point-in-time snapshots. Without current coverage, production entries return NO TRADE by default. Do not mark an incomplete source `complete`. Costs and coverage must have known as-of and validity times; high-impact known events block the configured window, default ±30 minutes. An unannounced event cannot be anticipated by this engine. Context is manual/ingested data, not automatic semantic analysis of news articles.

US equities require a configured minimum candle volume. FX has no centralized volume here; spread is a liquidity proxy, not order-book depth. Current spread/slippage/commission/broker assumptions must be operator-validated. A provider candle response does not prove these costs are valid. Real-time entitlement must be verified; delayed data produces research-only NO TRADE entries.

A USD account uses conversion 1 for USD-quoted instruments, inverse price for USD-base Forex, and a fresh supplied quote-to-USD rate for cross pairs. Paper P/L holds conversion at the entry snapshot; exact mark-to-market conversion requires a separate point-in-time FX series and remains a limitation.

Example server context body (illustrative values, not broker quotes; `validated` deliberately false):

```json
{
  "symbol":"EUR/USD",
  "cost_source":"Replace with broker quote source and timestamp",
  "costs":{"spread_bps":1.2,"slippage_bps":0.5,"commission_per_unit":0.000035,"min_units":1000,"unit_step":1000,"lot_units":100000,"min_volume":0,"validated":false,"asof":0,"valid_until":0},
  "events":{"coverage":"unknown","asof":0,"valid_until":0,"items":[]}
}
```

Events require `title`, UTC Unix `time`, UTC Unix `known_at`, `importance` and optional `blackout_seconds`. Only events known by the current replay frontier may influence a test. Context `conversion` accepts `quote_to_usd`, `asof`, `valid_until`. Secrets stay in the server secret store, never these bodies.

## Position sizing and portfolio controls

Settings default to equity $10,000, allocation $1,000, risk 1%, net target 2:1 and leverage 1. These are editable development defaults, not the user's actual account balance.

Per-unit risk = stop distance × quote-to-USD + estimated round-trip spread/slippage + round-trip per-unit commission in USD. Units are the minimum permitted by per-trade risk, portfolio risk remaining, exposure remaining, allocated margin × leverage and total margin available, rounded down to the broker unit step. Reject sizes below the minimum. FX lots = base units / configured lot units, default 100,000. Stock shares use the configured share step, default whole shares. Financing, stock borrow fees, taxes and market impact are not modeled. Short paper stocks do not imply borrow availability or broker permission.

Default limits: 3 open/pending positions, 100% gross notional exposure, 3% summed stop risk, 3% daily loss. Pending positions reserve exposure, risk and margin. Daily loss is the sum of realized losing exit legs today (UTC) plus current unrealized losses, without offsetting gains; this is deliberately conservative. Equity is manually maintained and does not silently compound with paper P/L. Independent recommendations each assume available capacity until approval; approval serializes reservations with a PostgreSQL transaction advisory lock (SQLite uses BEGIN IMMEDIATE).

Emergency stop blocks new approvals and cancels pending entries. Open paper trades remain monitored and recommend CLOSE; user approval is required to request a discretionary close. Protective paper stop/target simulation continues. Never use stopping the worker as a substitute for broker risk management. No broker is connected.

## Paper lifecycle and exits

`WAITING_FOR_USER_APPROVAL` signal → explicit approval → `PENDING_ENTRY` → later eligible bar open within entry zone → `OPEN` → optional `PARTIAL` → `CLOSED`. Unfilled entries expire. Invalid gaps or violated fill-time risk checks reject an entry. Repeated approvals of the same signal are rejected across processes.

Paper fills occur only on bars opening at or after approval, once those bars complete. This conservative OHLC model may wait an additional full candle compared with a tick-feed paper broker. It cannot fill on the already-observed signal candle. If a candle touches both stop and profit target, the stop wins. Stop gaps fill at the worse of opening mid and stop before friction. Targets fill at target mid before friction. Spread/2 and slippage are adverse at each side; commission is charged at each side.

Target 1 takes approximately half only if both partial and remaining quantities satisfy broker minimum/step. Target 2 closes the remainder. Weakening price and momentum can recommend CLOSE; otherwise HOLD. After target 1 the engine can recommend ADJUST STOP LOSS. It does not silently move the stop: a user action queues a tighter stop for a subsequent bar. Paper discretionary close likewise waits for a subsequent eligible bar. These are modeled paper actions, never live order changes. Recompute and revalidate production prices with a tick/bid-ask broker feed before any future live stage.

## API

All these routes require `Authorization: Bearer <ADMIN_TOKEN>`:

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/snapshot` | Existing dashboard data plus V2 risk settings, paper ledger and reports |
| GET | `/api/v2/state` | Ledger, portfolio risk, forward performance, reports and exit events |
| PATCH | `/api/v2/settings` | Merge validated risk changes without resetting other settings |
| POST | `/api/v2/context` | Store symbol costs, known events and conversion context |
| POST | `/api/v2/paper` | Explicit paper approval, body `{"signal_id":"..."}` |
| POST | `/api/v2/paper/{id}/action` | `close`, `cancel` or `adjust_stop` with optional `new_stop` |
| POST | `/api/v2/updates` | Authenticated price/candle updates, `alert_mode` close/intrabar |
| POST | `/api/v2/backtests` | Historical JSON request and saved walk-forward report |

`/api/v2/updates` accepts symbol, interval, bars, higher_bars, data_mode and alert_mode. Intrabar results are provisional, stored separately and rejected for paper approval. The market-data adapter still polls completed candles. Base and confirmation requests both consume provider quota; only a per-pass cache is used. A full universe at multiple intervals needs verified provider capacity and batching/streaming before production. To receive true intrabar updates, an external licensed stream must call this endpoint. No signed TradingView or paid streaming feed is activated. This endpoint does not silently mark external updates as the configured provider's production quotes.

Interactive OpenAPI documentation is available at `/docs` on the locally deployed FastAPI service. The hosted static preview has no Python API.

## Backtesting, forward testing and reports

Upload a complete JSON request (see `dist/sample-history.json`) or OHLC CSV through Backtesting on the connected backend. CSV uses columns `time,open,high,low,close,volume`, UTC Unix seconds, ascending unique timestamps. Use the CSV instrument/timeframe selectors. CSV starts with unknown events and unvalidated costs, so entries remain blocked until a JSON request supplies appropriate point-in-time context. Do not reuse today's broker/event knowledge as though it existed in past history.

The JSON body includes symbol, interval, bars, optional higher_bars, settings, context, data_source, train_bars and test_bars. Limits: up to 3,000 bars and 3,000 higher-timeframe bars per request. A default 1h replay requires 240 warmup bars, 200 training bars and 120 test bars (560 total). Higher-timeframe aggregation includes only complete, aligned, gap-free groups. For US sessions or irregular history, supply verified higher-timeframe candles explicitly rather than assuming UTC buckets match exchange/vendor sessions.

Each rolling fold compares confluence at 1.5R/2R and breakout at 2R/3R, excluding candidates below the configured minimum R and including the current R for both rules on training history. Choose maximum training average R with at least three completed trades; otherwise use confluence at the configured minimum R. Evaluate only that preselected rule on the following nonoverlapping test window. Warmup uses past bars only. Positions are closed at a predeclared test boundary. Results include candidate training metrics, selected parameters, fold dates, per-fold test metrics, fill legs, trade outcomes, fees and assumptions. Post-selection repeated experimentation can still overfit; these reports do not establish profitability.

Report metrics: closed-trade win rate, profit factor (null with no losses), maximum **realized** equity drawdown and average R-multiple. Average R is a risk-normalized return, not an annualized Sharpe ratio. No invented win rate for zero trades. Equity curves use realized trade cashflows; intratrade drawdown is not measured. Capital resets per fold; the aggregate curve is not a compounded portfolio test. Survivorship bias, corporate-action adjustments, financing, borrow and market impact require additional licensed datasets/models.

The bundled report is a real replay of **synthetic** candles, with both wins and losses. It is not real historical or forward validation. The browser walkthrough is a separate predetermined winning path for UI demonstration and cannot count toward the report. For genuine forward evidence, deploy the independent worker, approve paper entries with real-time licensed data, keep the ledger running and export `/api/v2/state`. No duration of genuine live forward data has been collected in this task.

## Validation and outstanding deployment work

Run the Python suite, JS paper-demo tests and production bundle build from README. Tests include point-in-time filters, event/cost gating, sizing, duplicate/expired approvals, ambiguous candles, partial broker minimums, explicit adjustment, risk preservation, paused-discovery monitoring and no-order authorization. The local tests use SQLite and mocked/synthetic data. Real PostgreSQL concurrency, a licensed provider, platform MFA, encrypted backups, uptime alerting and a production forward-test period still require deployment acceptance work. No services were purchased or activated.

Research references used to inform the implementation, not performance evidence:
- https://www.quantconnect.com/docs/v2/writing-algorithms/optimization/parameters
- https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts
