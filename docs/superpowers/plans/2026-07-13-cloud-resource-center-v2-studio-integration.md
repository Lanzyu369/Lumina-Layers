# Cloud Resource Center V2 Studio Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect Registry v2, legacy APIs, every material/LUT consuming workflow, session leases, and recipe/bug-report provenance to Studio's durable resource store without breaking old clients or ordered selections.

**Architecture:** Add a server-side Registry client and pure package binder first, then expose separate material/LUT lifecycle APIs backed by the store. Route every legacy mutation through static per-domain adapters after cutover, and route every managed read through a resource selection resolver that acquires exact revision leases before passing scalar paths to workers. Preserve legacy names/directories as projections while recipe v3 and new requests carry ordered exact provenance.

**Tech Stack:** Python 3, FastAPI/Pydantic, HTTPX, existing SessionStore/FileRegistry/worker pool, React TypeScript schema counterparts, pytest/Hypothesis, Vitest for recipe/feedback contracts.

---

## Branch And PR Boundaries

Use six Studio PRs in the interleaved order below, each cut from the freshly merged predecessor:

1. `codex/feat/resource-contract-client-v2`
   - vendored Registry fixtures, capability negotiation, public cache, exact detail/package binding;
   - starts only after Store Tasks 1-2 have merged; no local resource-store mutation.
2. `codex/feat/resource-lifecycle-api-v2`
   - Integration Task 4 together with Store Tasks 6-7;
   - strict material/LUT lifecycle APIs and origin guard adopt leases/lifecycle behind capability gates, without domain cutover.
3. `codex/feat/resource-store-cutover-v2`
   - Integration Tasks 5-6 together with Store Tasks 8-10;
   - static legacy adapters, writer drain/cutover/repair, and scheduler read-only split land as one anti-split-brain unit.
4. `codex/feat/resource-workflow-pinning-v2`
   - Integration Tasks 7-9;
   - ordered selection, managed-read adoption, restart-safe session/job leases.
5. `codex/feat/resource-provenance-v3`
   - Integration Tasks 10-11;
   - recipe/share-card/feedback/reproduction exact ordered provenance.
6. `codex/chore/resource-integration-gates-v2`
   - Integration Task 12 only;
   - logging, compatibility, direct-read inventory, session-close downloads, and canonical context evidence.

Do not add frontend resource-center layout here; that is the frontend/acceptance plan. Existing panels must continue working throughout these PRs.

## Execution Slices

1. Require the merged Store foundation PR (Store Tasks 1-2), then run Integration Tasks 1-3 and merge the client/binder PR.
2. Pause this plan while Store Tasks 3-5 consume the merged binder and land the shadow store PR.
3. Resume Integration Task 4 with Store Tasks 6-7; merge the lifecycle/API PR only while both domain cutover markers remain v1-active.
4. Resume Integration Tasks 5-6 with Store Tasks 8-10; merge the cutover/legacy-adapter PR only after writer-drain and mixed-domain tests pass.
5. Run Integration Tasks 7-9 and merge workflow pinning before any provenance/UI work.
6. Run Integration Tasks 10-11 as the provenance PR, then Task 12 as a separate evidence/gate PR.

Do not open a lifecycle API PR that merely assumes a future store implementation, and do not merge store cutover without its complete legacy-adapter/scheduler half. Do not bury workflow-reader adoption, provenance, or release-gate-only changes in either destructive lifecycle PR. The master PR train is authoritative if a task is prepared early while an upstream PR is under review.

## File Structure

Registry client PR:

- Create `tests/fixtures/registry-contract-v2/**` and `UPSTREAM.json`
- Create `core/resource_store/package_binding.py`
  - Pure exact-record/manifest/file/envelope binding and package limits.
- Create `api/services/resource_registry_config.py`
  - Stable `registry_key` mapped to existing material/LUT environment configuration.
- Create `api/services/resource_registry_client.py`
  - Capability, v1/v2 catalog, exact detail, controlled package stream.
- Create `api/services/resource_registry_cache.py`
  - Anonymous public metadata cache with generation/envelope-aware keys.
- Create `tests/test_resource_contract_fixtures_unit.py`
- Create `tests/test_resource_registry_client_unit.py`
- Create `tests/test_resource_registry_cache_unit.py`
- Create `tests/test_resource_package_binding_unit.py`

Lifecycle/integration PR:

- Create `api/schemas/resources.py`
  - Common state/action/error models plus separate material/LUT domain response models.
- Create `api/routers/resources.py`
  - Per-domain capability response only.
- Create `api/routers/material_resources.py`
- Create `api/routers/lut_resources.py`
- Create `api/services/resource_center.py`
  - Domain-independent orchestration and stable error mapping.
- Create `api/services/resource_selection.py`
  - Ordered material/LUT request resolution and lease acquisition/rollback.
- Create `api/resource_session_leases.py`
  - Session/job heartbeat, release, cleanup, and shutdown coordinator.
- Modify `api/local_origin_guard.py`
  - Resource-specific local/explicit-remote mutation policy that is never bypassed by the public-gray switch.
- Modify `api/app.py`, `api/routers/__init__.py`
  - Startup recovery before routes, router registration, expired-session lease release, shutdown cleanup.
- Modify `api/routers/material_sync.py`
  - Preserve old shapes; static v1/v2 mutation adapters.
- Modify `api/routers/lut_registry.py`
  - Preserve old shapes; static v1/v2 mutation adapters.
- Modify `api/material_sync_scheduler.py`
  - Read-only update check only.
- Modify `core/single_stage/materials.py`
  - Keep legacy projections; move v2 lifecycle out; enforce managed read-only.
- Modify `api/services/lut_registry_sync.py`
  - Keep v1 adapter/projection; remove direct managed writes after cutover.
- Modify `utils/lut_manager.py`
  - Exclude resource-store internals, project managed aliases, resolve explicit managed selections.
- Modify `core/material_lut_synthesis.py` and `core/material_lut_provider.py`
  - Add explicit path-based loaders while preserving directory-name APIs.
- Modify all LUT/material workflow entry points listed below.
- Modify `docs/local-docker-deployment.md`
  - Exact reverse-proxy authentication, Host/Origin allowlist, and direct-backend isolation requirements.
- Create focused API, origin-policy, resolver, scheduler, lease, compatibility, and logging tests.

Provenance PR:

- Modify `frontend/src/recipe/types.ts`, `exportRecipe.ts`, `importRecipe.ts`, `migration.ts`, `importFlow.ts`
- Modify PNG share-card adapters/tests that embed `LuminaRecipe`
- Modify `frontend/src/stores/converter/store.ts` and request builders
- Modify `frontend/src/utils/bugReportContext.ts`, `frontend/src/api/feedback.ts`
- Modify `api/routers/feedback.py`, `api/feedback_assembler.py`, `api/feedback_index.py`, `api/feedback_email.py`
- Modify `scripts/load_bug_repro.py`
- Add schema, round-trip, exact-reinstall, feedback, and reproduction tests.

## New Domain API Surface

Keep material and LUT routes separate:

```text
GET  /api/resources/capabilities

GET  /api/material-resources/catalog
GET  /api/material-resources/items
GET  /api/material-resources/{material_id}
GET  /api/material-resources/{material_id}/status
GET  /api/material-resources/{material_id}/revisions/{revision_id}/preview
GET  /api/material-resources/{material_id}/revisions/{revision_id}/distribution
GET  /api/material-resources/local-items/{local_id}
DELETE /api/material-resources/local-items/{local_id}
POST /api/material-resources/install
POST /api/material-resources/update
POST /api/material-resources/rollback
POST /api/material-resources/uninstall
POST /api/material-resources/repair
POST /api/material-resources/adopt-local-equivalent
POST /api/material-resources/create-local-copy
POST /api/material-resources/detach-management
POST /api/material-resources/update-all

GET  /api/lut-resources/catalog
GET  /api/lut-resources/items
GET  /api/lut-resources/{lut_id}
GET  /api/lut-resources/{lut_id}/status
GET  /api/lut-resources/{lut_id}/revisions/{revision_id}/preview
GET  /api/lut-resources/{lut_id}/revisions/{revision_id}/distribution
GET  /api/lut-resources/local-items/{local_id}
DELETE /api/lut-resources/local-items/{local_id}
POST /api/lut-resources/install
POST /api/lut-resources/update
POST /api/lut-resources/rollback
POST /api/lut-resources/uninstall
POST /api/lut-resources/repair
POST /api/lut-resources/adopt-local-equivalent
POST /api/lut-resources/create-local-copy
POST /api/lut-resources/detach-management
POST /api/lut-resources/update-all
```

`catalog` is cloud discovery; `items` is local managed/local inventory. The frontend adapter joins them by exact identity/state. Neither route combines material and LUT into one payload.

For both domains, the cloud detail and status GETs require `?source_registry={stable_key}` even when only one Registry is currently configured. Preview and distribution GETs carry the same query key as specified below. Local detail remains under `local-items/{local_id}` and never accepts a Registry key. No route chooses a default authority from resource ID alone.

## Task 1: Vendor Exact Registry Fixtures And Implement Pure Binding

**Files:**
- Create: `scripts/sync_registry_contract_fixtures.py`
- Create: `tests/fixtures/registry-contract-v2/UPSTREAM.json`
- Create: `tests/fixtures/registry-contract-v2/accepted/material-v2.zip`
- Create: `tests/fixtures/registry-contract-v2/accepted/material-v2-v1-envelope.zip`
- Create: `tests/fixtures/registry-contract-v2/accepted/lut-legacy-v1.zip`
- Create: `tests/fixtures/registry-contract-v2/accepted/lut-v2.zip`
- Create: `tests/fixtures/registry-contract-v2/accepted/lut-v2-v1-envelope.zip`
- Create: `tests/fixtures/registry-contract-v2/accepted/lut-v2-community-envelope.zip`
- Create: `tests/fixtures/registry-contract-v2/rejected/path-traversal.zip`
- Create: `tests/fixtures/registry-contract-v2/rejected/casefold-collision.zip`
- Create: `tests/fixtures/registry-contract-v2/rejected/symlink.zip`
- Create: `tests/fixtures/registry-contract-v2/rejected/file-hash-mismatch.zip`
- Create: `tests/fixtures/registry-contract-v2/rejected/record-binding-mismatch.zip`
- Create: `tests/fixtures/registry-contract-v2/rejected/manifest-too-large.zip`
- Create: `tests/fixtures/registry-contract-v2/rejected/manifest-duplicate-key.zip`
- Create: `tests/fixtures/registry-contract-v2/rejected/manifest-depth-overflow.zip`
- Create: `tests/fixtures/registry-contract-v2/rejected/npy-header-overflow.zip`
- Create: `tests/fixtures/registry-contract-v2/rejected/npz-inner-bomb.zip`
- Create: `tests/fixtures/registry-contract-v2/EXPECTED.json`
- Create: `tests/fixtures/registry-contract-v2/SHA256SUMS.json`
- Create: `tests/test_resource_contract_fixtures_unit.py`
- Create: `core/resource_store/package_binding.py`
- Create: `tests/test_resource_package_binding_unit.py`

- [ ] **Step 1: Write failing provenance and binding tests**

