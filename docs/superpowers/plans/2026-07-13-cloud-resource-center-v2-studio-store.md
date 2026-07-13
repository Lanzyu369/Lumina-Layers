# Cloud Resource Center V2 Studio Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a crash-safe, cross-process, independently cut-over resource store for managed and local material/LUT revisions without changing existing Studio mutations until a verified shadow index is committed.

**Architecture:** Add one reusable storage kernel with separate material and LUT roots/indexes. The kernel owns normalized identities, immutable revision publication, generation-CAS indexes, journals, lock ordering, leases, garbage collection, shadow migration, writer admission, and repair; domain adapters supply content hashing/loading and logical path rules. Existing APIs remain v1 writers during shadow mode and are switched in the integration plan only after per-domain cutover.

**Tech Stack:** Python 3, Pydantic/dataclasses where already appropriate, filesystem durability primitives, `psutil` for PID-reuse-safe owner checks, pytest/Hypothesis, FastAPI integration in a later plan.

---

## Repository And Branches

Repository: `lumina-layer-studio/Lumina-studio`

Execute this plan in four PR slices, interleaved with the Studio Integration plan:

1. `codex/feat/resource-store-foundation-v2`
   - Tasks 1-2 only: models, path safety, durability, locks, capacity, and the platform probe;
   - no Registry client, transaction manager, migration, router, or existing endpoint adoption.
2. `codex/feat/resource-store-shadow-v2`
   - Tasks 3-5 after Integration Tasks 1-3 have merged the package binder;
   - transaction/recovery kernel, domain adapters, and read-only migration shadow, with no repair apply, cutover, or existing endpoint mutation.
3. `codex/feat/resource-lifecycle-api-v2`
   - Tasks 6-7 in the same PR as Integration Task 4;
   - leases, local locks, lifecycle/guarded GC and strict domain APIs behind capability gates, with no domain cutover.
4. `codex/feat/resource-store-cutover-v2`
   - Tasks 8-10 in the same PR as Integration Tasks 5-6;
   - writer drain and activation-locked independent cutover machinery, repair, legacy adapters and read-only scheduler, with no new resource-center frontend;
   - both domains must still ship as `v1_active` because the complete reader generation lands only in the next Integration PR.

Never test migration or deletion against the user's primary `materials/` or `lut-preset/`. Use `tmp_path`, copied fixture trees, or a disposable worktree.

## Execution Slices

1. Run Store Tasks 1-2 and merge the foundation PR.
2. Pause this plan and run Integration Tasks 1-3; merge the client/binder PR against that foundation.
3. Resume Store Tasks 3-5 and merge the shadow PR.
4. Implement Store Tasks 6-7 together with Integration Task 4 and merge the gated lifecycle/API PR without cutting over either domain.
5. From the fresh merge, implement Store Tasks 8-10 together with Integration Tasks 5-6 and merge the cutover/legacy-adapter PR only after mixed-domain and old-contract gates pass, while proving every activation attempt remains locked at `v1_active` without the future reader generation.

Do not execute this document straight through without the pauses above. `VerifiedPackageBinding` is created by Integration Task 1 and consumed by Store Tasks 3 and 5. Destructive lifecycle methods land with their gated API adoption, while the separately reviewed cutover engine lands only with every legacy writer adapter and scheduler policy needed to prevent split-brain writes. Integration Tasks 7-9 then register the reviewed exact-reader generation; only a later full-stop operational run may execute the already-merged cutover engine.

## File Structure

Create `core/resource_store/` as a focused package:

- `errors.py`
  - Typed domain errors and stable codes; no `HTTPException`.
- `models.py`
  - Resource refs, index records, revisions, ownership files, transactions, leases, cutover markers.
- `paths.py`
  - POSIX relative normalization, Unicode NFC/casefold reservations, and held root/ancestor/final native-handle capabilities.
- `durability.py`
  - Atomic JSON write, fsync policy, same-filesystem staging, atomic directory publication.
- `locking.py`
  - Cross-process file locks and enforced order: capacity scope -> resource -> sorted revision instances -> global.
- `capacity.py`
  - Physical-volume free-space checks and durable cross-process peak-byte/inode reservations acquired before download/copy.
- `index.py`
  - Schema 2.0 load/validate/generation-CAS commit and backups.
- `hash_cache.py`
  - Bounded relative-path digest hints keyed by file size, mtime, and platform file identity; never an authority for ownership or deletion.
- `journal.py`
  - Durable transaction journal transitions and ownership/tree digests.
- `transactions.py`
  - Prepare, publish, commit, rollback, failure injection, startup recovery.
- `leases.py`
  - Create/renew/release/stale-delete with fence/version CAS.
- `gc.py`
  - `pending_gc`/`deleting` transitions, ownership preflight, idempotent deletion recovery.
- `admission.py`
  - Persistent writer leases, in-flight drain, domain closure/reopen.
- `migration.py`
  - Legacy scan, stable local IDs, shadow index, fingerprint comparison, cutover marker.
- `reader_registration.py`
  - Canonical managed-reader manifest, capacity-reserved proof/journal registration, and post-cutover verification.
- `service_epoch.py`
  - Process-lifetime service ownership plus offline full-stop/no-old-process proof for cutover.
- `repair.py`
  - Audit plan and explicit apply operations that never guess ownership.
- `resolver.py`
  - Resolve active/local/exact references and return only a trusted-root-relative locator plus an installation-instance/local-version-bound lease.
- `store.py`
  - Composition root and public lifecycle methods.
- `domains/base.py`
  - Domain adapter protocol.
- `domains/material.py`
  - Material canonical hash, package extraction binding, loadability, local directory projection.
- `domains/lut.py`
  - LUT legacy/v2 hashes, extension/loadability checks, local path projection and cache invalidation hook.

Create integration/configuration files:

- `api/resource_store_dependencies.py`
  - Construct independent material/LUT stores from configured roots; no router behavior yet.
- `scripts/repair_resource_store.py`
  - Offline `audit`/`repair --apply` entry point.
- `scripts/probe_resource_store.py`
  - Disposable platform/filesystem durability, lock, no-replace, and capacity probe for each configured root.
- `scripts/cutover_resource_store.py`
  - Offline two-root, exact-build, full-stop-only material/LUT activation entry point; it accepts no browser/request-supplied proof.
- `tests/resource_store_fixture_factory.py`
  - Deterministic builders for legacy indexes/files, every journal crash boundary, and corrupt/ambiguous/special-file trees; adopted by recovery and migration tests in this plan.
- `tests/test_resource_store_models_unit.py`
- `tests/test_resource_store_index_unit.py`
- `tests/test_resource_store_hash_cache_unit.py`
- `tests/test_resource_store_domains_unit.py`
- `tests/test_resource_store_capacity_unit.py`
- `tests/test_resource_store_platform_probe_unit.py`
- `tests/test_resource_store_transactions_unit.py`
- `tests/test_resource_store_recovery_unit.py`
- `tests/test_resource_store_leases_unit.py`
- `tests/test_resource_store_gc_unit.py`
- `tests/test_resource_store_migration_unit.py`
- `tests/test_resource_store_cutover_unit.py`
- `tests/test_resource_store_repair_unit.py`
- `tests/test_resource_store_properties.py`

Modify:

- `requirements.txt`
  - Add explicit `psutil>=5.9` for PID/create-time owner identity.
- `.gitignore`
  - Ignore resource-store runtime journals/leases/index backups without ignoring test fixtures.
- `docs/agents/domain.md`, a new `CONTEXT-MAP.md`, and a new `docs/context/resource-store/CONTEXT.md`
  - Record ownership and invariants after code exists.

## Persisted Layout

Each domain uses its own root and all runtime files remain below existing `_sync/`:

```text
{domain-root}/_sync/
  resource-store-marker.json
  resource-store/
    index-v2.json
    backups/
    {registry-key}/{resource-id}/{revision-id}-{hash12}-{installation-instance-id}/...
  transactions/{txid}/journal.json
  transactions/{txid}/staged/...
  locks/capacity.lock
  locks/global.lock
  locks/resources/{resource-key-hash}.lock
  locks/revisions/{logical-revision-plus-installation-instance-hash}.lock
  leases/{lease-id}.json
  local-locks/{lock-token-id}.json
  reader-guards/{token-id}/{guard-id}.json
  writers/{writer-id}.json
  space-reservations/{reservation-id}.json
  quarantine/...
```

No persisted record contains a token, Registry URL, absolute path, or browser-supplied package location. `immutable_path`, logical paths, file paths, and created directories are POSIX paths relative to the domain root or revision root as defined by the approved design.

## Task 1: Models, Errors, And Path Safety

**Files:**
- Create: `core/resource_store/errors.py`
- Create: `core/resource_store/models.py`
- Create: `core/resource_store/paths.py`
- Test: `tests/test_resource_store_models_unit.py`
- Test: `tests/test_resource_store_properties.py`

- [ ] **Step 1: Write failing model and path tests**

Cover complete-or-null `ResourceRevisionRef`, rejection of any hollow managed revision missing envelope/package/publisher binding or server-generated installation instance, nullable/JavaScript-safe `download_count_at_install`, every aggregate count/serialized-byte boundary, 63/64/65 and truncated candidate refs without implicit selection, valid revision lifecycle states, current/previous cardinality, same-logical-revision/different-instance repair records, at most one bounded `pending_gc` revision, uninstall-history latest-per-key and 9,999/10,000/10,001 deterministic eviction boundaries, stable local kinds, required managed-file facts, every `LocalDerivation` discriminator, ordered 2/64/65-input LUT merges with managed/local mixtures and duplicates preserved, the exact `local_delete`/`resolve_legacy_identity`/`adopt_local_equivalent` journal operation literals, deletion-capture `planned -> captured -> restored|cleaned` branching monotonicity and illegal cross-branch transitions, forbidden absolute paths, traversal/dot/empty segments, Windows drives/UNC/device names/ADS/trailing dot-space aliases, 255/256-byte segment and 512/513-byte total paths, Unicode NFC equivalence, raw/NFC/casefold collisions, managed/local reservation ownership and transfer, reserved `_sync` aliases, symlink/reparse/special files, and typed stable error codes. Process-owner fixtures use opaque integer microsecond boot/create markers and reject strings, floats, negative values, and whole-second-truncation aliases.

Use Hypothesis to generate mixed `/` and `\\`, Unicode composed/decomposed names, casing, and traversal segments. Any two logical paths with the same normalized reservation key must conflict even on a case-sensitive host.

- [ ] **Step 2: Run and verify failure**

```bash
set -euo pipefail
python -m pytest tests/test_resource_store_models_unit.py tests/test_resource_store_properties.py -v
```

Expected: FAIL because `core.resource_store` does not exist.

- [ ] **Step 3: Implement stable errors**

Create:

```python
from __future__ import annotations


class ResourceStoreError(Exception):
    code = "resource_store_error"


class ResourceCommitConflict(ResourceStoreError):
    code = "resource_commit_conflict"


class ResourceInUse(ResourceStoreError):
    code = "resource_in_use"


class ResourceHistoryBusy(ResourceStoreError):
    code = "resource_history_busy"


class ResourceLeaseFenced(ResourceStoreError):
    code = "resource_lease_fenced"


class LocalPathConflict(ResourceStoreError):
    code = "local_path_conflict"


class LocalIndexInvalid(ResourceStoreError):
    code = "local_index_invalid"


class LocalIndexRecoveryRequired(ResourceStoreError):
    code = "local_index_recovery_required"


class ResourceCutoverBusy(ResourceStoreError):
    code = "resource_cutover_busy"
```

Task 1 also defines typed `ResourceAtomicPublishUnsupported`, `ResourceCapacityExceeded`, `ResourceReservationInvalid`, `RegistryPackageBindingMismatch`, `UnsafeArchive`, `ContentUnloadable`, `ContentHashMismatch`, `LocalInstallDamaged`, `ManagedResourceReadOnly`, `LocalDeletePreconditionRequired`, and `LocalResourceChanged` subclasses with the corresponding snake-case public codes. Integration Task 4 owns network/origin/cursor HTTP-boundary codes and maps these core exceptions centrally; core code never imports `HTTPException`. Errors carry safe IDs/state and an optional internal structured reason/cause, but their public string never contains an absolute path, token, signed URL, package-controlled string, or traceback.

- [ ] **Step 4: Implement persisted model boundaries**

Define frozen identity/value objects and strict aggregate models with bilingual Google-style public docstrings. Repository code never mutates a loaded aggregate in place; it builds and fully validates a new copy before serialization. `ResourceIndexDelta` canonicalizes/deep-copies its maps and exposes read-only mappings/tuples so caller mutation cannot change a journaled delta hash:

```python
ResourceKind = Literal["material", "lut"]
ResourceUsageKind = Literal[
    "preview", "generate", "replace", "extract", "merge", "details",
    "calibration", "batch", "other",
]
LocalEntryKind = Literal[
    "local_import", "local_copy", "legacy_unresolved", "local_equivalent"
]
RevisionLifecycleState = Literal[
    "available", "pending_gc", "deleting", "gc_conflict",
    "quarantined_recovery", "deleted"
]
JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class ResourceRevisionRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_registry: str
    resource_kind: ResourceKind
    resource_id: str
    revision_id: str
    content_hash_algorithm: str
    content_hash: str


class ManagedFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: str
    path: str
    sha256: str
    bytes: int = Field(ge=0)


class InstalledDisplaySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str
    publisher_id: str | None
    publisher_kind: Literal["lumina", "community"]
    publisher_name: str
    summary: str
    brand: str
    tags: list[str]
    updated_at: str
    compatibility: dict[str, JsonValue]


class VerifiedFileIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    platform_file_id: str
    bytes: int = Field(ge=1)
    sha256: str


class RevisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: str
    installation_instance_id: str
    lifecycle_state: RevisionLifecycleState
    fencing_generation: int = Field(ge=1)
    content_hash_algorithm: str
    content_hash: str
    envelope_id: str
    package_sha256: str
    package_bytes: int = Field(gt=0)
    download_count_at_install: int | None = Field(
        default=None, ge=0, le=9_007_199_254_740_991
    )
    display_snapshot: InstalledDisplaySnapshot
    logical_path: str
    immutable_path: str
    managed_files: list[ManagedFile] = Field(min_length=1, max_length=128)
    created_directories: list[str] = Field(max_length=128)
    installed_at: str
    transaction_id: str


class DomainPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    local_directory: str | None = None
    local_path: str | None = None


class ObservedFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str
    sha256: str
    bytes: int = Field(ge=0)
    platform_file_id: str


class PathReservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    normalized_key: str
    owner: str
    generation: int = Field(ge=0)


class ManagedResourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_kind: Literal["managed"] = "managed"
    resource_kind: ResourceKind
    source_registry: str
    resource_id: str
    active: RevisionRecord
    previous: RevisionRecord | None
    pending_gc: list[RevisionRecord] = Field(max_length=1)
    updated_at: str


class ManagedDerivationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input_kind: Literal["managed_revision"] = "managed_revision"
    source_ref: ResourceRevisionRef


class LocalDerivationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input_kind: Literal["local_record"] = "local_record"
    local_id: str
    record_version: int = Field(ge=1)
    content_hash_algorithm: str
    content_hash: str


DerivationInput = Annotated[
    ManagedDerivationInput | LocalDerivationInput,
    Field(discriminator="input_kind"),
]


class DirectImportDerivation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    derivation_kind: Literal["direct_import"] = "direct_import"


class SingleSourceDerivation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    derivation_kind: Literal[
        "managed_copy", "detached_managed", "resolved_legacy"
    ]
    input: DerivationInput


class LutMergeDerivation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    derivation_kind: Literal["lut_merge"] = "lut_merge"
    inputs: list[DerivationInput] = Field(min_length=2, max_length=64)


LocalDerivation = Annotated[
    DirectImportDerivation | SingleSourceDerivation | LutMergeDerivation,
    Field(discriminator="derivation_kind"),
]


class LocalResourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_id: str
    entry_kind: LocalEntryKind
    resource_kind: ResourceKind
    domain_path: DomainPath
    display_snapshot: InstalledDisplaySnapshot
    content_hash_algorithm: str
    content_hash: str
    observed_files: list[ObservedFile] = Field(min_length=1, max_length=2_048)
    source_ref: ResourceRevisionRef | None
    derivation: LocalDerivation
    migration_state: Literal["resolved", "deferred"]
    candidate_refs: list[ResourceRevisionRef] = Field(max_length=64)
    candidate_ref_count: int = Field(ge=0)
    candidate_refs_truncated: bool
    scan_generation: int = Field(ge=0)
    record_version: int = Field(ge=1)
    created_at: str
    updated_at: str


class LegacyAliasRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target_resource_key: str
    original_relative_path: str
    observed_files: list[ObservedFile] = Field(min_length=1, max_length=2_048)
    scan_fingerprint: str


class UninstallHistoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_key: str
    revision_id: str
    content_hash_algorithm: str
    content_hash: str
    transaction_id: str
    deleted_at: str


class CutoverRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["v1_active", "migration_prepared", "v2_committed"]
    adapter_generation: Literal["resources-v2-1"] | None
    reader_adapter_generation: Literal["resource-readers-v2-1"] | None
    reader_manifest_sha256: str | None
    committed_generation: int | None
    legacy_index_sha256: str | None
    committed_at: str | None


class ResourceIndexV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"] = "2.0"
    store_id: str
    generation: int = Field(ge=0)
    cutover: CutoverRecord
    managed_resources: dict[str, ManagedResourceRecord] = Field(max_length=10_000)
    local_resources: dict[str, LocalResourceRecord] = Field(max_length=50_000)
    path_reservations: dict[str, PathReservation] = Field(max_length=60_000)
    legacy_aliases: dict[str, LegacyAliasRecord] = Field(max_length=50_000)
    uninstall_history: dict[str, UninstallHistoryRecord] = Field(max_length=10_000)


class ResourceIndexDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    transaction_id: str
    cutover_before: CutoverRecord
    cutover_after: CutoverRecord
    managed_before: dict[str, ManagedResourceRecord | None]
    managed_after: dict[str, ManagedResourceRecord | None]
    local_before: dict[str, LocalResourceRecord | None]
    local_after: dict[str, LocalResourceRecord | None]
    reservations_before: dict[str, PathReservation | None]
    reservations_after: dict[str, PathReservation | None]
    aliases_before: dict[str, LegacyAliasRecord | None]
    aliases_after: dict[str, LegacyAliasRecord | None]
    history_before: dict[str, UninstallHistoryRecord | None]
    history_after: dict[str, UninstallHistoryRecord | None]


class ProcessIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    pid: int = Field(ge=1)
    process_create_time_us: int = Field(ge=0, le=253_402_300_799_999_999)
    boot_time_us: int = Field(ge=0, le=253_402_300_799_999_999)


class LeaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_id: str
    store_id: str
    resource_key: str
    revision_id: str
    installation_instance_id: str
    fencing_generation: int = Field(ge=1)
    owner: ProcessIdentity
    usage_kind: ResourceUsageKind
    session_id: str | None
    job_id: str | None
    created_at: str
    heartbeat_at: str
    expires_at: str
    version: int = Field(ge=1)


class LocalLockRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lock_token_id: str
    store_id: str
    local_id: str
    local_record_version: int = Field(ge=1)
    owner: ProcessIdentity
    usage_kind: ResourceUsageKind
    session_id: str | None
    job_id: str | None
    created_at: str
    heartbeat_at: str
    expires_at: str
    version: int = Field(ge=1)


class ReaderGuardRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guard_id: str
    store_id: str
    token_kind: Literal["managed_lease", "local_lock"]
    token_id: str
    resource_key: str | None
    revision_id: str | None
    installation_instance_id: str | None
    revision_fencing_generation: int | None
    local_id: str | None
    local_record_version: int | None
    job_id: str
    owner: ProcessIdentity
    created_at: str
    version: int = Field(ge=1)


class WriterLease(BaseModel):
    model_config = ConfigDict(extra="forbid")
    writer_id: str
    store_id: str
    resource_kind: ResourceKind
    operation: str
    adapter_generation: Literal["legacy-v1", "resources-v2-1"]
    owner: ProcessIdentity
    started_at: str
    heartbeat_at: str
    expires_at: str
    version: int = Field(ge=1)


class SpaceReservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reservation_id: str
    store_id: str
    resource_kind: ResourceKind
    capacity_scope_id: str
    capacity_scope_members: tuple[str, ...]
    operation_id: str
    owner: ProcessIdentity
    package_bytes: int = Field(ge=0)
    expanded_bytes: int = Field(ge=0)
    copy_bytes: int = Field(ge=0)
    safety_bytes: int = Field(ge=0)
    total_reserved_bytes: int = Field(ge=1)
    package_inodes: int = Field(ge=0)
    expanded_inodes: int = Field(ge=0)
    copy_inodes: int = Field(ge=0)
    safety_inodes: int = Field(ge=0)
    total_reserved_inodes: int = Field(ge=1)
    created_at: str
    expires_at: str
    version: int = Field(ge=1)


class DeletionCaptureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["planned", "captured", "restored", "cleaned"]
    role: str = Field(min_length=1, max_length=64)
    source_relative_path: str = Field(min_length=1, max_length=512)
    trash_relative_path: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    platform_file_id: str = Field(min_length=1, max_length=256)


class TransactionJournal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    transaction_id: str
    operation: Literal[
        "install", "import_local", "update", "rollback", "uninstall",
        "adopt_local_equivalent", "resolve_legacy_identity",
        "create_local_copy", "detach_management",
        "local_delete", "gc", "repair", "cutover"
    ]
    state: Literal[
        "prepared", "revision_published", "deletion_captured", "committed",
        "aborted", "finalized", "quarantined_recovery"
    ]
    store_id: str
    base_generation: int = Field(ge=0)
    index_delta: ResourceIndexDelta
    resource_key: str
    involved_revision_instance_keys: list[str]
    path_reservation_precondition: PathReservation | None
    space_reservation_id: str | None
    space_reservation_version: int | None
    reserved_bytes: int | None
    reserved_inodes: int | None
    staged_relative_path: str | None
    final_relative_path: str | None
    managed_files: list[ManagedFile]
    created_directories: list[str]
    deletion_captures: list[DeletionCaptureRecord] = Field(max_length=2_048)
    tree_digest: str
    committed_generation: int | None
    created_at: str
    updated_at: str
    finalized_at: str | None


class ResourceStoreMarker(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    state: Literal["v1_active", "migration_prepared", "v2_committed"]
    store_id: str
    adapter_generation: Literal["resources-v2-1"] | None
    reader_adapter_generation: Literal["resource-readers-v2-1"] | None
    reader_manifest_sha256: str | None
    committed_generation: int | None
    legacy_index_sha256: str | None
    committed_at: str | None
```

Define bounded recursive `JsonValue` and enforce the cross-repository metadata contract exactly after NFC normalization: publisher/title/brand `1..128` UTF-8 bytes, summary `0..1024`, at most 32 unique casefold-safe tags of `1..64`, and JSON-only compatibility depth `4`, aggregate nodes `128`, keys `64`, key bytes `64`, and string-value bytes `256`. Strict numeric compatibility values are finite integers/floats with absolute value at most `1_000_000_000`, with booleans handled separately rather than as integers. Every new index, journal, lease, lock, guard, migration, and display timestamp uses the master plan's exact `YYYY-MM-DDTHH:MM:SSZ` UTC codec and valid `1970..9999` calendar range; reject offsets, fractions, leap seconds, impossible dates, and whitespace, and use injected monotonic clocks rather than wall timestamps for elapsed timeout tests. Reject control/bidi-override characters, HTML/script, duplicate normalized keys/tags, unknown fields, out-of-range/non-finite numbers, dedicated Registry/package/preview URL fields, and absolute path fields; plain summary text remains inert text. `InstalledDisplaySnapshot` comes only from the verified package manifest/domain adapter and lets My Resources render without Registry access. Managed cloud snapshots require the exact Registry-generated read-only `publisher_id`; local content forces it to null, and no store method accepts it as ownership authority. `download_count_at_install` is a non-authoritative JavaScript-safe observation copied only from the fresh exact Registry response that authorized install/update/remote rollback/repair; migrated managed records without a proven value use null, and local records always project null. Reads never refresh it in place or treat null as zero. For content installed through any restricted pair, including `team/private` and historical `team/team`, the snapshot is part of that installation record, not a reusable catalog/detail cache; it never contains channel, visibility, Registry URL, token, envelope query, preview URL, or absolute path. Serialization tests prove neither restricted literal can be recovered from the stored snapshot unless it also appears independently in inert user-facing text.

`VerifiedFileIdentity` is transient and never serialized into the index or journal. `platform_file_id` is derived from the already-open handle: POSIX device/inode or Windows volume serial/file index, encoded as a bounded opaque string. It is always paired with the full byte count and strict prefixed SHA-256 so neither identity reuse nor path replacement is trusted alone.

Validate `DomainPath` as exactly one field, with `local_directory` only for material and `local_path` only for LUT at the containing record. `PathReservation.owner` is exactly one typed key, `managed:{source_registry}:{kind}:{resource_id}` or `local:{local_id}`. Every `involved_revision_instance_keys` entry names the complete logical managed revision plus its server-generated installation instance; entries are normalized, unique, and recovery may never lock, delete, or republish by revision ID alone. Every before/after map in `ResourceIndexDelta` has the same key set; null means proven absence, and keys outside those maps cannot change. Ordinary deltas keep identical cutover before/after values; only the cutover transaction may change them. `reader_adapter_generation` and `reader_manifest_sha256` are both null or both present; the hash is exactly 64 lowercase hexadecimal characters over canonical manifest bytes. They may be registered while `v1_active` but only the cutover transaction may carry them into `migration_prepared`/`v2_committed`, and a committed record requires the reviewed generation plus exact manifest hash. Package-publishing journal operations require reservation ID/version plus reserved byte/inode counts and both staged/final paths; pointer-only and GC operations require those fields to be null unless they actually own staged objects. Cutover always owns the dedicated metadata/index/journal/marker capacity reservation defined in Task 8 even though candidate payload publication itself is same-filesystem rename. Only `uninstall`, `local_delete`, and `gc` may carry `deletion_captures`; every other operation requires an empty list. Each capture has one unique normalized source and trash path, raw lowercase file SHA-256, exact byte count, and opaque platform identity. Its immutable capture facts define the deletion operation's `tree_digest`; mutable progress state is excluded so the digest remains stable. Capture progress is a monotonic branch: `planned -> captured -> restored` for a pre-commit rollback, or `planned -> captured -> cleaned` after the deletion delta commits. It can never move backward, cross from `restored` to `cleaned`, skip a state, or change immutable file facts. The complete sorted `planned` inventory is durable before the first rename. `planned` means the journal has not recorded a move and normally requires the exact source with absent trash; `captured` requires absent source and exact trash; `restored` requires exact source and absent trash; `cleaned` requires absent trash and relinquishes all ownership of the source path, which another actor may have recreated after commit. The only tolerated physical/journal discrepancies are the single next protocol move interrupted between its filesystem rename or unlink and the following durable progress write; recovery must prove and advance that one entry before doing anything else. `deletion_captured` is valid only when every entry is exactly `captured`, the index still equals the before-values, and no captured byte has been unlinked. A pre-commit journal may contain only the strict progress shape `captured* restored* planned*`, with `restored` entries appearing only while rolling the captured prefix back in reverse order; a committed deletion may contain only `cleaned* captured*` in deterministic cleanup order after the exact deletion delta is durable. Any other ordering quarantines. `prepared`/`revision_published`/`deletion_captured` require null commit/finalized fields; `committed` requires the exact persisted generation and null `finalized_at`; `aborted` requires null committed generation/finalized time. `finalized` requires `finalized_at`; a committed deletion outcome requires every capture `cleaned`, while a safely aborted deletion requires every entry to be `planned` (never moved) or `restored` (moved and restored), every source exact, and every trash path absent. Quarantined records preserve the last known fields. `SpaceReservation` contains no absolute path. Local records carry a bounded display snapshot, optional single-revision equivalence `source_ref`, and a required bounded `LocalDerivation`. `lut_merge` is valid only for a LUT local-copy record, preserves its exact input order without deduplication, accepts each input only as a complete managed ref or stable local ID+record-version+canonical hash, and forces aggregate `source_ref` to null; direct import/single-source kinds reject incompatible input shapes. Derivation is historical provenance, not live ownership: restart or later source deletion never rewrites it or authorizes I/O from it. Lease/local-lock creation requires one server-selected `ResourceUsageKind`; it is the only persisted fact projected into `in_use_by`, while session/job/process/token IDs remain internal and never become display labels.

