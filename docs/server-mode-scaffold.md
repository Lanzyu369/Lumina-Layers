# Server-Mode Scaffold — Usage & Wake-Up Guide

Lumina Studio 服务端形态脚手架 — 现状与未来唤醒指南.

> **Status (2026-05-01)**: Scaffold merged in PR #137 (commit `4ddb01c`),
> currently **inert** (no application code reads/writes Postgres). This
> document is the runbook for the next time the team decides to wake it
> up.
>
> **状态**: 脚手架已并入 `dev-refactor`, 当前**不通电** (没有应用代码读写
> Postgres). 本文档是"未来某天决定接通时"的操作手册.

---

## 1. Why this guide exists

Phase A4-1 ("server-side data plane scaffold") landed because a future
B2B Elegoo deployment, a multi-user history/favorites feature, or a
multi-replica cloud rollout *might* need durable cross-restart state.
None of those are current product priorities — Lumina ships as an
**offline desktop tool**, both today and through the planned crowdfund
delivery (`.exe` / `.dmg` / `.AppImage` packages).

So the scaffold sits ready but unused: the env switch defaults to
`LUMINA_BACKEND=memory` (the in-process Python dicts that have always
powered desktop runs), and `LUMINA_BACKEND=postgres` raises
`NotImplementedError` pointing here.

This guide tells the future engineer (or AI agent) coming back to this
work three things:

1. **What's already in the repo** (so they don't re-build it)
2. **How to verify the scaffold still works** (a 5-minute smoke test)
3. **What's still missing and how to build it** (Phase A4-2 / A4-3
   implementation sketches)

为什么有这份文档: A4-1 已合并但未通电. 任何回来重启这条线的人, 第一站读
本文档, 不要重复造轮子.

---

## 2. What was shipped (PR #137 inventory)

| File | Lines | Purpose |
|---|---:|---|
| `docker-compose.yml` | 56 | Postgres 16 + Redis 7 services with healthchecks; bind to localhost ports `5432` / `6379`; named volumes for data persistence |
| `api/migrations/alembic.ini` | 58 | Alembic config; `script_location = %(here)s` (CWD-independent — use the same pattern for any future Alembic configs) |
| `api/migrations/env.py` | 100 | Reads `LUMINA_DATABASE_URL` at runtime; supports both offline and online migration modes; loaded only by `alembic` CLI (never by application code) |
| `api/migrations/script.py.mako` | 26 | Template for new migrations |
| `api/migrations/versions/001_initial_schema.py` | 156 | Creates `sessions`, `files`, `session_temp_files` tables with CHECK constraints + indexes (see §5 for full schema) |
| `api/dependencies.py` | 125 (Δ) | `_resolve_backend_name` + `_build_session_store` + `_build_file_registry` helpers; `LUMINA_BACKEND` env switch; module singletons + `get_*` factories preserved (lossless refactor) |
| `requirements.txt` | +6 | `alembic>=1.14`, `sqlalchemy>=2.0`, `psycopg[binary]>=3.2` (lazy-imported; never loaded when `LUMINA_BACKEND=memory`) |
| `.env.example` | +19 | Documents `LUMINA_BACKEND` and `LUMINA_DATABASE_URL` |
| `tests/test_backend_factory_unit.py` | 188 | 16 contract tests for env dispatch (default / memory / postgres / case-insensitivity / whitespace / invalid value) + lossless-refactor guards |

**Branch / commit references**:
- PR #137: `feat(a4-1): Postgres backend scaffold + LUMINA_BACKEND env switch`
- Bug fix on top: `4ddb01c` (`fix(a4-1): resolve Alembic script path` — corrected `script_location = .` → `%(here)s`)
- Merged into: `dev-refactor` @ `f666612`

---

## 3. Decision framework — when to wake this up

Wake the scaffold (i.e. start Phase A4-2) **only if** one of the
following is true:

| Trigger | What it looks like |
|---|---|
| **Multi-user history / favorites feature** | Product side designs a feature where a session, project, or selection persists across user sessions and across app restarts |
| **Elegoo specifies multi-operator state sharing** | Concrete requirement from Elegoo for a single workstation where multiple operators log in / hand off jobs, with state visible across operators |
| **Multi-replica cloud deployment** | A real B2C SaaS plan emerges (currently cancelled per memory `d2e13ccb`); replicas need a shared backend |
| **Long-running test deployment outgrows memory** | The current bug-finding deployment starts losing state often enough that testers complain |