Require the same `UPSTREAM.json` shape and exact fixture inventory as Materials: Registry repository, exact 40-character commit, source-relative path, raw SHA-256 of the upstream `SHA256SUMS.json` bytes, and that manifest's raw SHA-256 for every other fixture. The test compares the checksum-manifest digest and every vendored payload, rejects an extra/missing file, and proves no absolute checkout path is stored.

Accepted cases: one-resource material 2.0/2.1, legacy LUT 1.0 projected canonical hash, LUT 2.0, rewritten envelope, and the deterministic material/LUT v1 compatibility artifacts. Before implementing the new binder, run those two compatibility artifacts through the existing production material bundle validator/importer and LUT package installer with a fake same-origin transport; freeze their installed bytes, logical paths, historical hashes, and response semantics. The v2 binder then accepts canonical artifacts only when exact detail supplies their matching v2 package hash/bytes/envelope. Reject zero or two logical material/LUT records before binding. Rejected cases mutate each record/manifest binding field independently: kind, schema, ID, revision, algorithm, canonical hash, logical path, publisher kind/name, title, summary, brand, tags, compatibility, channel, visibility, role, file path, required flag, bytes, file SHA, package SHA/bytes, representation swap, URL envelope query, and response header envelope. Lock the encoding matrix: v2 content/package/preview aggregate hashes require lowercase `sha256:` plus 64 hex, file hashes require lowercase raw 64-hex, and legacy fields stay opaque. Test missing/double prefix, uppercase, raw-v2 aggregate hash, prefixed file hash, equal digest bytes under the wrong algorithm/encoding, v1 catalog paired with v2 package, and v2 exact paired with v1 package.

Also cover undeclared payload, casefold collision, special entry, compression/size limit, unsupported LUT extension, and invalid domain loadability.

- [ ] **Step 2: Run and verify failure**

```bash
python -m pytest tests/test_resource_contract_fixtures_unit.py tests/test_resource_package_binding_unit.py -v
```

Expected: FAIL because the vendored fixture root and binder are absent.

- [ ] **Step 3: Implement exact-commit fixture synchronization**

`scripts/sync_registry_contract_fixtures.py` accepts `--registry-checkout`, `--registry-commit`, and `--output`. It requires upstream `HEAD` to equal the supplied exact 40-character commit and the fixture tree to be clean, reads and hashes upstream `SHA256SUMS.json`, then reads only its listed files, rejects symlink/special/extra paths and traversal, copies the manifest and payload bytes through a request-owned temporary sibling, verifies every digest, writes canonical `UPSTREAM.json` with `checksum_manifest_sha256` but without the checkout path, and publishes the complete output with no-replace/verified replacement semantics. It performs no network access and refuses branch/tag names as the `--registry-commit` value.

Vendor from the exact merged Registry fixture PR:

```bash
REGISTRY_CHECKOUT=../Lumina-material-registry
REGISTRY_FIXTURE_COMMIT=$(git -C "$REGISTRY_CHECKOUT" rev-parse HEAD)
python scripts/sync_registry_contract_fixtures.py \
  --registry-checkout "$REGISTRY_CHECKOUT" \
  --registry-commit "$REGISTRY_FIXTURE_COMMIT" \
  --output tests/fixtures/registry-contract-v2
python -m pytest tests/test_resource_contract_fixtures_unit.py -k upstream -q
```

Expected: fixture provenance passes and `UPSTREAM.json` contains no local checkout path.

- [ ] **Step 4: Implement pure binding types**

Create:

```python
@dataclass(frozen=True)
class BoundFile:
    role: str
    path: str
    sha256: str
    bytes: int
    required: bool


@dataclass(frozen=True)
class VerifiedPayloadFile:
    role: str
    archive_path: str
    revision_path: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class ControlledPreviewRecord:
    preview_version: str
    summary: Mapping[str, JsonValue]
    preview_url: str
    preview_media_type: Literal["image/png"]
    preview_sha256: str
    preview_bytes: int
    width: int
    height: int


@dataclass(frozen=True)
class ExactRevisionRecord:
    contract_version: Literal["2.0"]
    resource_kind: Literal["material", "lut"]
    package_kind: str
    package_schema_version: str
    resource_id: str
    revision_id: str
    content_hash_algorithm: str
    content_hash: str
    legacy_content_hash: str | None
    envelope_id: str
    package_url: str
    package_sha256: str
    package_bytes: int
    publisher_id: str
    publisher_kind: Literal["lumina", "community"]
    publisher_name: str
    title: str
    summary: str
    brand: str
    tags: tuple[str, ...]
    published_at: str
    updated_at: str
    download_count: int
    channel: str
    visibility: str
    compatibility: Mapping[str, JsonValue]
    logical_path: str
    files: tuple[BoundFile, ...]
    authorization_generation: str
    preview: ControlledPreviewRecord


@dataclass(frozen=True)
class VerifiedPackageBinding:
    exact: ExactRevisionRecord
    archive_path: Path
    archive_identity: VerifiedFileIdentity
    payload_files: tuple[VerifiedPayloadFile, ...]
    display_snapshot: InstalledDisplaySnapshot
```

Import `JsonValue`, `InstalledDisplaySnapshot`, and `VerifiedFileIdentity` from the merged store foundation models. Expose `bind_downloaded_package(exact, archive_path, response_envelope_id)`. Open the request-owned archive without following links/reparse points, require a regular file, derive its platform file identity from that handle, and perform package byte hashing plus all ZIP reads through that same open handle. Recheck handle identity/size after parsing and return them with the strict prefixed full package SHA-256 in `archive_identity`; never treat the path as the verified object.

The exact-record parser forbids extra/missing fields and enforces the shared NFC/UTF-8 display/tag/compatibility limits from the master plan plus all timestamp, authorization-generation, controlled-preview, and count bounds before binding. New timestamps must match the master plan's exact `YYYY-MM-DDTHH:MM:SSZ` UTC codec and parse to a valid `1970..9999` instant. The catalog/latest parsers require `catalog_generation` to match `cat_[0-9a-f]{16}`, and every v2 response parser requires `authorization_generation` to match `auth_[0-9a-f]{16}`; each rejects swapped/missing prefixes, wrong case/width, signs, and whitespace, then treats both values as opaque. Exact detail must not contain a catalog generation. `download_count` must be an integer in `0..9007199254740991`, never a float or unsafe integer. It accepts only `official | community | team` for channel and `official | community | team | private` for visibility, treats only pairs wholly inside `{official, community}` as anonymous-public, treats every other allowed pair as restricted/no-store, and never derives publisher kind from either field. Tests accept distinct `team/private` and historical `team/team` records, reject `private` as a channel or any unknown visibility, and prove no one-field restricted pair enters the anonymous cache path. It requires publisher ID to match `[a-z0-9][a-z0-9_-]{0,63}`, Registry-generated envelope IDs to use the bounded lowercase safe type-prefixed format, and resource/revision IDs to retain the frozen legacy ASCII package pattern without case normalization. Before any member allocation, the binder applies the exact cross-repository outer ZIP ceilings: 64 MiB archive bytes, 128 entries, 64 MiB per member, 128 MiB total expanded bytes, and per-entry plus aggregate ratio `uncompressed / max(compressed, 1) <= 200`, including ZIP64, duplicate raw/NFC/casefold names, and manifest/directory entries. The manifest itself must use the same stricter parser as Registry and Materials: UTF-8 JSON at most 1 MiB; decoder-time rejection of BOM/non-UTF-8, non-finite constants, and duplicate raw keys; then, before model allocation, depth at most 12, 8,192 aggregate nodes, 2,048 aggregate object keys, at most 1,024 items per array, keys at most 128 UTF-8 bytes, strings at most 4,096 UTF-8 bytes, and no same-object NFC/casefold key collision. Binding tests import the three representative rejected golden fixtures and dynamically generate every exact/one-over structural boundary, requiring the same stable rejection category. The binder then verifies the safe ZIP inventory, schema adapter, canonical content hash, every exact/manifest field, publisher display/compatibility projection, and envelope header/query. `publisher_id`, preview/publication/count fields are Registry metadata rather than package-manifest identity, but they still must parse strictly; publisher ID enters the installed display snapshot only after the exact response/envelope/package binding succeeds, and the preview remains bound to the exact active envelope. Parse prefixed v2 aggregate hashes exactly once into algorithm plus digest bytes; never compare by stripping arbitrary text or by digest alone. Preserve opaque legacy values only for audit/projection. It returns the bounded display snapshot consumed by the local index. Any mismatch raises `RegistryPackageBindingMismatch`; unsafe archives, unloadable payloads, and an archive changed during binding remain distinct typed errors. Store Task 3 must re-open and compare this identity plus full hash immediately before bounded extraction, closing the check/use gap.

`BoundFile.path` is always the normalized archive-member path from Registry/manifest and is never reused as a filesystem destination. The binder derives `VerifiedPayloadFile` without accepting another path from the response: material `D` maps exact members `materials/{D}/material.json` and `materials/{D}/stage_A_parameters.json` to revision paths `material.json` and `stage_A_parameters.json`; LUT `P` maps exact member `luts/{P}` to revision path `basename(P)`. It rejects a repeated `materials/`, `luts/`, `lut-preset/`, or `Cloud/` prefix and every role/logical/member mismatch.

Freeze both accepted material bundle shapes instead of casting legacy JSON into the 2.1 model. Source/v1 material schema 2.0 accepts top-level `kind`, `schema_version`, `packages`, optional `material_count`, and optional `exported_at` only; all 174 current archives contain `material_count=1` and `exported_at`. When the count is present it must equal the exact one-package cardinality, and `exported_at` is legal only with that count, must be a nonempty string of at most 128 UTF-8 bytes, is preserved as opaque spelling, and never enters identity/display comparison. A Registry-generated schema-2.0 compatibility artifact may omit both fields. Material 2.1 forbids both fields. The separate top-level `lumina_material_export.json` remains a bounded metadata member: require its exact frozen kind/schema/count/one-directory contract, permit only its own optional historical opaque `exported_at`, exclude it from content identity/managed files, and never extract it. No other undeclared regular member is accepted. Tests run every current material package and both generated 2.0 variants through the production binder, then reject count/cardinality mismatch, lone/empty/129-byte/non-string `exported_at`, 2.1 legacy fields, duplicated-root, alternate-directory, same-hash/wrong-path, extra-member, and LUT auxiliary-member archives before staging.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest tests/test_resource_contract_fixtures_unit.py tests/test_resource_package_binding_unit.py -q
git add scripts/sync_registry_contract_fixtures.py tests/fixtures/registry-contract-v2/UPSTREAM.json tests/fixtures/registry-contract-v2/accepted/material-v2.zip tests/fixtures/registry-contract-v2/accepted/material-v2-v1-envelope.zip tests/fixtures/registry-contract-v2/accepted/lut-legacy-v1.zip tests/fixtures/registry-contract-v2/accepted/lut-v2.zip tests/fixtures/registry-contract-v2/accepted/lut-v2-v1-envelope.zip tests/fixtures/registry-contract-v2/accepted/lut-v2-community-envelope.zip tests/fixtures/registry-contract-v2/rejected/path-traversal.zip tests/fixtures/registry-contract-v2/rejected/casefold-collision.zip tests/fixtures/registry-contract-v2/rejected/symlink.zip tests/fixtures/registry-contract-v2/rejected/file-hash-mismatch.zip tests/fixtures/registry-contract-v2/rejected/record-binding-mismatch.zip tests/fixtures/registry-contract-v2/rejected/manifest-too-large.zip tests/fixtures/registry-contract-v2/rejected/manifest-duplicate-key.zip tests/fixtures/registry-contract-v2/rejected/manifest-depth-overflow.zip tests/fixtures/registry-contract-v2/rejected/npy-header-overflow.zip tests/fixtures/registry-contract-v2/rejected/npz-inner-bomb.zip tests/fixtures/registry-contract-v2/EXPECTED.json tests/fixtures/registry-contract-v2/SHA256SUMS.json tests/test_resource_contract_fixtures_unit.py core/resource_store/package_binding.py tests/test_resource_package_binding_unit.py
git commit -m "feat(resources): bind exact registry package contracts"
```

## Task 2: Server-Side Registry Configuration And Capability Negotiation

**Files:**
- Create: `api/services/resource_registry_config.py`
- Create: `api/services/resource_registry_client.py`
- Test: `tests/test_resource_registry_client_unit.py`

- [ ] **Step 1: Write config and capability fallback tests**

Cover absent URL, material-specific URL, LUT fallback to material URL, domain-specific channels/token/key, explicit stable key `public-default`, URL with no key, invalid/mismatched keys, same key across a same logical Registry URL rotation, different key at the same URL, capabilities v2 true, 404, timeout, malformed JSON, unsupported schema, and feature false. Lock legacy defaults independently from v2 discovery: material v1 remains `("official",)`, LUT v1 remains `("official", "community")`, while v2 defaults to both current public channels so community material/LUT content is discoverable. An explicitly configured domain channel list overrides that domain's v2 list without changing the other domain. Assert config repr/log/public errors contain no token or URL query.

- [ ] **Step 2: Implement stable config**

```python
@dataclass(frozen=True)
class RegistryConfig:
    registry_key: str | None
    base_url: str
    legacy_channels: tuple[str, ...]
    v2_channels: tuple[str, ...]
    token: str | None = field(repr=False)
    allow_insecure_localhost: bool = False
