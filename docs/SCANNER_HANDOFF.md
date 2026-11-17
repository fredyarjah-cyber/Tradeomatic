# Scanner ownership during deployment

The scanner uses one PostgreSQL session advisory lock. During overlapping deployments a replacement now waits in standby instead of crashing when the previous process owns the lock. Standby only updates `health/worker_standby`; it does not scan or replace the active worker heartbeat.

A dedicated connection holds the session lock outside an open transaction. Ownership checks verify that the database session has not been replaced before each cycle, each instrument and after provider waits. Connection loss ends that cycle and returns to acquisition. The implementation never terminates another database session or forcibly takes its lock.

SIGTERM and SIGINT stop discovery, cancel in-flight provider waits and release scanner ownership. The existing supervisor continues to manage its independent broker and notification children. If explicit unlock fails, the connection is invalidated rather than returning a potentially locked session to the pool.

Active worker heartbeats add `status`, `commit`, `instance` and `pid`, preserving the original `heartbeat` field. Render supplies `RENDER_GIT_COMMIT` and `RENDER_INSTANCE_ID`; other hosts report `unknown`/`local`. After deployment, verify that `/api/health` shows the new commit and an advancing heartbeat. A standby process alone is not proof of an active replacement.

Validation covers standby takeover, cancelling an in-flight scan, lock contention, connection identity changes, cleanup after database errors and health metadata. Database ownership tests use mock PostgreSQL connections; hosted PostgreSQL takeover remains a deployment acceptance check. SQLite remains the existing single-process development mode, without PostgreSQL leadership guarantees.

This change does not enable provider mode, scanning, notifications, broker permissions or live trading, and makes no schema changes.
