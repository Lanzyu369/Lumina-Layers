# Server-Mode Scaffold — Usage & Wake-Up Guide

Lumina Studio 服务端形态脚手架 — 现状与未来唤醒指南.

> **Status (2026-05-01)**: A4-1 scaffold merged in PR #137 (commit
> `4ddb01c`). A4-2 + A4-3 implementations followed in commit `fcf845d`,
> joined by migration `002_add_file_owner_id.py`. Doc-sync + Postgres
> path observability added in PR #XXX (this PR). The Postgres path is
> **live when explicitly opted in** via `LUMINA_BACKEND=postgres`; the
> default remains `memory` and desktop deployments are unchanged. This
> document is the runbook for future operators activating Postgres mode
> in a deployment, plus the historical record of how A4-1 → A4-3 landed.
>
> **状态**: A4-1 脚手架于 PR #137 (`4ddb01c`) 合入, A4-2/A4-3 实现于
> `fcf845d` 落地 (含迁移 `002_add_file_owner_id.py`), 本 PR 补 文档同步 +
> Postgres 路径可观测性. `LUMINA_BACKEND=postgres` 时 Postgres 路径已
> 可工作; 默认仍为 `memory`, 桌面部署不受影响. 本文档现为"部署中
> 启用 Postgres 模式"的操作手册, 并完整记录 A4-1 → A4-3 落地谱系.

---

## 1. Why this guide exists

Phase A4-1 ("server-side data plane scaffold") landed because a future
B2B Elegoo deployment, a multi-user history/favorites feature, or a
multi-replica cloud rollout *might* need durable cross-restart state.
None of those are current product priorities — Lumina ships as an
**offline desktop tool**, both today and through the planned crowdfund
delivery (`.exe` / `.dmg` / `.AppImage` packages).

The env switch defaults to `LUMINA_BACKEND=memory` (the in-process
Python dicts that have always powered desktop runs).
`LUMINA_BACKEND=postgres` engages the real `PostgresSessionBackend`
+ `PostgresFileRegistryBackend` shipped in `fcf845d`. Both subclass
the in-memory baselines (so `isinstance(store, SessionStore)` checks
still pass), are SQLAlchemy 2.0 sync, lazy-imported (the default
desktop path never loads SQLAlchemy / psycopg), and gated by
`LUMINA_DATABASE_URL`.

This guide tells the future engineer (or AI agent) coming back to this
work three things:

1. **What's already in the repo** (so they don't re-build it) — A4-1 +
   A4-2 + A4-3 are all in; only operational glue (`start_dev.py`
   integration, deploy pipeline, observability dashboards) remains
2. **How to verify the live Postgres path works** (the 5-minute smoke
   test now exercises a real database via `LUMINA_INTEGRATION_DB_URL`)
3. **What's still missing for production deployment** (`start_dev.py`
   `--postgres` flag, deploy migration step, query/pool observability
   events, `/healthz` endpoint)

为什么有这份文档: A4-1/A4-2/A4-3 均已落地, 但 Postgres 路径默认 dormant.
任何回来上生产 / 排查 Postgres 模式问题的人, 第一站读本文档, 不要重新设计.

---

## 2. What was shipped

Three landings stack on top of `dev-refactor` to deliver the live
Postgres path. Each is documented separately so future engineers can
trace any single behaviour back to its origin.

### 2.1 PR #137 — A4-1 scaffold (rails + env switch)

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
| `tests/test_backend_factory_unit.py` | 188 | 16 contract tests for env dispatch (default / memory / postgres / case-insensitivity / whitespace / invalid value) + lossless-refactor guards (later grew to 18 tests / 224 lines in `fcf845d` to cover real Postgres dispatch) |