```

Map existing `LUMINA_MATERIAL_REGISTRY_*` and `LUMINA_LUT_REGISTRY_*` values plus new non-secret `LUMINA_MATERIAL_REGISTRY_KEY`/`LUMINA_LUT_REGISTRY_KEY` into this type. LUT may inherit the material key only when it also inherits the same normalized material base origin; an independently configured LUT URL requires its own key. A configured key is an explicit operator-declared logical Registry identity matching `[a-z0-9][a-z0-9_-]{0,63}`; absence is represented only as `None`, never an empty/derived sentinel. A URL without a valid key keeps every legacy v1 request working but makes v2 capability/mutations unavailable with a safe configuration diagnostic; never derive source identity from URL text or silently assign `public-default` to arbitrary endpoints.

When a domain's existing `*_CHANNELS` value is present, normalize and use it for both legacy and v2 requests; when absent, retain that legacy client's historical default but set v2 to the reviewed public distribution set `("official", "community")`. Never change a v1 request default merely because capability negotiation succeeds or fails. Persist only `registry_key`. The same key across a base-URL rotation is an explicit assertion that this remains the same logical Registry and requires online generation/envelope revalidation; moving to a different authority requires a new key, which creates a separate cache/source identity and leaves old installed refs attached to their prior key. This Studio-local key selects configured client state only: do not place it in an upstream header/query/body or treat it as the Registry server's credential-scope authority ID. The Registry evaluates that separate server-owned ID when it parses the configured bearer token. Reject remote HTTP by default; explicit development config may allow loopback HTTP. HTTPS failure never retries over HTTP.

- [ ] **Step 3: Implement capabilities and v1/v2 selection**

Use one `httpx.Client(follow_redirects=False)` per request scope with connect/read/write/pool timeouts. `get_capabilities()` chooses v2 only when a valid stable Registry key exists and schema/features/package versions support the target domain; otherwise returns a complete v1 adapter decision. A missing key/old capability is not an error when v1 is available, but the reason is visible in safe server capability diagnostics.

Implement separate strict parsers for `CatalogPage`, `LatestResourceDetail`, `RevisionHistorySummary`, and `ExactRevisionRecord`; do not cast one response dict into another. Enforce the Registry plan's exact key sets, domain field exclusivity, page equations/end-state pair, field-specific generations, newest-first bounded history plus safe `history_total`, and v2-artifact-only package fields. Catalog/Latest parsing produces only sanitized browse/history models; only a fresh exact parser result can become `ExactRevisionRecord`. Tests reject missing/extra/mixed-domain keys, catalog generation on exact detail, absent authorization generation, inconsistent page or history counts, duplicate revision IDs, unsorted history, v1 schema/hash/artifact injected into v2, and package URL present in a history summary.

- [ ] **Step 4: Test origin and redirect rules**

Exact/package URL resolution requires same scheme/host/effective port as configured base. Reject userinfo, fragments, protocol-relative external hosts, cross-origin redirects, redirect chains, and query keys other than the trusted `envelope_id` supplied by exact detail. Catalog/detail may use relative same-origin paths only.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest tests/test_resource_registry_client_unit.py -q
git add api/services/resource_registry_config.py api/services/resource_registry_client.py tests/test_resource_registry_client_unit.py
git commit -m "feat(resources): negotiate registry catalog capabilities"
```

## Task 3: Public Metadata Cache And Controlled Package Stream

**Files:**
- Create: `api/services/resource_registry_cache.py`
- Modify: `api/services/resource_registry_client.py`
- Test: `tests/test_resource_registry_cache_unit.py`
- Test: `tests/test_resource_registry_client_unit.py`

- [ ] **Step 1: Write cache partition and offline tests**

Public key binds registry key, kind, anonymous mode, normalized channels/query/filters/sort, catalog generation, authorization generation, ETag, and fetched time. Detail key binds exact revision and active envelope. Test 304 revalidation, generation change, envelope change, publisher disable/unified 404 invalidation, same-key URL rotation with online revalidation, different-key config switch with zero old-cache reuse, malformed cache, offline stale browse, and no-cache empty offline state. Assert serialized cache entries contain no `package_url`, `package_sha256`, `package_bytes`, upstream preview URL/query, full Registry origin, Authorization-derived value, or absolute path, and cannot validate as `ExactRevisionRecord`/`VerifiedPackageBinding`. Fill every cache boundary exactly and one over; cover two-version replacement, oldest-fetched eviction, metadata/preview byte caps, same-volume cache-write versus install reservation, ENOSPC, manifest/file mismatch, symlink/reparse/unknown sibling, crash before/after pointer switch, and cache-write refusal degrading to the current online response without changing local resource state.

Test package download with insufficient free bytes or inodes before request, two clients racing the same physical-volume byte/inode budget, mismatched declared expanded bytes/file inventory, missing/duplicate/invalid/wrong Content-Length, chunked transfer, non-identity Content-Encoding, wrong/parameterized Content-Type, disconnect, timeout, byte/inode exhaustion after reservation, process crash/stale reservation, and success release. Assert no HTTP request occurs when reservation fails and no partial file/index pointer survives.

Any Authorization-bearing or potentially restricted response must leave persistent cache files unchanged and must not enter a cross-request shared memory object.

- [ ] **Step 2: Implement cache storage**

Define a separate `PublicResourceBrowseRecord` containing identity/ref, read-only publisher ID plus display fields, compatibility, logical relative path, publication/update/download facts, catalog/authorization generation, active envelope ID, fetched time, and Registry-controlled preview summary/hash/bytes, but no package locator/integrity fields or upstream preview URL. Store only this sanitized projection under `{domain_root}/_sync/registry-cache/public/{lookup_hash}/{version_hash}.json`, plus one atomic lookup pointer and `cache-index-v1.json`. Never serialize base URL, token, principal fingerprint, publisher ownership/external key, `package_url`, `package_sha256`, `package_bytes`, upstream preview URL/query, or absolute path. Online catalog/detail code explicitly converts exact responses to this projection before persistence; the reverse conversion does not exist.

The index owns only normalized paths below that exact cache root and records kind, lookup/version key, digest, bytes, fetched time, and current-pointer status. Hard-code initial per-domain caps of 1,024 lookup keys, two metadata versions per lookup, 64 MiB total metadata JSON, 512 preview objects, and 256 MiB total preview bytes; each individual catalog body is at most 4 MiB and detail body at most 1 MiB before strict JSON parsing. Before a cache write, acquire the existing same-volume `CapacityManager` locks/reservation for exact response bytes plus atomic-write byte/inode overhead, then under a cache lock evict oldest fetched non-current versions followed by oldest lookups until count, byte, and object caps fit. Publish file/index/pointer atomically in that order and release the capacity reservation only after convergence. Never reserve while holding the cache lock.

Eviction unlinks only an index-owned regular file after no-follow path, identity, byte-count, and digest proof; it never traverses or removes an unknown sibling/directory. Keep the prior current version until the new file and index are durable, so a crash leaves one valid pointer or a recoverable unpointed owned file. A malformed index, symlink/reparse/special file, ownership mismatch, capacity refusal, or cleanup ambiguity disables further persistent cache writes and emits a bounded structured warning; online parsing still returns the request-local sanitized response, and offline mode reports unavailable rather than trusting unindexed bytes. Startup reconciliation is bounded by the caps and may remove only a proven unpointed cache-owned temporary/version file. Material and LUT cache budgets remain independent in count but same-volume writes share the Store capacity scope.

Expose separate APIs: `browse_catalog(..., allow_offline=True) -> PublicResourceBrowsePage` and `get_exact_revision_online(...) -> ExactRevisionRecord`. Install/update/remote rollback/repair accept only the second type obtained in the current online request and never a union or duck-typed dict. On online browse reads, revalidate ETag/generations; offline cache can render/search only and cannot authorize package/preview network fetch or lifecycle mutation.

- [ ] **Step 3: Implement controlled package download**

Before network I/O, calculate peak bytes from exact `package_bytes` plus declared expanded file bytes and acquire a cross-process `SpaceReservation` from the target domain. The download function accepts an already-created exclusive same-filesystem staging destination and live reservation; it neither imports a not-yet-merged transaction manager nor constructs a path from browser data. Client-PR tests supply a `tmp_path` target, while the later lifecycle composition supplies a transaction-owned destination. Stream with `httpx.Response.aiter_raw()`/`iter_raw()`, a total timeout, no redirects, and incremental SHA. Inspect the raw response header list before reading the body: require status 200, exactly one canonical decimal `Content-Length` equal to the exact record, exactly one `Content-Type`, exactly one `X-Lumina-Envelope-ID`, zero `Transfer-Encoding` occurrences, and at most one `Content-Encoding` occurrence whose value is exact `identity`. Reject duplicate, comma-combined, obs-fold/whitespace-ambiguous, or conflicting security-relevant headers. Parsed media type must be exactly `application/zip` with no parameters; actual raw bytes equal the same length; prefixed package hash and envelope ID equal the exact record. Reject transfer/content decoding rather than comparing different representation layers. Delete only the request-owned incomplete file on failure and release by reservation version CAS; pass the live reservation, destination, and verified binding into package publication on success.

Install/update/remote rollback fetch fresh exact detail online immediately before package download; never install from catalog/offline cache alone.