Do **NOT** wake the scaffold just because:

- "It feels more enterprise" / "we should have a real database"
- "Desktop runs feel slow" — desktop performance has nothing to do with Postgres
- "I'm bored of the in-memory dict" — the dict is correct for single-user

何时唤醒: 必须有真实产品诉求 (history / Elegoo 多用户 / 多副本 / 测试部署
真崩了). 不要为了"高大上"而切换.

---

## 4. Smoke test — verify the scaffold still works

Five-minute end-to-end verification, runnable today, requires Docker
Desktop installed.

### 4.1 Start the data plane

```bash
docker compose up -d postgres redis
docker compose ps  # both services should report "healthy" within ~10s
```

Connect from your machine to confirm the containers accept connections:

```bash
docker compose exec postgres pg_isready -U lumina -d lumina_dev
# → /var/run/postgresql:5432 - accepting connections
docker compose exec redis redis-cli ping
# → PONG
```

### 4.2 Apply migrations

From the repo root:

```bash
$env:LUMINA_DATABASE_URL = "postgresql+psycopg://lumina:lumina@localhost:5432/lumina_dev"  # PowerShell
# or: export LUMINA_DATABASE_URL=postgresql+psycopg://lumina:lumina@localhost:5432/lumina_dev  # bash

alembic -c api/migrations/alembic.ini upgrade head
# → INFO  [alembic.runtime.migration] Running upgrade  -> 001
```

### 4.3 Inspect the schema

```bash
docker compose exec postgres psql -U lumina -d lumina_dev -c "\dt"
```

Expected output:

```
              List of relations
 Schema |        Name         | Type  | Owner
--------+---------------------+-------+--------
 public | alembic_version     | table | lumina
 public | files               | table | lumina
 public | session_temp_files  | table | lumina
 public | sessions            | table | lumina
```

### 4.4 Verify the env switch

The contract tests cover all dispatch paths:

```bash
python -m pytest tests/test_backend_factory_unit.py -v
# → 16 passed in 0.12s
```

Expected: 16/16 pass. If any fail after a future Python upgrade or
SQLAlchemy bump, fix before any further A4 work.

### 4.5 Tear down

```bash
docker compose down            # stop containers, keep volumes
docker compose down -v         # stop + delete volumes (full reset)
```

冒烟测试 5 步: 起容器 → 跑迁移 → 查表 → 跑契约测试 → 收摊. 任意一步失败,
先把脚手架修好再考虑实现 A4-2.

---

## 5. Schema reference

Migration `001_initial_schema.py` creates three tables. Schema mirrors
the public APIs of `api/session_store.py` and `api/file_registry.py`
1:1 — each in-memory state field maps to a column.

### 5.1 `sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | Replaces in-memory `_store` key |
| `data` | `JSONB` NOT NULL | Replaces `_store[id]` payload dict; default `'{}'::jsonb` |
| `created_at` | `timestamptz` NOT NULL | New; for audit / debugging |
| `last_seen_at` | `timestamptz` NOT NULL | Replaces `_timestamps[id]` lease tracking |
| `expires_at` | `timestamptz` NOT NULL | Lease expiry; same semantic as memory backend |
| `state` | `text` NOT NULL | `active` / `closing` / `retired` — replaces `_closing_sessions` set + `_retired_sessions` dict |

CHECK: `state IN ('active', 'closing', 'retired')`.
Indexes: `idx_sessions_expires_at`, `idx_sessions_state`.

### 5.2 `files`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | The `file_id` returned by `FileRegistry.register_*` |
| `session_id` | `UUID` FK → `sessions(id) ON DELETE CASCADE`, NULL | Owning session |
| `storage_kind` | `text` NOT NULL | `local` (filesystem) or `s3` (object storage, Phase A6) |
| `storage_key` | `text` NOT NULL | Filesystem path *or* S3 key |
| `filename` | `text` NOT NULL | User-facing filename |
| `lifecycle` | `text` NOT NULL | `session_bound` / `ephemeral` / `shared_cache` |
| `delete_on_cleanup` | `bool` NOT NULL | `false` for files under `MATERIALS_DIR` (asset preservation) |
| `created_at` | `timestamptz` NOT NULL | |
| `expires_at` | `timestamptz` NULL | NULL = no TTL |
| `ttl_seconds` | `integer` NULL | Original TTL for sliding-expiry refresh |

