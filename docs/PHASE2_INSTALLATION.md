# Tradeomatic AI — Phase 2 intelligence and paper research

Working deterministic multi-factor signal engine, paper ledger, exit monitoring and walk-forward replay, integrated with the existing Phase 1 dashboard and scanner. All previously stored record kinds and routes remain supported. No database reset or destructive schema migration is performed. See [Phase 2 engine guide](docs/PHASE2.md) for updated behavior and API examples; [original Phase 1 guide](docs/PHASE1.md) is retained for reference.

**Deployment status:** the privately published Sites dashboard is a synthetic browser demonstration. The included FastAPI/PostgreSQL/Python worker stack must be deployed to an always-on host for actual unattended scanning and forward paper testing. No real-time or news provider, paid inference service, broker or 24/7 cloud worker has been activated. This is a rules-based quantitative engine; no trained AI probability model or LLM is connected.

Start in **Intelligence**, inspect a YES setup, then choose **Approve paper setup**. In the static browser demo, **Paper trading → Advance sample** walks through a predetermined synthetic price path. It is visibly labeled and does not validate the strategy. **Backtesting** shows an actual Python-engine report calculated from synthetic OHLC history, including losses. It can export the report. **Risk controls** stores local demo settings or backend settings when connected. Browser demo storage remains separate from server records.

## Install and run

Python 3.12+, Node 22+ and a dedicated virtual environment:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
npm ci
npm run build
```

Set a new random administrator token of at least 32 characters in each terminal. Generate it locally with `python -c "import secrets; print(secrets.token_hex(32))"`.

PowerShell:
```powershell
$env:ADMIN_TOKEN='YOUR_GENERATED_SECRET'
$env:DATA_MODE='demo'
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

For bash, use `export ADMIN_TOKEN='YOUR_GENERATED_SECRET'` and `export DATA_MODE=demo` before the same uvicorn command. In a second terminal, activate the same environment, set the same variables and working directory, then run:

```bash
python -m backend.worker
```

Open http://127.0.0.1:8000, connect in Settings using the administrator token and start scanning. Default SQLite is development-only. For PostgreSQL, copy `.env.example` to `.env`, replace secret placeholders and run `docker compose up --build -d`. Keep provider approval false. Container setup, backup and TLS details are in the retained Phase 1 guide. Test PostgreSQL concurrency and restore on the actual deployment host before exposing this service. The token-only API is intended for a single owner on a private network; MFA/RBAC are still pending.

## Verify

```bash
python -m pytest -q
npm run test:ui
npm run build
```

Synthetic fixture/report generation: `python -m scripts.build_demo`. Production worker data never falls back to these fixtures after an error. Reports and fixture timestamps describe a fixed sample, not live data freshness. Existing browser watchlists and journal keys are preserved.