- [ ] **Step 4: Fetch and cache controlled previews without exposing Registry URLs**

Validate preview URL with the same same-origin/no-redirect/query rules as exact packages and require the envelope ID from exact detail. Stream raw through a 2 MiB hard limit. Inspect raw headers with the same duplicate/ambiguity rules: exactly one canonical `Content-Length` equal to `preview_bytes`, exactly one parameter-free `Content-Type: image/png`, zero `Transfer-Encoding`, and zero or one exact-`identity` `Content-Encoding`. Require actual length, PNG signature, prefixed `preview_sha256`, and decoded dimensions with Pillow under a pixel limit before acceptance. Anonymous public previews may use the bounded, capacity-reserved versioned public cache keyed by registry/kind/resource/revision/authorization generation/envelope/hash; Authorization-bearing or restricted previews stay request-local and `no-store`. Never return the Registry URL or envelope query to frontend state.

- [ ] **Step 5: Run and commit the client PR**

```bash
python -m pytest tests/test_resource_registry_client_unit.py tests/test_resource_registry_cache_unit.py tests/test_resource_package_binding_unit.py -q
git add api/services/resource_registry_cache.py api/services/resource_registry_client.py tests/test_resource_registry_cache_unit.py tests/test_resource_registry_client_unit.py
git commit -m "feat(resources): cache public metadata and stream packages"
```

Run `git diff --check`, fixture checksum tests, and token/local-path scan; open the client PR before any lifecycle mutation PR.

## Task 4: Resource Schemas, Capabilities, And Domain Routers

**Files:**
- Create: `api/schemas/resources.py`
- Create: `api/services/resource_center.py`
- Create: `api/routers/resources.py`
- Create: `api/routers/material_resources.py`
- Create: `api/routers/lut_resources.py`
- Modify: `api/local_origin_guard.py`
- Modify: `api/app.py`
- Modify: `api/routers/__init__.py`
- Modify: `docs/local-docker-deployment.md`
- Create: `tests/test_resource_center_api_unit.py`
- Create: `tests/test_resource_mutation_origin_unit.py`

- [ ] **Step 1: Write API contract tests**

Test capabilities with both domains at every marker combination, unknown adapter, migration prepared, recovery-required read-only, and v1 fallback. Lock `schema_version="1.0"`, field names, nullability, and each domain's single `actions` array to design section 9.3, including mixed material-v2/LUT-v1 and the reverse; the array may contain only the declared `ResourceItemAction | ResourceBatchAction` literals supported by that committed domain. Do not introduce `item_actions`, `batch_actions`, or a root-level cutover state. Test common local states/actions, cloud/local detail, preview, distribution detail, install/update/rollback/uninstall/repair/adopt/copy/detach/local-delete/update-all request/response shapes, deterministic HTTP/error code mapping, domain-specific ID/path fields, and equal resource IDs under different stable Registry keys. Explicitly call `/catalog` and `/items` in both domains and prove FastAPI does not dispatch either literal as `{material_id}`/`{lut_id}`; register all one-segment static routes before the dynamic detail route and keep an app-route contract test for this order. Cloud `/{resource_id}` and `/{resource_id}/status` GETs require the bounded backend-returned `source_registry` query key; without it they return a typed validation error instead of selecting a default, and equal IDs under two configured keys yield isolated details/status. Local endpoints accept only stable `local_id`; cloud lifecycle endpoints accept the non-secret server-declared `source_registry` key plus resource/revision IDs and never a Registry URL or filesystem path. The server resolves that key only against its configured Registry map or an exact installed managed key; an arbitrary/new key cannot select an endpoint. Local detail returns a strong ETag; DELETE requires the exact value in `If-Match`, returning 428 when absent and 412 with zero deletion when current file facts changed. ETag/path facts never enter JSON, logs, browser persistence, or a lifecycle request body.

For every classified POST/PATCH/PUT/DELETE route in the API surface, assert the outer origin middleware runs before FastAPI routing/body parsing, then the endpoint dependency rechecks before Registry resolution, disk staging, writer admission, or index mutation. Drive multipart cases with a controlled ASGI `receive` and prove a rejected request never calls it. Cover allowed loopback browser origins on ports `4174`, `5174`, and `8000`; loopback native clients without Origin; `Origin: null`; malformed Host/Origin/Referer; cross-site fetch; public-gray mode; remote client/Host; exact HTTPS remote allowlists; wrong scheme/port/subdomain; wildcard-looking configuration; missing remote Origin; and one domain being read-only. A rejected request returns the same safe `403 resource_mutation_origin_forbidden` and leaves files, spools, journals, indexes, downloads, and Registry request count unchanged. GET catalog/detail/preview routes remain readable under their existing policy.

Also test same-revision envelope replacement caused by publisher/channel/visibility metadata. The installed revision/content state remains `installed`, never `update_available`. The local `items` list is strictly index-only and makes zero Registry requests: it returns the immutable installed display snapshot with `display_provenance="installed_snapshot"`, `metadata_stale=true`, `metadata_verified_at=null`, and `distribution_available=null`. A separate domain distribution-detail GET, invoked only by details selection or explicit refresh, resolves the installed full ref and performs one fresh exact online read. When it matches, the response carries a separate current distribution display plus `display_provenance="current_registry"`, `metadata_stale=false`, and `metadata_verified_at`; timeout/unreachable retains the snapshot with unknown availability, while a live unified 404 retains the snapshot and sets `distribution_available=false`. No branch rewrites the installed envelope/display record in a read endpoint, no N+1 refresh occurs on list load, and a stale snapshot is never labeled as current Registry authority.

- [ ] **Step 2: Define shared schemas without erasing domain fields**

```python
ResourceItemAction = Literal[
    "install",
    "update",
    "rollback",
    "uninstall",
    "repair",
    "adopt_local_equivalent",
    "create_local_copy",
    "detach_management",
    "delete",
]
ResourceBatchAction = Literal["update_all"]
# Import ResourceUsageKind from core.resource_store.models; do not redeclare it.
ResourceLocalState = Literal[
    "not_installed",
    "installed",
    "update_available",
    "local_equivalent",
    "damaged",
    "local_import",
    "local_copy",
    "legacy_unresolved",
]


class ResourceActionResultBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["success", "skipped", "failed"]
    operation: ResourceItemAction | ResourceBatchAction
    source_registry: str | None = None
    local_id: str | None = None
    revision_id: str | None = None
    local_state: ResourceLocalState
    error_code: str | None = None


class MaterialActionResult(ResourceActionResultBase):
    resource_kind: Literal["material"] = "material"
    material_id: str | None = None
    local_directory: str | None = None


class LutActionResult(ResourceActionResultBase):
    resource_kind: Literal["lut"] = "lut"
    lut_id: str | None = None
    local_path: str | None = None


class InstallMaterialResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_registry: str
    material_id: str
    revision_id: str


class InstallLutResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_registry: str
    lut_id: str
    revision_id: str


class MaterialUpdateAllResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    succeeded: list[MaterialActionResult]
    skipped: list[MaterialActionResult]
    failed: list[MaterialActionResult]


class LutUpdateAllResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    succeeded: list[LutActionResult]
    skipped: list[LutActionResult]
    failed: list[LutActionResult]
```

Every material wire model uses `material_id/local_directory`; every LUT wire model uses `lut_id/local_path`. The common base contains no generic `resource_id`, and no request/response JSON may substitute that internal-store field for the domain identifier. Define corresponding domain-specific update/rollback/uninstall/repair/adopt/copy/detach/delete request classes rather than accepting a common request and renaming keys in a route. Shared list/view fields use exact semantics from the design, including `local_equivalent`, `damaged`, `is_in_use`, `history_busy`, previous revision, and backend-narrowed `allowed_actions`. `in_use_by` is a sorted/deduplicated list of at most eight `ResourceUsageKind` values derived from server-owned workflow registration; it never contains PID, process identity, session/job/lease/local-lock/guard ID, path, or arbitrary caller text. `history_busy` is true only when the single pending-GC slot cannot converge; update/rollback actions are omitted until lease release/GC/repair, and a raced mutation maps the core error to deterministic `409 resource_history_busy` without downloading. Domain capability preserves design section 9.3's one `actions` array; its element type is `ResourceItemAction | ResourceBatchAction`. Item `allowed_actions` contains only `ResourceItemAction`, never `update_all`, and the frontend derives separate item/batch sets locally without changing the wire contract. A managed item returns non-null `source_registry` plus the matching domain ID, null `local_id`, and one complete matching `ResourceRevisionRef` with stable registry key and canonical algorithm/hash. A pure local/unresolved item returns null address-level `source_registry` and domain ID, non-null stable `local_id`, and a null ref. `local_copy`/`local_equivalent` may additionally expose a complete non-authoritative `source_ref`, but lifecycle requests still address them by `local_id`.

Use action-specific validation for every domain result. Install/update/rollback/uninstall/repair and every `update_all` item require the complete managed `(source_registry, resource_kind, material_id|lut_id)` address and null `local_id`; delete and local-only failures require `local_id` and null `source_registry`/domain ID; only successful adopt/create-copy/detach transitions may carry both addresses. Their direction is fixed by `operation`: `adopt_local_equivalent` uses `local_id` for the unchanged source local item and managed fields plus `revision_id` for the newly managed result; `create_local_copy` uses managed fields plus `revision_id` for the exact source and `local_id` for the new local result; `detach_management` uses managed fields plus `revision_id` for the detached source revision and `local_id` for the new local result. Skipped/failed transitions never invent a result address and therefore cannot carry both. No other operation-specific interpretation is allowed, and `revision_id` cannot appear without the complete domain-specific managed address. Tests reject generic `resource_id`, both domain IDs, every empty/partial/illegal mixed combination, and prove the frontend refreshes the operation-defined result row while retaining/removing the source row as specified, never guessing by title/path. Add `display_provenance`, `metadata_stale`, `metadata_verified_at`, and `distribution_available` as explicit fields; do not infer them from network errors in the browser. Optional technical content/package hash prefixes are either null or exactly the first 12 lowercase hex characters of the already-validated digest, without `sha256:`; only the server computes them and they never authorize any operation.

Catalog/detail responses replace every Registry preview URL with a Studio-relative domain route: `/api/material-resources/{material_id}/revisions/{revision_id}/preview?source_registry={stable_key}` or `/api/lut-resources/{lut_id}/revisions/{revision_id}/preview?source_registry={stable_key}`. Those GET routes accept only the bounded stable key plus path IDs, no upstream URL/hash/envelope input, resolve the key against server configuration or the exact installed record, revalidate when online, return only verified PNG bytes, and use `Cache-Control: private, no-store` toward the browser. Offline returns a verified anonymous-public cached preview for that complete identity when present or typed `resource_preview_unavailable`; it never returns a zero-byte/blank success. Test equal IDs under different Registry keys and prove that no Studio JSON, browser request, Zustand value, or error contains a Registry origin, envelope query, token, or absolute cache path.

Expose the distribution-detail reads as `/api/material-resources/{material_id}/revisions/{revision_id}/distribution` and `/api/lut-resources/{lut_id}/revisions/{revision_id}/distribution`. They require the stable `source_registry` query value, accept no URL/hash/envelope/channel input, require the complete requested identity to equal the installed full ref, do not authorize lifecycle mutation, and return a request-scoped restricted result or sanitized anonymous-public projection. A stale persistent browse cache may support offline details but is always labeled `installed_snapshot`/stale; only the currently successful online response may use `current_registry`.

