# Server Architecture — Design Document (Twin-Track)

> **Status**: Draft v0. Phase A current-state diagnosis + A4-A6 detailed plan + Phase B/C/D outline. Each later phase will get its own self-contained design doc when started.
> **Author**: Cascade (planning, post-PR-#130).
> **Trigger**: Recent A1+A2 audit (PRs #126/#129/#130) revealed that single-process FastAPI + in-memory `SessionStore`/`FileRegistry` cannot meet the twin-track production posture (B2B for Elegoo single-tenant + B2C crowdfunded SaaS). The cross-session GLB overwrite leak fixed by PR #130 is one symptom; restart-loses-state and worker-pool process-affinity are the other two we have already hit.
> **Scope**: `api/`, `api_server.py`, `start_dev.py`, storage/persistence layer, worker orchestration, deployment topology. Pipeline internals (`core/pipeline/S01-S12`) are out of scope here — see `progress/pipeline-refactor-design.md`.
> **Constraint** (hard): Lossless migration per `AGENTS.md` L48-51. Each Phase A sub-step must keep all current behavior bit-exact for existing color modes / endpoints; tests written first, then implementation, then verification.
> **Companion docs**:
> - `progress/pipeline-refactor-design.md` — pipeline / staging / color-mode taxonomy
> - `progress/governance-roadmap.md` — logging governance program (now at log-governance-v2)
> - `progress/glb-internals-audit-2026-04-30.md` — A2 audit + LEAK report (PR #129; LEAK fixed by PR #130)
> - `progress/round-17-onwards-master-plan.md` — log governance round structure
> - `AGENTS.md` — repository engineering rules

---

## 1. Mission & Scope

### 1.1 The actual pain point

Lumina Studio currently runs as a single uvicorn process (`api_server.py:18-20`) with all session state, file registry, and worker pool living in that one process's memory. Three symptoms accumulate as we approach a real production posture:

1. **Restart loses every active session.** `SessionStore` is `Dict[str, Dict[str, Any]]` in-memory (`api/session_store.py:18-24`); a deploy or crash drops all WIP previews, calibration boards, and LUTs.
2. **Cross-process / multi-instance becomes impossible.** `FileRegistry` is per-process `dict` (`api/file_registry.py:16-19`); a second uvicorn replica cannot serve `/api/files/{glb_id}` URLs minted by the first.
3. **Worker pool affinity ties heavy CPU work to one box.** `WorkerPoolManager` is `ProcessPoolExecutor(max_workers=min(cpu_count, 4))` (`api/worker_pool.py:78-90`); we cannot scale CPU-bound stages (S04 LUT solve, S08 vector engine, S11 GLB) horizontally.

These three are tolerable for a developer machine and for an Elegoo-internal demo. They are blockers for either production track.

### 1.2 Twin-track production posture

The product roadmap, agreed upon with the user, has two simultaneous deployment forms:

| Track | Audience | Topology | Persistence | Scaling | Trust model |
|---|---|---|---|---|---|
| **B2B for Elegoo** | Elegoo internal / partner studios | Single-tenant, on-premises or single-VM | Local Postgres + Redis + filesystem (or NAS) | Vertical only | Trusted operator; no per-user authn beyond optional basic-auth |
| **B2C 众筹版** | Backers + post-launch general public | Multi-tenant SaaS, cloud-hosted | Managed Postgres + Redis + object storage (S3-compatible) | Horizontal; pool of stateless API replicas + worker fleet | Untrusted users; full session isolation, rate limiting, billing tier enforcement |

Both tracks **share the same core code path** — the same `core/`, the same `api/` routers, the same pipeline. The only differences are configuration (`.env`), provisioning (single docker-compose vs cloud), and a thin tenancy/auth layer applied at the API boundary in track C onwards. **Phase A makes this sharing possible by removing the in-process state assumptions.**

### 1.3 What this document is

- A diagnosis of the current single-process architecture (Section 2).
- A detailed plan for Phase A4-A6 (data plane productionization, Section 4).
- An outline for Phase B/C/D (Sections 5-7).
- Migration safety guarantees and open questions (Sections 8-9).

### 1.4 What this document is NOT

- It is **not** a final spec for Phase B/C/D — those get their own design docs when started.
- It does **not** propose any user-facing feature change. End state must remain bit-exact through Phase A.
- It does **not** redesign the pipeline internals; those live in `progress/pipeline-refactor-design.md`.
- It does **not** change persistent file formats (LUT `.npz`/`.json`, 3MF, calibration board files, settings).
- It does **not** introduce new runtime languages — backend stays Python; frontend stays React + TypeScript + Vite.

---

## 2. Current State (as of 2026-04-30 `dev-refactor` `2bb72d1`)

### 2.1 Process topology

```
Developer / Demo:
+----------------------------------------------+
|  uvicorn (api_server.py)                     |
|  +----------------------------------------+  |
|  |  FastAPI app (api.app)                 |  |
|  |  - 9 router families, ~50 mutating EPs |  |
|  |  - SessionStore (threading.Lock)       |  |
|  |  - FileRegistry (threading.Lock)       |  |
|  |  - WorkerPoolManager                   |  |
|  |    +- ProcessPoolExecutor(<=4)         |  |
|  |  - structured_logging                  |  |
|  +----------------------------------------+  |
|  Local fs: OUTPUT_DIR, TEMP_DIR, MATERIALS,  |
|             logs/lumina_<ts>.log             |
+----------------------------------------------+
              ^
              | HTTP :8000
              v
       +---------------+
       |  Vite dev     |
       |  (frontend)   |
       |  :5174        |
       +---------------+
```

Single uvicorn process. Single OS user. Local filesystem. No external services.

### 2.2 In-process state — `SessionStore`

`api/session_store.py:8-24`:

- `_store: Dict[str, Dict[str, Any]]` — every session's data, keyed by UUID.
- `_timestamps: Dict[str, float]` — lease expiry per session (default 1800s).
- `_temp_files: Dict[str, list[str]]` — paths registered for cleanup on close.
- `_closing_sessions: set[str]` — soft-deleted but still being cleaned up.
- `_retired_sessions: Dict[str, float]` — tombstones to prevent UUID re-use.
- `_lock: threading.Lock` — serializes all reads/writes.

**Implications**:
- Restart wipes everything; users re-upload, re-extract, re-preview from scratch.
- Two replicas would each have their own `SessionStore`; sticky session routing or shared-state replacement is mandatory before scaling out.
- The lock is process-local; replacing it with Redis transactions does not change the public API of `SessionStore` — only the backend.

### 2.3 In-process state — `FileRegistry`

`api/file_registry.py:8-20`:

- `_registry: dict[str, dict]` — `file_id` (UUID) → `{path, filename, session_id, created_at, expires_at, lifecycle, delete_on_cleanup}`.
- `_lock: threading.Lock`.
- File bytes live on the local filesystem under `OUTPUT_DIR` (config-defined) for generated artifacts and `TEMP_DIR` for upload staging.

The registry maps URL-safe IDs to on-disk paths, which is what enables `/api/files/{file_id}` to serve generated GLBs/3MFs/PNGs without exposing path traversal vulnerabilities. **Lifecycle policy** is enforced by `cleanup_session()` and `cleanup_expired()` (`file_registry.py:129-148`). PR #130 closed the cross-session collision class for segmented GLB writes; the residual class (cross-session collisions on `OUTPUT_DIR/empty_bed_*.glb` and other deterministic-named caches) is recorded in the audit but lower-impact and addressed in Phase A6 below.

**Implications**:
- A second replica cannot resolve IDs minted by the first (registry is in memory).
- `OUTPUT_DIR`/`TEMP_DIR` on a single VM disk caps total throughput at that VM's IOPS and total tenant data at that disk's free space.
- Object storage migration (Phase A6) replaces `path` with `object_key`; resolve becomes a presigned-URL mint instead of a local-fs `os.path.exists` check.

### 2.4 Worker pool

`api/worker_pool.py:61-159`:

- `ProcessPoolExecutor(max_workers=min(cpu_count, 4), initializer=_worker_init)`.
- Tasks are submitted via `asyncio.run_in_executor`; futures are awaited with `asyncio.wait_for` for timeouts.
- Parent-side contextvars (`request_id`, `session_id`) are captured pre-submit and replayed inside the worker so worker logs correlate with HTTP requests.
- PR #126 (A1) fixes a double-recycle hook bug here.

**Implications**:
- Workers and the API server share one OS process tree; CPU pressure on workers starves the event loop.
- The pool cannot span machines; horizontal scaling of CPU-bound stages requires a real broker.
- The `multiprocessing` ProcessPool serializes arguments via pickle; this constrains worker entry points to top-level callables and small picklable arg lists (`AGENTS.md` Engineering Rules).

### 2.5 Filesystem layout

```
<repo>/
  OUTPUT_DIR/        (configured in config.py; per-deployment)
    segmented_<sid>_<uuid>.glb           # PR #130: session-scoped
    empty_bed_<bedW>x<bedH>.glb          # deterministic cache (still shared)
    Lumina_<base>_<mode>_<color>_<ts>.3mf
    ...
  TEMP_DIR/          (upload staging, ephemeral)
    upload_<sid>_<uuid>.png
    ...
  MATERIALS/         (read-only material catalog)
  printer_profiles/  (read-only printer templates)
  logs/
    lumina_<ts>.log  (JSON Lines; current request)
```

`OUTPUT_DIR` is shared across all sessions; this was the LEAK locus PR #130 closed for `segmented_*.glb`. `empty_bed_*.glb` is a memo-style cache where deterministic naming is intentional and safe (bed dimensions are not user-specific). Other caches (`realtime_preview.glb`, `last_preview.png`) followed the same anti-pattern as `segmented_preview.glb` and need the same audit before Phase A6.

### 2.6 Logging / observability

Already production-quality post log-governance-v2 (`progress/governance-roadmap.md`):

- Structured logging via `api.structured_logging.get_logger` + `extra={"event": ...}`.
- JSON Lines file handler; human-readable console handler.
- Per-workflow INFO budget enforced by `scripts/log_quality_check.py` (14/30 fast, 29/30 full, 7/8 per-endpoint).
- Worker subprocesses inherit `LUMINA_LOG_PATH` and `LUMINA_LOG_INIT_BY_PARENT=1`.

This is the **only** part of the architecture that already meets twin-track production needs. It does not need migration.

### 2.7 Known limits at-a-glance

| Limit | Severity | Track impact | Phase fix |
|---|---|---|---|
| Restart loses sessions | High | B2C (every deploy = customer rage); B2B (operators tolerate but lose work) | A4 |
| Single-process worker pool | High | B2C (cannot meet SLO at scale); B2B (acceptable on workstation-class VM) | A5 |
| Local-fs file registry | High | B2C (multi-replica impossible); B2B (single-VM acceptable) | A6 |
| Cross-session output collisions | Medium | Both | A2 ✓ (PR #130 closes segmented; A6 closes the rest) |
| In-process SessionStore lock contention | Low | B2C only at high QPS | A4 (Redis swap removes lock) |
| No tenant authn/billing | High | B2C only | Phase C |
| No vendor-customizable branding/profiles | Medium | B2B only | Phase B |

---

## 3. Target State — Twin-Track Posture

### 3.1 B2B for Elegoo (self-hosted single-tenant)

```
Elegoo / Partner studio:
+-----------------------------------------------+
|  docker compose up                            |
|  +-----------+  +-----------+  +-----------+  |
|  | API       |  | Worker    |  | Postgres  |  |
|  | (uvicorn) |  | (arq)     |  | + Redis   |  |
|  +-----------+  +-----------+  +-----------+  |
|       |              |              |        |
|       +-- shared volume: OUTPUT_DIR --+      |
+-----------------------------------------------+
```

- Single docker-compose file, ~5 services. Operator runs `docker compose up -d`.
- Postgres holds session state and file registry; Redis holds the arq queue + rate-limit counters.
- `OUTPUT_DIR` is a single shared volume; object storage is **opt-in** (default = local volume).
- No multi-tenancy; one operator = one logical tenant. Optional basic-auth or company SSO at the reverse proxy.
- Branding and printer profiles configurable via `.env` and a `printer_profiles/` mount.

### 3.2 B2C 众筹版 (multi-tenant SaaS)

```
Cloud:
+--------------------+    +--------------------+
| Reverse proxy      |    | Object storage     |
| (Caddy / Cloudflare|    | (S3 / R2 / Tigris) |
|  + Lumina auth)    |    +--------------------+
+--------------------+              ^
        | x-tenant-id               |
        v                           |
+--------------------+    +-------------------+
| API replicas       |    | Worker fleet      |
| (uvicorn x N)      |--->| (arq workers x M) |
+--------------------+    +-------------------+
        |                           |
        +-> Managed Postgres <------+
        +-> Managed Redis <---------+
        +-> Managed object store <--+
```

- API replicas are stateless; any one can serve any request.
- Workers are stateless except for arq job context.
- Tenant isolation enforced at the database row level + object-key prefix (`tenant_<id>/sessions/<sid>/...`).
- Rate limiting per tenant via Redis sliding window.
- Billing tier checked at endpoint entry (per-tenant feature flags + per-month quotas).
- Domain: `studio.lumina-layers.com` (or similar); custom domains in a later phase.

### 3.3 Shared core (data plane)

The data plane that powers both tracks is identical and is what Phase A delivers:

| Concern | Component | Implementation |
|---|---|---|
| Session state | `SessionStoreBackend` interface | Postgres table `sessions(id, data jsonb, created_at, expires_at)` |
| File registry | `FileRegistryBackend` interface | Postgres table `files(id, key, filename, session_id, ...)` + S3-compatible blob store |
| Task queue | arq | Redis-backed; tasks reference session_id + file_id |
| Caches (preview, LUT) | Redis hash per session | Falls back to Postgres on Redis miss |
| Logs | Already structured | JSON Lines → log shipper (Loki / CloudWatch / Datadog) |

**The Python interface stays stable**: `api/dependencies.py` continues to inject `get_session_store()` / `get_file_registry()` / `get_worker_pool()` / etc. The implementations swap based on `LUMINA_BACKEND=memory|postgres|aws` configuration.

---

## 4. Phase A — Data Plane Productionization

Phase A is the prerequisite for both tracks. It has 6 numbered sub-steps; A1+A2 are done as PRs, A3 is this document, A4-A6 are the remaining work.

### 4.1 A1 ✓ — Worker pool double-recycle fix (PR #126)

Fixed a bug where the worker recycle hook fired twice per task in certain failure modes, leaving stale subprocesses pinned to the pool. **Status**: PR #126 (draft on `dev-refactor`).

### 4.2 A2 ✓ — GLB output_path session scoping (PRs #129/#130)

- PR #129 (audit): documents the segmented/realtime GLB internals; surfaces the LEAK ("3 of 4 callers pass no `output_path`, fall back to a process-global path").
- PR #130 (fix): makes `output_path` a required argument on both `generate_segmented_glb` and `generate_realtime_glb`; introduces `core.naming.generate_segmented_glb_filename(session_id)` for collision-free per-session paths.

**Status**: Both PRs draft on `dev-refactor`. PR #130 supersedes the LEAK section of PR #129.

### 4.3 A3 ◐ — This document

Establishes the architecture vocabulary and Phase A4-A6 detailed plan so the next implementation rounds can start without re-arguing scope. **Status**: Draft v0; user review pending.

### 4.4 A4 — Postgres + Redis docker-compose

**Goal**: Replace `SessionStore` + `FileRegistry` in-memory dicts with Postgres-backed implementations, gated by a feature flag so the in-memory backend remains the default for fast local dev and the existing test suite.

**Concrete deliverables**:

1. **`docker-compose.yml`** at repo root:
   ```yaml
   services:
     postgres: image=postgres:16, port=5432, volume=postgres_data
     redis:    image=redis:7,    port=6379
     # API + worker remain on host for now; only data plane in containers
   ```
   - `start_dev.py` is updated to detect `LUMINA_BACKEND=postgres` and run `docker compose up postgres redis -d` before launching uvicorn.
   - Default stays `LUMINA_BACKEND=memory` — no behavior change for current dev workflow or pytest runs.

2. **Schema migrations** under `api/migrations/` (Alembic or plain `.sql` — TBD; lean toward Alembic for parity with FastAPI ecosystem):
   ```sql
   CREATE TABLE sessions (
       id            uuid PRIMARY KEY,
       data          jsonb NOT NULL DEFAULT '{}',
       created_at    timestamptz NOT NULL DEFAULT now(),
       last_seen_at  timestamptz NOT NULL DEFAULT now(),
       expires_at    timestamptz NOT NULL,
       state         text NOT NULL DEFAULT 'active'  -- active|closing|retired
   );
   CREATE INDEX idx_sessions_expires_at ON sessions(expires_at);

   CREATE TABLE files (
       id              uuid PRIMARY KEY,
       session_id      uuid REFERENCES sessions(id) ON DELETE CASCADE,
       storage_kind    text NOT NULL,                 -- local|s3
       storage_key     text NOT NULL,                 -- path or object key
       filename        text NOT NULL,
       lifecycle       text NOT NULL DEFAULT 'session_bound',
       created_at      timestamptz NOT NULL DEFAULT now(),
       expires_at      timestamptz
   );
   CREATE INDEX idx_files_session_id ON files(session_id);
   CREATE INDEX idx_files_expires_at ON files(expires_at);

   CREATE TABLE session_temp_files (
       session_id  uuid REFERENCES sessions(id) ON DELETE CASCADE,
       path        text NOT NULL,
       PRIMARY KEY (session_id, path)
   );
   ```

3. **Backend abstraction** — extract a thin interface:
   ```python
   # api/session_store_backend.py
   class SessionStoreBackend(Protocol):
       def create(self, session_id: str | None) -> str: ...
       def get(self, sid: str) -> Optional[dict]: ...
       def put(self, sid: str, key: str, value: Any) -> None: ...
       def close(self, sid: str) -> int: ...
       # ... all current public methods of SessionStore
   ```
   - Existing `SessionStore` becomes `MemoryBackend` (rename file to `api/session_store_memory.py`).
   - New `PostgresBackend` in `api/session_store_postgres.py`.
   - `api/dependencies.py::get_session_store()` selects backend by env.
   - Public callsites (every router) keep using `SessionStore` as the abstract type — **no router code changes required**.

4. **Test strategy**:
   - All existing `tests/` keep running against `MemoryBackend` (default).
   - New `tests/integration/test_session_store_postgres.py` and `test_file_registry_postgres.py` running against a docker-managed Postgres (skipped if `LUMINA_INTEGRATION_DB_URL` not set).
   - CI matrix gets a new "integration" job that brings up docker-compose and runs only the integration tier; the existing fast `pytest tests/` job stays Postgres-free.

5. **Rollout switch**: `.env.local` flag `LUMINA_BACKEND=postgres` flips both stores together (sessions and files; consistent or none). Per-store flags add complexity without clear benefit at this stage.

6. **Out of scope for A4**: Object storage (kept on local fs even with Postgres backend; A6 swaps later); arq (workers stay in-process; A5 swaps later); auth/tenancy (Phase C).

**Acceptance**:
- All 2413 currently-passing pytest tests still pass with `LUMINA_BACKEND=memory`.
- New integration tests pass with `LUMINA_BACKEND=postgres` against the docker-compose stack.
- Manual smoke (`scripts/run_smoke_tests.py` extended) exercises a full preview + replace + generate against Postgres-backed session/registry.
- `log_quality_check --mode fast` and `--mode full` continue to PASS.

**Estimated effort**: 3-4 PRs (~1 PR for scaffold + memory rename, 1 PR for Postgres session backend, 1 PR for Postgres file registry backend, 1 PR for docker-compose + start_dev integration + integration test suite).

### 4.5 A5 — arq migration

**Goal**: Replace the in-process `WorkerPoolManager` with arq workers that pull from a Redis queue. Same API surface (`worker.submit_async(fn, *args)`); different transport.

**Why arq**:
- Native `asyncio` (matches FastAPI). No `asyncio.run_in_executor` adapter needed.
- Redis-only dependency — already present from A4.
- Mature, lightweight (~1.5k LOC), small dependency surface.
- Good DX: `arq.worker` CLI, automatic job retries, deferred jobs, cron-like jobs.

**Alternatives considered**:
- **Celery**: more mature but heavier, sync-first, RabbitMQ pulled in.
- **Dramatiq**: solid but smaller community.
- **RQ**: simple but sync-first; Python 3.11 asyncio integration awkward.
- **Custom Redis Streams**: too much glue for too little payoff.

**Concrete deliverables**:

1. **Worker entry-point reorg** (`AGENTS.md` already mandates top-level picklable workers; arq tightens this further):
   - Each existing worker function (e.g. `api/workers/converter_workers.py::worker_generate_preview`) gets an arq-compatible registration in `api/workers/arq_app.py`.
   - Pickle-via-multiprocessing is replaced by JSON serialization through Redis (arq default); large payloads (numpy arrays, image bytes) **must** go through file paths or object keys, not arguments.

2. **Backend abstraction** parallels A4:
   ```python
   # api/worker_pool_backend.py
   class WorkerPoolBackend(Protocol):
       async def submit_async(self, fn: Callable, *args, timeout: float | None) -> Any: ...
       def shutdown(self, wait: bool) -> None: ...
   ```
   - `LocalProcessPool` (renamed `WorkerPoolManager`) keeps the current behavior for `LUMINA_BACKEND=memory`.
   - `ArqPool` calls `arq.connections.ArqRedis.enqueue_job(...)` and awaits the result.
   - `api/dependencies.py::get_worker_pool()` selects backend by env.

3. **Job correlation**: arq supports `job_id`; we use the existing `request_id` so worker-emitted logs continue to correlate via the structured-logging contextvar replay.

4. **Test strategy**:
   - Existing tests keep running against `LocalProcessPool` (default).
   - New `tests/integration/test_arq_worker.py` runs against a docker-managed Redis with a tiny in-test arq worker subprocess (skipped if Redis URL missing).
   - The worker contract (`AGENTS.md`: top-level, picklable, scalars + paths only) is **already enforced** in current code; no per-worker rewrites expected.

5. **Out of scope for A5**: Multi-host worker fleet (single arq worker process is enough for B2B; B2C scaling lands in Phase C).

**Acceptance**:
- All current pytest tests pass against `LocalProcessPool` default.
- Integration tests pass against arq backend.
- `scripts/profile_stage3.py` shows comparable wall-clock numbers (within 10%) between the two backends; the goal is not perf parity (arq adds Redis hop), it is the option to scale.

**Estimated effort**: 2-3 PRs (1 for backend abstraction + LocalProcessPool rename, 1 for ArqPool implementation + integration tests, 1 for tuning + docs).

### 4.6 A6 — Object storage selection + cutover

**Goal**: Replace local-fs `OUTPUT_DIR`/`TEMP_DIR` writes with an S3-compatible object store. Local-fs remains the default for B2B single-VM operators; cloud blob store is the default for B2C.

**Selection criteria**:

| Provider | Pros | Cons | Best fit |
|---|---|---|---|
| **AWS S3** | De-facto standard; richest tooling | Egress cost; vendor-specific quirks at scale | B2C if AWS-only |
| **Cloudflare R2** | Zero egress; cheapest at our expected volume | Slightly behind S3 on advanced features | B2C primary |
| **Tigris** | Globally replicated by default | Smaller community | B2C secondary |
| **MinIO** (self-hosted) | OSS; API-compatible | Operator burden | B2B opt-in |
| **Local fs (default)** | Zero ops | No replication, no scale-out | B2B default; dev default |

**Tentative pick**: **R2 for B2C primary**, **local-fs for B2B**. MinIO offered as an opt-in alt for B2B operators who already run object storage.

**Concrete deliverables**:

1. **Storage abstraction** — extract a thin interface:
   ```python
   # api/storage.py
   class StorageBackend(Protocol):
       def put(self, key: str, data: bytes | BinaryIO, content_type: str) -> str: ...
       def get(self, key: str) -> Optional[bytes]: ...
       def url(self, key: str, ttl: int) -> str: ...   # presigned for S3; static for local-fs
       def delete(self, key: str) -> bool: ...
       def exists(self, key: str) -> bool: ...
   ```
   - `LocalFsStorage` writes to `OUTPUT_DIR` (current behavior) and serves via `/api/files/{file_id}` resolution.
   - `S3Storage` uses `aiobotocore` (or `boto3` in a thread executor; aiobotocore is preferred for parity with FastAPI's async style).

2. **`FileRegistry` becomes pure metadata**:
   - `storage_kind` column from A4 distinguishes `local` vs `s3`.
   - `storage_key` is either an absolute path (local) or an object key (s3).
   - `/api/files/{file_id}` either streams from local fs (current) or returns a 302 redirect to an R2/S3 presigned URL (new); the choice is per-file, set at registration time.

3. **GLB / 3MF export sites** continue to use `core.naming.generate_*_filename()` for **keys**; there's no semantic change, just a swap of `os.path.join(OUTPUT_DIR, ...)` for `storage.put(key=..., data=...)`. PR #130's session-scoped naming already enforces collision-free keys.

4. **Residual cross-session caches** (Section 2.5) get audited and either:
   - Made session-scoped (same fix as PR #130) if user-specific, or
   - Confirmed deterministic + safe (e.g. `empty_bed_400x400.glb` is a function of bed dimensions only) and kept as a shared cache with explicit `lifecycle='shared_cache'` in the registry.

5. **Migration safety**: A flag `LUMINA_STORAGE=local|s3` flips per deployment. Existing `OUTPUT_DIR` files remain readable in `local` mode; `s3` mode starts fresh (no historical data; we have no production users yet).

6. **Out of scope for A6**: Cross-region replication (B2C scale concern; later); CDN in front of object store (Phase C); per-tenant bucket isolation (Phase C; uses object-key prefix `tenant_<id>/...` not bucket-per-tenant).

**Acceptance**:
- All current pytest tests pass against `LUMINA_STORAGE=local`.
- Integration tests pass against MinIO (CI-friendly) and a real R2 bucket (manual smoke).
- 3D preview / generate endpoints work end-to-end with `LUMINA_BACKEND=postgres` + `LUMINA_STORAGE=s3`.

**Estimated effort**: 2 PRs (1 for `StorageBackend` extraction + LocalFsStorage parity, 1 for S3Storage + integration tests + R2 manual smoke).

### 4.7 Phase A summary

After A6, both tracks share the same Python codebase, the same pytest suite (the unit/property layer runs against memory backends; the integration layer runs against Postgres + Redis + MinIO/R2), and the same logging governance. The only deployment-specific code is `.env` config and docker-compose / cloud manifests.

```
End of Phase A → ready to start Phase B (B2B branding) or Phase C (B2C tenancy) in parallel.
```

---

## 5. Phase B — B2B for Elegoo (outline)

**Goal**: Package Phase-A-complete Lumina Studio as a turnkey product for Elegoo / partner studios.

**Outline (TBD; expand into own design doc when started)**:
1. **B1**: Branding hooks — replaceable logo, color theme tokens, default printer profile, default LUT bundle, default copy strings (e.g. "Powered by Lumina" footer).
2. **B2**: Operator packaging — single `docker compose up`; healthcheck endpoint; backup/restore script for Postgres + `OUTPUT_DIR`.
3. **B3**: Optional basic-auth at reverse proxy + audit log for operator actions.
4. **B4**: Custom-printer integration kit — schema for `printer_profiles/` extensions, slicer adapter plugin loading.
5. **B5**: Documentation — Operator Guide (install, backup, upgrade), Troubleshooting Runbook, Tier-1 support handoff.

**Dependencies**: Phase A (A4-A6) complete. Phase B does **not** depend on Phase C (B2C SaaS is a separate codebase deployment, not a fork).

**Estimated effort**: 5-8 PRs.

---

## 6. Phase C — B2C 众筹版 (outline)

**Goal**: Multi-tenant SaaS, gated on a successful crowdfunding campaign.

**Outline (TBD; expand into own design doc when started)**:
1. **C1**: Tenancy model — tenant_id contextvar at request boundary; row-level security in Postgres (`policy USING (tenant_id = current_setting('app.tenant_id')::uuid)`); object-key prefix.
2. **C2**: Authn / authz — passwordless email + OAuth (Google, GitHub); session JWT; per-tier feature flags loaded from Postgres.
3. **C3**: Billing — Stripe integration; per-tenant Postgres `subscriptions` table; usage metering on per-month preview / generate counts; quota enforcement at endpoint entry.
4. **C4**: Rate limiting — per-tenant sliding-window via Redis; per-IP defense for unauthenticated endpoints.
5. **C5**: Multi-replica deployment — k8s manifests OR docker-swarm (TBD); Cloudflare or AWS ALB in front; managed Postgres + managed Redis + R2.
6. **C6**: Privacy / GDPR — data retention policy; tenant data export endpoint; tenant data delete endpoint.
7. **C7**: Onboarding flow — frontend account creation, email verification, first-print walkthrough.

**Dependencies**: Phase A complete; Phase B can ship in parallel without blocking.

**Estimated effort**: 12-20 PRs (largest phase; spans frontend + backend).

---

## 7. Phase D — Open source after crowdfunding milestone (outline)

**Goal**: Release the codebase under an OSS license once the crowdfunding goal is met.

**Outline (TBD; expand into own design doc when started)**:
1. **D1**: License selection — likely **AGPL-3.0** to keep the SaaS moat (B2C track) while enabling community contribution; alternative is MPL-2.0 if AGPL deters contributors.
2. **D2**: CLA / DCO setup for external contributors.
3. **D3**: Public README, CONTRIBUTING.md, security policy, code of conduct.
4. **D4**: CI infrastructure that runs on the public GitHub fork.
5. **D5**: Issue triage rotation; community PR review SLA.
6. **D6**: Marketing — release post, demo video, Hacker News / r/3Dprinting submission.

**Dependencies**: Crowdfunding milestone achieved (Phase C launch confirms this); Phase A and Phase B both shipped.

**Estimated effort**: 3-5 PRs (mostly docs + CI; the code is already there).

---

## 8. Migration Safety Guarantees

These are non-negotiable per `AGENTS.md` "Lossless Refactoring":

1. **Public APIs unchanged through Phase A.** Every router, every endpoint, every response shape stays bit-exact. The only acceptable observable change is *latency* (Postgres + Redis add tens of ms per request; documented in the A4 PR body).
2. **Default backend stays `memory`.** Every contributor's `pytest tests/` continues to run against in-memory `SessionStore` / `FileRegistry` / `WorkerPool` without docker. Integration tests are explicitly opt-in via env flags.
3. **Test discipline**: each Phase A sub-step starts with regression tests against the current behavior (memory backend), THEN swaps the implementation, THEN adds new tests for the new backend. Tests are **never** weakened to make the new backend pass.
4. **Logging governance preserved.** Every Phase A PR runs `python scripts/log_quality_check.py --mode fast` (and `--mode full` before release). INFO budget thresholds (14/30 fast, 29/30 full, 7/8 per-endpoint) cannot be raised; events that newly fire from backend swaps must either reuse existing canonical events or land in a structured-events whitelist with governance review.
5. **Frontend is not blocked.** Phase A is purely backend; the React app continues to run unchanged against either backend. Phase B (branding) and Phase C (tenancy) introduce frontend changes; those are scoped to their own design docs.
6. **Encoding rules respected** (`AGENTS.md` "Encoding & Text Safety"): all new design docs and migration scripts are UTF-8; bilingual docstrings preserved; mojibake treated as data corruption.

---

## 9. Open Questions

These are deferred for explicit user answer before the corresponding phase starts:

| ID | Question | Blocks | Asked when |
|---|---|---|---|
| Q1 | Alembic vs raw SQL migrations? | A4 implementation kickoff | Before A4 PR #1 |
| Q2 | Single Postgres database for both tracks, or dedicated databases? | A4 final config | Before A4 PR #1 |
| Q3 | Is `LUMINA_BACKEND` granular per-store or global? (Section 4.4 leans global) | A4 backend abstraction | Resolved here: global. |
| Q4 | aiobotocore vs boto3-in-executor for S3? (Section 4.6 leans aiobotocore) | A6 implementation | Before A6 PR #1 |
| Q5 | R2 vs Tigris for B2C primary object store? | A6 production cutover | After A6 integration tests |
| Q6 | AGPL vs MPL for OSS license? | Phase D launch | After Phase C crowdfunding milestone confirmed |
| Q7 | Does B2B need built-in operator UI for backup/restore, or is CLI sufficient? | Phase B B2 | Before Phase B kickoff |
| Q8 | Stripe vs Paddle vs Lemon Squeezy for B2C billing? | Phase C C3 | Before Phase C kickoff |
| Q9 | k8s vs docker-swarm vs single VPS for B2C deployment? | Phase C C5 | Before Phase C kickoff |
| Q10 | Cross-session cache audit (Section 4.6 step 4): which deterministic-named caches stay shared? | A6 implementation | During A6 PR #1 |

---

## 10. References

### Internal docs
- `AGENTS.md` — engineering rules, especially Lossless Refactoring (L48-51), Logging Governance, Tests, Encoding & Text Safety.
- `progress/pipeline-refactor-design.md` — pipeline / staging / color-mode taxonomy.
- `progress/governance-roadmap.md` — log governance v2 final state.
- `progress/glb-internals-audit-2026-04-30.md` — A2 audit + LEAK report (PR #129).
- `progress/round-17-onwards-master-plan.md` — log governance round structure.
- `docs/logging-guide.md` — operator + contributor guide for the structured logging stack.

### Code anchors (current state, dev-refactor `2bb72d1`)
- `api_server.py:18-20` — uvicorn entry.
- `api/session_store.py:8-24` — in-memory session store.
- `api/file_registry.py:8-20` — in-memory file registry.
- `api/worker_pool.py:61-159` — process-pool worker manager.
- `api/structured_logging.py` — structured logger (no migration needed).
- `core/naming.py::generate_segmented_glb_filename` — session-scoped GLB filename helper introduced by PR #130.

### PRs
- **PR #126** (A1): worker pool double-recycle fix (draft).
- **PR #129** (A2 audit): GLB internals audit + LEAK report (draft).
- **PR #130** (A2 follow-up): output_path required on segmented/realtime GLB (draft; supersedes the LEAK section of #129).

### Roadmap snapshot
- **Done**: A1, A2, A3.
- **Next**: A4 (Postgres + Redis docker-compose).
- **Then**: A5 (arq), A6 (object storage), Phase B/C/D in track-specific design docs.
