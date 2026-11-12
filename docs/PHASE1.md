# Tradeomatic AI — Phase 1

A working React research dashboard, FastAPI API, independent Python scanner, PostgreSQL deployment configuration and a gated Twelve Data adapter. No order routing or paid API activation. The hosted Sites preview is a static browser demonstration; it does not host the Python service.

## Run locally

Requirements: Python 3.12+, Node 22+, or Docker Compose. Use a dedicated virtual environment.

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm ci
npm run build
```

Generate a random secret with `python -c "import secrets; print(secrets.token_hex(32))"`. In **each terminal** set the same ADMIN_TOKEN and DATABASE_URL. Do not paste the token into source code. The default database is a local SQLite file for development.

Linux/macOS:
```bash
export ADMIN_TOKEN='YOUR_GENERATED_SECRET'
export DATA_MODE=demo
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Windows PowerShell uses `$env:ADMIN_TOKEN='YOUR_GENERATED_SECRET'` and `$env:DATA_MODE='demo'` before the same uvicorn command. In a second terminal with the same environment and working directory:

```bash
python -m backend.worker
```

Open http://127.0.0.1:8000. Open Settings, enter the administrator token and connect. Press Start scanning. The worker writes quotes and signals to the database even after the browser closes. The dashboard refreshes from the API every five seconds. `/api/ws` also exposes a WebSocket stream, authenticated by the first client message; the dashboard currently uses HTTP polling.

## Container deployment

Copy `.env.example` to `.env`; replace both secret placeholders. Keep `DATA_MODE=demo` and `PROVIDER_APPROVED=false` until the owner approves provider activation.

```bash
docker compose up --build -d
docker compose logs scanner
docker compose ps
```

Open the dashboard through the API at localhost:8000 and enable scanning. PostgreSQL persists configuration, quotes, signal history, audit records and journal entries in a named volume. Deploy the Compose stack on an always-on host; stopping a browser does not stop the scanner. Exactly one scanner replica is supported. PostgreSQL advisory locking rejects a second scanner process. SQLite is development-only and lacks that cross-process singleton guard. The worker restarts with the container restart policy and preserves the enabled/paused flag across restarts.

The API is bound to loopback by default. Do not expose this initial token-authenticated API to the public internet. Before external access, add managed OIDC with mandatory MFA, user isolation, roles, rate limits, TLS and tested authorization. Phase 1 does not claim those features are complete. For a private deployment, use an authenticated private network and a TLS reverse proxy. Set secrets through the host secret manager; `.env` is a local development convenience, not an encrypted credential vault.

## Market-data configuration

The provider adapter calls Twelve Data `/time_series`, requests UTC intraday candles, removes incomplete candles and suppresses stale or invalid OHLC data. This integration is tested against mocked provider responses only; no live provider account was connected.

Before activation, the owner must approve use, verify symbol/exchange coverage, redistribution/display rights, geographic rights, subscription limits and actual real-time/delayed entitlements. Then set on the server:

```
DATA_MODE=provider
PROVIDER_APPROVED=true
TWELVEDATA_API_KEY=<secret manager reference or injected secret>
DATA_ENTITLEMENT=delayed
REQUEST_SPACING_SECONDS=15
```

Use `real-time` only with verified rights. The label is operator-configured; it is not inferred from a successful HTTP response. Activation is intentionally fail-closed. Never transmit the provider key to a browser. Provider errors are logged as sanitized instrument identifiers rather than URLs that may contain credentials.

Coverage: 28 Forex pairs plus AAPL, MSFT, NVDA, AMZN, GOOGL, META, SPY, QQQ, DIA and IWM. The stock indices are represented through ETF proxies in this phase; direct indices and international exchanges are not implemented. The API validates a configurable subset of the supported universe.

Timeframes: 5min, 15min, 30min, 1h, 4h and 1day in demo mode. Provider intraday intervals are supported. Provider daily US equities are deliberately blocked pending exchange-session candle normalization; they never silently fall back to demo data. Provider daily FX uses UTC candles, subject to verification against the provider's session conventions before production use.

US equities use the XNYS exchange calendar, including holidays and early closes. This is appropriate only to the supported US regular-session universe; international calendars and extended-hours execution are not implemented. Forex uses Sunday 17:00 through Friday 17:00 America/New_York; broker-specific holiday closures and exceptional outages need a provider/broker session feed in Phase 2. Data freshness checks suppress stale recommendations. The calendar is not a promise that every Forex provider is open on every holiday.