- [ ] **Step 3: Enforce a resource-specific mutation-origin policy**

Extend `api/local_origin_guard.py` with one pure policy plus an outer ASGI guard used by both new resource routers and every legacy resource mutation adapter:

```python
@dataclass(frozen=True)
class ResourceMutationOriginDecision:
    allowed: bool
    mode: Literal["local", "remote"]
    reason: str

def require_resource_mutation_origin(request: Request) -> None:
    decision = evaluate_resource_mutation_origin(request)
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "resource_mutation_origin_forbidden",
                "message": "Resource changes are not allowed from this request origin.",
            },
        )
```

Define an immutable `RESOURCE_MUTATION_ROUTE_PATTERNS` table of anchored method/path patterns and `ResourceMutationOriginMiddleware`. It inspects only HTTP scope/client/headers, never calls `receive`, and sends the structured 403 itself when a classified mutation is rejected. Register it as the outermost application middleware before CORS/error/body parsing. An app-route contract test enumerates every resource-family POST/PATCH/PUT/DELETE, requires exactly one mutation or documented read-only classification, and proves the middleware table and endpoint dependency cannot drift. Multipart endpoints may keep existing request shapes, but no rejected body is parsed or spooled.

Implement `evaluate_resource_mutation_origin(request)` as a pure header/client-policy evaluator returning the model above. Local mode requires a loopback client and Host. Browser Origin/Referer, when present, must normalize to loopback and one of `4174`, `5174`, `8000`, or an integer in `LUMINA_RESOURCE_MUTATION_ALLOWED_LOCAL_PORTS`; `Sec-Fetch-Site: cross-site`, `Origin: null`, malformed headers, user-info, query/fragment, and unlisted ports fail closed. A no-Origin native request is accepted only when client and Host are loopback and Referer is absent or valid.

Remote mode is disabled by default. It activates only with `LUMINA_RESOURCE_MUTATION_REMOTE_ENABLED=1`, a nonempty comma-separated `LUMINA_RESOURCE_MUTATION_ALLOWED_ORIGINS` containing exact absolute HTTPS origins, and a nonempty exact `LUMINA_RESOURCE_MUTATION_ALLOWED_HOSTS`. It requires an Origin and exact normalized Origin/Host matches; it never accepts wildcard, suffix, forwarded-header, missing-Origin, HTTP, or `null` equivalence. `LUMINA_ALLOW_PUBLIC_GRAY_API=1` must not bypass this policy. Log only normalized safe host/origin plus reason with event `resource_mutation_origin_forbidden`; never log Referer path/query, headers, token, or client credentials.

Attach `Depends(require_resource_mutation_origin)` to each new POST/PATCH/PUT/DELETE mutation and, in Task 5, every old material/LUT mutating route, while the outer middleware provides the pre-body guarantee. This policy prevents browser cross-site writes; it is not user authentication. Update `docs/local-docker-deployment.md` to require an authenticated HTTPS reverse proxy that strips client-supplied auth assertion headers, exposes only the proxy, preserves an allowlisted Host, and blocks direct backend access before remote mode may be enabled. Document that public-gray mode alone leaves resource writes disabled.

- [ ] **Step 4: Implement stable error mapping**

Core errors never become raw tracebacks or ad hoc strings. Map not configured/unreachable/contract/path/hash/binding/loadability/commit/index/lease/in-use/read-only/cursor codes to deterministic 4xx/5xx. Public messages contain actionable next steps and no token, URL query, or absolute path. Log structured internal details with safe IDs. Preserve the origin guard's structured `403` instead of remapping it through a generic lifecycle error.

- [ ] **Step 5: Register startup recovery before mutating routes**

FastAPI lifespan runs each domain's transaction/cutover recovery before exposing actions. If one domain needs repair, it remains readable with empty mutation actions while the other can operate. Startup never silently downgrades a committed domain.

- [ ] **Step 6: Run and commit**

```bash
python -m pytest tests/test_resource_center_api_unit.py tests/test_resource_mutation_origin_unit.py tests/test_local_origin_guard_unit.py -q
git add api/schemas/resources.py api/services/resource_center.py api/routers/resources.py api/routers/material_resources.py api/routers/lut_resources.py api/local_origin_guard.py api/app.py api/routers/__init__.py docs/local-docker-deployment.md tests/test_resource_center_api_unit.py tests/test_resource_mutation_origin_unit.py
git commit -m "feat(resources): expose domain lifecycle APIs"
```

Together with Store Tasks 6-7, run the lease/GC/API/origin failure matrix, `git diff --check`, and secret/path scans; open the `resource-lifecycle-api-v2` PR with both domain markers still `v1_active` and new mutation actions capability-gated off. Exact-head review must prove the new APIs are real adoption sites for the store kernel while no old writer has changed yet. Merge before Task 5 or Store Task 8.

## Task 5: Preserve Legacy Mutations Through Static V2 Adapters

**Files:**
- Modify: `api/routers/material_sync.py`
- Modify: `api/routers/lut_registry.py`
- Modify: `api/routers/lut.py`
- Modify: `api/routers/single_stage.py`
- Modify: `api/routers/material_registry.py`
- Modify: `core/single_stage/materials.py`
- Modify: `api/services/lut_registry_sync.py`
- Modify: `tests/test_resource_mutation_origin_unit.py`
- Create: `tests/test_resource_legacy_adapters_unit.py`
- Modify: `tests/test_material_sync_api_unit.py`
- Modify: `tests/test_lut_registry_sync_unit.py`
- Modify: `tests/test_lut_api_unit.py`
- Modify: `tests/test_single_stage_unit.py`
- Modify: `tests/test_material_registry_api_unit.py`

- [ ] **Step 1: Freeze all old request/response contracts**

Build and freeze an explicit persistent-mutation inventory: material-sync multipart `/install`, both `/install-from-registry` request shapes, `/refresh`, `/rollback`; LUT-registry `/install`; LUT `/upload` and `/merge`; single-stage gradient-card material `/save-gradient-card-material`, DELETE/PATCH, and bulk import; and embedded material-registry package upload/upload-local/approve. Cover their current request/response/error contracts plus read-only `/status`/catalog/export/compare/detail routes. For every local upload/import, add unsafe archive, oversized/expanded/compression-limit, invalid LUT allocation header, source path-swap, fake official metadata, partial staging, and filename/path-conflict cases; failure leaves no local record, reservation, spool, or unowned file. An AST/app-route test fails when a new POST/PATCH/PUT/DELETE under these resource families lacks an explicit classification and either `require_resource_mutation_origin` or a documented read-only exemption. Assert browser-provided URL/hash/path/channel values cannot affect server resolution.

- [ ] **Step 2: Implement marker-selected static adapters**

Every old material/LUT-library mutating route is classified by the outer `ResourceMutationOriginMiddleware`, rechecks through `require_resource_mutation_origin`, then acquires a domain writer ticket, reads `resource-store-marker.json`, and dispatches through a statically registered adapter generation. At `v1_active`, call old implementation. At `v2_committed/resources-v2-1`, call `ResourceStore` and project the old response. At migration/recovery/unknown adapter, reject writes; never fall back based on an in-memory flag. Add a cross-site/public-gray test for every inventory mutation and prove the outer guard runs before receive/parsing/staging and the dependency runs before Registry calls, backups, cache invalidation, or either adapter.

- [ ] **Step 3: Preserve local multipart and read-only ownership**

After cutover, material multipart/bulk imports and LUT upload first build `VerifiedLocalImportBinding` through the domain adapter, then call `ResourceStore.import_local`; preserve content type, field names, and response shape. They never pass an `UploadFile`, multipart filename, claimed publisher/channel, or browser path into the store and never create a managed ref from package metadata. LUT merge resolves/leases ordered inputs, writes a derived `local_copy` with source provenance, and never edits a managed payload. Gradient-card save creates a validated local import; PATCH/DELETE resolve the indexed local item and reject managed content with `409 managed_resource_read_only`. Existing edit/delete/export APIs resolve stable local IDs/validated paths; export is read-only and may resolve managed or local bytes under leases. Legacy local delete internally requires current facts to equal the indexed observation and fails closed when changed; it cannot manufacture the new UI's confirmation ETag after the request starts. New local DELETE uses detail `ETag`/`If-Match`. Create-local-copy duplicates into editable local storage with source provenance; no managed file is edited in place.

The embedded `api/routers/material_registry.py` package staging root remains a separately guarded legacy maintenance surface because it stores review ZIPs, not active material payloads. Keep its existing password and response/channel contracts, but it never writes the v2 resource index, never supplies `publisher_kind`, and never makes `channel="official"` imply `lumina`. New Resource Center APIs and badges do not consume it. Add tests proving an embedded-package approval changes only that isolated package root/cache and cannot change managed/local state or current publisher display.

- [ ] **Step 4: Keep legacy refresh distinct from update-all**