CHECK: `storage_kind IN ('local', 's3')`,
`lifecycle IN ('session_bound', 'ephemeral', 'shared_cache')`.
Indexes: `idx_files_session_id`, `idx_files_expires_at`.

### 5.3 `session_temp_files`

| Column | Type | Notes |
|---|---|---|
| `session_id` | `UUID` FK → `sessions(id) ON DELETE CASCADE`, PK part 1 | |
| `path` | `text`, PK part 2 | Filesystem path registered for cleanup |

Composite primary key `(session_id, path)`. ON DELETE CASCADE is the
reason `SessionStore.close()` does not need an explicit delete on this
table — dropping the row in `sessions` cascades.

`storage_kind = 's3'` and `lifecycle = 'shared_cache'` are present in
the schema today as forward-compat for Phase A6 (object storage); A4-2
implementations should accept them as valid but never emit them.

---

## 6. What's still missing — A4-2 + A4-3 concretely

The scaffold has the rails (env switch, schema, infra) but not the
trains (actual SQL-backed implementations).

### 6.1 Phase A4-2: `PostgresSessionBackend`

**Goal**: replace the `NotImplementedError` in `_build_session_store()`
with a real SQLAlchemy-backed class that satisfies the same 14 public
methods as the in-memory `SessionStore`.

**Public method surface to satisfy** (verified by contract tests
extracted from `tests/test_session_store_*_unit.py`):

| Method | Behavior |
|---|---|
| `create(session_id=None) -> str` | INSERT row in `sessions`; collide → mint new UUID4 |
| `get(session_id) -> Optional[Dict]` | SELECT data; renew lease |
| `put(session_id, key, value) -> None` | UPSERT into `sessions.data` JSONB |
| `register_temp_file(session_id, path) -> None` | INSERT into `session_temp_files` |
| `touch(session_id) -> float \| None` | UPDATE `last_seen_at` + `expires_at`; return new expiry |
| `close(session_id) -> int` | DELETE row (cascades to `session_temp_files`); cleanup paths |
| `close_except(session_id, keep_paths) -> int` | Same but preserve listed paths |
| `cleanup_temp_files_except(session_id, keep_paths) -> int` | Cleanup paths without removing session |
| `cleanup_expired() -> list[str]` | DELETE WHERE `expires_at < now()`; return IDs |
| `clear_all() -> int` | TRUNCATE `sessions` (cascades) |
| `exists(session_id) -> bool` | EXISTS query, exclude state='closing'/'retired' |
| `get_temp_file_paths(session_id) -> list[str]` | SELECT path FROM `session_temp_files` |
| `get_inactive_session_ids() -> list[str]` | SELECT id WHERE state='closing' |
| `get_registry_cleanup_candidate_session_ids() -> list[str]` | SELECT id WHERE state IN ('closing','retired') |

**Implementation sketch** (sync SQLAlchemy 2.0 Core, single connection
pool per process, transaction per public method):

```python
# api/session_store_postgres.py (NEW)
from typing import Any, Optional
from sqlalchemy import create_engine, Table, MetaData, select, insert, update, delete
from sqlalchemy.engine import Engine

class PostgresSessionStore:
    """Postgres-backed SessionStore. Same public API as in-memory version."""
    def __init__(self, database_url: str, ttl: int = 1800) -> None:
        self._engine: Engine = create_engine(database_url, pool_size=5, pool_pre_ping=True)
        self._lease_seconds = ttl
        self._meta = MetaData()
        self._sessions = Table("sessions", self._meta, autoload_with=self._engine)
        self._temp_files = Table("session_temp_files", self._meta, autoload_with=self._engine)

    def create(self, session_id: str | None = None) -> str:
        sid = session_id or str(uuid.uuid4())
        with self._engine.begin() as conn:
            # Collision check: try-insert, mint fresh on conflict
            ...
        return sid

    # ... 13 more methods
```

**Then update** `api/dependencies.py::_build_session_store` to:

```python
if backend == "postgres":
    url = os.environ.get("LUMINA_DATABASE_URL")
    if not url:
        raise RuntimeError("LUMINA_DATABASE_URL required when LUMINA_BACKEND=postgres")
    from api.session_store_postgres import PostgresSessionStore
    return PostgresSessionStore(database_url=url, ttl=1800)
```