Index validation enforces active/previous `available`, previous at most one, `pending_gc` at most one with exact pending-GC state membership, key/record identity equality, exact ref kind, reservation ownership, no managed/local path overlap, no duplicate/casefold observed paths, and no absolute values. Logical `(source_registry, kind, resource_id, revision_id)` may repeat across active/previous/pending only when every record has a distinct server-generated `installation_instance_id`, distinct immutable path, and independently verified tree; physical identity is never inferred from the logical revision alone. Publisher badge facts have one persisted source of truth: each revision's verified `display_snapshot`; `ManagedResourceRecord` does not duplicate `publisher_kind`. Every managed revision has a nonempty strict envelope ID, installation instance ID, prefixed package SHA-256, positive package bytes, nonempty managed files, and a display snapshot with non-null public publisher ID; migration may not manufacture placeholders for any of them. Every local resource and legacy alias has at least one bounded observed-file fact; missing current files remain represented by their last indexed facts plus deterministic damaged/changed evaluation and never by an empty record. Candidate refs are deterministically sorted by complete identity without selecting one: `candidate_ref_count >= len(candidate_refs)`, `candidate_refs_truncated` is exactly whether the count is larger, and more than 64 candidates remains deferred for explicit search/choice rather than silently dropping ambiguity. `uninstall_history` is keyed only by canonical managed resource key and stores exactly the latest tombstone for that key; reinstall/uninstall replaces it instead of appending transaction-keyed history. It is capped at 10,000 entries, and insertion at the cap removes the oldest deterministic `(deleted_at, resource_key)` tombstone in the same index delta; tombstones are display/audit hints and never own payloads, reservations, local source refs, or reinstall authority. `LeaseRecord` and managed `ReaderGuardRecord` require the exact installation instance plus logical revision/fence; local guards require local ID/record version and null managed fields. `created_directories` uses the internal root sentinel `"."` only when the transaction created the immutable revision root; all other entries pass strict POSIX-relative normalization. The sentinel is never accepted from a manifest, browser request, Registry field, `normalize_relative_path`, or as a child segment. Deletion resolves it only as the already ownership-proven revision root and handles it last after all listed children.

- [ ] **Step 5: Implement path primitives**

Expose:

```python
def normalize_relative_path(value: str) -> str: ...
def reservation_key(value: str) -> str: ...
def open_store_root(configured_root: Path) -> RootHandle: ...
def bind_beneath(
    root: RootHandle,
    relative: str,
    *,
    expected_kind: Literal["file", "directory", "missing"],
) -> BoundPathHandle: ...
```

Canonicalize separators and Unicode NFC to POSIX form, cap each segment at 255 UTF-8 bytes and the complete relative path at 512, reject unsafe segments/drives/UNC/NUL/controls, colon/NTFS alternate streams, trailing dot/space, Windows device basenames including extensions, and preserve raw/NFC/casefold collision evidence; casefold only for reservation identity, never for the displayed path. `RootHandle` and `BoundPathHandle` are closeable capabilities, not wrappers around a resolved `Path`: they retain the root/ancestor/final native handles and expose only descriptor-relative open/create/read/hash/rename-no-replace/unlink/rmdir/fsync operations plus the normalized logical relative text. No security-sensitive store, transaction, repair, resolver, cache, lease, GC, or migration API accepts a `Path` returned from a prior check.

On POSIX, prefer `openat2` with `RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS`; the supported fallback walks each segment with `openat`/`O_NOFOLLOW` while retaining directory descriptors and performs final operations with `dir_fd`, `renameat2`/platform-exclusive rename, and `unlinkat`. On Windows, use reparse-safe directory handles and root-relative native opens (or final-handle operations) with `FILE_FLAG_OPEN_REPARSE_POINT`, verify volume/file identity at every component, and keep the parent/final handles through use; a backend that can only return an unchecked absolute path is unsupported/read-only. Platform probes race every ancestor/final swap and prove the opened handle remains the intended object or the operation fails. Never use `.resolve()`, `GetFinalPathNameByHandle` text, or an ancestor scan as ownership proof by itself. Add a separate private `bind_created_directory()` that accepts exactly `"."` as the already-open revision-root handle or delegates non-root values to `normalize_relative_path`; tests prove all external/general path APIs still reject `"."`, `a/./b`, and empty segments.

- [ ] **Step 6: Run and commit**

```bash
set -euo pipefail
python -m pytest tests/test_resource_store_models_unit.py tests/test_resource_store_properties.py -q
git add core/resource_store/errors.py core/resource_store/models.py core/resource_store/paths.py tests/test_resource_store_models_unit.py tests/test_resource_store_properties.py
git commit -m "feat(resources): define durable resource store contracts"
```

## Task 2: Durable Files And Ordered Cross-Process Locks

**Files:**
- Create: `core/resource_store/durability.py`
- Create: `core/resource_store/locking.py`
- Create: `core/resource_store/capacity.py`
- Create: `scripts/probe_resource_store.py`
- Create: `scripts/check_tracked_delta_hygiene.py`
- Modify: `requirements.txt`
- Test: `tests/test_resource_store_index_unit.py`
- Test: `tests/test_resource_store_capacity_unit.py`
- Test: `tests/test_resource_store_platform_probe_unit.py`
- Test: `tests/test_tracked_delta_hygiene_unit.py`
- Test: `tests/test_resource_store_properties.py`

- [ ] **Step 1: Write durability and lock-order tests**

Inject write/flush/fsync/replace/parent-fsync failures. Assert the prior file remains valid or the new complete file exists, never partial JSON. Race a pre-existing empty directory, nonempty directory, regular file, symlink/reparse point, and same-name directory created by another process against immutable publication; the target remains byte-identical and publication returns conflict. Spawn two processes to prove lock exclusion. Assert sorted capacity-scope locks -> resource -> sorted revisions -> global succeeds and every reverse order raises before acquiring the lower-rank lock. Assert timeout returns a typed busy error and lock metadata distinguishes PID reuse. Race two processes against limited fake byte/inode capacity and assert only reservations whose summed peaks fit; include bytes-available-but-inodes-exhausted on POSIX and explicit inode-not-applicable behavior. Then race a material reservation against a LUT reservation whose roots report the same device/volume and prove they share both budgets. Repeat with different volumes and prove they do not block or subtract each other. Test stale/dead/reused PID, boot change, expiry, disk/inode-full during write, malformed/foreign-scope reservation, changed configured scope membership, and cleanup ambiguity.

- [ ] **Step 2: Add explicit process identity dependency**

Add:

```text
psutil>=5.9
```

Use `round(psutil.Process(pid).create_time() * 1_000_000)` plus `round(psutil.boot_time() * 1_000_000)` for owner validation in leases, writers, space reservations, and deletion journals. Persist both as opaque nonnegative integer microsecond markers and compare only exact equality; they are process-identity evidence, not business timestamps, and must never pass through the whole-second UTC timestamp codec. Do not rely on `os.kill(pid, 0)` alone because a reused PID, subsecond process replacement, or reboot can make an abandoned owner appear alive. If the platform cannot produce a stable pair or returns an ambiguous value, destructive cleanup fails closed and repair reports the owner record.

- [ ] **Step 3: Implement durable write primitives**

`atomic_write_json(parent: BoundPathHandle, relative_name, value)` must:

1. create a unique sibling `.tmp` with exclusive create;
2. serialize UTF-8 JSON with sorted keys and final newline;
3. flush and `os.fsync` the file;
4. atomically replace the destination through the held parent capability;
5. durably flush the replacement and parent directory through native platform handles;
6. remove only its own temporary file on failure.

POSIX uses descriptor-relative replacement plus file and directory `fsync`. Windows flushes the temporary file with `FlushFileBuffers`, uses a native atomic replacement (`ReplaceFileW` for an existing destination or the reviewed `MoveFileExW` replacement form) with write-through semantics, reopens/verifies the final identity, and flushes the parent directory handle when the filesystem supports it. `os.replace` is not an accepted Windows durability substitute. The platform probe injects/observes file flush, replacement, write-through, final-identity, and parent-directory-flush behavior; if the filesystem/runtime cannot establish the required crash-durable equivalence, the affected capacity scope is read-only.

`publish_directory_no_replace(staged: BoundPathHandle, final_parent: BoundPathHandle, final_name: str)` verifies same-device storage, held plain server-owned ancestors, staged tree digest, and final absence immediately before an atomic exclusive rename. Implement Linux `renameat2(..., RENAME_NOREPLACE)`, macOS `renamex_np(..., RENAME_EXCL)`, and Windows `MoveFileExW` without `MOVEFILE_REPLACE_EXISTING` plus `MOVEFILE_WRITE_THROUGH`. A platform without a proven same-filesystem exclusive primitive returns typed `resource_atomic_publish_unsupported`; never fall back to check-then-`os.replace`. After success, re-open the final tree relative to the still-held parent without following links, verify the journal digest, and flush the final/parent handles. Existing/raced targets are never overwritten, renamed, chmodded, or removed.

- [ ] **Step 4: Implement lock service**

Use persistent lock files that are never deleted during normal operation. POSIX uses `fcntl.flock`; Windows uses a one-byte `msvcrt.locking` region. After acquisition, write safe owner metadata to the held file and flush. Maintain a thread-local held-rank stack and enforce:

```python
LOCK_RANK = {"capacity": 5, "resource": 10, "revision": 20, "global": 30}
```

`locking.py` returns an opaque `GlobalLockGuard` containing store ID, lock-service instance nonce, owner thread ID, and acquisition nonce. Only the lock service constructs it; context exit marks it released. Repository methods call `guard.assert_live(lock_service, store_id)` before disk I/O, so a forged, stale, cross-thread, or cross-store guard is rejected.

Capacity locks are acquired in sorted persistent store-ID order and only before any resource/revision/global lock; managed revision locks use sorted canonical logical-revision-plus-installation-instance keys. A publishing transaction validates and pins its live reservation while holding the capacity scope locks, then takes resource/revision/global locks; it never tries to acquire or renew capacity while already holding a higher-rank lock. No network download, archive parse/extraction, domain loadability check, or ordinary source/staging hash occurs under the global lock. The byte-scan exceptions are the bounded final immutable-tree digest immediately after exclusive publication and the one-time cutover source/staged fingerprint recheck while that domain's admission is closed and drained. Package/expanded-size and migration-capacity limits bound both; concurrency tests prove normal request paths cannot hold the global lock for unbounded input.

- [ ] **Step 5: Implement capacity reservation and platform probe**

At composition time, `CapacityManager` receives all configured material/LUT roots, opens each without following links, groups them by actual POSIX device ID or Windows volume identity, and builds a `CapacityScope` from sorted persistent store IDs. Its scope ID is a hash of those store IDs, never an absolute path. Before reserve/renew/release/stale-cleanup it acquires the dedicated `locks/capacity.lock` in every same-volume member in sorted store-ID order, validates every member's reservation records and exact scope membership, obtains one `shutil.disk_usage(member_root).free` value for the volume, and subtracts live reservations from every member. A process configured with a different same-volume member roster, an unknown store ID, or conflicting volume identity makes the affected scope read-only; it cannot silently count only the roots it knows.

`CapacityManager.reserve()` requires `package_bytes + expanded_bytes + copy_bytes + max(64 MiB, 10% of that subtotal)` and trusted package/expanded/copy file-plus-directory counts plus `max(32, ceil(10% of the inode subtotal))`. Values are nonnegative bounded integers from exact detail/domain inventory or the fixed cache-write protocol, not browser input. On POSIX, read `f_favail` under the same scope locks and subtract every live inode reservation; on platforms without meaningful inode accounting, report that capability as not applicable while archive/member caps remain mandatory. Persist the new byte/inode reservation atomically in the requesting store before releasing scope locks; renew/release require scope ID/member set, reservation ID, owner identity, expected version, and store ID. Stale cleanup uses the same PID/create-time/boot checks as leases and never deletes an unrecognized file. The transaction validates its reservation before each write phase and releases it only after commit or verified caller-owned cleanup; ENOSPC/ENOSPC-like inode exhaustion becomes recoverable/quarantined state with no index pointer to partial content.