`/api/material-sync/refresh` fetches one complete no-limit v1 catalog, checks every returned revision in order, skips revisions already present either as managed active/previous/pending content, as a local record with the same complete source ref, or as current local bytes whose validated package kind/ID/revision/canonical content identity all match without claiming authority, imports every other missing revision even for a previously unseen logical material, continues per-item failures, and preserves all old count/list/message fields and input order. After v2 cutover, refresh is deliberately a legacy bulk-import adapter rather than a sequence of managed updates. It validates the downloaded v1 compatibility artifact as a local package, recomputes canonical core identity from payload bytes, and may create a `local_copy` with non-authoritative source ref only when one fresh online exact-detail read has the same Registry key/kind/ID/revision/algorithm/canonical hash. It does not compare the v1 package SHA/schema with the distinct v2 artifact, does not download v2 merely to bless the local copy, and never persists exact-detail envelope/package fields. A v1-only or offline package becomes `local_import` with null source ref. It never churns one resource's bounded managed current/previous/pending slots, never grants official/managed ownership from v1 metadata, and repeated refresh is idempotent by a fresh full local content scan rather than name/path/hash alone. Explicit install-from-registry and new lifecycle routes are the only paths that create/update managed cloud state. New update-all touches only managed resources with newer revisions. Add three-revision/same-resource and representation-mismatch tests proving refresh retains all missing payloads without `history_busy`, repeats as no-op, installs a missing old revision that update-all does not, and never records v1 transport hash as v2 identity.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest tests/test_resource_legacy_adapters_unit.py tests/test_material_sync_api_unit.py tests/test_lut_registry_sync_unit.py -q
git add api/routers/material_sync.py api/routers/lut_registry.py api/routers/lut.py api/routers/single_stage.py api/routers/material_registry.py core/single_stage/materials.py api/services/lut_registry_sync.py tests/test_resource_mutation_origin_unit.py tests/test_resource_legacy_adapters_unit.py tests/test_material_sync_api_unit.py tests/test_lut_registry_sync_unit.py tests/test_lut_api_unit.py tests/test_single_stage_unit.py tests/test_material_registry_api_unit.py
git commit -m "feat(resources): route legacy mutations through v2 stores"
```

## Task 6: Split Scheduler Checks From Installation

**Files:**
- Modify: `api/material_sync_scheduler.py`
- Modify: `core/single_stage/materials.py`
- Create: `tests/test_resource_update_check_unit.py`
- Modify: `tests/test_material_sync_scheduler_unit.py`

- [ ] **Step 1: Write no-write scheduler tests**

Snapshot index/files and run startup/interval checks with catalog updates, missing resources, unreachable Registry, partial malformed catalog, and both cutover states. Assert no package download, install, update, rollback, path creation outside public metadata cache, index generation change, or v1 refresh call.

- [ ] **Step 2: Implement read-only `check_resource_updates`**

Fetch/revalidate catalog and compute update availability against managed active refs. Only a different approved revision ID with its canonical ref sets `update_available`; a changed envelope/package/publisher/display on the same revision updates request-local metadata freshness only. Existing `LUMINA_MATERIAL_SYNC_STARTUP_REFRESH` and interval settings map to checks and emit one deprecation event, not installation. The scheduler never writes installed display/envelope records and never calls legacy refresh or update-all.

- [ ] **Step 3: Run and commit**

```bash
python -m pytest tests/test_resource_update_check_unit.py tests/test_material_sync_scheduler_unit.py -q
git add api/material_sync_scheduler.py core/single_stage/materials.py tests/test_resource_update_check_unit.py tests/test_material_sync_scheduler_unit.py
git commit -m "fix(resources): make background sync read-only"
```

Together with Store Tasks 8-10, run every legacy request/response, writer-drain, mixed-domain, migration recovery, repair, and scheduler no-write test; open the `resource-store-cutover-v2` PR. Exact-head review must prove cutover can commit only for the domain whose old writers have drained and whose complete adapter generation is present. Merge before Task 7.

## Task 7: Ordered Resource Selection And Explicit Material Paths

**Files:**
- Create: `api/services/resource_selection.py`
- Modify: `core/material_lut_synthesis.py`
- Modify: `core/material_lut_provider.py`
- Modify: `utils/lut_manager.py`
- Create: `tests/test_resource_selection_unit.py`
- Modify: `tests/test_lut_loader_unit.py`
- Modify: `tests/test_material_lut_provider_unit.py`
- Modify: `tests/test_material_lut_synthesis_unit.py`
- Modify: `tests/test_lut_canary_integration_unit.py`

- [ ] **Step 1: Write ordered selection tests**

Cover one LUT, legacy multi-LUT with same names/different IDs, missing middle item, incompatible first/middle/last LUT, color-mode aliases, exact refs out of order, material slots with duplicate titles, backing index, pure local null refs, local-equivalent versus managed, active update during resolve, and exact historical revision. Assert order and null positions never compact/re-sort/deduplicate, and compatibility is evaluated for every selected exact payload rather than inferred from the first LUT, display name, metadata field alone, or requested mode alone.

- [ ] **Step 2: Add explicit path loaders without changing old signatures**

Create `load_material_params_from_path(material_dir, directory_name)` and `load_multiple_material_paths(selections)`. Existing `load_material_params`/`load_multiple_materials` remain and call the path version after safe legacy resolution. Cache keys include immutable path and file identity/hash, not just mutable display names.

- [ ] **Step 3: Add managed LUT projections and explicit resolution**

`LUTManager.get_all_lut_files()` continues legacy display projection but ignores `_sync` scans. Resource-store active aliases are injected through a provider, not discovered recursively. Add a new explicit resolver that takes ordered `ResourceRevisionRef | None` plus legacy names; a complete ref always wins and must hash-match. Existing `resolve_source_selection` remains callable and delegates legacy names through aliases.

- [ ] **Step 4: Implement all-or-rollback selection acquisition**

Mint session/job owner first. Acquire leases in canonical revision-lock order while preserving caller order in the returned list. Load/validate RGB entries, metadata, palette, canonical color mode, base channel, layer order, stacks/recipe rebuild, and requested workflow compatibility for every selected LUT; validate every material role/slot and backing index against the same resolved list. If any item is missing/incompatible/fenced, release every lease acquired by this call and return a per-index diagnostic. Multi-LUT runtime bundle creation consumes the ordered immutable paths; material paths are passed as scalar strings to workers.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest tests/test_resource_selection_unit.py tests/test_lut_loader_unit.py tests/test_material_lut_provider_unit.py tests/test_material_lut_synthesis_unit.py tests/test_lut_canary_integration_unit.py -q
git add api/services/resource_selection.py core/material_lut_synthesis.py core/material_lut_provider.py utils/lut_manager.py tests/test_resource_selection_unit.py tests/test_lut_loader_unit.py tests/test_material_lut_provider_unit.py tests/test_material_lut_synthesis_unit.py tests/test_lut_canary_integration_unit.py
git commit -m "feat(resources): resolve ordered material and LUT revisions"
```

## Task 8: Adopt Resolver In Every Reading Workflow

**Files:**
- Modify: `api/routers/converter/preview.py`
- Modify: `api/routers/converter/generate.py`
- Modify: `api/routers/converter/replace.py`
- Modify: `api/routers/converter/puzzle.py`
- Modify: `api/routers/converter/color_card.py`
- Modify: `api/routers/lut.py`
- Modify: `api/routers/five_color.py`
- Modify: `api/routers/extractor.py`
- Modify: `api/routers/single_stage.py`
- Modify: `core/lut_details/service.py`, `core/lut_details/parser.py`
- Modify: `api/feedback_assembler.py`
- Modify: `api/services/lut_presentation.py`
- Modify: `core/converter.py`
- Modify: `core/extractor.py`
- Modify: `core/lut_merger.py`
- Modify: `core/vector_engine.py`
- Create: `tests/test_resource_workflow_resolution_unit.py`
- Modify: `tests/test_api_routers_unit.py`
- Modify: `tests/test_lut_canary_integration_unit.py`
- Modify: `tests/test_converter_structure_contract_unit.py`

- [ ] **Step 1: Build the managed-read inventory**

Run:

```bash
rg -n 'LUTManager\.(get_lut_path|get_all_lut_files|resolve_source_selection|load_lut_with_metadata)|load_multiple_materials|load_materials\(' api core utils --glob '*.py'
```

Classify every result as list projection, local-only read, or workflow payload read. Put the reviewed inventory in the PR body. Every managed payload read must resolve/lease; list projection may use aliases; pure local reads retain safe local resolution.

- [ ] **Step 2: Write end-to-end workflow resolver tests**

For preview/generate/replace/batch/extractor/LUT merge/compare/details/five-color/material calibration, update active revision after resolve and assert the workflow still reads old immutable bytes. Attempt uninstall during the workflow and expect `resource_in_use`. Release and retry uninstall. Include session switch/close and source file deletion attempts. Persist a Postgres-backed session, terminate the owning API process, start a new app process, and resume each workflow: old token IDs/relative paths must never authorize I/O; the new process must reacquire exact refs/local IDs and atomically replace the serialized handle bundle before dispatch. Cover missing/fenced/withdrawn exact revisions, changed local record versions, partial ordered multi-LUT reacquisition, SessionStore compare-and-swap conflict, and a stale token file owned by the dead process. Every failure releases newly acquired tokens, performs zero payload I/O, preserves per-index diagnostics/order, and never falls back to latest, a legacy path, or the dead token.

- [ ] **Step 3: Move owner minting before resolution**

Preview mints session ID before LUT/material resolution; batch and short operations mint job ID. Resolve in the main process and pass only scalar paths/metadata plus lease/local-token ID, expected fence-or-local-record version, token version, and job ID to top-level picklable worker entry points; never let a worker re-resolve current/latest. Before opening any managed/local path, the worker registers its own durable `ReaderGuardRecord`, rechecks the token/fence/version, performs I/O, and releases the guard in `finally`. The main process retains the parent token until the worker future has converged. If the API process dies, the live worker guard prevents a restarted process from deleting its input; if registration fails, the worker performs zero payload I/O. On pre-session/dispatch failure, release by owner in `finally`.

- [ ] **Step 4: Store both legacy projections and exact handles**

Session data keeps old `lut_name`, ordered `lut_names`, and `selected_materials` for compatibility plus safe serialized exact managed refs, stable local IDs with expected local-record version and canonical content-hash algorithm/hash, store IDs, lease/local-token IDs, and immutable/local relative paths for new code. Postgres SessionStore codec tests must round-trip these JSON-safe values and reject absolute path fields. Persisted token IDs and relative paths are restart/resume hints only: before any resumed workflow payload I/O, compare every formal token's owner to the current opaque `ProcessIdentity`; an absent, dead-process, mismatched, fenced, or otherwise stale token is never renewed or trusted. Re-resolve the ordered exact managed refs or the exact stable-local-ID/version/hash tuples under current store state, acquire fresh current-process leases/locks in canonical lock order, then compare-and-swap one complete replacement handle bundle into the still-current SessionStore version before dispatch. A changed local record/version/hash is an indexed failure, not permission to adopt the current local bytes. A CAS loss or any item failure releases every newly acquired token and returns typed per-index diagnostics with zero payload I/O; it cannot reuse a partial old/new bundle or select latest/same-name content. Startup stale-owner convergence remains responsible for old formal files and cannot make them valid for the resumed session. The current process may compose an absolute resolved path only into a nonserialized short-lived job context immediately before worker dispatch; it is never written to memory/Postgres SessionStore, a bug-report context, logs, recipe, or frontend response. No token or Registry URL/query enters either representation.

- [ ] **Step 5: Run workflow gates and commit**

```bash
python -m pytest tests/test_resource_workflow_resolution_unit.py tests/test_api_routers_unit.py tests/test_lut_canary_integration_unit.py tests/test_converter_structure_contract_unit.py -q
git add api/routers/converter/preview.py api/routers/converter/generate.py api/routers/converter/replace.py api/routers/converter/puzzle.py api/routers/converter/color_card.py api/routers/lut.py api/routers/five_color.py api/routers/extractor.py api/routers/single_stage.py api/feedback_assembler.py api/services/lut_presentation.py core/lut_details/service.py core/lut_details/parser.py core/converter.py core/extractor.py core/lut_merger.py core/vector_engine.py tests/test_resource_workflow_resolution_unit.py tests/test_api_routers_unit.py tests/test_lut_canary_integration_unit.py tests/test_converter_structure_contract_unit.py
git commit -m "feat(resources): pin workflow inputs to exact revisions"
```

Repeat the managed-read search after edits. Any remaining direct read must have a documented local-only/list-projection reason.

## Task 9: Session Heartbeat, Expiry, Close, And Shutdown Leases

**Files:**
- Create: `api/resource_session_leases.py`
- Modify: `api/routers/session.py`
- Modify: `api/app.py`
- Modify: `api/routers/converter/cleanup.py`
- Test: `tests/test_resource_session_leases_unit.py`
- Modify: `tests/test_session_routes_unit.py`
- Modify: `tests/test_session_value_codec_unit.py`

- [ ] **Step 1: Write race tests**