**Test strategy**:

- **Unit**: shared `SessionStoreContract` mixin with both
  `MemorySessionStoreContract` and `PostgresSessionStoreContract` test
  classes inheriting it. The mixin asserts behavior parity for all 14
  methods.
- **Integration**: `@pytest.mark.integration` tests gated by
  `LUMINA_TEST_POSTGRES=1` env var; spins up `docker compose up
  postgres`, runs migration, executes the contract suite. Default CI
  skips these; release-gate runs them.

### 6.2 Phase A4-3: `PostgresFileRegistryBackend`

**Goal**: same as A4-2 but for `FileRegistry`'s 9 public methods. Drops
into `_build_file_registry()`.

| Method | Behavior |
|---|---|
| `register_path(session_id, path, filename=None, ttl_seconds=None) -> str` | INSERT files row with `storage_kind='local'`, `storage_key=path` |
| `register_bytes(session_id, data, filename, ttl_seconds=None) -> str` | Write to temp file, then `register_path` |
| `resolve(file_id) -> Optional[Tuple[str, str]]` | SELECT path + filename; expire if past `expires_at`; refresh lease |
| `get_entry(file_id) -> dict \| None` | SELECT * |
| `get_session_entries(session_id) -> dict[str, dict]` | SELECT * WHERE `session_id` = $1 |
| `cleanup_expired() -> int` | DELETE WHERE `expires_at < now()` + filesystem unlink |
| `cleanup_session(session_id) -> int` | DELETE WHERE `session_id` = $1 + filesystem unlink |
| `cleanup_session_except(session_id, keep_file_ids) -> int` | Same but preserve listed file_ids |
| `clear_all() -> int` | TRUNCATE files + filesystem unlink |

