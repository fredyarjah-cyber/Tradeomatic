# Production deployment and operations plan

## Review gate and current status

The source is ready for review and paper deployment acceptance. The Sites publication is a static private demo. No persistent cloud services have been created in this work. Render has been connected for this request; connection alone does not authorize resource charges or prove deployment operations are callable in the current session. Do not re-request a Render connection that is already confirmed.

`deploy/render.yaml` is a concrete **billable, review-only** plan: one always-on 0.5c-512mb web service, one 0.5c-512mb consolidated background worker and one 0.1c-256mb PostgreSQL database with 1 GB storage, all in Ohio. The worker runs the scanner, notification sender and broker supervisor as independent child processes. A sleeping free web service is not a substitute for continuous monitoring; Render's background workers have no free plan.

A planning estimate is about $20/month in base compute/database charges ($7 web + $7 worker + $6 database), plus storage, bandwidth and any other usage/account charges. Current published pricing checked November 12, 2026 confirms these base rates and $0.30/GB database storage (about $20.30/month total before other usage/account charges). This is not a binding quote or spending cap. Check the actual workspace checkout/current pricing before provisioning. No market data subscription, brokerage fee, domain purchase or paid AI API is included or authorized. The owner approved a $25/month paper-only hosting budget on November 12, 2026. Do not request the same budget approval again; verify workspace charges fit it before applying. Use https://render.com/pricing and https://render.com/articles/production-rails-hosting-guide for current review; compute plan IDs were checked against https://render.com/docs/blueprint-spec.

The source repository currently belongs to the private Sites workflow. Confirm Render can access that exact repository/commit, or obtain approval for an appropriate connected Git provider copy. Never publish source publicly or copy runtime secrets to solve repository access.

## Install on an existing host without creating new paid resources

1. Back up the existing database and copy the existing persistent secret keys securely.
2. Use Python 3.12+, Node 22+ or Docker Compose. Install dependencies/build from README.
3. Configure `.env` from `.env.example`; keep all provider/broker/push approval flags false initially.
4. Set POSTGRES_PASSWORD to a new long random password. Special URL characters need percent-encoding; an alphanumeric password avoids that setup issue.
5. Generate ENCRYPTION_KEY and VAPID keys locally using `python -m scripts.generate_secrets`. Keep them stable across restarts and shared between services. Do not post their output to chat.
6. Configure PUBLIC_ORIGIN to the exact HTTPS origin, COOKIE_SECURE=true, LEGACY_ADMIN_ENABLED=false and ALLOW_LEGACY_RESEARCH_APPROVALS=false.
7. Run `docker compose up --build -d`. PostgreSQL has a health check. API and worker restart unless stopped. PostgreSQL init is serialized; record kinds are additive and no table is reset.
8. Configure a trusted TLS reverse proxy to the loopback API port. Do not expose PostgreSQL publicly. Honor proxy timeouts, HTTPS/WSS and secure cookies.
9. Run owner setup in the API container: `docker compose exec api python -m scripts.setup_owner`. Complete credential/authenticator entry yourself.
10. Open the HTTPS app, sign in with MFA and verify it can read the existing data. Do not store ADMIN_TOKEN in the browser. The production legacy bearer path is disabled.

For direct PowerShell development, `.env` is not auto-loaded. Use `$env:ENCRYPTION_KEY='...'`, `$env:DATA_MODE='demo'`, and other variables in each terminal, or a trusted secret-manager launcher. bash uses `export`. `uvicorn backend.app:app --host 127.0.0.1 --port 8000` and `python -m backend.supervisor` must use the same database and keys. For localhost HTTP testing only, COOKIE_SECURE=false; restore true before production.

## Render deployment, after approval

1. Confirm the Render workspace with the owner (the connected account lists Tradeomatic), verify the already-approved $25/month budget against current account charges, and establish private GitHub/GitLab/Bitbucket repository access and the exact pushed commit. The existing Sites repository is not a supported Render Git source.
2. Validate `deploy/render.yaml` against Render's current Blueprint validation API/CLI. Local YAML parsing is not a substitute for host validation.
3. Create the web service, worker and private database only within the approved scope. Blueprint creation is billable; this step has not occurred.
4. Supply PUBLIC_ORIGIN, ENCRYPTION_KEY, the matching VAPID key pair and VAPID_SUBJECT on the API service at initial creation. The worker references those API variables with fromService. Only nonsecret settings belong in the shared environment group: Render ignores sync:false entries inside groups. Use proper Fernet/P-256 keys. Automatic deploys and preview environments are disabled in the Blueprint.
5. Set PUBLIC_ORIGIN to the actual Render HTTPS URL. Database URLs are normalized to psycopg3. Confirm automatic private DB networking and an empty public IP allowlist.
6. Deploy the reviewed commit. Verify API health, all three worker heartbeats, DB persistence and restart recovery.
7. Use the web service shell for interactive owner setup. Do not enter account passwords or authenticator seeds through chat.
8. Register an actual phone push subscription. After explicit push activation, queue a test, verify delivery while the app is closed and inspect retry/disable state.
9. Start with simulated data only; then separately verify the approved licensed feed, event coverage and costs. Only then verify paper broker accounts. No live key is required.
10. Run the paper acceptance matrix and a real multi-day soak; retain evidence. Never unlock automated/live mode from a deployment flag in this release.