**Branch / commit references**:
- PR #137: `feat(a4-1): Postgres backend scaffold + LUMINA_BACKEND env switch`
- Bug fix on top: `4ddb01c` (`fix(a4-1): resolve Alembic script path` — corrected `script_location = .` → `%(here)s`)
- Merged into: `dev-refactor` @ `f666612`
- A4-1 wake-up doc: PR #138 (`docs/a4-1-scaffold-followup-guide`) — initial version of this guide

At this point `LUMINA_BACKEND=postgres` raised `NotImplementedError` —
the rails were laid but no train ran on them.

### 2.2 Commit `fcf845d` — A4-2 + A4-3 implementation (live)

A4-2 (`PostgresSessionBackend`) and A4-3 (`PostgresFileRegistryBackend`)
landed in a single commit pushed directly to `dev-refactor` (range
`9974e4f..fcf845d`, +1204/-38). Subclass-of-baseline strategy keeps
`isinstance(store, SessionStore)` and `isinstance(registry, FileRegistry)`
checks across all routers passing without further changes.

| File | Lines | Purpose |
|---|---:|---|
| `api/postgres_db.py` | 53 | `resolve_database_url` + `create_engine_from_env`; both raise actionable `RuntimeError` if `LUMINA_DATABASE_URL` is missing |
| `api/session_value_codec.py` | 134 | JSONB codec preserving `np.ndarray`, `set`, `tuple`, `bytes`, NaN/±Inf via typed envelopes; `pickle` fallback for arbitrary objects |
| `api/session_store_postgres.py` | 409 | `PostgresSessionBackend(SessionStore)` — drop-in subclass; explicit `Table` definitions over `sessions` + `session_temp_files`; transaction-per-method via `engine.begin()` |
| `api/file_registry_postgres.py` | 295 | `PostgresFileRegistryBackend(FileRegistry)` — drop-in subclass; two-phase cleanup (DB read → filesystem unlink outside transaction → DB delete) matching memory backend's pattern |
| `api/migrations/versions/002_add_file_owner_id.py` | 35 | Adds nullable `files.owner_id text` + index; backfills from `session_id::text` so arbitrary FileRegistry owner strings (e.g. `material-library:owner`) survive losslessly |
| `api/dependencies.py` | +46 (Δ) | Wires `LUMINA_BACKEND=postgres` to the new backends; lazy `from api.postgres_db import …` keeps SQLAlchemy out of the desktop import graph |
| `api/routers/converter/generate.py` | +1 | Adds explicit `store.put(sid, "svg_large_format_policy", policy)` after `session_data["svg_large_format_policy"] = policy` — the **only** in-place mutation site in the API tree (audited; no other callers rely on `get()` returning a live mutable dict) |
| `tests/test_backend_factory_unit.py` | +61 (Δ) | Grew 16→18 tests; adds postgres dispatch + missing-URL fast-fail coverage |
| `tests/test_session_value_codec_unit.py` | 71 | 4 unit tests covering nested preview-cache payloads, JSON shape contract, bytes + NaN/Inf, unpickleable failure mode |
| `tests/test_postgres_backend_integration_unit.py` | 137 | 3 integration tests gated by `LUMINA_INTEGRATION_DB_URL`; applies Alembic head, truncates A4 tables per test |

**Branch / commit reference**:
- Commit `fcf845d` (direct push): `Implement Postgres session and file backends`
- Wake trigger at landing: **not formally recorded in commit metadata**;
  implementation landed pre-emptively while the desktop posture remains
  in effect (memory `d2e13ccb-...`). The env switch staying opt-in means
  no production runs were affected — the code is ready but dormant.

**Review verdict** (Cascade): code-level PASS — 2627 regression tests
pass, log-quality gate passes, in-place mutation audit clean. Process
gap: bypassed PR review. Mitigation: this followup PR captures the
audit + adds the missing observability the original commit skipped.

### 2.3 PR #XXX — Followup: doc sync + Postgres path observability (this PR)