For managed `LeaseRecord` and local `LocalLockRecord`, cover heartbeat versus explicit close, heartbeat versus expiration cleanup, release while renew is in flight, session not yet stored after preview resolve, worker guard registration/release, API crash with a live worker, worker failure, process shutdown, Postgres/memory SessionStore, fenced managed renew, changed local-record-version renew, and app restart with a persisted session carrying dead-process token IDs/relative paths. Assert coordinator serializes each owner, stops heartbeat before release, uses each token's last returned version, cannot recreate either record, and keeps managed GC/local delete blocked for every live exact reader. On restart, assert current-process exact reacquisition plus SessionStore CAS succeeds before dispatch, while stale/missing/formally live-other-process tokens, partial reacquisition, and CAS conflict produce zero payload I/O and release only the newly acquired records.

- [ ] **Step 2: Implement coordinator**

`ResourceSessionLeaseCoordinator` scans formal material/LUT managed leases and local lock tokens by `session_id` or `job_id`, holds a per-owner process lock, renews each discriminated token with expected fence-or-local-record-version plus token version, updates only after success, releases all with aggregate diagnostics, and supports startup cleanup of dead owners. It renews only records whose complete opaque owner identity equals the current process; a persisted session that names another/dead/absent owner is routed through the Task 8 exact reacquisition/CAS path, never heartbeat renewal. Fenced/unavailable renew of either kind marks the owner failed so new I/O stops.

- [ ] **Step 3: Integrate endpoint and cleanup order**

Heartbeat renews managed resource leases and local lock tokens before extending SessionStore TTL. Explicit close stops new dispatch and coordinator renew, requests cancellation, and drains owned jobs for a configured default 30-second/hard-120-second bound. If any worker/reader guard remains live or ambiguous at the bound, return deterministic `409 resource_jobs_in_use`, restore renewal for the still-active session, and leave session/temp/parent records intact; a successful retry follows the normal release order. Once jobs converge, verify guards released or process owners are dead, release both parent record kinds, then clean session/temp files. Periodic cleanup applies the same ordering for every expired session ID returned by `cleanup_expired`; the still-formal parent token/reader-guard records are the durable deferred-cleanup evidence, and every temp cleaner rechecks them by session/job before deleting. It retries after convergence rather than restoring an expired session or deleting its files early; stale-delete handles process crashes without clearing a live worker guard. App shutdown stops new work, drains within the same hard bound, requests worker termination through the existing pool when needed, proves every remaining guard process dead/reused before parent release, then cleans up and shuts the pool down; if proof is ambiguous, preserve records/files for startup recovery and report non-clean shutdown rather than hanging or deleting.

`cleanup-session-files` preserves session resource leases because the session remains active; it releases only when the session is actually closed.

- [ ] **Step 4: Run and commit**

```bash
python -m pytest tests/test_resource_session_leases_unit.py tests/test_session_routes_unit.py tests/test_session_store_clear_properties.py tests/test_session_store_properties.py tests/test_session_thread_safety_properties.py tests/test_session_ttl_properties.py tests/test_session_value_codec_unit.py -q
git add api/resource_session_leases.py api/routers/session.py api/app.py api/routers/converter/cleanup.py tests/test_resource_session_leases_unit.py tests/test_session_routes_unit.py tests/test_session_value_codec_unit.py
git commit -m "feat(resources): renew and release workflow leases"
```

The listed files are the current memory/session contracts. Add a focused Postgres lease-coordinator test to `tests/test_resource_session_leases_unit.py` by injecting the existing Postgres SessionStore test double; do not require a live database.

Run the full ordered-selection/managed-read/session-restart matrix, repeat the direct-read inventory, and open the `resource-workflow-pinning-v2` PR. Exact-head review must prove every managed payload read acquires the exact revision, every local read binds exact version/hash, failed multi-selection performs zero payload I/O, and no persisted dead-process token authorizes resumed work. Merge before Task 10.

## Task 10: Recipe V3 Ordered Provenance

**Files:**
- Create: `frontend/src/types/resources.ts`
- Modify: `frontend/src/recipe/types.ts`
- Modify: `frontend/src/recipe/exportRecipe.ts`
- Modify: `frontend/src/recipe/importRecipe.ts`
- Modify: `frontend/src/recipe/migration.ts`
- Modify: `frontend/src/recipe/importFlow.ts`
- Modify: `frontend/src/recipe/pngMetadata.ts`
- Modify: `frontend/src/stores/converter/store.ts`
- Modify: `frontend/src/api/converter.ts`
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/__tests__/resource-provenance-recipe.test.ts`
- Modify: `frontend/src/__tests__/recipe-roundtrip.property.test.ts`
- Modify: `frontend/src/__tests__/recipe-export.test.ts`
- Modify: `frontend/src/__tests__/recipe-import.test.ts`
- Modify: `frontend/src/__tests__/recipe-png-metadata.test.ts`
- Modify: `frontend/src/__tests__/recipe-integration.test.ts`

- [ ] **Step 1: Define exact TypeScript types and failing tests**

```typescript
// frontend/src/types/resources.ts
export interface ResourceRevisionRef {
  source_registry: string;
  resource_kind: "material" | "lut";
  resource_id: string;
  revision_id: string;
  content_hash_algorithm: string;
  content_hash: string;
}

// frontend/src/recipe/types.ts imports ResourceRevisionRef from ../types/resources.
export interface ResourceProvenance {
  schema_version: "1.0";
  legacy_luts: Array<{
    selection_index: number;
    name: string;
    resource: ResourceRevisionRef | null;
  }>;
  materials: Array<{
    slot_index: number;
    directory_name: string;
    resource: ResourceRevisionRef | null;
  }>;
  backing_material: {
    directory_name: string;
    selected_material_index: number | null;
    resource: ResourceRevisionRef | null;
  } | null;
}
```

Define `ResourceRevisionRef` only in `frontend/src/types/resources.ts`; recipe types and the later resource-center feature import it rather than declaring structural copies. Add `resource_provenance?: ResourceProvenance` under `ConverterRecipeSource`, bump exported recipe schema to 3, and test ordered duplicate names, null middle entries, backing equality, multi-LUT first-item legacy projection, and v1/v2 migration.

- [ ] **Step 2: Validate hard cardinality/index/name rules**

V3 import rejects wrong array length, non-contiguous index, name/directory mismatch, wrong resource kind, partial ref, invalid backing index, backing item mismatch, unknown algorithm, malformed hash, and exact detail hash mismatch. It never compacts nulls or selects latest/same-name fallback.

- [ ] **Step 3: Resolve missing exact revisions during import**

Import first validates integrity and structure. For each missing complete ref, call Studio exact status/reinstall flow and present a deterministic missing-resource action; offline or withdrawn revision remains unresolved with a visible warning. Pure local null references preserve legacy names/paths and never trigger cloud guessing.

- [ ] **Step 4: Keep PNG share cards on the same recipe object**

Do not create a second provenance schema. Share-card encode/decode includes schema v3 recipe and integrity hash. Round-trip tests compare the complete ordered provenance object.

- [ ] **Step 5: Run frontend tests and commit**

```bash
python scripts/run_vitest.py run src/__tests__/resource-provenance-recipe.test.ts src/__tests__/recipe-roundtrip.property.test.ts src/__tests__/recipe-export.test.ts src/__tests__/recipe-import.test.ts src/__tests__/recipe-png-metadata.test.ts src/__tests__/recipe-integration.test.ts
```

Expected: all pass.

```bash
git add frontend/src/types/resources.ts frontend/src/recipe/types.ts frontend/src/recipe/exportRecipe.ts frontend/src/recipe/importRecipe.ts frontend/src/recipe/migration.ts frontend/src/recipe/importFlow.ts frontend/src/recipe/pngMetadata.ts frontend/src/stores/converter/store.ts frontend/src/api/converter.ts frontend/src/api/types.ts frontend/src/__tests__/resource-provenance-recipe.test.ts frontend/src/__tests__/recipe-roundtrip.property.test.ts frontend/src/__tests__/recipe-export.test.ts frontend/src/__tests__/recipe-import.test.ts frontend/src/__tests__/recipe-png-metadata.test.ts frontend/src/__tests__/recipe-integration.test.ts
git commit -m "feat(recipe): preserve exact ordered resource provenance"
```

## Task 11: Bug Report And Reproduction Provenance

**Files:**
- Modify: `frontend/src/utils/bugReportContext.ts`
- Modify: `frontend/src/api/feedback.ts`
- Modify: `api/routers/feedback.py`
- Modify: `api/feedback_assembler.py`
- Modify: `api/feedback_index.py`
- Modify: `api/feedback_email.py`
- Modify: `scripts/load_bug_repro.py`
- Modify: `tests/test_feedback_assembler_unit.py`
- Modify: `tests/test_feedback_assembler_integration_unit.py`
- Modify: `tests/test_feedback_router_unit.py`
- Modify: `tests/test_feedback_sanitizer_unit.py`
- Modify: `tests/test_feedback_index_unit.py`
- Modify: `tests/test_feedback_email_unit.py`
- Modify: `tests/test_feedback_ticket_unit.py`
- Modify: `tests/test_feedback_canary_integration_unit.py`
- Modify: `tests/test_feedback_materials_bundle_unit.py`
- Modify: `frontend/src/utils/__tests__/bugReportContext.test.ts`
- Modify: `frontend/src/api/__tests__/feedback.test.ts`
- Modify: `frontend/src/components/__tests__/BugReportModal.test.tsx`

- [ ] **Step 1: Write API and round-trip tests first**

Add optional `context.resource_provenance` using the exact Recipe shape. Test ordered multi-LUT/material/backing/null round trip, payload size/list limits, invalid/partial refs, legacy absence, ticket JSON, index/summary rendering, missing/restricted attachment diagnostics, and attachment/email allowlists. The complete canonical `content_hash` is intentionally retained as exact identity, but no ticket JSON, index, summary, email body, browser response, or attachment manifest may contain `package_sha256`, Registry/package/preview URL, envelope/query, Authorization/token, client absolute path, resolved server path, or SessionStore path. Ticket attachment locations are normalized ticket-relative names only.

- [ ] **Step 2: Capture and sanitize provenance**

Frontend derives provenance from current ordered selections and backend resource states, not from display-card position after filtering. Backend validates cardinality/index/name and safe string lengths, then stores the normalized object unchanged in `reproduction.json.context.resource_provenance`/ticket context. Sanitization parses the browser page URL and keeps only the existing safe route facts; it drops query/fragment and never serializes a Registry origin or package locator copied from logs/errors.

- [ ] **Step 3: Collect exact attachments server-side**

Generic LUT/material collectors first classify every selected path through ResourceStore and exclude all managed cloud payloads from the legacy `lut.*`/`materials.zip` bundlers, preventing the old path-based collector from bypassing distribution policy. For a complete managed ref, the assembler takes a short job lease and performs one fresh anonymous exact-authorization check through the server Registry client. It may copy the exact verified revision into the ticket only when that check proves the current envelope is anonymously public. Team/token-bearing content becomes `restricted_not_attached`; offline/timeout/indeterminate authorization becomes `authorization_unavailable`; missing/withdrawn/fenced content keeps its typed unavailable status. It never falls back to an installed snapshot, cached public metadata, latest, same-name content, or a caller-provided path.

The assembler emits an explicit bounded `email_attachment_names` allowlist containing only ticket-owned regular files eligible for email. `feedback_email.py` opens only those normalized direct children with no-follow identity/size checks and never iterates arbitrary ticket contents, follows a link, or attaches a restricted/unclassified managed payload. Client disk paths remain diagnostic-only sanitized labels. Per-index statuses survive ticket/index/summary/email rendering without exposing an absolute path or authorization reason detail.

- [ ] **Step 4: Reproduce exact or report unresolved**

`load_bug_repro.py` validates positional mapping, accepts only a ticket-relative attachment whose manifest position/kind/ref and canonical content identity all match, then attempts exact Registry reinstall by full ref when the operator's current server configuration permits it. `restricted_not_attached`, authorization failure, hash/algorithm mismatch, or unavailable exact revision is reported in `repro_manifest.md`; it never substitutes latest or discloses the configured Registry URL/token.

- [ ] **Step 5: Run feedback gates and commit**

```bash
python -m pytest \
  tests/test_feedback_assembler_unit.py \
  tests/test_feedback_assembler_integration_unit.py \
  tests/test_feedback_router_unit.py \
  tests/test_feedback_sanitizer_unit.py \
  tests/test_feedback_index_unit.py \
  tests/test_feedback_email_unit.py \
  tests/test_feedback_ticket_unit.py \
  tests/test_feedback_canary_integration_unit.py \
  tests/test_feedback_materials_bundle_unit.py -q