## Push setup

Set VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY from the same generated P-256 pair. VAPID_SUBJECT must be a valid `mailto:` URI or contact URL you control. After authorization, set PUSH_ENABLED=true. Enable notification preferences and register a device through the signed-in UI. The browser must grant permission in a user gesture. iOS Home Screen web-app support is described at https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/.

Push transport is standards-based Web Push. It does not require buying an Apple developer membership, but this statement does not guarantee a specific device/OS policy or external hosting/data service is free. Only public VAPID key is exposed by readiness. Subscription keys/endpoints are encrypted in PostgreSQL with the server encryption key. The service worker stores only event IDs for local deduplication and never caches prices, APIs or credentials. All notification actions open authenticated application flows; none sends an order from a background push handler.

## Health, recovery and audit

- `/api/health` is API liveness; it does not assert every worker is fresh. `/api/v3/state` reports scanner, broker supervisor and notification heartbeats after authentication.
- A separate assistant process detects stale scanner/notification heartbeats, queues incidents once, and records recovery. If every process/host is down, internal push cannot report it; configure an external uptime monitor through an independently approved service.
- The supervisor restarts crashed child processes with backoff. PostgreSQL advisory locking permits one scanner; outbox claim transactions protect notifications and orders across restarts/overlap.
- Push leases recover after expiration. Duplicate presentation is suppressed by stable tags and service-worker event IDs, but at-least-once delivery remains the transport model.
- Broker writes transition READY → SUBMITTING before network I/O. An ambiguous outcome becomes UNKNOWN or stays SUBMITTING for reconciliation; a restart never resets it to READY. No blind POST retry.
- New orders require fresh broker reconciliation. Missing/protection-inconsistent positions or unresolved submissions block approvals.
- Audit events cover signals, owner sign-in, reviews, decisions, controls, queued orders, broker acknowledgments and reconciliation. Database audit storage is not tamper-proof WORM storage; offsite append-only export remains deployment work.
- Prefer one worker instance; scaling and rolling restarts must be verified against PostgreSQL, not only local SQLite tests.

## Backup and rollback

Preserve the database volume and the application encryption key. Do not rebuild a database from scratch to fix an application deployment. The previous Phase 2 source commit is `dc84a9afcbecbf0ab6cd4ebd0c221dfd9434e0ae`; rolling back code does not require deleting V3 record kinds. Pause new activity before rollback and keep existing broker protections unchanged.

The optional encrypted backup script uses pg_dump with credentials in process environment, encrypts a bounded in-memory dump before any disk write, writes owner-only files atomically and retains seven daily copies. It is disabled by default. Configure a **separate** BACKUP_ENCRYPTION_KEY and BACKUP_ENABLED=true only on the backup service. `docker compose --profile backups up -d backups` schedules one per UTC day. Prepare a backup directory writable by the unprivileged container user. Dumps over 100 MB require a reviewed streaming backup solution. The included local-volume backup is not an offsite or disaster-recovery guarantee.

On Render, use the managed database's verified backup/PITR features and an independently configured encrypted offsite export if needed. Do not assume a paid tier's backup entitlement without checking the actual workspace plan. Retain keys outside the database backup. Test decryption and pg_restore into a disposable staging database, compare record counts and sample signal/ledger IDs, then delete the staging restore through the normal controlled workflow. A real PostgreSQL restore was not performed during this development task.

## Acceptance matrix

| Test | Required evidence before production paper operation |
|---|---|
| Secure login | Password + TOTP on actual HTTPS host; CSRF failure; sign-out invalidation |
| Phone delivery | Actual iPhone/Android receipt while the app is closed, all in-app actions reachable |
| Freshness | Stale quote/heartbeat blocks approval and creates health notification |
| Amount approval | Exact amount/loss/costs shown; changed quantity or price invalidates; duplicate rejected |
| Broker paper | Account permission, market data, native stops, target behavior, minimums and buying power verified |
| Outage | Kill scanner/notifier/supervisor; recover without repeated POST or silent protection removal |
| Global pause | Discovery/new submissions stop; open native protective legs remain |
| Position monitoring stop | Explicit acknowledgment and new entries paused |
| Sustained test | Real elapsed multi-day paper ledger, alert samples, broker reconciliation and failure evidence |
| Backup | Encrypted copy restored and reconciled in staging |

Local automated tests cover the corresponding logic with mocks/synthetic data. They do not complete the actual-device, host, broker or duration requirements. Live trading is not a supported deployment option in this release.