| File | Lines | Purpose |
|---|---:|---|
| `docs/server-mode-scaffold.md` | (Δ) | Sync status banner from "inert" → "live"; replace A4-2/A4-3 sketches with as-built deltas; add `files.owner_id` to schema reference; add Postgres backend smoke-test step |
| `api/session_store_postgres.py` | (Δ) | `_log = get_logger(__name__)` + ERROR `postgres_session_backend_init_failed` on engine creation failure + WARNING `postgres_session_backend_dispose_failed` on dispose failure (best-effort, doesn't re-raise) |
| `api/file_registry_postgres.py` | (Δ) | Symmetric: `postgres_file_registry_init_failed` ERROR + `postgres_file_registry_dispose_failed` WARNING |

No new INFO emit — the canonical `--mode fast` log governance budget
(14/30 INFO, 7/8 per endpoint) is unchanged. New ERROR/WARNING events
only fire on Postgres failure paths that the canonical desktop workflow
never exercises, so the gate stays green.

**Branch**: `docs/a4-2-followup-doc-and-logging`
**Base**: `dev-refactor` @ `fcf845d`

---

## 3. Decision framework — when to **activate** this in a deployment

A4-2/A4-3 implementations already exist on `dev-refactor`. The decision
that remains is whether a given deployment should set
`LUMINA_BACKEND=postgres` to use them. **Activate the Postgres path
only if** one of the following is true:

| Trigger | What it looks like |
|---|---|
| **Multi-user history / favorites feature** | Product side designs a feature where a session, project, or selection persists across user sessions and across app restarts |
| **Elegoo specifies multi-operator state sharing** | Concrete requirement from Elegoo for a single workstation where multiple operators log in / hand off jobs, with state visible across operators |
| **Multi-replica cloud deployment** | A real B2C SaaS plan emerges (currently cancelled per memory `d2e13ccb`); replicas need a shared backend |
| **Long-running test deployment outgrows memory** | The current bug-finding deployment starts losing state often enough that testers complain |

Do **NOT** flip `LUMINA_BACKEND=postgres` in any deployment just because:

- "It feels more enterprise" / "we should have a real database"
- "Desktop runs feel slow" — desktop performance has nothing to do with Postgres
- "I'm bored of the in-memory dict" — the dict is correct for single-user
- "The code is already there, why not use it" — opt-in is intentional;
  desktop runs without Postgres remain the supported configuration

何时在部署中启用 (不是开发, 开发已完): 必须有真实产品诉求
(history / Elegoo 多用户 / 多副本 / 测试部署真崩了). 不要因为"已经
写了"就打开, 桌面默认 `memory` 是唯一受支持的消费者配置.

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

### 4.4 Verify the env switch + codec

Fast contract tests run without a live database:

```bash
python -m pytest tests/test_backend_factory_unit.py tests/test_session_value_codec_unit.py -v
# → 20 passed, 2 skipped in 0.3s     (psycopg not installed)
# → 22 passed, 0 skipped in 0.3s     (psycopg installed; postgres dispatch tests run)
```

Expected: every non-skipped test passes. The 2 skips are the postgres
dispatch tests in `test_backend_factory_unit.py` that `importorskip`
on `psycopg`; running with `pip install psycopg[binary]` pulls them
in too.

If any fail after a future Python upgrade or SQLAlchemy bump, fix
before any further A4 work.

### 4.5 Verify the live Postgres backend (optional, requires Docker)

Integration tests against a real database are gated by
`LUMINA_INTEGRATION_DB_URL` so they never run in default CI. Run them
when you actually want to prove the Postgres backend round-trips:

```powershell
$env:LUMINA_INTEGRATION_DB_URL = "postgresql+psycopg://lumina:lumina@localhost:5432/lumina_dev"
python -m pytest tests/test_postgres_backend_integration_unit.py -v
# → 3 passed in ~2s
```

The fixture applies `alembic upgrade head` per session and truncates
`session_temp_files`, `files`, `sessions` (CASCADE) around each test.
The fixture does **not** roll back transactions — it commits + truncates,
so the database is left empty after the suite. **Never** point
`LUMINA_INTEGRATION_DB_URL` at a database with real data.

The 3 tests prove: (a) `PostgresSessionBackend` CRUD + temp-file
cleanup + close work, (b) `PostgresFileRegistryBackend` register →
resolve → cleanup works, (c) non-UUID owner strings (e.g.
`material-library:owner`) round-trip losslessly.

### 4.6 Tear down

```bash
docker compose down            # stop containers, keep volumes
docker compose down -v         # stop + delete volumes (full reset)
```

冒烟测试 6 步: 起容器 → 跑迁移 → 查表 → 跑快速契约 +
codec 测试 → (可选) 跑 Postgres 集成 → 收摊. 任意一步失败, 先修复
再考虑在部署中启用 Postgres 模式.

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
| `owner_id` | `text` NULL | **Added in migration `002`** — preserves arbitrary FileRegistry session ids (memory backend accepts any string; Postgres baseline `session_id` is UUID-only). Backfilled from `session_id::text` for existing rows; new rows get the original input string. Read via OR (`session_id = $uuid OR owner_id = $raw`) in `_owner_clause`. |

CHECK: `storage_kind IN ('local', 's3')`,
`lifecycle IN ('session_bound', 'ephemeral', 'shared_cache')`.
Indexes: `idx_files_session_id`, `idx_files_expires_at`,
`idx_files_owner_id` (added in migration `002`).

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

## 6. Implementation status — A4-2 / A4-3 (DONE) + remaining glue

### 6.1 Phase A4-2: `PostgresSessionBackend` — ✅ DONE in `fcf845d`

**Source**: `api/session_store_postgres.py` (409 lines).

**As-built shape**: subclass of `api.session_store.SessionStore` (not
the standalone `PostgresSessionStore` the original sketch proposed).
Inheriting the baseline class means every `isinstance(store, SessionStore)`
check that already exists across all routers keeps passing without
edits — the cleanest possible drop-in.

**Public method coverage** (all 14 methods from the original sketch):

| Method | Postgres realization |
|---|---|
| `create(session_id=None) -> str` | INSERT into `sessions`; on UUID collision retries with fresh UUID4; non-UUID input is hashed via `uuid5(_SESSION_ID_NAMESPACE, ...)` |
| `get(session_id) -> Optional[Dict]` | SELECT `data` (JSONB), decode via `decode_session_value`, renew lease via UPDATE; **returns a fresh decoded dict, not a live reference** |
| `put(session_id, key, value) -> None` | SELECT-decode-mutate-encode-UPDATE within one `engine.begin()` transaction; encodes via `encode_session_value` (handles `np.ndarray`, `set`, `tuple`, NaN/Inf, bytes, pickle fallback) |
| `register_temp_file(session_id, path) -> None` | INSERT into `session_temp_files` with `ON CONFLICT DO NOTHING` on `(session_id, path)` PK |
| `touch(session_id) -> float \| None` | UPDATE `last_seen_at` + `expires_at`; returns POSIX timestamp |
| `close(session_id) -> int` | Two-phase via `_cleanup_session(remove_session=True)`: filesystem unlink outside transaction, then state→`'retired'` |
| `close_except(session_id, keep_paths) -> int` | Same as above but skips paths in `keep_paths` |
| `cleanup_temp_files_except(...) -> int` | `_cleanup_session(remove_session=False)` |
| `cleanup_expired() -> list[str]` | SELECT WHERE `expires_at <= now()` + per-id `_cleanup_session` |
| `clear_all() -> int` | SELECT all non-retired ids + per-id `_cleanup_session` |
| `exists(session_id) -> bool` | EXISTS query + `state == 'active'` |
| `get_temp_file_paths(session_id) -> list[str]` | SELECT path FROM `session_temp_files` |
| `get_inactive_session_ids() -> list[str]` | SELECT id WHERE `state == 'closing'` |
| `get_registry_cleanup_candidate_session_ids() -> list[str]` | SELECT id WHERE `state IN ('closing','retired')` |

**Key engineering choices** (as-built deltas vs. the original sketch):

- **Subclass instead of new class**: makes `isinstance(...)` checks across
  all routers keep working without code changes
- **Explicit `Table` definitions over `autoload_with`**: deterministic
  import time, no schema introspection round-trip, cleaner errors when
  the migration head doesn't match
- **Transaction per public method** via `engine.begin()` context: same
  semantics as memory backend's `with self._lock`
- **JSONB codec** (`api/session_value_codec.py`): handles every type the
  in-memory `SessionStore` accepts. Pickle fallback for arbitrary objects
  preserves the "anything goes" memory contract; `set` / `tuple` /
  `ndarray` / `NaN` / `bytes` get typed envelopes for portability
- **`_session_uuid` helper**: maps non-UUID session ids (e.g. legacy
  callers) to deterministic `uuid5` so the Postgres `UUID PK` accepts
  any string the memory backend would have

**Wired into**: `api/dependencies.py::_build_session_store` —
`LUMINA_BACKEND=postgres` + `LUMINA_DATABASE_URL` set ⇒ returns the
Postgres backend; missing URL ⇒ `RuntimeError` with example URL.

**Test coverage**:

- `tests/test_backend_factory_unit.py` — 18 dispatch contract tests
  (16 baseline + 2 postgres-specific). 2 of the 18 use
  `pytest.importorskip("psycopg")` so they skip when the driver isn't
  installed (default development environment).
- `tests/test_session_value_codec_unit.py` — 4 unit tests covering
  nested preview-cache payloads, JSON shape contract, bytes + NaN/Inf,
  unpickleable failure mode.
- `tests/test_postgres_backend_integration_unit.py` — 3 integration
  tests gated by `LUMINA_INTEGRATION_DB_URL` (note: env var name
  changed from the sketch's `LUMINA_TEST_POSTGRES=1` to a URL-shaped
  env var carrying the connection string itself).

### 6.2 Phase A4-3: `PostgresFileRegistryBackend` — ✅ DONE in `fcf845d`

**Source**: `api/file_registry_postgres.py` (295 lines).

**As-built shape**: subclass of `api.file_registry.FileRegistry`.
Inherits `register_bytes` from the baseline (calls `self.register_path`
internally, which is overridden — works correctly via Python MRO).

**Public method coverage**:

| Method | Postgres realization |
|---|---|
| `register_path(session_id, path, filename=None, ttl_seconds=None) -> str` | INSERT `files` row; UUID-typed `session_id` if input parses, otherwise `NULL` (with `owner_id` carrying the raw string) |
| `register_bytes(...)` | Inherited from `FileRegistry`; uses overridden `register_path` |
| `resolve(file_id) -> Optional[Tuple[str, str]]` | SELECT row; if expired ⇒ filesystem unlink + DELETE row; if path missing ⇒ DELETE row; otherwise refresh expiry + return `(path, filename)` |
| `get_entry(file_id) -> dict \| None` | SELECT row + `_entry_from_row` (rebuilds memory-format dict) |
| `get_session_entries(session_id) -> dict[str, dict]` | SELECT WHERE `_owner_clause` (matches both UUID `session_id` and raw `owner_id`) |
| `cleanup_expired() -> int` | Two-phase: SELECT expired ids → filesystem unlink → DELETE rows |
| `cleanup_session(session_id) -> int` | Same pattern, expires `session_bound` rows on filesystem failure |
| `cleanup_session_except(session_id, keep_file_ids) -> int` | Same but skips `keep_file_ids` |
| `clear_all() -> int` | All ids + two-phase cleanup |

**Migration `002_add_file_owner_id.py`**: adds nullable `files.owner_id text`
plus index. The original A4-1 schema had `session_id UUID FK → sessions(id)`,
but the memory backend accepts any string as a session id (e.g.
`material-library:owner` is used by the material archive system).
Migration 002 backfills `owner_id = session_id::text` for existing rows
and lets new rows store the raw string in `owner_id` while leaving
`session_id` `NULL` if unparseable. `_owner_clause` queries both columns
via `OR`.

**Two-phase cleanup**: filesystem `os.remove` runs **outside** the
database transaction so a slow `unlink` (network mount, antivirus
quarantine) doesn't hold a write lock. This matches the memory
backend's locking pattern. On filesystem failure for a `session_bound`
row, the implementation marks the row `expires_at = now()` so the
periodic `cleanup_expired()` sweep retries.

### 6.3 `start_dev.py --postgres` integration — ⏳ PENDING

The original A4-3 sketch included a `start_dev.py --postgres` flag.
That work was **not** done in `fcf845d`. To activate Postgres mode in
local dev today, set the env vars manually:

```powershell
$env:LUMINA_BACKEND = "postgres"
$env:LUMINA_DATABASE_URL = "postgresql+psycopg://lumina:lumina@localhost:5432/lumina_dev"
python start_dev.py
```

A future PR can add the `--postgres` flag per the original sketch:

1. Verify `docker compose ps postgres` reports healthy (or start it)
2. Set `LUMINA_BACKEND=postgres` + `LUMINA_DATABASE_URL=...` for the
   spawned `api_server.py` process
3. Emit a `startup_backend_selected` INFO event with `backend=postgres`

Default `python start_dev.py` (no flag) keeps `LUMINA_BACKEND=memory`
= desktop behavior unchanged.

### 6.4 Other operational glue still pending

These weren't done in `fcf845d` and are not blockers for the dormant
state, but they're prerequisites for any deployment that actually
flips `LUMINA_BACKEND=postgres`:

- **Deploy pipeline migration step** (§7.1): bake `alembic upgrade head`
  into whichever process starts the API server in production. Without
  this, the first POST hits a missing schema.
- **`db_query_slow` WARNING / `db_pool_exhausted` ERROR** (§7.4): the
  `fcf845d` implementation doesn't emit these. Adding them needs an
  event listener on `engine.events.before_execute` or similar. Not
  urgent until production load monitoring matters.
- **`/healthz` endpoint** (§7.5): pings Postgres + Redis when in
  postgres mode; returns 200 unconditionally in memory mode. Cheap to
  add (one new router file, two SELECT 1 queries).
- **AGENTS.md governance row** for the new structured events
  (`postgres_*_init_failed` / `postgres_*_dispose_failed`): if a future
  release-gate refresh of `progress/log_audit_*_reviewer.json` runs in
  Postgres mode, the new events should be added to the appropriate
  whitelist; in memory mode the events never fire so the canonical
  `--mode fast` workflow is unaffected.

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
`request_id` / `session_id`. The Postgres backend adds **failure-path**
structured events (no INFO emit, so the canonical `--mode fast`
workflow's INFO budget is unchanged):

| Event | Level | Source | When it fires | Actionable fields |
|---|---|---|---|---|
| `postgres_session_backend_init_failed` | ERROR | `api/session_store_postgres.py::__init__` | `create_engine_from_env()` raises (missing URL, parse error, transient infra failure) | `error_type`, `error_message`, `dependency=postgres` |
| `postgres_session_backend_dispose_failed` | WARNING | `api/session_store_postgres.py::dispose` | `engine.dispose()` raises during shutdown | same fields |
| `postgres_file_registry_init_failed` | ERROR | `api/file_registry_postgres.py::__init__` | symmetric to session backend init | same fields |
| `postgres_file_registry_dispose_failed` | WARNING | `api/file_registry_postgres.py::dispose` | symmetric to session backend dispose | same fields |

Dispose failures are **best-effort** — logged at WARNING, not re-raised
so `shutdown` paths can keep tearing down other resources.

**Still pending** (out of scope for `fcf845d` and this followup PR;
tracked in §6.4):

- `db_query_slow` WARNING when a query exceeds a configurable threshold
  (event listener on `engine.events.before_execute`)
- `db_pool_exhausted` ERROR when `engine.pool.checkedout()` saturates
- Per-method `session_create_done` / `session_close_done` /
  `file_register_done` INFO events were sketched in the A4-1 plan but
  intentionally **not** emitted by the as-built code; the desktop
  default has zero session-CRUD INFO emits, so adding them would skew
  the canonical INFO budget.

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

- PR #137: A4-1 scaffold landing — `feat(a4-1): Postgres backend scaffold + LUMINA_BACKEND env switch`
- Commit `4ddb01c`: `fix(a4-1): resolve Alembic script path`
- PR #138: A4-1 wake-up doc landing — initial version of this guide (status was: scaffold inert)
- Commit `fcf845d`: A4-2 + A4-3 implementation, plus migration `002_add_file_owner_id.py` (direct push to `dev-refactor`)
- PR #XXX (this PR): `docs+log: a4-2 scaffold doc sync + Postgres path observability` — doc rewrite for current state + 4 failure-path structured events
- `progress/server-architecture.md` §4.4: original A4 design (note: §3.2 B2C SaaS plan and parts of §5 / §6 are **superseded** — the project posture is desktop-first per memory `d2e13ccb-5834-4484-b84e-e2eda326f083`)
- `docs/logging-guide.md`: structured logging conventions for any new code paths
- `progress/governance-roadmap.md`: log governance v2 closure (frozen baselines, `fast` / `full` workflow definitions)
- `tests/test_backend_factory_unit.py`: 18 dispatch contract tests pinning the env switch behavior (16 baseline + 2 postgres dispatch)
- `tests/test_session_value_codec_unit.py`: 4 codec round-trip tests
- `tests/test_postgres_backend_integration_unit.py`: 3 integration tests gated by `LUMINA_INTEGRATION_DB_URL`

---

## 10. Quick exit guide for AI agents

If you (a future AI agent) are dropped into this guide and asked to
"continue Phase A4" or "activate Postgres mode":

### Phase A4-2 / A4-3 are already DONE — do not re-implement

1. Read §2.2 — confirm `fcf845d` is still in the history (`git log
   --oneline | grep fcf845d`); the as-built source is
   `api/session_store_postgres.py` + `api/file_registry_postgres.py`.
2. Run §4.4 contract tests — they should pass on the current
   `dev-refactor` HEAD without a database; if they fail, fix that
   first.
3. **Do not** start a second A4-2 / A4-3 implementation. The work is
   merged. Re-implementing risks divergence from the existing test
   coverage.

### To activate Postgres mode in a deployment

4. Read §3 — confirm an actual activation trigger exists
   (multi-user history / Elegoo multi-operator / multi-replica /
   long-running test deployment). "The code is there" is **not** a
   trigger.
5. Implement §6.3 (`start_dev.py --postgres`) and §6.4 (deploy
   migration step, `/healthz`, query/pool observability) as separate
   PRs. None of these were done in `fcf845d`.
6. Run §4.5 integration tests against a throwaway Postgres to confirm
   the live path round-trips.
7. Update memory `d2e13ccb-5834-4484-b84e-e2eda326f083` if the project
   posture has changed (e.g., a real SaaS plan emerged); the current
   memory says desktop-first.

If the activation trigger is **not** present, do **not** flip
`LUMINA_BACKEND=postgres` in any production deployment. Tell the user
the trigger is missing and ask for explicit confirmation.

未来 AI 的快速指南: A4-2/A4-3 已完, 不要重复实现. 要在部署中启用 Postgres,
必须 有 真触发条件 (§3), 且 补齐 §6.3 (start_dev.py) + §6.4 (部署迁移 / healthz /
查询连接池可观测性). 没触发 → 别打开.