Reservation records are at most 16 KiB canonical JSON. A capacity scope admits at most 1,024 live/formal reservation records across all same-volume members after clearing only proven-dead owners; exact-boundary overflow returns `resource_capacity_busy` before download/staging and unknown/malformed/symlink entries make the scope read-only rather than disappearing from accounting. Directory scans and aggregate integer sums are bounded and overflow-checked.

`python scripts/probe_resource_store.py --material-root "$MATERIAL_ROOT" --lut-root "$LUT_ROOT" --json` requires both configured roots on every invocation, opens both before creating anything, and builds the exact production capacity-scope membership. It creates one UUID-owned `_sync/platform-probe/{probe-id}` child in each root, exercises locks, atomic JSON, exclusive directory publication, fsync, byte/inode capacity reservation accounting, same-volume cross-root contention or cross-volume independence, and raced-target preservation, then removes only its verified children. A one-root mode does not exist, because it could misclassify reservations on a shared volume. Application startup calls the same two-root implementation. Reports use safe store/volume labels, capabilities, free bytes, and either free inodes or explicit not-applicable, never absolute paths. Missing/duplicate roots, symlink/reparse roots, unsupported network filesystems, scope disagreement, or cleanup ambiguity exit nonzero and force every member of that capacity scope read-only. Tests require both flags and prove no file is created when either preflight fails.

Add `scripts/check_tracked_delta_hygiene.py --base <target-ref>` as the shared Studio PR scanner. It obtains changed tracked entries from NUL-safe Git plumbing, reads HEAD/base blobs directly with bounded byte decoding, and rejects forbidden runtime/config pathnames plus only the sensitive text findings newly introduced relative to that exact base blob. Rules cover concrete macOS/Linux root-or-user homes, Windows profiles, the current checkout, bearer/private-key material, and literal sensitive `LUMINA_*` assignments. Renames compare the matched base blob; added files have an empty baseline. It never walks untracked/ignored files or agent scratch data, and its dynamically constructed policy literals do not self-match. Binary fixture exceptions are exact-path allowlists whose package validators remain mandatory. Tests seed existing baseline findings, one new finding per rule, rename/copy/delete, binary/oversized/symlink/special entries, non-ancestor/missing base, malicious filenames, and prove an existing finding cannot whitelist a new occurrence elsewhere.

- [ ] **Step 6: Run process tests and commit**

```bash
set -euo pipefail
python -m pytest tests/test_resource_store_index_unit.py tests/test_resource_store_capacity_unit.py tests/test_resource_store_platform_probe_unit.py tests/test_tracked_delta_hygiene_unit.py tests/test_resource_store_properties.py -q
git add requirements.txt core/resource_store/durability.py core/resource_store/locking.py core/resource_store/capacity.py scripts/probe_resource_store.py scripts/check_tracked_delta_hygiene.py tests/test_resource_store_index_unit.py tests/test_resource_store_capacity_unit.py tests/test_resource_store_platform_probe_unit.py tests/test_tracked_delta_hygiene_unit.py tests/test_resource_store_properties.py
git commit -m "feat(resources): add durable storage primitives"
```

## Task 3: Generation-CAS Index And Immutable Transactions

**Files:**
- Create: `core/resource_store/index.py`
- Create: `core/resource_store/journal.py`
- Create: `core/resource_store/transactions.py`
- Test: `tests/test_resource_store_index_unit.py`
- Test: `tests/test_resource_store_transactions_unit.py`

- [ ] **Step 1: Write index and state-machine tests**

Assert missing store creates schema 2.0 generation 0, every commit increments exactly once, a stale generation with changed touched preconditions conflicts, unrelated-resource concurrent commits rebase safely, same-resource commits conflict, reservation collision uses NFC/casefold, index backups precede schema migration, and a transaction cannot skip or reverse journal states.

- [ ] **Step 2: Implement index repository**

Public methods:

```python
class ResourceIndexRepository:
    def load(self) -> ResourceIndexV2: ...
    def initialize(self, *, store_id: str) -> ResourceIndexV2: ...
    def apply_delta(
        self,
        *,
        expected_generation: int,
        delta: ResourceIndexDelta,
    ) -> ResourceIndexV2: ...
    def apply_delta_locked(
        self,
        *,
        guard: GlobalLockGuard,
        expected_generation: int,
        delta: ResourceIndexDelta,
    ) -> ResourceIndexV2: ...
    def backup_before_schema_change(self) -> Path: ...
```

`apply_delta` acquires the global lock once and delegates to `apply_delta_locked`. The locked variant requires a live `GlobalLockGuard` created by the same lock service, thread, and store; it never reacquires the lock and rejects a missing, released, foreign-store, or foreign-thread guard before disk I/O. It re-reads disk and compares every touched managed/local/reservation/alias/history value plus cutover with the delta's exact before values. If disk generation equals `expected_generation`, apply once. If disk generation is newer, rebase only when every touched before value is still exact; a changed touched value conflicts, and an expected generation ahead of disk is invalid. Validate the complete resulting index, write current disk `generation + 1` atomically, and return the persisted model. Never accept or merge a caller-cached whole index. Tests instrument lock acquisition and prove transaction/recovery paths acquire the global lock exactly once.

Open index/marker/backup JSON through no-follow regular-file handles, reject an index above 64 MiB before decoding, reject duplicate JSON keys/non-finite numbers/excess nesting before model construction, and reject a serialized replacement above the same cap before creating a temp file. Generation is a checked signed 64-bit nonnegative integer and cannot wrap. A parse/schema/size violation preserves the old bytes, closes writes for that domain, and reports repair required without logging package-controlled text or an absolute path.

- [ ] **Step 3: Implement journal schema and ownership digest**

Journal states are `prepared`, `revision_published`, `deletion_captured`, `committed`, `finalized`, `aborted`, and `quarantined_recovery`. Persist `base_generation`, the complete `ResourceIndexDelta`, resource key, sorted `involved_revision_instance_keys`, logical-path reservation precondition, space-reservation ID/version/byte+inode counts, staged/final relative paths, normalized managed files, created directories, the bounded per-file deletion-capture inventory/progress, per-file hashes/bytes/identities, deterministic tree digest, committed index generation, and timestamps. A journal is at most 16 MiB canonical JSON; read it through a no-follow regular-file handle with duplicate-key/non-finite/depth rejection and refuse an oversized delta or capture inventory before staging, capture, or index mutation.

Every state transition and monotonic per-file capture-progress rewrite validates the previous durable record, writes atomically, and fsyncs before the next irreversible operation. No cleanup unlink is legal until `deletion_captured` and then the matching index delta/`committed_generation` are both durable.

- [ ] **Step 4: Implement archive-identity recheck and bounded extraction**

`ResourceTransactionManager` accepts only the merged `VerifiedPackageBinding`. Immediately before extraction it maps `binding.archive_root_id` through trusted configuration and reopens `binding.archive_relative_path` through held root/ancestor handles, requires a regular final handle, compares the handle-derived `VerifiedFileIdentity`, size, and full strict prefixed SHA-256 with the binding, and keeps that same handle open for the whole extraction. After all member checks, rewind and recompute the full package hash and file identity/size from that still-open handle before fsyncing the prepared journal; a changed archive removes only verified transaction-owned staging and returns the existing public `registry_package_binding_mismatch` with an internal structured reason `archive_changed_after_binding`. A path/ancestor swap, truncation, mutation, identity mismatch, or special final handle cannot publish payload files; no checked-but-unpinned `Path` enters the manager.

Never call `ZipFile.extract()`, `extractall()`, or trust ZIP names/permissions. Iterate only `binding.payload_files` in canonical `(revision_path, archive_path)` order; open exactly the already-bound regular `archive_path`, create exactly the separately validated revision-root-relative `revision_path`, and derive persisted `ManagedFile.path` only from that destination. The transaction manager never strips or adds `materials/`, `luts/`, `lut-preset/`, or `Cloud/` itself and never extracts a manifest or material export descriptor. Create transaction-owned directories beneath the staged root with no-follow checks; create every file exclusively; stream from the open archive handle with per-file and total byte caps; and verify exact bytes plus raw file SHA-256 before fsync. Reject duplicate/casefold-colliding source or destination names, encrypted/data-descriptor surprises not accepted by the binder, sparse/special entries, undeclared payload, short/long streams, and compression-ratio changes. Ignore archive modes/timestamps/owners, force owner-only staging permissions where supported, and never chmod an existing path. On failure, remove only transaction-owned staged names after identity verification or quarantine ambiguity.

Tests bind a valid archive, atomically replace its path with byte-identical and different archives, mutate it in place, swap a parent for a symlink/reparse point, race a destination path, and inject short/overlong member reads. Assert rejection occurs before domain loadability or index publication and no unverified payload survives.

- [ ] **Step 5: Implement install/update transaction sequence**

`ResourceTransactionManager.publish()` performs:

1. require a live caller-owned `SpaceReservation` sized from exact package/file facts;
2. stage under `_sync/transactions/{txid}/staged` on the target filesystem;
3. archive identity/full-hash recheck and bounded extraction from the same no-follow handle, then domain loadability verification;
4. fsync staged files/directories and recheck reservation/free-space state;
5. write `prepared` journal;
6. acquire/pin the sorted capacity scope, then resource, sorted revision, and global locks;
7. re-read index plus logical-path/space-reservation/generation preconditions;
8. allocate one server-generated `installation_instance_id`, derive the never-existing immutable path as `{resource-id}/{revision-id}-{content-hash12}-{installation-instance-id}`, call handle-relative `publish_directory_no_replace`, and verify the final tree digest;
9. write `revision_published` journal;
10. apply the journaled active/previous/pending-GC `ResourceIndexDelta` through `apply_delta_locked` with the already-held guard against the latest index;
11. write `committed` journal with the exact persisted index generation;
12. release global and revision locks but retain the resource and capacity-scope guards; release the reservation by version CAS under the already-held capacity guard, then finish bounded transaction-owned staging/temp/trash cleanup while both guards remain held;
13. reacquire the global lock in the allowed resource-to-global order, require current generation at least `committed_generation` plus exact touched after-values/final ownership, and persist `finalized`; release global, then resource, then the sorted capacity-scope guards in strict reverse acquisition order, and invoke domain cache convergence once. Unrelated-resource commits may advance the generation during cleanup; same-resource mutation cannot begin before this finalization. Leave pruning to the bounded journal reaper.

Download and ZIP parsing are injected inputs and occur before locks. The logical `ResourceRevisionRef` deliberately excludes installation instance; the index/journal/path/lease/guard carry the instance separately. The first 12 canonical content-hash hex characters are only a diagnostic path suffix, the random instance prevents same-revision repair collisions, and full hash remains authoritative.

- [ ] **Step 6: Test two-resource and same-resource interleavings**

Use controlled barriers before global commit. Both different resources must commit without lost updates even when based on the same generation. Same resource yields one success and one `resource_commit_conflict` or a deterministic retry that revalidates exact detail before committing.

- [ ] **Step 7: Run and commit**

```bash
set -euo pipefail
python -m pytest tests/test_resource_store_index_unit.py tests/test_resource_store_transactions_unit.py -q
git add core/resource_store/index.py core/resource_store/journal.py core/resource_store/transactions.py tests/test_resource_store_index_unit.py tests/test_resource_store_transactions_unit.py
git commit -m "feat(resources): publish immutable revisions transactionally"
```

## Task 4: Startup Recovery At Every Crash Boundary

**Files:**
- Modify: `core/resource_store/transactions.py`
- Create: `tests/test_resource_store_recovery_unit.py`
- Create: `tests/resource_store_fixture_factory.py`

- [ ] **Step 1: Add failure-injection hooks and crash tests**

In `tests/resource_store_fixture_factory.py`, expose deterministic builders that materialize each state under caller-supplied `tmp_path`; they accept no absolute source path, perform no network I/O, and create only UUID-owned fixture children. Inject a process-termination exception at: staged files complete, prepared journal persisted, final rename complete, revision-published journal persisted, deletion inventory persisted, before/after each capture rename and its progress write, all captures complete but before `deletion_captured`, `deletion_captured` persisted, deletion index replaced, committed journal persisted, before/after each pre-commit restore rename and its progress write, before/after each cleanup unlink and its progress write, cleanup complete, and finalized journal persisted. Restart a fresh manager for each generated persisted tree and assert the exact expected convergence. Include original-path recreation during pre-commit restore, original-path recreation after commit, changed trash identity, missing capture, multiple unrecorded physical moves, and planned/captured/restored/cleaned state-order mismatch; every ambiguous pre-commit case retains bytes/reservation and closes writes rather than overwriting or unlinking, while post-commit cleanup never treats a recreated source path as journal-owned. Add finalized-journal pruning boundaries at rank 255/256/257 and age 29/30/31 days plus foreign/symlink transaction children. Finalize install A, update B, rollback A, then uninstall/local-delete/GC and restart; every superseded finalized journal must remain valid/prunable rather than quarantining because its old index values or payload no longer exist. Task 5 reuses the same helper for migration trees, providing two adoption sites in the shadow PR.

- [ ] **Step 2: Implement deterministic recovery table**

Before admitting any mutation for a resource, recover every non-final transaction that names it under the same capacity/resource/revision/global lock protocol; a newer same-resource transaction cannot supersede an unfinalized committed or aborted outcome. Branch on operation before applying path/state rules, and use `apply_delta_locked` with the one already-held global guard rather than nesting `apply_delta`:

- non-deletion index contains transaction after-record: verify final and mark committed;
- deletion operation in `prepared`: first require exact index before-values and the legal `captured* restored* planned*` progress shape, then reconcile at most one interrupted protocol move. Only when no entry is yet `restored`, if the first `planned` entry after the captured prefix is physically absent at source and exact in trash, persist it as `captured`. If rollback has started, or recovery has selected rollback for an incomplete captured prefix, and the last `captured` entry before the restored suffix is physically exact at source and absent in trash, persist it as `restored`. All other entries must match their recorded physical state. Simultaneous forward/rollback discrepancies, multiple unrecorded moves, both paths present, neither path present, changed identity/hash/bytes, or a non-prefix move quarantines both locations and retains the reservation;
- deletion operation in `prepared` with zero entries captured after reconciliation: verify every `planned` or `restored` source exactly and every trash path absent, persist aborted/finalized, and release only the journal-owned reservation;
- deletion operation in `prepared` with a strict but incomplete captured prefix and optional restored suffix: restore each remaining captured file in reverse order with atomic no-replace and persist it as `restored` before restoring the next, then verify all sources and absent trash before abort/finalize; any occupied source or ownership ambiguity quarantines without overwrite or unlink;
- deletion operation in `prepared` with every entry recorded `captured` and physically exact in trash: persist `deletion_captured` without unlinking, then follow that state;
- `deletion_captured` + exact index before-values: apply the journaled deletion delta once and persist committed generation; if the after-values are already present, only verify/persist committed; any third state or changed capture quarantines with zero unlink;
- committed deletion operation: verify exact after-values and the legal `cleaned* captured*` progress shape. Every later `captured` entry must still have its exact trash file; only the first `captured` entry may have absent trash because the crash occurred after its unlink but before the progress write, and recovery then persists that single entry as `cleaned` before rescanning. Otherwise no-follow recheck the first captured trash identity/hash/bytes, unlink only that trash file, fsync, and persist `cleaned` before advancing. A recreated source path is no longer journal-owned and must remain untouched. Multiple absent captured trash files, changed trash, non-exact after-values, or any other state quarantines; release the reservation only at its operation-defined post-commit point and finalize only when every entry is `cleaned` and every trash path is absent;
- prepared + no final: persist aborted, delete only owned staging/release its reservation, verify index before-values, then mark finalized with null committed generation;
- prepared + final + no staging + complete ownership/tree/binding: persist revision-published then forward;
- prepared + final/staging both present or mismatch: quarantine, keep reservations, close domain writes;
- revision-published + base generation unchanged: forward commit;
- revision-published + unrelated generation changed + resource precondition unchanged: rebase delta and forward;
- revision-published + resource/reservation conflict or damaged final: quarantine and require repair;
- committed non-deletion: require current generation at least the exact recorded committed generation, verify touched after-values/final tree while same-resource mutation is excluded, finish owned reservation/temp/trash cleanup, then mark finalized; never replay mutation;
- aborted/finalized aborted deletion: require only `planned` or `restored` entries, exact sources, absent trash, null committed generation, and operation-defined reservation release; never rewrite `restored` back to `planned`;
- finalized: validate the terminal journal and absence of transaction-owned staging/reservation/trash only. A finalized committed deletion requires every entry `cleaned`; a finalized aborted deletion keeps its `planned`/`restored` history. Do not require its historical before/after values or immutable final tree to remain current, because a later finalized same-resource update, rollback, GC, detach, or uninstall may legitimately supersede them.

Recovery validates the journal's space-reservation identity. It may release a dead-owner reservation only after abort/commit/quarantine state is durably recorded; it never recreates a missing reservation or downloads again. A fully published final can converge its index without reserving already-consumed bytes, while an incomplete staged/final write aborts or quarantines.

The reaper sorts finalized committed/aborted outcomes by `(finalized_at, transaction_id)`, retains at most the newest 256 and no finalized journal older than 30 days, then removes only the exact no-follow transaction directory whose terminal journal identity/state and empty transaction-owned staging/trash still match under the transaction cleanup lock. `finalized` is durable proof that the index/final-or-absent outcome and cleanup were checked while same-resource mutation was excluded; the reaper must not compare that historical delta to a legitimately newer current index or payload lifecycle. A raced/unknown child, changed journal, symlink/reparse point, or cleanup failure is retained and quarantined. `committed`, active, aborted-with-unproven-cleanup, and quarantined journals are never auto-pruned. Recovery cannot download, overwrite, infer ownership, or delete uncertain final content.

- [ ] **Step 3: Test quarantine visibility and write closure**

Resolver must never expose `quarantined_recovery`. Capability action list becomes empty for the affected domain. Repair dry-run reports journal/final/staging differences with relative paths and hashes, not absolute paths.

- [ ] **Step 4: Run and commit**

```bash
set -euo pipefail
python -m pytest tests/test_resource_store_recovery_unit.py tests/test_resource_store_transactions_unit.py -q
git add core/resource_store/transactions.py tests/resource_store_fixture_factory.py tests/test_resource_store_recovery_unit.py
git commit -m "feat(resources): recover interrupted revision commits"
```

## Task 5: Domain Adapters And Shadow Migration

**Files:**
- Modify: `.gitignore`
- Create: `core/resource_store/domains/base.py`
- Create: `core/resource_store/domains/material.py`
- Create: `core/resource_store/domains/lut.py`
- Create: `core/resource_store/hash_cache.py`
- Create: `core/resource_store/migration.py`
- Create: `api/resource_store_dependencies.py`
- Create: `scripts/rehearse_resource_store_shadow.py`
- Read: `tests/resource_store_fixture_factory.py`
- Test: `tests/test_resource_store_domains_unit.py`
- Test: `tests/test_resource_store_hash_cache_unit.py`
- Test: `tests/test_resource_store_migration_unit.py`
- Test: `tests/test_resource_store_shadow_rehearsal_unit.py`

- [ ] **Step 1: Write domain hash/loadability tests**

Material covers exact required roles and `lumina-material-required-files-v1`. LUT covers `.npy`, keyed `.json`, `.npz`, `.msgpack`, legacy v1 filename hash, raw-byte canonical hash, metadata/palette/color mode/base channel/layer order/stacks, synthetic empty/all-Air recipes, and supported standard LUT sizes. Invalid content is `content_unloadable`, never a valid local equivalent.

- [ ] **Step 2: Define the adapter protocol**

This task starts only after the merged client/binder PR and imports `VerifiedPackageBinding` from `core.resource_store.package_binding`; do not redeclare a structural copy.

```python
@dataclass(frozen=True)
class RevisionPayload:
    resource_kind: ResourceKind
    logical_path: str
    content_hash_algorithm: str
    content_hash: str
    managed_files: tuple[ManagedFile, ...]
    created_directories: tuple[str, ...]
    display_snapshot: InstalledDisplaySnapshot


@dataclass(frozen=True)
class LegacyResourceFact:
    resource_kind: ResourceKind
    source_relative_path: str
    legacy_record_id: str | None
    legacy_revision_id: str | None
    observed_files: tuple[ObservedFile, ...]
    canonical_content_hash_algorithm: str | None
    canonical_content_hash: str | None
    loadable: bool
    scan_fingerprint: str


@dataclass(frozen=True)
class VerifiedLocalImportBinding:
    source_kind: Literal["material_package", "lut_file"]
    source_root_id: str
    source_relative_path: str
    source_identity: VerifiedFileIdentity
    payload: RevisionPayload


class ResourceDomainAdapter(Protocol):
    kind: ResourceKind

    def canonical_hash_for_local(self, logical_path: str) -> str: ...
    def validate_staged_revision(self, staged_root: BoundPathHandle, binding: VerifiedPackageBinding) -> RevisionPayload: ...
    def bind_local_import(
        self,
        source: BoundPathHandle,
        source_kind: Literal["material_package", "lut_file"],
    ) -> VerifiedLocalImportBinding: ...
    def scan_legacy_resources(self) -> Iterable[LegacyResourceFact]: ...
    def project_legacy_alias(self, revision: RevisionRecord) -> str: ...
    def validate_loadable(self, revision_root: BoundPathHandle, files: Sequence[ManagedFile]) -> None: ...
    def invalidate_runtime_caches(self) -> None: ...
```

Material adapter calls existing Stage A validation/load logic without importing API modules. Its local-package binder applies the same entry/path/count/expanded-byte/compression/hash/role/loadability limits as managed package validation but does not require or synthesize a Registry/envelope identity. LUT local binding accepts one no-follow regular `.npy`, keyed `.json`, `.npz`, or `.msgpack` file, runs the allocation preflight and complete loader checks, and records one raw-byte canonical hash. Both derive `VerifiedFileIdentity` by hashing through the same open handle used for validation.

Local package metadata, filename, parent directory, channel, and `publisher_kind` never confer cloud identity or Lumina authority. `VerifiedLocalImportBinding.payload.display_snapshot.publisher_kind` is forced to `community`, `source_ref` remains null, derivation is `direct_import`, and the frontend uses `display_provenance="local_content"` rather than presenting an official/community cloud-source badge. A later unique canonical-hash match may create `local_equivalent` with explicit `resolved_legacy` derivation, but it still does not acquire managed ownership without explicit adoption.

- [ ] **Step 3: Implement a bounded non-authoritative hash cache**

Persist only normalized domain-relative path, byte count, mtime nanoseconds, platform file identity, algorithm, digest, and last-observed generation under `_sync/resource-store/hash-cache-v1.json`. Write atomically, cap at 50,000 entries and 32 MiB canonical JSON, evict deterministic oldest `(last_observed_generation, normalized_path)` entries before writing, remove missing paths, and invalidate on any identity/size/mtime mismatch, managed mutation, repair, or cache schema error. Read through a no-follow bounded handle and never persist an absolute path.

The cache may accelerate read-only inventory hints. Exact cloud-equivalence/adoption, package binding, managed-health convergence, workflow resolution, repair, uninstall, and GC always stream the complete current bytes and compare the full digest, even when every metadata hint matches. Tests modify bytes while restoring size/mtime, replace inode/file identity, corrupt the cache, collide casefold paths, and prove every authority-bearing operation ignores the stale hint.

- [ ] **Step 4: Write migration tests before implementation**

Import the deterministic tree builders from `tests/resource_store_fixture_factory.py`. Cover empty/new install, offline v1 index, missing/partial/corrupt v1 index, exact hash match, hash ambiguity across cloud identities, same name/different hash, same hash/different names, managed-looking directories without ownership, local files under Cloud, Unicode/casefold path collision, renamed local file, duplicate source paths, unknown sidecar, symlink, insufficient double-storage capacity, source change during copy, copy crash, raced final destination, and separate material/LUT marker state.

- [ ] **Step 5: Implement read-only shadow generation**

Migration computes fingerprints of legacy indexes and observed files, allocates a persistent `store_id`, calculates the full additional bytes required by managed candidates, acquires a capacity reservation, and writes a candidate index plus migration journal under `_sync/resource-store/shadow/{scan-id}/`. For each legacy record that already has provable managed ownership, require an online or previously exact-v2-authorized binding for the same complete resource ref, canonical content hash, non-null public publisher ID, active envelope, package hash/bytes, and bounded display snapshot before creating any managed candidate. Then copy its exact regular payload files into scan-owned immutable staging, full-hash/loadability verify them, fsync, and record source/staged tree digests plus intended final relative path. A legacy/cloud-looking record without that complete evidence remains `local_import`, `local_equivalent`, or `legacy_unresolved`; offline migration never inserts placeholder envelope/package/publisher values and may promote it only in a later explicit adoption transaction after exact binding. Once all staged bytes are durable, release the reservation because current free-space accounting now includes those consumed bytes; same-filesystem cutover only renames them. A crash before release converges through owner/journal recovery. Migration never moves, edits, chmods, deletes, or claims ownership of the original payload. Abort removes only scan-owned staged files after journal/tree verification; ambiguity is retained for repair.

Every observed non-managed local item gets a stable UUID-style `local_id`. Cloud identity is assigned only on exact canonical hash with one visible candidate; zero candidates become `legacy_unresolved`; multiple candidates remain unresolved with candidate IDs for user choice. Names, paths, channels, and IDs alone never decide equivalence. Candidate index `immutable_path` values are the intended final paths, while the migration journal is the sole mapping to staged copies; shadow readers never expose those not-yet-published paths as active. Each legacy alias binds the original relative path, complete observed file set, bytes/hashes, and scan fingerprint; it suppresses only an unchanged duplicate. A later-changed original automatically becomes a visible stable local import and is never hidden by path alone.

- [ ] **Step 6: Add per-domain construction and an executable shadow rehearsal**

`api/resource_store_dependencies.py` builds material and LUT paths/stores lazily and exposes test overrides. During this PR, application startup may audit/recover a shadow only behind `LUMINA_RESOURCE_STORE_SHADOW=1`; it must not register lifecycle routes or modify old handlers.

`scripts/rehearse_resource_store_shadow.py` requires distinct explicit `--material-root-copy`, `--lut-root-copy`, and owner-marked `--evidence-dir` paths outside the checkout and refuses configured primary roots, symlinks/reparse points, overlapping/equal roots, or a nonempty foreign evidence directory. It opens both copied roots, runs the production two-root platform probe, writes a normalized NUL-safe before manifest of every pre-existing regular file's relative path/identity/bytes/full SHA, invokes the exact production shadow migration for both domains, and writes the after/delta report. Success requires every pre-existing payload/index byte, mode, identity, and mtime to remain unchanged and permits new files only in the explicitly enumerated `_sync/resource-store/shadow/**`, per-domain marker, hash-cache, and bounded shadow audit paths; it rejects any move/delete/chmod/timestamp drift, unknown sibling, absolute path in evidence, partial domain result, or cleanup ambiguity. The harness never imports/calls the later repair CLI. Tests inject source mutation during scan, low capacity, crash/restart, extra output, path collision, primary-root confusion, and exact one-over evidence bounds.