**Subtlety**: filesystem deletion must remain **outside** the database
transaction (matches memory implementation's two-phase pattern). On
filesystem failure, mark the row as expired (`expires_at = now()`) and
let `cleanup_expired()` retry on the next sweep.

### 6.3 `start_dev.py` integration (part of A4-3)

Add an opt-in `--postgres` flag that:

1. Verifies `docker compose ps postgres` reports healthy (or starts it)
2. Sets `LUMINA_BACKEND=postgres` and `LUMINA_DATABASE_URL=...` for the
   spawned `api_server.py` process
3. Logs `mode=postgres` at startup so the user knows which backend ran

Default `python start_dev.py` (no flag) keeps `LUMINA_BACKEND=memory` =
desktop behavior unchanged.

---

## 7. Operational concerns (when running in production)

When and if Postgres mode goes live in any deployment:

### 7.1 Migrations on deploy

Bake into the deploy pipeline:

```bash
alembic -c api/migrations/alembic.ini upgrade head
# Then start app servers
```

Migrations must run **before** any app server starts to prevent app
servers from querying tables that don't exist yet. For zero-downtime
rolling deploys, follow the standard "expand-contract" pattern:
schema-additive migrations first, app deploy, then schema-removing
migrations in a follow-up release.

### 7.2 Connection pool sizing

`pool_size=5` is fine for a single API server with worker pool
parallelism = `WorkerPoolConfig.MAX_WORKERS`. If multiple API server
replicas land (B2C scenario), set `pool_size = ceil(p99_concurrent_requests / replica_count) + 1`
and add `max_overflow=5` for spike handling.

### 7.3 Backups

Trivial in single-tenant: `pg_dump` cron. For B2C: managed Postgres
(RDS / Supabase / Neon) with point-in-time recovery. Document the RPO
target before going live.

### 7.4 Monitoring

Existing `api/structured_logging.py` already emits per-request
`request_id` / `session_id`; Postgres backend additions should emit:

- `session_create_done` / `session_close_done` / `file_register_done`
  (already in INFO budget)
- New `db_query_slow` WARNING when query duration > 100ms
- New `db_pool_exhausted` ERROR when pool wait exceeds 1s

Reuse `from api.structured_logging import get_logger` per logging
governance rules — no `print(...)` and no `[TAG]` prefixes.

### 7.5 Observability

Add a `/healthz` endpoint that pings Postgres + Redis when in postgres
mode. Memory mode returns 200 unconditionally (already healthy if the
process is running).

---

## 8. Design choice FAQ

Recorded so future engineers don't re-litigate.

**Why sync SQLAlchemy, not async?**

The existing `api/session_store.py` and `api/file_registry.py` use
`threading.Lock` and are called synchronously from FastAPI routers
(via `Depends(get_session_store)` and direct `.create()` calls, not
`await`). Going async would require touching every router that uses
session state — a massive blast radius for zero user-visible benefit.
SQLAlchemy 2.0's sync API + psycopg3 sync driver are production-grade
and match the existing call pattern.

**Why SQLAlchemy Core, not ORM?**

The Alembic migrations use `op.create_table` / `op.execute` (Core
style). Adding ORM declarative models would mean maintaining schema in
two places (the migration *and* a `models.py`). Core matches the
migration style and avoids dual-source-of-truth.

**Why `state` column instead of separate `is_closing` + `is_retired` bools?**

Three reasons: (1) memory backend's `_closing_sessions` set + 
`_retired_sessions` dict are mutually exclusive — encoding as one enum
column makes the constraint declarative; (2) CHECK constraint
(`state IN ('active', 'closing', 'retired')`) enforces validity at the
DB level; (3) querying "all non-active sessions" becomes one
`WHERE state != 'active'` instead of two boolean ORs.

**Why `storage_kind` and `lifecycle` columns now?**

Forward-compat for Phase A6 (object storage). Adding columns later
requires a schema migration and existing-data backfill. Adding them
unused now is free. The CHECK constraint defines the valid value space.

**Why are the migrations under `api/migrations/`, not at repo root?**

Convention: alembic config + migration scripts live next to the API
code that uses them, like Django's `app/migrations/`. Repo root stays
clean; the scaffold is contained.

**Why `script_location = %(here)s` instead of `.`?**

Bug fixed in commit `4ddb01c`. Relative `.` is interpreted against
**CWD where alembic is invoked**, not where `alembic.ini` lives.
Running `alembic -c api/migrations/alembic.ini upgrade head` from the
repo root would resolve `.` → repo root and fail to find `versions/`.
`%(here)s` is an Alembic 1.13+ built-in that resolves to the directory
containing `alembic.ini` itself, making the config CWD-independent.
**Always use `%(here)s` for any future Alembic configs.**

**Why is the Postgres backend opt-in, not auto-detected?**

Auto-detection (e.g., "if Postgres is reachable on localhost, use it")
would silently change behavior between dev runs based on whether
Docker happens to be running. Explicit env opt-in gives the operator
full control and makes the active backend obvious in logs.

---

## 9. References

- PR #137: scaffold landing — `feat(a4-1): Postgres backend scaffold + LUMINA_BACKEND env switch`
- Commit `4ddb01c`: `fix(a4-1): resolve Alembic script path`
- `progress/server-architecture.md` §4.4: original A4 design (note: §3.2 B2C SaaS plan and parts of §5 / §6 are **superseded** — the project posture is desktop-first per memory `d2e13ccb-5834-4484-b84e-e2eda326f083`)
- `docs/logging-guide.md`: structured logging conventions for any new code paths
- `tests/test_backend_factory_unit.py`: 16 contract tests pinning the env dispatch behavior

---

## 10. Quick exit guide for AI agents

If you (a future AI agent) are dropped into this guide and asked to
"continue Phase A4":

1. Read §3 — confirm a wake trigger actually exists, don't auto-start
2. Run §4 smoke test — confirm scaffold still works on the current
   `dev-refactor` HEAD
3. Read `api/session_store.py` + `api/file_registry.py` source for the
   exact behavior contracts
4. Build A4-2 per §6.1 sketch; PR it; gate Postgres tests behind
   `LUMINA_TEST_POSTGRES=1`
5. Build A4-3 per §6.2 sketch; PR it; update `start_dev.py` per §6.3
6. Update memory `d2e13ccb-5834-4484-b84e-e2eda326f083` if the project
   posture has changed (e.g., a real SaaS plan emerged)

If the wake trigger is **not** present, do **not** start Phase A4-2.
Tell the user the trigger is missing and ask for explicit confirmation
before touching backend code.

未来 AI 的快速指南: 没有真触发条件 → 别动. 有触发 → 按 §6 草图照做, 别
重新设计.