Quota planning matters: 38 instruments × 6 intervals = 228 requests per pass. At 15 seconds/request that is at least 57 minutes. Start with one timeframe and a small configured universe. No promise is made that a free plan sustains the full matrix at a five-minute cadence. Build provider batching, streaming and entitlement-aware token buckets before high-frequency production use.

Provider references: https://twelvedata.com/docs and https://support.twelvedata.com/en/articles/5745849-timezones. Deployment concepts: https://fastapi.tiangolo.com/deployment/concepts/.

## Analysis and risk

Closed candles only. EMA20/EMA50 trend, Wilder RSI14, MACD histogram, Wilder ATR14 and 20-bar support/resistance. BUY requires close > EMA20 > EMA50, RSI between 45 and 70 and positive MACD histogram; SELL requires the inverse trend, RSI between 30 and 55 and negative histogram. Otherwise NO TRADE. Stops are 1.5 ATR from entry and target reward/risk defaults to 2. Signals are research outputs; historical candle close is not a guaranteed executable price. No machine learning or LLM is used in this phase.

Probability is null, explicitly uncalibrated. Do not interpret rule agreement as a win rate. Calibration needs point-in-time data, out-of-sample evaluation, realistic spread/fees/slippage, leakage prevention, reliability curves and sample-size disclosure. Backtesting is not implemented yet.

Position units = min(equity × risk% / (stop distance × quote-to-USD), allocation / (entry × quote-to-USD)). This is an **unleveraged notional cap**, not broker margin. Default risk is 1%, target 2:1; the allocation, equity, conversion and limits are editable. The quote conversion is manual and must be current. Fractional units are calculated; broker lot steps, minimums and buying-power checks are deferred. Fees, slippage, spread, gaps and correlated portfolio exposure are excluded. UI changes to risk/reward affect the sizing planner; scanner signal targets remain the engine's default 2:1 in this phase.

Signals are uniquely keyed by data mode, symbol, timeframe and completed candle time. Repeated scans upsert the same signal. Historical records remain research snapshots and are not backfilled with hypothetical outcomes. No live execution route exists; authenticated `/api/orders` always rejects.

## Tests and verification

```bash
python -m pytest -q
npm run build
```

Tests exercise risk/allocation constraints, invalid inputs, flat/no-signal analysis, null confidence, holidays/weekends, API authentication, scanner start/stop, deduplication, journal persistence, prohibited orders, provider approval gating and completed-candle filtering. Tests use local SQLite and mocked provider data; PostgreSQL container operation, external provider entitlements and production TLS are deployment acceptance checks, not completed tests.

## Operations

- `GET /api/health` exposes a lightweight API status and worker heartbeat. A healthy API does not mean the worker is fresh. Alert on worker heartbeat age > 180 seconds, missing quotes, provider errors, disk capacity and restart loops. Heartbeats advance during scanning and while paused.
- `GET /api/audit` requires the administrator token. Audit entries are in the same database; tamper-resistant offsite audit storage is deferred.
- Daily encrypted database backups: use `docker compose exec -T db pg_dump -U tradeomatic -Fc tradeomatic > backup.dump`, encrypt it and upload to a separate controlled storage location. Keep 7 daily and 4 weekly copies. Restore into a disposable database with `pg_restore` and verify quotes, config and journal counts monthly. Backup scheduling, encryption and restore verification are deployment work; no automated backup job is active in this preview.
- Avoid leaking keys through reverse proxy access logs, exception URLs, browser storage or WebSocket URLs. WebSocket credentials are sent in a first message, not a query parameter. Frontend admin tokens live only in memory.
- PWA manifest and service worker registration are included. No API or market-data caching. iOS Add to Home Screen works as a website shortcut; native App Store packages, push notifications and offline research are later phases. Native paths: React Native/Expo client sharing API schemas, with platform secure storage and push delivery.

## Next phases and preservation

1. Phase 1 (this source): responsive working demo, API, scanner, persistence, provider adapter, indicators, sizing, journal, deployment recipe and tests.
2. Phase 2: multi-user OIDC/MFA/RBAC, encrypted secret management, provider session/status feeds, robust quota scheduling, signed TradingView webhook ingestion with replay protection, schema migrations and automatic encrypted backups.
3. Phase 3: multi-timeframe confluence, market structure, breakout/reversal/consolidation rules, replay/backtest engine, signal calibration, portfolio risk and outcome analytics.
4. Phase 4: alerts, native clients and optional paper brokerage. Live execution remains separately gated by explicit owner authorization, broker permissions, idempotency keys and pre-trade checks.

Keep tests passing and preserve routes/data through migrations. This phase is a development foundation, not a completed production trading platform.