- [ ] **Step 7: Run and commit shadow PR**

```bash
set -euo pipefail
python -m pytest tests/test_resource_store_models_unit.py tests/test_resource_store_index_unit.py tests/test_resource_store_transactions_unit.py tests/test_resource_store_recovery_unit.py tests/test_resource_store_domains_unit.py tests/test_resource_store_hash_cache_unit.py tests/test_resource_store_migration_unit.py tests/test_resource_store_shadow_rehearsal_unit.py tests/test_resource_store_properties.py -q
git add core/resource_store/domains/base.py core/resource_store/domains/material.py core/resource_store/domains/lut.py core/resource_store/hash_cache.py core/resource_store/migration.py api/resource_store_dependencies.py scripts/rehearse_resource_store_shadow.py tests/test_resource_store_domains_unit.py tests/test_resource_store_hash_cache_unit.py tests/test_resource_store_migration_unit.py tests/test_resource_store_shadow_rehearsal_unit.py .gitignore
git commit -m "feat(resources): build material and LUT migration shadows"
```

Open the shadow PR. Its acceptance evidence must prove old endpoint tests unchanged and a shadow run leaves all legacy payload hashes untouched.

## Task 6: Revision Leases And Heartbeat CAS

**Files:**
- Create: `core/resource_store/leases.py`
- Create: `core/resource_store/resolver.py`
- Test: `tests/test_resource_store_leases_unit.py`

- [ ] **Step 1: Write barrier-controlled lease tests**

Cover managed create only on `available`, create blocked on `pending_gc`, existing lease renew allowed on `pending_gc`, and local-lock create only for the exact current local record version. For both record kinds cover expected fence-or-record-version/version/owner/session/job checks, missing renew cannot recreate, idempotent release only when file is already absent, wrong identity cannot release, stale TTL alone cannot delete a live owner, dead/reused PID detection, active session/job guard, temporary-file crash, and formal record files only. Register a worker `ReaderGuardRecord` before opening a managed/local path; race guard registration against owner death, token release, pending-GC/delete, fence/record-version change, and process reuse. A live exact guard blocks destructive convergence after the API owner dies; a missing, malformed, wrong-job, wrong-token, stale-fence/version, or dead/reused-process guard never authorizes I/O or remains as a permanent blocker. Restart with live/dead local tokens and reader guards and prove delete remains blocked or safely clears them by the same owner proof.

- [ ] **Step 2: Implement lease record persistence**

Use the exact design schema and this public result:

```python
@dataclass(frozen=True)
class ResolvedResourceLease:
    reference: ResourceRevisionRef
    store_id: str
    installation_instance_id: str
    immutable_relative_path: str
    lease_id: str
    revision_fencing_generation: int
    lease_version: int
    expires_at: str


@dataclass(frozen=True)
class ResolvedLocalLease:
    local_id: str
    store_id: str
    local_relative_path: str
    local_record_version: int
    content_hash_algorithm: str
    content_hash: str
    lock_token_id: str
    lock_token_version: int
    expires_at: str
```

Managed create, renew, release, reader-guard registration/release, and stale-delete all acquire the same installation-instance revision lock and re-read index plus lease. Local-token/reader-guard operations acquire the local resource lock and re-read the exact local record/version plus `LocalLockRecord`. Lease/local-lock creation takes a `ResourceUsageKind` selected by the server workflow adapter, never arbitrary browser text; renew cannot change it. A worker guard requires the still-existing token, matching job ID, installation instance, fence or local-record version, and its own handle-derived `ProcessIdentity`; it is durable before the worker opens the payload through its trusted root handle. Parent token release or stale deletion requires the last successful version and zero live/ambiguous guards bound to that token; an owner crash therefore retains the parent record until every guard releases or its process identity is proven dead/reused. Writes use sibling temp + durable native replacement through held handles. Renew increments only the record version. `.tmp` files never count as leases/locks/guards and recovery deletes only unambiguous owned temp files.

Each formal lease/local-lock/reader-guard JSON is at most 16 KiB. Per domain, cap managed leases at 4,096 with at most 64 per revision, local locks at 4,096 with at most 64 per local ID, and reader guards at 8,192 with at most 64 per parent token; configurable values may only lower these hard ceilings. Creation first clears only proven-dead/reused owners under the same locks, then returns a typed `resource_lease_capacity` without creating a temp/formal record when still full. An unknown, oversized, malformed, symlink/reparse, or identity-ambiguous record fails destructive operations closed and appears in repair; it is never skipped to make capacity available.

- [ ] **Step 3: Implement resolver behavior**

Resolve by complete resource reference or managed key; select the current matching installation instance, then verify logical revision, instance ID, content hash algorithm/hash, lifecycle state, managed file facts, and domain loadability while holding that instance's revision lock; persist lease; recheck instance/fence/state; then return only store ID plus normalized relative location. Never resolve managed resources by title/display name or silently select latest for an exact request. A same-revision repair creates a new active instance, while an already-issued lease/guard remains pinned to the old instance until release and GC.

`immutable_relative_path`/`local_relative_path` are safe to persist but do not authorize path I/O. The API/worker maps `store_id` through the trusted process configuration, opens the root capability, and performs the final no-follow relative open only after its lease/guard proof; no absolute resolved path is serialized, passed across processes, logged, or exposed to a browser. Local resources use stable `local_id` and no cloud-revision lease, but resolution under the local-item lock must handle-relative scan the complete observed inventory, stream full hashes, compare record version plus canonical content algorithm/hash, and verify domain loadability before issuing a token. Workflows that need deletion protection receive `ResolvedLocalLease` carrying that exact version/hash proof; its `LocalLockRecord` under `local-locks/` uses the same owner/session/job heartbeat, version CAS, stale-owner proof, and release ordering as managed leases, and local delete refuses while one or any bound reader guard is live or ambiguous. External replacement, same-size/mtime mutation, sidecar drift, or record mismatch fails before token creation and payload I/O.

- [ ] **Step 4: Test renew versus stale-delete interleavings**

With a barrier inside the revision lock, prove either renew commits first and stale-delete exits, or stale-delete advances/removes first and the late renew returns `resource_lease_fenced` without recreating a file.

- [ ] **Step 5: Run and commit**

```bash
set -euo pipefail
python -m pytest tests/test_resource_store_leases_unit.py -q
git add core/resource_store/leases.py core/resource_store/resolver.py tests/test_resource_store_leases_unit.py
git commit -m "feat(resources): lease exact immutable revisions"
```

## Task 7: Pending GC, Ownership-Proven Deletion, And Lifecycle State Machine

**Files:**
- Create: `core/resource_store/gc.py`
- Create: `core/resource_store/store.py`
- Test: `tests/test_resource_store_gc_unit.py`

- [ ] **Step 1: Write lifecycle transition tests**

Cover install, update, local material-package import, local raw-LUT import, local rollback, remote exact rollback, repair, resolve-legacy-identity, adopt-local-equivalent by copy, create-local-copy, uninstall, detach management, local delete, and update-all partial success. Assert current+previous slot swapping, one leased older installation instance temporarily in the bounded pending-GC slot, no in-place modification, and stable failure state. Repair an active damaged revision while its old instance is leased: publish a distinct instance of the same logical revision, atomically make it active, retain the old lease/bytes in previous or pending GC, and collect only after release. Inject crash before/after new-instance publication, index switch, old-instance slot movement, and reservation release; restart must expose exactly one active instance without losing or overwriting either tree. With the pending slot still leased, attempt another update/rollback/repair that would evict the previous slot and require `resource_history_busy` before network download, capacity reservation, staging, or index mutation; after release/GC, retry successfully. For local imports cover source path swap/in-place mutation, unsafe archive, allocation-bomb LUT, fake `publisher_kind=lumina`, filename/path collision, capacity failure, copy/extract crash, and source cleanup; no case may create a managed ref or official badge. Cover same target requested twice, update during rollback, insufficient disk, target reservation conflict, copy-name collision, partial copy crash, detached content restart, atomic managed-to-local reservation transfer, local-delete strong ETag/`If-Match`, file replacement after confirmation, reservation release after file convergence, crash before/after transfer/release, and delete while a local lock token is active. Uninstall and detach must test leases on every active, previous, and pending installation instance independently. Add the complete `legacy_unresolved -> local_equivalent -> adopt copy -> managed lease -> blocked uninstall -> release -> uninstall -> restart GC` chain for each domain, including crashes around resolution/adoption/GC, and prove original local bytes survive with no duplicate owner. Persist/reload direct-import, managed-copy, detached, resolved-legacy, and mixed managed/local ordered LUT-merge derivations; delete or update every source afterward and prove the immutable derivation remains ordered/auditable but grants no stale read authority. Inject conflict/crash before the first, between middle, and after the last deletion-capture rename; prove no bytes are unlinked before the full capture/index commit and recovery either restores exact originals or retains an explicit quarantine plus reservation.

- [ ] **Step 2: Write deletion fail-closed tests**

Modify one managed file, byte count, hash, mode, inode type, symlink/reparse point, add an unknown sidecar, change an ancestor, or alter reservation after preflight. Assert no managed file is deleted and revision becomes/stays `gc_conflict`. Confirm detach removes ownership only and preserves every byte.

- [ ] **Step 3: Implement slot and GC transitions**

Moving an installation instance out of active/previous first persists that exact instance as `pending_gc` under its instance revision lock, closing new leases and reader-guard registrations except a worker guard whose matching job token was already issued before the state transition. Before any update/rollback/repair would need that slot, synchronously converge the existing pending instance if it has no live lease/reader guard; if it remains leased, guarded, conflicted, or ambiguous, return `ResourceHistoryBusy` before download/reservation/staging and leave the active/previous/index state unchanged. Never append a second pending instance. GC clears only provably stale instance-bound leases/guards, then under instance-revision+global locks increments that instance's fence and commits `deleting`. It rechecks installation ID, zero live records/state/fence before releasing locks for filesystem work.

Before destructive cleanup, preflight the complete `managed_files`, created-directory inventory, reservation, and all unknown sidecars while holding the revision/local/global lock order. Build the complete sorted `DeletionCaptureRecord` list with state `planned`, exact handle-derived platform identity/hash/bytes, source-relative path, and transaction-owned same-filesystem trash-relative path; persist/fsync that journal before the first rename. Then capture each exact regular file with an identity-guarded atomic no-replace rename, fsync both parents, and atomically rewrite that one entry to `captured` before moving the next. After every expected entry is verified in trash, persist `deletion_captured`, apply the exact index/reservation ownership delta, and persist `committed_generation`. No captured file is unlinked before both durable points. A race/mismatch during pre-commit capture restores already moved files in reverse order with no-replace semantics and atomically persists each corresponding entry as `restored`; entries never moved remain `planned`. If an original name has been raced into existence or restore proof is ambiguous, retain both the trash bytes and reservation as `gc_conflict`/quarantined repair rather than overwriting or deleting either file. A crash between a capture or restore rename and its progress write is reconciled only for the one exact next entry under the same locks; any second discrepancy or non-prefix move quarantines.

After complete capture and index convergence, delete journal-owned trash files in deterministic capture order, rechecking the captured platform identity/hash/bytes before each unlink, fsyncing, and persisting that one entry as `cleaned` before advancing; then deepest-first `rmdir` exact `created_directories`, retaining non-empty directories. If recovery proves the committed after-values and finds only the first still-`captured` entry's trash absent, it treats that as the single unlink-before-progress crash window and advances it to `cleaned`; a later or second missing trash file quarantines. Recovery never inspects, opens, or deletes a source path that may have been recreated after commit. The same model and state machine applies to uninstall, local delete, and GC; none may maintain an ad hoc deletion checklist. On crash, recovery deterministically resumes/rolls back a strict pre-commit capture prefix or finishes post-commit cleanup; it never infers ownership from a path, trusts an old process token, restores the old fence, or turns pre-commit missing trash into success. Tests assert a preflight/race failure never unlinks any user or managed byte, including when the changed file sorts after already captured files.

- [ ] **Step 4: Implement `ResourceStore` lifecycle composition**

Expose typed methods for status, managed install, verified local import, update, rollback, repair, resolve legacy identity, adopt, local copy, uninstall, detach, local delete, update-all, payload resolve, recover, migrate, and audit. Every method takes IDs/refs plus injected verified payloads; no method accepts a package URL, absolute destination, browser hash, channel, visibility, or unvalidated upload object.

`import_local(binding)` maps the trusted `source_root_id`, reopens `source_relative_path` through a held root/ancestor capability, compares its full `VerifiedFileIdentity`, acquires same-volume capacity for source copy plus expanded bytes, and stages into a transaction-owned local destination handle. Material packages reuse Task 3's member-by-member exclusive extractor over only `payload.managed_files`; raw LUTs stream-copy from the same verified handle into one exclusive file. Recompute source/full output hashes after copy, run domain loadability, durably flush, publish no-replace, commit a stable `local_id`/reservation/observed-file/derivation set, then remove only the request-owned upload staging name relative to its still-held parent after identity proof. The logical local destination comes from the validated content suggestion with a bounded server suffix, never the multipart filename or browser path. Any mismatch/crash leaves no index pointer and cleans or quarantines only transaction-owned staging.

