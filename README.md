# Tradeomatic AI — Phase 3 mobile assistant

Responsive PWA with market research, a multi-factor engine, an approved internal-paper ledger, mobile decision inbox, owner MFA, exact-quote approvals, Web Push outbox, paper-only broker adapters and independent monitoring processes. Prior routes, record kinds, dashboards and browser storage keys are preserved.

**Current hosted state:** the ChatGPT Sites publication is a private, synthetic browser demonstration. The Python backend is not running on that static host. No real phone delivery, licensed real-time feed, news feed, external broker account or sustained live paper test has been activated. Live and preauthorized automated execution are locked in code.

- [Professional user manual](docs/USER_MANUAL.md)
- [Deployment and operations](docs/DEPLOYMENT_V3.md)
- [Broker compatibility evaluation](docs/BROKERS.md)
- [Phase 2 engine and research](docs/PHASE2.md)
- [Previous installation guide](docs/PHASE2_INSTALLATION.md)
- [Phase 1 reference](docs/PHASE1.md)

## Quick installation

Python 3.12+, Node 22+, a dedicated environment and, for production, PostgreSQL and HTTPS.

```bash
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
# bash: source .venv/bin/activate
pip install -r requirements.txt
npm ci
npm run build
```

Copy `.env.example` to `.env` and configure secrets through your server's secret manager. `.env` is not automatically loaded by the Python command line; Docker Compose loads it. See deployment instructions for PowerShell and bash environment setup.

Generate private setup values **on your own computer**, not in chat:

```bash
python -m scripts.generate_secrets
```

Store the output securely. Use the same persistent ENCRYPTION_KEY for the API, scanner and push processes. Set VAPID_SUBJECT to a valid `mailto:` contact URI you control. PUBLIC_ORIGIN must be the exact HTTPS backend origin. Keep provider, push and broker activation flags false until the corresponding setup is explicitly approved.

Run `python -m scripts.setup_owner` interactively on the backend host using the configured database and encryption key. It verifies your authenticator before saving an Argon2 password hash and encrypted TOTP seed. No credentials are written into the source.

Two terminals, same environment and database:

```bash
uvicorn backend.app:app --host 127.0.0.1 --port 8000
python -m backend.supervisor
```

For local HTTP-only development, set COOKIE_SECURE=false temporarily and leave PUBLIC_ORIGIN empty or set the exact local origin. This is not a production configuration. Browser localhost is the supported development exception to HTTPS; a phone visiting a raw LAN HTTP address cannot use production Web Push securely.

For a persistent local/hosted stack:

```bash
docker compose up --build -d
```

The API and consolidated worker use PostgreSQL. The worker supervises independent scanner, broker-reconciliation and notification-delivery processes, with backoff and graceful shutdown. It must run on an always-on host for unattended monitoring. Container restarts and source-code tests do not prove a real multi-day cloud run.

## Validation

```bash
python -m pytest -q
npm run test:ui
node --test tests/push-worker.test.mjs
python -m scripts.smoke_worker
npm run build
```

These use local SQLite, mock transports and synthetic candles. Real-device push, hosted PostgreSQL concurrency, real broker paper permissions, protective-order behavior and a sustained paper trial remain deployment acceptance checks. A real elapsed-time demo-only soak recorder is included: `python -m scripts.soak_paper --hours 72`. Do not describe a short run or virtual replay as 72 hours of forward testing.

Source delivery: `python -m scripts.package_source` creates the ZIP, excluding secrets and databases. `deploy/render.yaml` is a **review-only, billable infrastructure plan**, not an activated deployment. No Render resources are created by building or publishing the Sites preview.

## Reproducible cloud build

The Docker build generates the clearly labeled synthetic demonstration fixtures with `python -m scripts.build_demo`, then builds React with `npm ci && npm run build`. Generated large fixture and JavaScript bundle files are omitted from the public source repository. For local source builds, run the fixture generator before the frontend build. Runtime credentials and private hosting metadata are excluded.