python scripts/run_vitest.py run \
  src/utils/__tests__/bugReportContext.test.ts \
  src/api/__tests__/feedback.test.ts \
  src/components/__tests__/BugReportModal.test.tsx
```

```bash
git add frontend/src/utils/bugReportContext.ts frontend/src/api/feedback.ts frontend/src/utils/__tests__/bugReportContext.test.ts frontend/src/api/__tests__/feedback.test.ts frontend/src/components/__tests__/BugReportModal.test.tsx api/routers/feedback.py api/feedback_assembler.py api/feedback_index.py api/feedback_email.py scripts/load_bug_repro.py tests/test_feedback_assembler_unit.py tests/test_feedback_assembler_integration_unit.py tests/test_feedback_router_unit.py tests/test_feedback_sanitizer_unit.py tests/test_feedback_index_unit.py tests/test_feedback_email_unit.py tests/test_feedback_ticket_unit.py tests/test_feedback_canary_integration_unit.py tests/test_feedback_materials_bundle_unit.py
git commit -m "feat(feedback): capture exact resource provenance"
```

Run the recipe/share-card/feedback/reproduction round trips and attachment-exfiltration matrix, then open the `resource-provenance-v3` PR. Exact-head review must validate ordered duplicate/null positions and exact historical reinstall behavior independently of the later logging/gate-only delta. Merge before Task 12.

## Task 12: Logging, Compatibility Matrix, And Integration PR Gate

**Files:**
- Modify: `api/services/resource_center.py`
- Modify: `tests/test_logging_exception_governance_unit.py`
- Modify: `tests/test_resource_center_api_unit.py`
- Modify: `docs/context/resource-store/CONTEXT.md`
- Create: `tests/test_resource_download_session_lifecycle_unit.py`

**Verification-only existing suites:**
- `tests/test_resource_workflow_resolution_unit.py`
- `tests/test_resource_session_leases_unit.py`

`docs/context/resource-store/CONTEXT.md` is created by Store Task 10 in the merged lifecycle PR before this provenance task starts; update that canonical ownership document rather than creating a second integration context.

- [ ] **Step 1: Add bounded structured lifecycle events**

Use operation-specific event names: `resource_install_*`, `resource_update_*`, `resource_rollback_*`, `resource_uninstall_*`, `resource_repair_*`, `resource_adopt_local_equivalent_*`, `resource_create_local_copy_*`, `resource_detach_management_*`, `resource_local_delete_*`, and `resource_update_all_*`, where `*` is `done` or `failed`. Do not add a catch-all `resource_lifecycle_*`, `request_*`, or `status_*` event. Each single mutation emits exactly one INFO success convergence event or one actionable WARNING/ERROR failure with request ID, kind, bounded normalized ID, revision, operation, prior/final state, package bytes, duration, and safe error type/message. Update-all emits one INFO summary and at most eight item failure records plus `failed_count`/`failure_logs_truncated`; it never emits one INFO per item. Intermediate transaction/lease progress is DEBUG.

Add the exact literal set as `RESOURCE_CENTER_STRUCTURED_EVENTS` in `tests/test_logging_exception_governance_unit.py`, add `api/services/resource_center.py` to the governed targets, and test event cardinality/safe fields in `tests/test_resource_center_api_unit.py`. Do not log token, authorization, private URL/query, principal fingerprint, full package/content hash, package-controlled display text, absolute path, session/job/lease/guard ID, or traceback. Registering events may not increase the existing per-request/full-workflow INFO budgets or weaken any baseline.

- [ ] **Step 2: Run logging governance**

```bash
python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v
python scripts/log_quality_check.py --mode fast
```

Expected: PASS without weakening thresholds or adding catch-all events.

- [ ] **Step 3: Run the complete backend compatibility matrix**

```bash
python -m pytest \
  tests/test_resource_contract_fixtures_unit.py \
  tests/test_resource_registry_client_unit.py \
  tests/test_resource_registry_cache_unit.py \
  tests/test_resource_package_binding_unit.py \
  tests/test_resource_center_api_unit.py \
  tests/test_resource_legacy_adapters_unit.py \
  tests/test_resource_update_check_unit.py \
  tests/test_resource_selection_unit.py \
  tests/test_resource_workflow_resolution_unit.py \
  tests/test_resource_session_leases_unit.py \
  tests/test_material_sync_api_unit.py \
  tests/test_lut_registry_sync_unit.py \
  tests/test_material_sync_scheduler_unit.py \
  tests/test_feedback_assembler_unit.py -q
```

Expected: all pass.

Run the exact frontend provenance matrix as well:

```bash
python scripts/run_vitest.py run \
  src/__tests__/resource-provenance-recipe.test.ts \
  src/__tests__/recipe-roundtrip.property.test.ts \
  src/__tests__/recipe-export.test.ts \
  src/__tests__/recipe-import.test.ts \
  src/__tests__/recipe-png-metadata.test.ts \
  src/__tests__/recipe-integration.test.ts \
  src/utils/__tests__/bugReportContext.test.ts \
  src/api/__tests__/feedback.test.ts \
  src/components/__tests__/BugReportModal.test.tsx
```

Expected: all listed backend and frontend files pass; record these exact commands and counts in the provenance PR.

- [ ] **Step 4: Re-run managed-read and legacy-writer inventories**

Search direct LUT/material reads and every mutating endpoint/scheduler. The PR body maps each to resolver/provider or writer admission adapter. Any unmanaged direct managed-root operation is blocking.

- [ ] **Step 5: Verify session-close download regression**

In `tests/test_resource_download_session_lifecycle_unit.py`, generate `.3mf`, `.zip`, recipe, and share-card artifacts, capture their final URLs, close and separately switch the source session, release all resource leases, then fetch each URL through the real download router. They remain TTL/ephemeral as currently required and byte/hash match the pre-close response; resource lease release cannot delete final downloads. Advance the injected TTL beyond expiry and assert deterministic expiration. Preview/cache artifacts may remain session-bound.

Run:

```bash
python -m pytest tests/test_resource_download_session_lifecycle_unit.py -q
```

Expected: all artifact types survive close/switch and expire only at their own TTL.

- [ ] **Step 6: Run diff/secret/path scans and open the integration-gate PR**

```bash
git add api/services/resource_center.py tests/test_logging_exception_governance_unit.py tests/test_resource_center_api_unit.py tests/test_resource_download_session_lifecycle_unit.py docs/context/resource-store/CONTEXT.md
git commit -m "chore(resources): complete integration release gates"
git diff --check origin/dev-refactor...HEAD
POSIX_HOME_PATTERN="$(printf '/%s/' Users)"
WINDOWS_HOME_PATTERN="$(printf '[A-Za-z]:\\\\%s\\\\' Users)"
SENSITIVE_PATTERN='Bearer[[:space:]]+[A-Za-z0-9._~+/-]+|BEGIN[[:space:]]+(RSA[[:space:]]+|EC[[:space:]]+|OPENSSH[[:space:]]+)?PRIVATE[[:space:]]+KEY|LUMINA_[A-Z0-9_]*(TOKEN|SECRET|KEY)[A-Z0-9_]*[[:space:]]*=[[:space:]]*[^$[:space:]]'
rg -n --hidden --glob '!\.git/**' --glob '!tests/fixtures/**' "(${SENSITIVE_PATTERN}|${POSIX_HOME_PATTERN}|${WINDOWS_HOME_PATTERN})"
```

Open `resource-integration-gates-v2`. Its PR body records exact Registry fixture/service commit, Studio store/provenance commits, base/head, capability/fallback evidence, legacy response evidence, resolver inventory, lease race matrix, provenance round trips, full command counts, session-close downloads, and scans. Request a fresh exact-head review; prior feature-PR approvals do not approve this gate delta.

## Integration Merge Gates

Registry client PR is blocked unless:

- vendored fixture bytes match exact Registry commit;
- v1 capability fallback is complete and harmless;
- browser/client fields cannot select URL/hash/path/envelope;
- package origin/redirect/size/time/hash/bytes/header/binding checks are complete;
- only anonymous public metadata persists and offline cache cannot authorize install.

Lifecycle/API PR is blocked unless:

- both domains expose independent capability/actions;
- every old/new resource mutation is origin-guarded, public-gray does not bypass it, and remote write mode requires exact HTTPS Origin/Host plus authenticated reverse-proxy isolation;
- material/LUT wire IDs and paths stay domain-specific and generic resource IDs are rejected;
- lease/local-lock/lifecycle/guarded-delete races pass while both domain markers remain `v1_active`;
- no old mutation or scheduler behavior changes in this PR.

Cutover/legacy-adapter PR is blocked unless:

- every legacy mutation uses persistent writer admission and static marker adapter;
- material multipart and old JSON/LUT responses remain compatible;
- legacy refresh and new update-all remain behaviorally distinct;
- scheduler cannot write;
- cutover commits only after that domain's in-flight old writers drain, while the other domain may remain v1;
- repair/recovery ambiguity keeps writes closed without deleting content.

Workflow-pinning PR is blocked unless:

- every managed payload read resolves exact immutable paths and holds a lease;
- every local payload read binds exact record version/content hash and holds a local lock;
- multi-LUT/material/backing order survives resolution;
- session/job heartbeat, close, expiry, failure, and shutdown release correctly;
- Postgres SessionStore restart reacquires the whole ordered handle set before I/O and rejects stale/partial/CAS-conflicted bundles.

Provenance PR is blocked unless:

- recipe v3/share-card/bug-report use one exact ordered schema;
- v1/v2 imports remain compatible;
- null local entries preserve position;
- exact reinstall never substitutes latest/name/ID-neighbor revision;
- feedback attachments are server-authorized and per-item missing diagnostics survive;
- backend/frontend provenance and secret checks pass at the exact reviewed head.

Integration-gate PR is blocked unless:

- logging governance/INFO budgets and the complete backend/frontend compatibility matrix pass;
- the repeated direct-read/legacy-writer inventory has no unexplained managed-root access;
- final download URLs survive source session close/switch and expire only at artifact TTL;
- context ownership docs and exact upstream commit evidence are current;
- all diff/secret/path scans pass at the exact reviewed head.