Create-local-copy acquires an exact instance-bound source lease, copies only verified payload files into a same-filesystem staged local destination, validates domain loadability/full hash, publishes with no-replace semantics, and commits a stable `local_copy` ID plus complete source ref and `managed_copy` derivation before releasing the lease. The server derives a normalized available logical path from the source title/path with a bounded numeric suffix; browser text cannot supply a path segment. `resolve_legacy_identity(local_id, expected_etag, exact_ref, verified_local_binding)` takes a freshly online-validated candidate supplied by the integration layer, reopens every current local file through the held root/local capability, verifies record version/ETag, domain roles/path/loadability and canonical algorithm/hash, then commits only `entry_kind=local_equivalent`, complete non-authoritative `source_ref`, `resolved_legacy` derivation, cleared candidate ambiguity, and incremented local record version. It never copies/moves bytes, stores envelope/package/display authority, or creates managed ownership; failure leaves the record byte-identical. Adoption is a separate later action requiring a fresh active exact binding, compares every local role/path/byte/hash plus canonical content identity, then copies that exact local equivalent into a new immutable managed installation instance bound to the active envelope; it leaves the original local bytes untouched and is unavailable offline. Direct imports use `direct_import`; detach uses `detached_managed`. LUT merge receives the already ordered, currently leased/locked managed/local inputs and commits one `lut_merge` derivation whose immutable inputs preserve exact order and duplicates; it never collapses them into one `source_ref`. The store itself performs no network request.

Uninstall and detach first acquire all installation-instance revision locks for that resource in sorted order and fail with `ResourceInUse` when any active, previous, or pending instance has a live/ambiguous lease. Uninstall captures every owned instance through the deletion journal before removing the managed record and reservations. Detach first converges/captures previous and pending instances, then commits the active immutable payload as a `local_import` with source ref, `detached_managed` derivation, and observed-file facts, removes envelope/update ownership, and atomically transfers the same active-path reservation from the managed owner to the newly allocated stable `local_id`; it does not move or delete the active bytes. Resolver continues to expose them only by stable local ID/provider alias. A crash cannot leave both owners, no owner, an untracked historical instance, or a local record without its reservation.

Local detail performs a read-only, no-follow scan under the local-item lock and returns a quoted strong ETag derived from store ID, local ID, local-record version, normalized recognized-file inventory, current file identities/bytes/full hashes, and unknown-sidecar set. Local DELETE requires explicit local ID plus `If-Match`; missing precondition is `428 local_delete_precondition_required`. Under the same lock it recomputes the complete facts. A mismatch is `412 local_resource_changed` with zero deletion; the UI must refetch details and reconfirm. An unknown sidecar or unrecognized file makes delete unavailable and returns `409 local_path_conflict`; it retains both bytes and reservation. The browser never supplies a path or an independently trusted digest, the ETag is not logged/persisted in frontend state, and legacy adapters may delete only when current facts still equal the indexed observation.

After a matching preflight, create a `local_delete` journal with the exact current recognized files, all capture entries initially `planned`, and the exact local record/reservation before/after delta; fsync it before the first rename and use the same capture-before-unlink transaction described above. Persist every per-file `captured` transition, then `deletion_captured`, then local-index removal/committed generation. Release the local reservation only after that commit; post-commit trash cleanup persists each `cleaned` transition and does not restore the reservation. A race before full capture becomes `local_resource_changed`; already captured bytes are restored in reverse order and persisted as `restored`, or retained with the reservation in explicit quarantine if a no-replace restore cannot be proven. It never deletes the raced file, an unrelated sibling, a captured byte before commit, or a source path recreated after commit. The operation never accepts a managed ID and never follows a logical display path.

Batch update uses `LUMINA_RESOURCE_UPDATE_MAX_CONCURRENCY` with default `3` and valid range `1..8`, gives each resource its own transaction, continues after failures, preserves input order in the result, and invokes one final domain cache convergence. Tests instrument active downloads/file descriptors and prove the configured bound.

- [ ] **Step 5: Run and commit**

```bash
set -euo pipefail
python -m pytest tests/test_resource_store_gc_unit.py tests/test_resource_store_leases_unit.py tests/test_resource_store_transactions_unit.py -q
git add core/resource_store/gc.py core/resource_store/store.py tests/test_resource_store_gc_unit.py
git commit -m "feat(resources): manage revision lifecycle and guarded GC"
```

## Task 8: Writer Admission And Independent Domain Cutover

**Files:**
- Create: `core/resource_store/admission.py`
- Modify: `core/resource_store/capacity.py`
- Modify: `core/resource_store/migration.py`
- Create: `core/resource_store/reader_registration.py`
- Create: `core/resource_store/service_epoch.py`
- Modify: `api/resource_store_dependencies.py`
- Create: `scripts/cutover_resource_store.py`
- Test: `tests/test_resource_store_cutover_unit.py`

- [ ] **Step 1: Write writer-drain and mixed-domain tests**

Cover in-flight v1 writer completion, close admission, bounded drain timeout/reopen, persistent writer lease with live/dead/reused PID/boot, marker `v1_active -> migration_prepared -> v2_committed`, canonical reader-manifest ordering/hash and exact/one-over bounds, interrupted reader proof/journal/marker writes, missing/forged/mismatched `reader_adapter_generation` and manifest hash, Stage-11 composition with no production reader registration, old API/worker/scheduler process surviving a restart, held service-epoch lock, missing/forged/changed service-manager deployment fence, inaccessible/ambiguous process or root-handle inventory, wrong exact build, one-root/equal-root CLI use, fingerprint CAS failure before publication back to v1, capacity refusal before reader proof or marker work, crash before/after cutover-reservation binding, first/middle/last candidate publication crash, raced final destination, index commit crash, marker commit crash, reservation release crash, partial final set, staged/final digest mismatch, unknown adapter generation read-only behavior, and material/LUT in opposite states. At every inventory/checkpoint boundary, race an attempted restart of the old service/unit/container and a direct old binary launch; either the OS/service-manager fence prevents creation or the held service epoch makes the process exit before reader/writer composition. Tests prove every failed reader/quiescence/fence/capacity precondition leaves both marker and index byte-identical at `v1_active` with no journal/final publication.

- [ ] **Step 2: Implement admission tickets**

Every mutating handler/scheduler/repair apply will obtain:

```python
@dataclass(frozen=True)
class WriterTicket:
    writer_id: str
    store_id: str
    domain: ResourceKind
    operation: str
    adapter_generation: Literal["legacy-v1", "resources-v2-1"]
    lease_version: int


@contextmanager
def writer_ticket(
    domain: ResourceKind,
    operation: str,
    adapter_generation: Literal["legacy-v1", "resources-v2-1"],
) -> Iterator[WriterTicket]: ...
```

Admission checks the marker under its own lock, writes a persistent owner lease with PID/start marker/operation/start time, and removes it on exit. Closing admission prevents new tickets but does not hold resource/global locks while waiting. Dead tickets are cleared only after PID/create-time verification.

Writer records are at most 16 KiB and capped at 128 formal entries per domain after clearing only proven-dead/reused owners under the admission lock. Cap exhaustion returns `resource_cutover_busy` before handler work; malformed/unknown writer entries keep admission closed for repair rather than being ignored.

- [ ] **Step 3: Implement reader registration and the offline full-stop boundary**

`reader_registration.py` defines a closed `ReaderAdapterManifest` whose entries contain exactly domain, workflow ID, resolver strategy, worker-guard strategy, and focused test ID. Canonical UTF-8 JSON sorts complete entries, rejects duplicates/unknowns/missing reviewed workflows, caps the manifest at 128 entries and 64 KiB, and computes one raw lowercase SHA-256. Store Task 8 implements the registration kernel but no production caller: it accepts only an in-process typed manifest object, requires both domains at `v1_active`, and obtains a same-volume-aware two-root capacity reservation for the proof, journal, marker/shadow replacements, temporary files, directories, and safety bytes/inodes before any marker lock. A dedicated idempotent reader-registration journal binds both roots, prior marker/shadow generations, manifest bytes/hash, reservation/version, and intended proof paths. It publishes `reader-adapter-v1.json`, updates only the paired reader generation/hash fields, converges every crash boundary, and releases only its exact reservation after both domains agree. Failure or ambiguity keeps both domains read-only and never treats a lone proof/marker as registration. Integration Task 8 supplies the first reviewed manifest and caller in Stage 12.

`service_epoch.py` gives every Stage-11-or-later Studio API lifespan a process-lifetime ownership record and held service-epoch lock for both roots; scheduler/worker process identities remain covered by their writer/lease/guard records. It consumes the already-adopted `api.runtime_build_identity.RuntimeBuildIdentity` used by the deployment-attestation endpoint, rather than defining a second commit source. The trusted release launcher also installs a platform-specific `ServiceManagerFenceProvider` for the deployed service identity. Systemd/launchd/Windows SCM/container orchestration implementations create a supervisor-owned `GuardianFenceSession` in a process/control plane independent of the old service, cutover CLI, and successor: it stops and generation-fences every old deployment, proves exact unit/service/container plus executable/image identity, and prevents all service starts except one exact-build one-use successor admission. The guardian remains live even if the CLI or successor dies. A manual boolean, PID list, environment flag, JSON receipt, ordinary lock file, or CLI-owned process is not a guardian. Unsupported/uninspectable managers cannot perform operational cutover.

The offline CLI can construct `CutoverActivationContext` only after the provider returns a live guardian session and it exclusively acquires both service-epoch locks, validates all process identity records, observes zero live writer/lease/guard owner from an older build, and performs a bounded `psutil` inventory for Lumina API/worker/scheduler entry points, listeners, and open handles under either root. Any inaccessible candidate process, ambiguous PID/create-time/boot identity, held listener/root handle, unknown process record, scope mismatch, service-manager generation/config change, or lost guardian fails closed. The resulting epoch binds both store IDs, the already-established exact runtime build commit, process-inventory digest, service-manager identity/generation/guardian nonce, stop timestamp, and one-use random nonce; the build identity is established before app/CLI composition by the trusted release launcher from the immutable deployment artifact (the exact archived HEAD in E2E), not by a cutover argument. The epoch itself is never accepted from JSON, an environment value, browser request, or caller-supplied file.

Keep the guardian and both CLI epoch locks live through every final publication, index/marker commit, and fsync. After a successful marker commit, write/fsync one bounded guardian-issued handoff ticket under both roots through a dedicated journal; it binds both store IDs/marker generations, exact successor build/reader manifest, guardian nonce, and one-use native admission token but contains no transferable secret in JSON. The CLI then releases both epoch locks while the independent guardian still blocks every old/unapproved start. The guardian launches only the ticket's exact-build deployment and passes its one-use admission over protected inherited IPC/handle state, not argv/environment/disk. Before app/router/worker/scheduler composition, the successor must acquire both now-free epoch locks, re-read the ticket/markers/build/reader proof, and acknowledge those live lock identities to the guardian. Only after that acknowledgement may the guardian mark the handoff complete, retire the old unit, and restore the new generation's restart policy. This is an ordered guarded gap, not lock transfer: the CLI and successor never need to hold the same epoch lock concurrently, while no old process can enter between them. A CLI/successor/IPC crash, timeout, wrong build, lock race, or missing acknowledgement leaves every service generation fenced and the affected domain write-closed for fresh operator recovery; it never restarts the old binary against a committed marker.

`scripts/cutover_resource_store.py` is the only operational activation entry point. It requires explicit distinct `--material-root`, `--lut-root`, `--domain material|lut`, and `--expected-studio-commit` arguments, imports the current build's compiled reader registry plus pre-established runtime build identity, and accepts no generation/hash/manifest/full-stop/build-identity/guardian override. It first audits both roots and the complete capacity scope, obtains the guardian-backed full-stop epoch above, requires the expected 40-character commit to equal that identity, then invokes the engine and handoff state machine. Stage 11 has no compiled `resource-readers-v2-1` registry, so the same exact command necessarily exits before any mutation; Stage 12 can activate one domain at a time only after its durable proof matches. Tests run the real CLI/provider/successor in child processes and prove a fabricated proof, copied old proof, missing/malformed launcher identity, dirty/wrong build, surviving service, guardian loss, old process racing every lock-release/handoff boundary, or one-root view cannot reach writer admission/composition.

- [ ] **Step 4: Implement activation-locked cutover protocol exactly**

The engine accepts only the `CutoverActivationContext` minted by Step 3, never browser/CLI JSON fields. It requires writer adapter `resources-v2-1`, exact compiled/durable reader adapter `resource-readers-v2-1` plus matching manifest SHA, and the one-use full-stop epoch whose process inventory plus still-live guardian prove no older API, worker, scheduler, listener, or open store-root handle survives or can restart. Revalidate the guardian generation and repeat the bounded process/listener/root-handle inventory immediately before `migration_prepared`, after every candidate publication, before index commit, before marker commit, before handoff-ticket publication, and before CLI lock release; a newly observed old process/lost guardian follows the abort/quarantine rules without another irreversible step. Stage 11 has no production reader registrar and therefore every activation attempt fails closed; Integration Task 8 provides it only after the managed-read inventory is complete. Close one domain and drain or time out while the other domain remains independent.

Before taking any resource/revision/global lock, acquire one shared `CapacityManager` reservation owned by the cutover scan/journal for the exact worst-case new/backup index bytes, journal versions, marker temporary/replacement, reader-proof copy, directory entries, fsync/atomic-write overhead, and byte/inode safety margin. Re-read the shadow and current index sizes under their open handles to calculate bounded input, cap the reservation independent of attacker-controlled legacy text, and fail before marker/journal work when it cannot fit. The migration journal durably binds reservation ID/scope/members/version/budget before `migration_prepared`; after that point only cutover recovery may release it. Candidate payload staging already consumed physical space and same-filesystem final publication is rename, but neither fact waives this metadata reservation.

With that live reservation pinned, take the global commit lock and re-read legacy index/file fingerprints, shadow generation, staged same-device tree digests, absence of another live/incomplete scan reservation, exact reader/quiescence proof, and intended path reservations. If they match, persist `migration_prepared` with the bound migration journal before any final publication. Publish every managed candidate with `publish_directory_no_replace`, recording per-candidate completion and fsyncing the journal after each; persist `revisions_published`, re-read source fingerprints and reader/quiescence proof once more, write the verified v2 index generation 0 carrying both adapter generations/reader manifest, persist `index_committed`, and finally persist `v2_committed` marker with the same values. Release the reservation by version only after marker/index/journal convergence; a crash after commit is completed forward by recovery. Reopen admission only for the exact committed adapter. Original v1 payloads remain byte-identical and are suppressed only while their fingerprint-bound non-owning aliases still match; migration never deletes them.

If fingerprints/reader/quiescence proof differ before any final publication, remove only verified scan-owned staging, release the exact cutover reservation, return marker to `v1_active`, reopen v1, and rebuild after a new full-stop epoch. If the second fingerprint/proof check detects a source edit or old process after final publication, mark the scan aborted, retain/quarantine journal-owned finals plus reservation, return to `v1_active` only when no v2 index was committed, and surface the edited source normally. Repair may deterministically resume a complete proven set forward or preserve the quarantine, but this plan never deletes an uncommitted final. Otherwise startup resumes a complete verified set forward while owning the durable reservation. A target race, partial/mismatched final, missing staging, reservation ambiguity, unsupported adapter, or missing reader proof keeps the domain write-closed for repair and never overwrites/deletes the target or reopens concurrent v1 writes.

Startup at `migration_prepared`, any incomplete handoff, or committed marker without a live acknowledged successor keeps writes closed. Recovery never trusts a persisted stop epoch/ticket alone: the operator must obtain a fresh live guardian session, exclusively reacquire both epoch locks, revalidate the exact current service-manager generation, and repeat the complete process/listener/root-handle/owner-record inventory before reading or converging an irreversible journal. Only then may it combine persistent writer leases, backup hash, source fingerprints, scan plus cutover capacity history, staged/final trees, shadow/index generation, journals, both adapter generations, reader manifest, and the matching guardian/ticket facts to prove rollback-to-v1 (only before publication) or forward-to-v2/handoff. Recovery validates and version-CAS adopts/releases only the journal-bound reservation under the shared two-root capacity scope; it never reconstructs a budget from free space or a single root. Tests SIGKILL the guardian request, CLI, journal, each publication, marker, ticket, lock release, successor start, successor lock acquisition, acknowledgement, and guardian completion boundary while an old process repeatedly attempts restart; no case admits two generations or trusts a stale fence. Ambiguity becomes read-only repair. `v2_committed` cannot auto-revert.

- [ ] **Step 5: Run and commit**

```bash
set -euo pipefail
python -m pytest tests/test_resource_store_cutover_unit.py tests/test_resource_store_migration_unit.py -q
git add core/resource_store/admission.py core/resource_store/capacity.py core/resource_store/migration.py core/resource_store/reader_registration.py core/resource_store/service_epoch.py api/resource_store_dependencies.py scripts/cutover_resource_store.py tests/test_resource_store_cutover_unit.py
git commit -m "feat(resources): cut over domain writers independently"
```

## Task 9: Offline Audit And Explicit Repair

**Files:**
- Create: `core/resource_store/repair.py`
- Create: `scripts/repair_resource_store.py`
- Modify: `tests/resource_store_fixture_factory.py`
- Test: `tests/test_resource_store_repair_unit.py`

- [ ] **Step 1: Write dry-run non-mutation tests**

Snapshot every file/hash/mtime across both configured roots, run audit on valid, corrupt-index, interrupted-journal, orphan staging, orphan final, ambiguous ownership, sidecar conflict, stale lease, live/stale/malformed space reservation, cutover metadata reservation, writer lease, reader-generation proof, path reservation mismatch, and deferred migration. Assert dry-run leaves the snapshot identical. Every invocation opens and validates both roots plus the complete capacity-scope membership before auditing either target domain; a missing/unreadable peer root fails closed before cleanup or action generation.

- [ ] **Step 2: Implement typed repair actions**

Report `action_id`, risk, evidence, affected relative paths, expected index generation, and whether auto-apply is allowed. Apply requires explicit `--action-id` or `--all-safe`, takes admission/locks, revalidates evidence/generation, and can only:

- rebuild an index from complete journals and fully verified immutable revisions;
- finalize or abort a deterministic transaction;
- clear a proven dead writer/stale lease;
- remove caller-owned abandoned staging;
- quarantine uncertain content;
- rebuild aliases/reservations from persisted identities;
- detach management while preserving content.

It cannot map by name/path, delete conflicting content, overwrite a revision, or choose one of multiple hash candidates.

- [ ] **Step 3: Add CLI and JSON output**

```bash
set -euo pipefail
: "${STORE_REHEARSAL_PARENT:?set a private parent outside all repositories and primary roots}"
python tests/resource_store_fixture_factory.py rehearse-store-release \
  --owner-parent "$STORE_REHEARSAL_PARENT" \
  --shadow-script scripts/rehearse_resource_store_shadow.py \
  --repair-script scripts/repair_resource_store.py
```

The fixture helper verifies the parent is private/outside every Git worktree and configured primary root, creates a fixed-prefix random child with an owner sentinel, and never accepts an existing/inherited child path or automatically deletes it. It seeds one legacy shadow scenario and one independent stale-lease safe-repair scenario, copies each before mutation, calls the committed production shadow harness, then calls material/LUT repair audit, proves dry-run byte/identity/mtime equality, selects exactly one auto-apply action by parsed JSON, applies that exact ID, and verifies convergence plus an untouched outside sentinel. It prints the retained evidence root for later reviewed cleanup; cleanup after merge must revalidate canonical parent, fixed generated basename, sentinel identity/mode/bytes, and expected manifest before removal. The repair CLI requires both explicit `--material-root` and `--lut-root` even when `--domain` selects one action set, refuses the project root or equal roots, redacts absolute paths in output, and exits nonzero when write admission must remain closed. Tests prove a one-root invocation cannot clear, adopt, or release a same-volume peer reservation.

- [ ] **Step 4: Run and commit**

```bash
set -euo pipefail
python -m pytest tests/test_resource_store_repair_unit.py tests/test_resource_store_recovery_unit.py -q
git add core/resource_store/repair.py scripts/repair_resource_store.py tests/resource_store_fixture_factory.py tests/test_resource_store_repair_unit.py
git commit -m "feat(resources): audit and repair local resource stores"
```

## Task 10: Architecture Docs And Store-Level Gate

**Files:**
- Create: `docs/context/resource-store/CONTEXT.md`
- Create: `CONTEXT-MAP.md`
- Modify: `docs/agents/domain.md`
- Modify: `.gitignore`

- [ ] **Step 1: Document ownership and invariants**

The context doc identifies the storage kernel, domain adapters, API adapter boundary, runtime paths, lock order, transaction states, lease/GC fences, marker states, repair entry point, forbidden direct filesystem access, and test map. It states that material/LUT remain distinct domains using a shared kernel.

- [ ] **Step 2: Run focused full store suite**

```bash
set -euo pipefail
python -m pytest \
  tests/test_resource_store_models_unit.py \
  tests/test_resource_store_index_unit.py \
  tests/test_resource_store_domains_unit.py \
  tests/test_resource_store_hash_cache_unit.py \
  tests/test_resource_store_capacity_unit.py \
  tests/test_resource_store_platform_probe_unit.py \
  tests/test_resource_store_transactions_unit.py \
  tests/test_resource_store_recovery_unit.py \
  tests/test_resource_store_leases_unit.py \
  tests/test_resource_store_gc_unit.py \
  tests/test_resource_store_migration_unit.py \
  tests/test_resource_store_cutover_unit.py \
  tests/test_resource_store_repair_unit.py \
  tests/test_resource_store_properties.py -q
```

Expected: all pass with no skipped crash/concurrency cases on the development platform.

- [ ] **Step 3: Prove legacy baseline and shadow non-mutation**

```bash
set -euo pipefail
python -m pytest tests/test_material_sync_api_unit.py tests/test_lut_registry_sync_unit.py tests/test_material_sync_scheduler_unit.py -q
```

Expected: all legacy tests pass before endpoint adoption. Then run the committed `scripts/rehearse_resource_store_shadow.py` against copied realistic roots and retain its normalized before/after/delta evidence outside the repository; only its enumerated `_sync` shadow/marker/cache/audit files may be new, and no pre-existing payload byte/identity/mode/mtime may change. This stage does not claim a repair rehearsal because `scripts/repair_resource_store.py` is introduced only in Task 9; the exact-head Stage-11 gate runs both the shadow harness and repair dry-run/apply rehearsal after that merge.

- [ ] **Step 4: Run hygiene and diff checks**

```bash
set -euo pipefail
git diff --check origin/dev-refactor...HEAD
git status --short
python scripts/check_tracked_delta_hygiene.py --base origin/dev-refactor
```

Expected: no runtime index/journal/lease/database is newly tracked and no token or concrete machine-local path finding is introduced relative to the target branch. Existing unrelated baseline findings and untracked agent state cannot fail or whitelist this delta.

- [ ] **Step 5: Commit docs and open exact-scope PRs**

```bash
set -euo pipefail
git add docs/context/resource-store/CONTEXT.md CONTEXT-MAP.md docs/agents/domain.md .gitignore
git commit -m "docs(resources): map resource store ownership"
```

The shadow PR must merge before the lifecycle/API PR, which must merge before the cutover/legacy-adapter PR. Each PR body records exact base/head, copied-data hash evidence, crash matrix, concurrency matrix, platform, feature/capability state, and known residual risks. The lifecycle/API PR proves both domains remain uncut-over; the cutover PR proves both still ship `v1_active` and no marker can commit until all old writers are drained, the complete writer and future reader generations match, both-root capacity is reserved, and a full-stop epoch excludes every old process.

- [ ] **Step 6: Re-run the store release gate on committed HEAD**

After the Step 5 commit, rerun the complete focused store suite, legacy baseline/shadow non-mutation rehearsal, platform probe, repair rehearsal, and Step 4 scans against that exact commit. Then require:

```bash
set -euo pipefail
: "${STORE_EXACT_HEAD_REHEARSAL_PARENT:?set a fresh private parent outside repositories/primary roots}"
python tests/resource_store_fixture_factory.py rehearse-store-release \
  --owner-parent "$STORE_EXACT_HEAD_REHEARSAL_PARENT" \
  --shadow-script scripts/rehearse_resource_store_shadow.py \
  --repair-script scripts/repair_resource_store.py
python scripts/check_tracked_delta_hygiene.py --base origin/dev-refactor
git diff --check origin/dev-refactor...HEAD
test -z "$(git status --short --untracked-files=no)"
```

Expected: the exact committed head passes and the tracked tree is clean. Any formatter, generated artifact, documentation correction, or follow-up fix changes HEAD and invalidates earlier evidence.

## Store Merge Gates

Shadow PR is blocked unless:

- models reject every unsafe/incomplete persisted shape;
- index writes are generation-CAS and use proven crash-durable native replacement/file+directory flushing on every supported platform;
- all security-sensitive filesystem use is rooted in held descriptor/handle capabilities; an ancestor check never returns an unpinned path for later use;
- lock ordering is enforced across processes;
- one required two-root disposable probe proves lock/fsync/no-replace support plus correct same-volume/cross-volume capacity topology;
- cross-process capacity reservations prevent download/copy oversubscription and recover dead owners safely;
- transaction recovery covers every named crash boundary;
- same-logical-revision repair publishes a distinct installation instance, swaps it atomically, and preserves old leased bytes until instance-bound GC;
- local derivation preserves ordered mixed managed/local LUT inputs across restart and source deletion without granting stale read authority;
- material/LUT hashes and loadability match all supported formats;
- shadow migration never changes existing payload bytes or guesses identity;
- material and LUT markers/indexes are independent;
- repair defaults to a byte-for-byte non-mutating audit;
- legacy endpoint tests remain green.

Lifecycle/cutover PR is blocked unless:

- lease create/renew/release/stale-delete and GC use the same installation-instance revision lock/fence/version CAS;
- delayed heartbeat cannot recreate a stale lease or outlive `deleting`;
- update/rollback preserve paths held by existing workflows;
- uninstall/delete fail on active leases and ownership ambiguity;
- managed-file changes/sidecars/symlinks cause zero deletion;
- current/previous/pending-GC policy is deterministic and crash recoverable;
- writer admission drains or reopens safely on timeout;
- cutover reserves metadata/index/journal/marker bytes and inodes through the shared two-root capacity scope before taking higher-rank locks;
- `v2_committed` cannot silently return to v1;
- both mixed-domain cutover combinations pass under the compiled reader proof, exclusive service epochs, and a live verifiable service-manager deployment fence;
- the merged Stage-11 composition keeps both markers `v1_active` and rejects activation without the later exact-reader manifest;
- no operational endpoint cutover occurs until the integration plan wraps every legacy writer and managed reader; the old deployment remains OS-fenced through marker commit and exact-build successor epoch acquisition, with restart races tested at every irreversible boundary.
