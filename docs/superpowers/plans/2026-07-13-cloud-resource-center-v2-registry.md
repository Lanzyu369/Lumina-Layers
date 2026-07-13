# Cloud Resource Center V2 Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add immutable, authorization-safe material and LUT v2 catalog/detail/package contracts to Lumina Material Registry while preserving every v1 behavior and migrating existing JSON state without downtime data loss.

**Architecture:** Keep package bytes on the filesystem and introduce a standard-library SQLite metadata database as the transactional source for publishers, resources, revisions, immutable-envelope publication batches, generations, download counts, and bounded catalog snapshots. Existing `RegistryStore` and `LutRegistryStore` become v1 facades over the common repository; separate domain adapters retain material/LUT schemas and projections, while v2 routes add cursor paging, exact revisions, publisher policy, controlled previews, cache policy, and live active-envelope authorization.

**Tech Stack:** Python 3, FastAPI/Pydantic, standard-library `sqlite3`, `zipfile`, `hashlib`, `hmac`, pytest, HTTPX/FastAPI TestClient.

---

## Repository And Branches

Repository: `lumina-layer-studio/Lumina-material-registry`

Required base: `master@ba6e642b4a9565f66363951bcceef095eb8081da`

Use five sequential reviewable branches, each cut from freshly merged `master`:

1. `codex/feat/resource-contract-fixtures-v2`
   - Tasks 1-2.
2. `codex/feat/resource-registry-storage-v2`
   - Tasks 3-5; v2 remains disabled and the unchanged v1 facade is the lighthouse consumer.
3. `codex/feat/resource-publication-v2`
   - Task 6 only; durable dual-artifact publication remains unadvertised by v2 routes.
4. `codex/feat/resource-catalog-v2`
   - Tasks 7-8; versioned read/auth/cache/preview surface over merged publication.
5. `codex/chore/resource-registry-operations-v2`
   - Task 9; Materials import, readiness, repair, probe, and deployment evidence.

Do not stack later branches on an unmerged predecessor or combine storage, publication, authorization/read API, and operations into one review. Each boundary keeps v1 operational and v2 disabled or capability-false until its own readiness conditions are satisfied.

Do not commit `data/`, SQLite files, journal/WAL files, uploaded packages, logs, tokens, or local environment configuration.

## File Structure

Create or modify these files with one responsibility each:

- Create `registry_service/contracts.py`
  - Schema constants, canonical hashes, field normalization, stable public error codes.
- Create `registry_service/database.py`
  - SQLite connection policy, schema migration, `BEGIN IMMEDIATE` transaction helper, generation counters.
- Create `registry_service/repository.py`
  - Transactional publisher/resource/revision/file/envelope/publication-batch/snapshot/download persistence shared by both domains.
- Create `registry_service/domain_adapters.py`
  - Material 2.0/2.1 and LUT 1.0/2.0 normalization plus separate v1/v2 projections.
- Create `registry_service/content_validation.py`
  - Bounded, domain-aware loadability checks for material JSON and every supported LUT storage format.
- Create `registry_service/previews.py`
  - Deterministic, Registry-controlled preview summaries and PNG assets derived only from validated content.
- Create `registry_service/upload_intake.py`
  - Request-level multipart byte/time limits and request-owned same-data-root staging for both legacy upload routes.
- Create `registry_service/import_metadata.py`
  - Dry-run/apply import of Materials metadata through normal validation and approver policy.
- Create `registry_service/build_identity.py`
  - Immutable exact Registry build identity shared by capability attestation and release harnesses.
- Create `registry_service/cursor.py`
  - Signed random snapshot handles; query/principal/generation bindings remain server-side with replay/expiry validation.
- Create `registry_service/cache_policy.py`
  - Public versus private response headers, ETags, `Vary`, and surrogate keys.
- Create `registry_service/cache_invalidation.py`
  - Durable surrogate-key invalidation outbox, bounded retry worker, health-gated public cache mode.
- Create `registry_service/api_v2.py`
  - Capability, v2 catalog/detail/exact revision/package routes and error mapping.
- Create `registry_service/migrate_v2.py`
  - JSON-to-SQLite dry-run/apply CLI with package verification and backup evidence.
- Create `registry_service/fixtures.py`
  - Deterministic contract-fixture generator used by tests and the script.
- Create `scripts/build_contract_fixtures.py`
  - Checked-in fixture regeneration entry point.
- Create `scripts/probe_storage_platform.py`
  - Disposable same-root SQLite/lock/fsync/no-replace capability probe used before migration.
- Create `tests/fixtures/contracts/v2/`
  - Exact accepted/rejected ZIP bytes, expected projections, and checksum manifest.
- Create focused tests:
  - `tests/test_contracts_v2.py`
  - `tests/test_registry_migration_v2.py`
  - `tests/test_registry_v1_contract.py`
  - `tests/test_registry_catalog_v2.py`
  - `tests/test_registry_exact_revision_v2.py`
  - `tests/test_registry_auth_cache_v2.py`
  - `tests/test_registry_cache_invalidation_v2.py`
  - `tests/test_registry_envelopes_v2.py`
  - `tests/test_registry_concurrency_v2.py`
  - `tests/test_registry_content_validation_v2.py`
  - `tests/test_registry_previews_v2.py`
  - `tests/test_registry_upload_intake_v2.py`
  - `tests/test_registry_metadata_import_v2.py`
  - `tests/test_registry_storage_probe_v2.py`
- Modify `requirements.txt`
  - Add `numpy>=1.24`, `msgpack>=1.0.7`, and `Pillow>=10.0` for validation/preview generation.
- Modify `registry_service/manifest.py`
  - Accept material 2.0/2.1 and LUT 1.0/2.0 without redefining legacy hashes; expose normalized file bytes.
- Modify `registry_service/auth.py`
  - Return a scoped `Principal`; use constant-time token checks; never expose token-derived values.
- Modify `registry_service/store.py`
  - Preserve public v1 methods as facades; remove duplicated persistence after parity tests exist.
- Modify `registry_service/app.py`
  - Include the new router, preserve v1 route signatures/defaults, and stream authorized packages.
- Modify `registry_service/repair.py`
  - Read migrated state and rebuild/revoke envelopes without rewriting a package path.
- Modify `README.md` and create `docs/resource-registry-v2-deployment.md`
  - Migration, feature flag, secrets, health checks, backup, rollback, and repair runbook.

## Task 1: Canonical Hashes And Schema Adapters

**Files:**
- Modify: `requirements.txt`
- Create: `registry_service/contracts.py`
- Create: `registry_service/content_validation.py`
- Modify: `registry_service/manifest.py`
- Create: `tests/test_contracts_v2.py`
- Create: `tests/test_registry_content_validation_v2.py`

- [ ] **Step 1: Write failing canonical-vector tests**

Create tests that assert exact bytes, not self-derived expected values:

```python
from registry_service.contracts import (
    LUT_HASH_ALGORITHM,
    MATERIAL_HASH_ALGORITHM,
    canonical_lut_hash,
    canonical_material_hash,
)


def test_material_hash_uses_fixed_logical_names() -> None:
    assert MATERIAL_HASH_ALGORITHM == "lumina-material-required-files-v1"
    assert canonical_material_hash(
        material_sha256="00" * 32,
        stage_a_sha256="11" * 32,
    ) == "sha256:1506f9b2cf695d8b030f1bd348161fa919eb7c03e18cc27bb7f99a33b9ce2752"


def test_lut_v2_hash_is_raw_file_sha() -> None:
    assert LUT_HASH_ALGORITHM == "lumina-lut-file-bytes-v1"
    assert canonical_lut_hash(b"lumina-lut-v2\n") == (
        "sha256:e12a8cc48077999a61886b26e9830303bb6e4f0ea94679d3645a51a4c0a3e5d2"
    )
```

Before committing the expected constants, independently verify them with `printf` plus `shasum -a 256`; do not calculate expected values by calling production functions.

- [ ] **Step 2: Run the tests and verify failure**

Run:

```bash
set -euo pipefail
.venv/bin/python -m pytest tests/test_contracts_v2.py -v
```

Expected: FAIL because `registry_service.contracts` does not exist.

- [ ] **Step 3: Implement strict canonical functions and schema constants**

Create `registry_service/contracts.py` with these public signatures:

```python
from __future__ import annotations

import hashlib
import re

MATERIAL_HASH_ALGORITHM = "lumina-material-required-files-v1"
LUT_HASH_ALGORITHM = "lumina-lut-file-bytes-v1"
MATERIAL_SCHEMAS = frozenset({"2.0", "2.1"})
LUT_SCHEMAS = frozenset({"1.0", "2.0"})
RESOURCE_STATUSES = frozenset(
    {"pending", "approved", "withdrawn", "rejected", "purged"}
)
PUBLISHER_KINDS = frozenset({"lumina", "community"})
_HEX64 = re.compile(r"[0-9a-f]{64}")


def require_raw_sha256(value: object) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ValueError("value must be lowercase raw SHA-256 hex")
    return value


def require_prefixed_sha256(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError("value must use the sha256: prefix")
    digest = value[7:]
    if not _HEX64.fullmatch(digest):
        raise ValueError("value must be sha256: plus lowercase SHA-256 hex")
    return value


def sha256_prefixed(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def canonical_material_hash(*, material_sha256: str, stage_a_sha256: str) -> str:
    material_hex = require_raw_sha256(material_sha256)
    stage_hex = require_raw_sha256(stage_a_sha256)
    payload = (
        f"material.json:{material_hex}\n"
        f"stage_A_parameters.json:{stage_hex}"
    ).encode("ascii")
    return sha256_prefixed(payload)


def canonical_lut_hash(payload: bytes) -> str:
    return sha256_prefixed(payload)
```

Extend manifest validation so material 2.0 defaults the algorithm to `MATERIAL_HASH_ALGORITHM`, material 2.1 requires it explicitly, LUT 1.0 validates its legacy top-level hash then derives a separate canonical v2 hash from raw file bytes, and LUT 2.0 requires `LUT_HASH_ALGORITHM` plus the raw-byte hash. Return both `content_hash` and optional `legacy_content_hash` from normalized validation records.

Use one encoding matrix everywhere: v2 catalog/detail `content_hash`, `package_sha256`, and `preview_sha256` are lowercase `sha256:` plus 64 hex characters and pass `require_prefixed_sha256`; manifest `files[].sha256`, fixture `SHA256SUMS.json`, and internal byte-digest inputs are lowercase 64-hex and pass `require_raw_sha256`. Preserve every v1 field's current encoding, including the current raw-hex v1 package hash and LUT catalog/file hash; `legacy_content_hash` is an opaque copied legacy value and is never normalized into v2 identity. Any historical trimming or representation conversion lives only inside the schema-specific v1 projection/validation adapter and cannot call a permissive shared normalizer. Store the v2 normalized forms in SQLite and let `project_v1` remove/add only the exact legacy representation required by frozen tests. Reject uppercase, whitespace, missing/duplicate prefixes, non-hex, and algorithm/hash encoding mismatch.

Use the master plan's exact `YYYY-MM-DDTHH:MM:SSZ` UTC timestamp codec for all new metadata, API, cursor claims, audit rows, SQLite text columns, and repair/import output. Validate calendar dates and the `1970..9999` year range before persistence, serialize only through the shared codec, and compare parsed instants or canonical fixed-width values. Reject offsets, fractions, leap seconds, impossible dates, and whitespace. V1 projections preserve their existing timestamp strings. Fixture/schema tests cross the minimum/maximum years and reject every alternate spelling.

Fix the new-schema outer ZIP contract to the same values consumed by Materials and Studio: archive bytes at most 64 MiB, at most 128 entries, each member at most 64 MiB, total expanded bytes at most 128 MiB, and per-entry plus aggregate compression ratio `uncompressed / max(compressed, 1) <= 200`. Count the manifest and directory entries, reject ZIP64 values outside these limits before allocation, and reject duplicate raw/NFC/casefold names. Deployment configuration may only tighten upload admission if capability/readiness reports the effective lower archive limit and approval refuses incompatible packages before publication; it cannot loosen parser limits or create a Registry-accepted package that the standard Studio binder rejects.

Manifest parsing has a stricter shared boundary than ordinary archive members. Require UTF-8 JSON of at most 1 MiB, reject BOM/non-UTF-8/non-finite JSON constants and duplicate raw object keys in the decoder, then walk the decoded value before any schema-model construction. Cap depth at 12, aggregate scalar/container nodes at 8,192, aggregate object keys at 2,048, any one array at 1,024 items, each key at 128 UTF-8 bytes, and each string at 4,096 UTF-8 bytes. Counting follows the master definition exactly: root depth/node 1, one node per JSON value including null/bool, keys counted separately, and strict decoded UTF-8 byte lengths. During the bounded walk also reject NFC/casefold-colliding keys in one object; schema-specific display/path/compatibility limits remain tighter. Export these constants and stable `manifest_too_large`, `manifest_duplicate_key`, and `manifest_structure_invalid` categories for the golden contract tests, and prove Registry never falls back to an unbounded `json.load` path.

Make archive-to-runtime path mapping part of manifest validity, not an extraction convention. A material with normalized `local_directory=D` has exactly one required `material_archive` member at `materials/{D}/material.json` and one required `stage_a_parameters` member at `materials/{D}/stage_A_parameters.json`; these map to revision-relative `material.json` and `stage_A_parameters.json`. A LUT with normalized `local_path=P` has exactly one `lut_file` member at `luts/{P}` and maps it to revision-relative `basename(P)`. Reject any repeated `materials/`, `luts/`, `lut-preset/`, or `Cloud/` prefix and any role/path/logical-path mismatch, even if bytes and hashes are otherwise valid. Keep `files[].path` as the archive path on Registry wires; the revision-relative path is a Studio-derived typed binding field and is never accepted from upload metadata.

The only non-directory members outside declared `files[]` are the domain manifest itself and, for material compatibility, exactly one top-level `lumina_material_export.json`. Frozen material bundle schema 2.0 may additionally contain only top-level `material_count=1` and an optional nonempty string `exported_at` of at most 128 UTF-8 bytes alongside `kind/schema_version/packages`; all 174 current source archives contain both, while a compatibility artifact derived from 2.1 may omit both. When `material_count` is present require `material_count == len(packages) == 1`; `exported_at` is allowed only together with that legacy count. Preserve `exported_at` as an opaque legacy spelling without parsing or normalizing it, and exclude both fields from canonical identity and reviewed envelope metadata. Material 2.1 omits both fields. Parse the separate export descriptor with the same 1 MiB JSON safety boundary, require its frozen `kind="lumina_material_export"`, `schema_version="1.0"`, `material_count=1`, and one `directory_names` entry equal to `D`, but preserve its own optional historical `exported_at` spelling under the same 128-byte bound and exclude all descriptor bytes/fields from canonical content identity, exact-record `files[]`, and installed managed files. New material 2.1 builders emit the descriptor without `exported_at`, so bytes remain deterministic while unchanged v1 consumers still recognize it. LUT packages permit no analogous auxiliary member. Any other member is `undeclared_payload`.

Define one normalized envelope metadata block for both domains: `publisher_kind`, `publisher_name`, `title`, `summary`, `brand`, `tags`, `channel`, `visibility`, and compatibility. V2.0 accepts exactly `official`, `community`, or `team` for `channel`, and exactly `official`, `community`, `team`, or `private` for `visibility`. A pair is anonymous-public only when both values are in `{official, community}`. Any `channel=team` or `visibility in {team, private}` is restricted and requires an authenticated principal whose registry, channel, and visibility scopes all allow that exact pair; both `team/private` and historical `team/team` are valid and remain distinct. Normalize display text to Unicode NFC and require valid UTF-8 with no control/bidi-override characters or HTML/script content. Count UTF-8 bytes, not only code points: publisher/title/brand are `1..128` bytes, summary `0..1024`, at most 32 unique casefold-safe tags of `1..64` bytes, and compatibility is JSON-only with depth at most 4, 128 aggregate nodes, 64 keys, keys at most 64 bytes, and string values at most 256 bytes. Numeric compatibility values must be strict JSON integers/floats, finite, and have absolute value at most `1_000_000_000`; booleans are validated as booleans rather than accepted through Python's integer subtype. Reject unknown fields, duplicate normalized keys/tags, dedicated external preview/package/authority URL fields, and unsupported channel/visibility enums before DB insertion or preview generation; plain summary text is never interpreted as HTML or an executable link. A source material 2.0 or LUT 1.0 package may omit the new publisher/display fields, but an approved v2 artifact must contain the Registry-reviewed values while retaining its accepted source package schema version; these fields are outside the legacy core content-hash input. The separate v1 compatibility artifact carries only fields/shapes accepted by the frozen client and must be proven by that client rather than assuming arbitrary additive fields are ignored. Validators expose source-package versus active-envelope modes so the latter rejects absent/mismatched metadata instead of silently filling it from the record.

- [ ] **Step 4: Add malformed-schema, role-cardinality, and real loadability tests**

Cover wrong algorithm, uppercase/prefix variants, zero/two material or LUT records, material-2.0 top-level count absent/present/wrong plus opaque exported-at bounds, forbidden material-2.1 legacy top-level fields, missing or duplicate required roles, unsupported extension, unknown payload, bytes/hash mismatch, non-UTF8 manifest, manifest bytes/depth/nodes/keys/array/key-byte/string-byte boundaries, duplicate raw and NFC/casefold-colliding object keys, material descriptor absent/duplicate/wrong directory/unsafe JSON, archive-to-revision path mismatch and repeated root prefixes, every display/tag/compatibility boundary, NFC/casefold collision, control/bidi/HTML/script values, forbidden dedicated URL fields, traversal, absolute/drive/UNC, NUL/control/backslash ambiguity, colon/NTFS ADS, trailing dot/space, every Windows device basename with/without extension, 255/256-byte segment and 512/513-byte total paths, raw/NFC/casefold path collision, symlink/device/FIFO entries, entry count, expanded bytes, and compression ratio. Both domain validators require exactly one logical resource revision per archive. Validators expose a stable rejection category plus a bounded internal diagnostic; the upload API maps it to a generic safe public message. Assert public output contains no input absolute path, client filename, package-controlled path/display text, control character, or unbounded JSON representation.

For every accepted LUT format, load a minimal valid fixture through the production reader only after a format-specific allocation preflight. NPY parsing first validates magic/version, caps header bytes at 64 KiB, accepts only fixed-width numeric non-object dtypes, checks dimension/count multiplication without overflow, requires the declared data bytes to equal the bounded payload, and only then calls NumPy with `allow_pickle=False`. NPZ first scans its inner central directory with no extraction, caps members/count/individual and total expanded bytes/compression ratio, rejects encrypted/special/duplicate/casefold/unknown members and object arrays, then loads only the allowlisted keys. JSON and msgpack have lower configurable raw-byte limits than binary LUTs; JSON rejects excessive nesting/container/string/item counts after parsing a bounded payload, and msgpack sets explicit max buffer/map/array/string/bin/ext lengths, strict keys, and no extension/object hooks. Monkeypatch tests prove invalid header/inner-archive cases fail before `numpy.load` is called.

Validate RGB entries, metadata, palette, color mode, base channel, layer order, stacks, standard LUT sizes, and rebuild eligibility together. Standard-size LUTs with absent or synthetic empty/all-Air stacks are accepted only when deterministic recipe rebuilding succeeds; nonstandard payloads with no real recipes are rejected. Material validation parses both required JSON roles and verifies the Stage A structure expected by Studio. Truncated, oversized, compression-bomb, integer-overflow, non-finite, wrong-shape, object/pickle, and deeply nested payloads fail with stable `content_unloadable` or `content_invalid` codes. Configuration fixes concrete per-format byte/member/container ceilings at startup and cannot exceed the request/archive hard caps.

The validator receives bytes from the already bounded archive scan and never follows filesystem paths from package content. Add NumPy, msgpack, and Pillow dependencies explicitly in `requirements.txt`; do not silently skip a format when an optional import is absent.

- [ ] **Step 5: Run focused and existing validation suites**

```bash
set -euo pipefail
.venv/bin/python -m pytest tests/test_contracts_v2.py tests/test_registry_content_validation_v2.py tests/test_registry_service.py -q
```

Expected: all tests pass and the original 55 cases remain green.

- [ ] **Step 6: Commit**

```bash
set -euo pipefail
git add requirements.txt registry_service/contracts.py registry_service/content_validation.py registry_service/manifest.py tests/test_contracts_v2.py tests/test_registry_content_validation_v2.py
git commit -m "feat(contracts): define resource package v2 identities"
```

## Task 2: Deterministic Golden Fixtures

**Files:**
- Create: `registry_service/fixtures.py`
- Create: `scripts/build_contract_fixtures.py`
- Create: `tests/fixtures/contracts/v2/accepted/material-v2.zip`
- Create: `tests/fixtures/contracts/v2/accepted/material-v2-v1-envelope.zip`
- Create: `tests/fixtures/contracts/v2/accepted/lut-legacy-v1.zip`
- Create: `tests/fixtures/contracts/v2/accepted/lut-v2.zip`
- Create: `tests/fixtures/contracts/v2/accepted/lut-v2-v1-envelope.zip`
- Create: `tests/fixtures/contracts/v2/accepted/lut-v2-community-envelope.zip`
- Create: `tests/fixtures/contracts/v2/rejected/path-traversal.zip`
- Create: `tests/fixtures/contracts/v2/rejected/casefold-collision.zip`
- Create: `tests/fixtures/contracts/v2/rejected/symlink.zip`
- Create: `tests/fixtures/contracts/v2/rejected/file-hash-mismatch.zip`
- Create: `tests/fixtures/contracts/v2/rejected/record-binding-mismatch.zip`
- Create: `tests/fixtures/contracts/v2/rejected/manifest-too-large.zip`
- Create: `tests/fixtures/contracts/v2/rejected/manifest-duplicate-key.zip`
- Create: `tests/fixtures/contracts/v2/rejected/manifest-depth-overflow.zip`
- Create: `tests/fixtures/contracts/v2/rejected/npy-header-overflow.zip`
- Create: `tests/fixtures/contracts/v2/rejected/npz-inner-bomb.zip`
- Create: `tests/fixtures/contracts/v2/EXPECTED.json`
- Create: `tests/fixtures/contracts/v2/SHA256SUMS.json`
- Modify: `tests/test_contracts_v2.py`

- [ ] **Step 1: Add failing fixture inventory tests**

The inventory must require these exact logical names:

```python
REQUIRED_FIXTURES = {
    "accepted/material-v2.zip",
    "accepted/material-v2-v1-envelope.zip",
    "accepted/lut-legacy-v1.zip",
    "accepted/lut-v2.zip",
    "accepted/lut-v2-v1-envelope.zip",
    "accepted/lut-v2-community-envelope.zip",
    "rejected/path-traversal.zip",
    "rejected/casefold-collision.zip",
    "rejected/symlink.zip",
    "rejected/file-hash-mismatch.zip",
    "rejected/record-binding-mismatch.zip",
    "rejected/manifest-too-large.zip",
    "rejected/manifest-duplicate-key.zip",
    "rejected/manifest-depth-overflow.zip",
    "rejected/npy-header-overflow.zip",
    "rejected/npz-inner-bomb.zip",
    "EXPECTED.json",
    "SHA256SUMS.json",
}
```

Test that `SHA256SUMS.json` lists every other file exactly once and each digest equals the checked-in bytes.

- [ ] **Step 2: Verify the fixture test fails**

```bash
set -euo pipefail
.venv/bin/python -m pytest tests/test_contracts_v2.py -k fixture -v
```

Expected: FAIL because the fixture directory is absent.

- [ ] **Step 3: Implement deterministic ZIP writing**

Use one helper for all fixture members:

```python
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def write_member(archive, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, payload)
```

Serialize manifests with UTF-8, sorted keys, separators `(',', ':')`, and a final newline. Add explicit constructors for accepted and rejected fixtures; rejected fixtures must each violate exactly one rule so a passing rejection is attributable.

- [ ] **Step 4: Generate twice and prove byte reproducibility**

```bash
set -euo pipefail
FIXTURE_AUDIT_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/lumina-registry-fixtures.XXXXXX")
printf '%s\n' 'lumina-registry-fixtures-v1' > "$FIXTURE_AUDIT_ROOT/.owner"
cleanup_fixture_audit() {
  test "$(cat "$FIXTURE_AUDIT_ROOT/.owner")" = 'lumina-registry-fixtures-v1'
  case "$(basename "$FIXTURE_AUDIT_ROOT")" in lumina-registry-fixtures.??????) ;; *) return 1 ;; esac
  rm -rf -- "$FIXTURE_AUDIT_ROOT"
}
trap cleanup_fixture_audit EXIT
.venv/bin/python scripts/build_contract_fixtures.py --output tests/fixtures/contracts/v2
cp -R tests/fixtures/contracts/v2 "$FIXTURE_AUDIT_ROOT/first"
.venv/bin/python scripts/build_contract_fixtures.py --output tests/fixtures/contracts/v2
diff -r "$FIXTURE_AUDIT_ROOT/first" tests/fixtures/contracts/v2
```

Expected: `diff` prints nothing and exits `0`.

- [ ] **Step 5: Validate expected projections**

`EXPECTED.json` must contain the exact normalized material v2 record, legacy LUT v1 record plus v2 projection, LUT v2 record, rewritten envelope fields, and both deterministic v1 compatibility-artifact projections. Tests read fixture bytes through production validators and compare the complete object, including algorithms, IDs, revision, files, archive/revision paths, channel, visibility, representation, package bytes, and package SHA. Assert v2 aggregate hashes carry `sha256:`, file/checksum hashes are raw 64-hex, and the v1 facade/artifacts remain byte-for-byte equal to their historical schema/hash fields while normalizing to the same core revision as v2.

- [ ] **Step 6: Commit and open the fixture PR**

```bash
set -euo pipefail
git add registry_service/fixtures.py scripts/build_contract_fixtures.py tests/fixtures/contracts/v2/accepted/material-v2.zip tests/fixtures/contracts/v2/accepted/material-v2-v1-envelope.zip tests/fixtures/contracts/v2/accepted/lut-legacy-v1.zip tests/fixtures/contracts/v2/accepted/lut-v2.zip tests/fixtures/contracts/v2/accepted/lut-v2-v1-envelope.zip tests/fixtures/contracts/v2/accepted/lut-v2-community-envelope.zip tests/fixtures/contracts/v2/rejected/path-traversal.zip tests/fixtures/contracts/v2/rejected/casefold-collision.zip tests/fixtures/contracts/v2/rejected/symlink.zip tests/fixtures/contracts/v2/rejected/file-hash-mismatch.zip tests/fixtures/contracts/v2/rejected/record-binding-mismatch.zip tests/fixtures/contracts/v2/rejected/manifest-too-large.zip tests/fixtures/contracts/v2/rejected/manifest-duplicate-key.zip tests/fixtures/contracts/v2/rejected/manifest-depth-overflow.zip tests/fixtures/contracts/v2/rejected/npy-header-overflow.zip tests/fixtures/contracts/v2/rejected/npz-inner-bomb.zip tests/fixtures/contracts/v2/EXPECTED.json tests/fixtures/contracts/v2/SHA256SUMS.json tests/test_contracts_v2.py
git commit -m "test(contracts): publish cross-repository golden packages"
```

Request an independent exact-head review. Merge this PR before creating downstream `UPSTREAM.json` files.

## Task 3: Transactional Metadata Database And Migration

**Files:**
- Create: `registry_service/database.py`
- Create: `registry_service/repository.py`
- Create: `registry_service/migrate_v2.py`
- Test: `tests/test_registry_migration_v2.py`

- [ ] **Step 1: Write failing migration parity tests**

Create material and LUT v1 JSON databases with approved, pending, withdrawn, team, and multiple-revision records plus real fixture ZIPs. Assert dry-run does not create `registry-v2.sqlite3`; apply creates it; a second apply is idempotent; and repository v1 projections equal the original stores' catalog output byte-for-byte after JSON serialization with sorted keys.

- [ ] **Step 2: Run the migration tests and verify failure**

```bash
set -euo pipefail
.venv/bin/python -m pytest tests/test_registry_migration_v2.py -v
```

Expected: FAIL because the migration module is absent.

- [ ] **Step 3: Create the SQLite schema**

`registry_service/database.py` must initialize with `PRAGMA foreign_keys=ON`, `PRAGMA journal_mode=WAL`, and `PRAGMA synchronous=FULL`. Apply this schema inside one transaction:

```sql
CREATE TABLE registry_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE publishers (
    publisher_id TEXT PRIMARY KEY,
    publisher_kind TEXT NOT NULL CHECK(publisher_kind IN ('lumina','community')),
    publisher_name TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('active','disabled','banned')),
    ownership_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX one_publisher_per_ownership_key
ON publishers(ownership_key) WHERE ownership_key IS NOT NULL;
CREATE TABLE publisher_external_keys (
    source_key TEXT NOT NULL,
    external_key TEXT NOT NULL,
    publisher_id TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    PRIMARY KEY(source_key, external_key),
    FOREIGN KEY(publisher_id) REFERENCES publishers(publisher_id)
);
CREATE TABLE resources (
    resource_kind TEXT NOT NULL CHECK(resource_kind IN ('material','lut')),
    resource_id TEXT NOT NULL,
    publisher_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    brand TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0 CHECK(disabled IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(resource_kind, resource_id),
    FOREIGN KEY(publisher_id) REFERENCES publishers(publisher_id)
);
CREATE TABLE revisions (
    resource_kind TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    package_schema_version TEXT NOT NULL,
    source_package_path TEXT NOT NULL UNIQUE,
    source_package_sha256 TEXT NOT NULL,
    source_package_bytes INTEGER NOT NULL CHECK(source_package_bytes > 0),
    status TEXT NOT NULL CHECK(status IN ('pending','approved','withdrawn','rejected','purged')),
    content_hash_algorithm TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    legacy_content_hash TEXT,
    logical_path TEXT NOT NULL,
    display_json TEXT NOT NULL,
    compatibility_json TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    published_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(resource_kind, resource_id, revision_id),
    FOREIGN KEY(resource_kind, resource_id) REFERENCES resources(resource_kind, resource_id)
);
CREATE TABLE revision_files (
    resource_kind TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    role TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_count INTEGER NOT NULL CHECK(byte_count >= 0),
    required INTEGER NOT NULL CHECK(required IN (0,1)),
    PRIMARY KEY(resource_kind, resource_id, revision_id, path),
    FOREIGN KEY(resource_kind, resource_id, revision_id)
      REFERENCES revisions(resource_kind, resource_id, revision_id)
);
CREATE TABLE registry_audit_events (
    audit_id TEXT PRIMARY KEY CHECK(
      length(audit_id) BETWEEN 1 AND 128 AND
      audit_id NOT GLOB '*[^a-z0-9_-]*'
    ),
    occurred_at TEXT NOT NULL,
    actor_mode TEXT NOT NULL CHECK(actor_mode IN ('system','read','maintainer','approver')),
    actor_id TEXT CHECK(
      actor_id IS NULL OR (
        length(CAST(actor_id AS BLOB)) BETWEEN 1 AND 64 AND
        actor_id NOT GLOB '*[^a-z0-9_-]*'
      )
    ),
    event TEXT NOT NULL CHECK(
      length(CAST(event AS BLOB)) BETWEEN 1 AND 64 AND
      event NOT GLOB '*[^a-z0-9_]*'
    ),
    resource_kind TEXT CHECK(resource_kind IN ('material','lut')),
    resource_id TEXT,
    revision_id TEXT,
    payload_json TEXT NOT NULL CHECK(
      length(CAST(payload_json AS BLOB)) <= 16384 AND json_valid(payload_json)
    ),
    CHECK((actor_mode='system' AND actor_id IS NULL) OR (actor_mode!='system' AND actor_id IS NOT NULL)),
    CHECK(
      (resource_kind IS NULL AND resource_id IS NULL AND revision_id IS NULL) OR
      (resource_kind IS NOT NULL AND resource_id IS NOT NULL)
    )
);
CREATE TABLE envelopes (
    envelope_id TEXT PRIMARY KEY,
    resource_kind TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('active','revoked')),
    channel TEXT NOT NULL CHECK(channel IN ('official','community','team')),
    visibility TEXT NOT NULL CHECK(visibility IN ('official','community','team','private')),
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    CHECK(
      (state='active' AND revoked_at IS NULL) OR
      (state='revoked' AND revoked_at IS NOT NULL)
    ),
    FOREIGN KEY(resource_kind, resource_id, revision_id)
      REFERENCES revisions(resource_kind, resource_id, revision_id)
);
CREATE UNIQUE INDEX one_active_envelope_per_revision
ON envelopes(resource_kind, resource_id, revision_id) WHERE state='active';
CREATE TABLE envelope_package_artifacts (
    envelope_id TEXT NOT NULL,
    representation TEXT NOT NULL CHECK(representation IN ('v1','v2')),
    package_schema_version TEXT NOT NULL,
    package_path TEXT NOT NULL UNIQUE,
    package_sha256 TEXT NOT NULL,
    package_bytes INTEGER NOT NULL CHECK(package_bytes > 0),
    created_at TEXT NOT NULL,
    PRIMARY KEY(envelope_id, representation),
    FOREIGN KEY(envelope_id) REFERENCES envelopes(envelope_id)
);
CREATE TABLE envelope_previews (
    envelope_id TEXT PRIMARY KEY,
    preview_version TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    preview_path TEXT NOT NULL UNIQUE,
    preview_media_type TEXT NOT NULL CHECK(preview_media_type='image/png'),
    preview_sha256 TEXT NOT NULL,
    preview_bytes INTEGER NOT NULL CHECK(preview_bytes > 0),
    width INTEGER NOT NULL CHECK(width > 0),
    height INTEGER NOT NULL CHECK(height > 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY(envelope_id) REFERENCES envelopes(envelope_id)
);
CREATE TABLE download_counts (
    resource_kind TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0 CHECK(count >= 0),
    PRIMARY KEY(resource_kind, resource_id, revision_id),
    FOREIGN KEY(resource_kind, resource_id, revision_id)
      REFERENCES revisions(resource_kind, resource_id, revision_id)
);
CREATE TABLE catalog_snapshots (
    snapshot_handle TEXT PRIMARY KEY,
    resource_kind TEXT NOT NULL,
    principal_fingerprint TEXT NOT NULL,
    policy_fingerprint TEXT NOT NULL,
    query_digest TEXT NOT NULL,
    catalog_generation INTEGER NOT NULL CHECK(catalog_generation >= 0),
    authorization_generation INTEGER NOT NULL CHECK(authorization_generation >= 0),
    item_count INTEGER NOT NULL CHECK(item_count >= 0),
    next_page_sequence INTEGER NOT NULL CHECK(next_page_sequence >= 0),
    next_position INTEGER NOT NULL CHECK(next_position >= 0),
    replay_input_sequence INTEGER CHECK(replay_input_sequence >= 0),
    replay_input_position INTEGER CHECK(replay_input_position >= 0),
    replay_response_json TEXT,
    replay_response_sha256 TEXT,
    replay_response_bytes INTEGER CHECK(replay_response_bytes >= 0),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    CHECK(
      (replay_input_sequence IS NULL AND replay_input_position IS NULL AND
       replay_response_json IS NULL AND
       replay_response_sha256 IS NULL AND replay_response_bytes IS NULL) OR
      (replay_input_sequence IS NOT NULL AND replay_input_position IS NOT NULL AND
       replay_response_json IS NOT NULL AND
       replay_response_sha256 IS NOT NULL AND replay_response_bytes IS NOT NULL)
    )
);
CREATE TABLE catalog_snapshot_items (
    snapshot_handle TEXT NOT NULL,
    position INTEGER NOT NULL CHECK(position >= 0),
    resource_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    sort_primary TEXT NOT NULL,
    projection_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_handle, position),
    UNIQUE(snapshot_handle, resource_id),
    FOREIGN KEY(snapshot_handle) REFERENCES catalog_snapshots(snapshot_handle) ON DELETE CASCADE
);
CREATE TABLE cache_invalidation_outbox (
    invalidation_id TEXT PRIMARY KEY,
    invalidation_generation INTEGER NOT NULL CHECK(invalidation_generation >= 0),
    surrogate_keys_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','delivered','failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    next_attempt_at TEXT NOT NULL,
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    CHECK(
      (state='delivered' AND delivered_at IS NOT NULL) OR
      (state IN ('pending','failed') AND delivered_at IS NULL)
    )
);
CREATE TABLE publication_batches (
    batch_id TEXT PRIMARY KEY,
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('resource','publisher','channel')),
    scope_key TEXT NOT NULL,
    expected_operation_count INTEGER NOT NULL CHECK(expected_operation_count > 0),
    capacity_reservation_id TEXT UNIQUE,
    capacity_reserved_bytes INTEGER,
    capacity_safety_bytes INTEGER,
    capacity_reserved_inodes INTEGER,
    capacity_safety_inodes INTEGER,
    state TEXT NOT NULL CHECK(
      state IN ('allocating','reserved','prepared','assets_published','committed','aborted','quarantined')
    ),
    requested_policy_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(
      (capacity_reservation_id IS NULL AND capacity_reserved_bytes IS NULL AND capacity_safety_bytes IS NULL AND
       capacity_reserved_inodes IS NULL AND capacity_safety_inodes IS NULL) OR
      (capacity_reservation_id IS NOT NULL AND capacity_reserved_bytes > 0 AND
       capacity_safety_bytes >= 0 AND capacity_safety_bytes < capacity_reserved_bytes AND
       capacity_reserved_inodes > 0 AND capacity_safety_inodes >= 0 AND
       capacity_safety_inodes < capacity_reserved_inodes)
    ),
    CHECK(state IN ('allocating','aborted') OR capacity_reservation_id IS NOT NULL),
    CHECK(state != 'allocating' OR capacity_reservation_id IS NULL)
);
CREATE TABLE publication_operations (
    operation_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    resource_kind TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    prior_envelope_id TEXT,
    new_envelope_id TEXT,
    expected_asset_count INTEGER NOT NULL CHECK(expected_asset_count > 0),
    state TEXT NOT NULL CHECK(
      state IN ('allocating','reserved','prepared','assets_published','committed','aborted','quarantined')
    ),
    requested_record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(batch_id) REFERENCES publication_batches(batch_id),
    FOREIGN KEY(resource_kind, resource_id, revision_id)
      REFERENCES revisions(resource_kind, resource_id, revision_id),
    FOREIGN KEY(prior_envelope_id) REFERENCES envelopes(envelope_id)
);
CREATE TABLE publication_assets (
    asset_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    asset_kind TEXT NOT NULL CHECK(asset_kind IN ('package_v1','package_v2','preview')),
    staging_path TEXT NOT NULL UNIQUE,
    destination_path TEXT NOT NULL UNIQUE,
    expected_sha256 TEXT NOT NULL,
    expected_bytes INTEGER NOT NULL CHECK(expected_bytes > 0),
    expected_media_type TEXT NOT NULL,
    state TEXT NOT NULL CHECK(
      state IN ('prepared','published','committed','aborted','quarantined')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(operation_id, asset_kind),
    FOREIGN KEY(operation_id) REFERENCES publication_operations(operation_id)
);
```

Initialize `schema_version=1`, a cryptographically random immutable 128-bit lowercase-hex `database_uuid`, `writer_backend=legacy_json`, `post_migration_write_admitted=0`, `writer_epoch=0`, `writer_epoch_state=legacy_json`, null writer-transition intent fields, `catalog_generation=0`, `authorization_generation=0`, `cache_invalidation_generation=0`, `delivered_invalidation_generation=0`, `v2_projection_ready=0`, and source JSON SHA fingerprints in `registry_meta`. Whole-candidate rebuilds before writer selection may allocate a new DB UUID; after an external writer epoch binds one final UUID, no migration/restore may substitute another. The writer-state values are closed literals/booleans read under transaction: only Task 6's three-party epoch protocol may change `writer_backend`, internal epoch/state, or `post_migration_write_admitted`. Candidate rebuild/promotion, deterministic policy-fingerprint initialization, read-only audit, checkpoint, readiness inspection, and completed-download count/catalog-generation updates are explicitly reconstructible migration/control-plane/cosmetic operations and cannot close the recovery window or alter resource/publisher/revision/envelope ownership or package facts; import apply, repair apply, upload, approval/distribution, publisher mutation, and every HTTP repository mutation other than the exact download-count-only transaction are authoritative business mutations and must first close it through that protocol. Tests enumerate this closed classification, run a complete v1 download smoke while the epoch/flag stay zero, and prove a new mutator cannot bypass the external gate. `cache_invalidation_generation` is internal and never appears in a v2 payload or cursor; it advances for every committed authorization/distribution/display mutation that requires public cache removal before the normal 60-second TTL. Monotonic download-count changes advance only catalog generation and ETag: they may remain cosmetically stale for at most that TTL, do not affect package authorization, and must not invalidate an existing authorization-bound snapshot cursor or flood the purge outbox. Expose `transaction(immediate=True)` that executes `BEGIN IMMEDIATE`, commits on success, and rolls back on typed exceptions.

Open a fresh connection per request/worker context with `check_same_thread=True`, `busy_timeout=5000`, explicit row factory, and no connection inherited across process fork. On every connection require `PRAGMA foreign_keys=ON`, verify the returned value, use WAL plus `synchronous=FULL` and `wal_autocheckpoint=1000`, and reject an unexpected `application_id`, `user_version`, journal mode, or unsupported SQLite version before use. Set a fixed nonzero application ID and schema user version during migration. Run `PRAGMA quick_check` once during startup readiness before admitting writes, after migration/import/repair apply, and in the explicit storage/repair probes, not on every request connection. A migration/apply checkpoint uses `PRAGMA wal_checkpoint(FULL)`, fsyncs the database/WAL/directory files that exist through no-follow handles, and never copies a live SQLite file as its only backup; the deployment-level backup is taken while writes are stopped as specified later. Normal operation relies on bounded auto-checkpointing and may issue non-blocking `PASSIVE` checkpoints after write bursts; it never runs `TRUNCATE` while request connections are active. Tests hold a reader across many writes/restarts and prove requests stay responsive, committed rows survive, and WAL pages converge after the reader closes without weakening `synchronous=FULL`.

Validate the configured DB/data roots and every existing ancestor against symlink/special-file traversal; create DB/runtime files owner-readable/writable only where the platform supports it. Map busy/locked/corrupt/full/I/O failures to distinct internal errors and safe public availability codes. SQL sort/filter identifiers come from fixed enums, never string interpolation of request values. `registry_audit_events` is append-only through repository APIs, uses opaque server-secret HMAC actor IDs rather than credentials/names, and is inserted in the same transaction as the mutation it describes; no v2 mutation appends the legacy JSONL file as a second source of truth. Audit IDs use the bounded typed-ID codec, actor IDs are at most 64 lowercase-safe characters, event names are fixed snake-case literals of at most 64 bytes, and `payload_json` is canonical UTF-8 JSON at most 16 KiB with depth 4, 128 nodes, 64 keys, 64-byte keys, and 512-byte string values. It contains only safe normalized IDs, before/after state enums, counts, and digest prefixes; never credentials, actor name/email, package-controlled display text, full hash, URL/query, client filename, absolute path, or traceback. Tests prove every foreign key, partial unique index, state/timestamp/reference invariant, reservation-budget/audit-payload invariant, and CHECK constraint rejects invalid rows even when repository code is bypassed, a child process cannot inherit/reuse a parent connection, and rollback leaves neither state nor audit event.

All generation/high-water values are decimal canonical integers in `0..9223372036854775807`. Increment helpers use one checked SQL update and fail write readiness with a typed exhaustion error instead of wrapping, switching representation, or partially committing. Tests seed the maximum-minus-one, maximum, negative, noncanonical, and noninteger values and prove one final increment succeeds and the next mutation leaves all metadata/outbox state unchanged. Public catalog and authorization generations use the field-specific `cat_`/`auth_` plus 16-lowercase-hex wire codec defined in Task 7; internal cache-invalidation/delivery high-water values have no wire encoding.

`publishers.publisher_id` is a Registry-generated stable opaque identity matching `[a-z0-9][a-z0-9_-]{0,63}`. Envelope/batch/operation/snapshot IDs use the same lowercase safe alphabet with explicit type prefixes and a 128-character maximum; existing resource/revision IDs retain their frozen legacy ASCII package pattern and are never lowercased. Publisher ID is not derived from display name, brand, channel, path, or filename. V2 catalog/detail expose it only as a read/filter identity so equal names remain distinct; v1 shapes do not change. No upload/package/Materials document/browser mutation may select it, and possession grants no ownership. `ownership_key` and configured `publisher_assignment_key` are separate opaque server-side assignments matching the 1..64 lowercase safe pattern and are never a raw token, email, or public response field. `publisher_external_keys` maps an explicit reviewed source key such as a Materials inventory publisher key to the internal identity; only an approver may create/rebind the mapping, and equal names never create it implicitly.

`publication_batches`, per-revision `publication_operations`, and per-file `publication_assets` are the durable bridge between immutable filesystem publication and SQLite metadata. Store data-directory-relative normalized paths only. `allocating` means the complete batch/operation inventory and conservative budget are durable in `requested_policy_json`, but no staging or capacity reservation may yet exist. Each later batch state persists the immutable reservation ID and budget; the matching reservation record must carry `owner_kind=publication` and `owner_id=batch_id`. Its mutable version/consumed count is read under the capacity lock and changed only with version CAS; SQLite never pretends to commit that filesystem-record version atomically. `reserved` means the shared storage-capacity reservation binding is durable but asset bytes/rows are not yet complete; `prepared` requires every expected asset row and staged byte/hash/media type to be durable. Task 6 publishes exactly the dual package assets while `v2_projection_ready=0`; any pre-readiness active envelope, migrated or newly approved, may therefore have no `envelope_previews` row and is never v2-visible. Task 8 extends the same protocol to exactly one preview asset; Task 9 metadata import/readiness invokes it to republish every approved envelope before enabling v2. Once readiness is true, every active/v2-visible envelope must have exactly one validated preview row bound to that envelope. An allocating/reserved/prepared operation or asset is never treated as active and is retained until recovery proves the complete batch and metadata converged or an operator resolves a quarantined ambiguity.

All immutable whole-object SHA columns in the v2 database, including `revisions.source_package_sha256`, `envelope_package_artifacts.package_sha256`, `envelope_previews.preview_sha256`, and `publication_assets.expected_sha256`, store exactly `sha256:` plus 64 lowercase hex characters and pass `require_prefixed_sha256` on every read/write. `publication_assets.expected_sha256` is therefore an internal canonical digest independent of whether the eventual v1 HTTP projection removes the prefix; it is compared against raw staged/destination bytes before any state transition. Only `revision_files.sha256` stores raw 64-hex member digests. Migration converts a verified legacy whole-archive raw digest once at the schema adapter boundary and never guesses an encoding from length. Schema/recovery tests reject mixed raw/prefixed forms, uppercase, whitespace, and a publication asset whose persisted expected digest differs from either staged or destination bytes.

`revisions.source_package_*` is the immutable upload/source archive, not an envelope artifact. Its path is data-root-relative, its SHA is strict prefixed v2 SHA-256, and its bytes/schema are verified from the same no-follow descriptor before any approval, metadata republish, restore, or repair build. Pending and non-approved revisions retain this record indefinitely. V2 projection never serializes these fields. A migrated approved v1 archive may initially be referenced both as the source and as that legacy envelope's v1 artifact; storage audit counts the physical inode/bytes once while preserving both typed roles. Any newly published v1/v2 pair still uses two distinct immutable destination paths.

An approved envelope becomes v2-visible only with exactly one `v1` and one `v2` row in `envelope_package_artifacts`, both generated from the same validated core revision and reviewed publisher/channel/visibility fields. The v1 artifact is material bundle schema 2.0 or LUT bundle schema 1.0 and carries the exact historical content-hash representation consumed by the frozen v1 projection; the v2 artifact retains the accepted canonical package schema and fields. Material 2.1 -> 2.0 projection removes only the explicit algorithm field whose value was already validated as `lumina-material-required-files-v1`. LUT 2.0 -> 1.0 projection deterministically derives the frozen filename-plus-file-SHA legacy top-level hash while retaining the same LUT bytes and exact logical path. No other lossy schema downgrade is permitted; an unsupported future core field makes approval fail before assets are staged. Distinct immutable paths are mandatory even when both representations happen to be byte-identical. `envelopes` owns authorization/revocation; revoking it denies both artifacts. Package hash/bytes are always selected from the endpoint's representation row and are never copied between rows.

Initial v2 retention is deliberately fail-closed: revoked envelopes, their package/preview assets, rejected/withdrawn/purged revision records, committed publication rows, and quarantined assets are retained indefinitely. No request path, startup recovery, migration, or `repair --apply` automatically unlinks them. Read authorization still makes revoked/non-approved content indistinguishable from missing, while storage accounting reports retained bytes by state and the age/count/bytes of unreferenced candidates. A future destructive retention command requires a separate reviewed design with a minimum age, external backup evidence, exact DB ownership proof, open-handle/download exclusion, no-follow identity/hash recheck, dry-run manifest, and crash-safe deletion journal; it is outside this plan.

- [ ] **Step 4: Implement strict dry-run/apply migration**

`DATA_DIR="${LUMINA_REGISTRY_DATA_DIR:?set the Registry data directory}"; python -m registry_service.migrate_v2 --data-dir "$DATA_DIR"` prints counts, JSON/audit fingerprints, package verification failures, duplicate identities, and the target path but writes nothing. `--apply` acquires a migration lock, copies both JSON files, legacy audit JSONL, and catalog snapshots to `migration-backups/{utc_timestamp}/`, imports all records into a same-root candidate DB, verifies every referenced package and the complete v1 projection, commits/checkpoints/fsyncs it, atomically promotes it while the service is stopped or maintenance-read-only, fsyncs the parent, and writes `migration-v2.json` with source hashes and completion timestamp. While `writer_backend=legacy_json` and `post_migration_write_admitted=0`, a later changed source fingerprint may rebuild and replace that shadow DB by the same whole-candidate protocol; it never merges JSON changes into an old projection. Once either writer state advances, changed-source rebuild is forbidden. The legacy audit file remains a fingerprinted read-only migration artifact. The shadow contains only a fixed system-migration audit actor; no credential-derived actor row or new SQLite mutation is permitted before Task 6 installs stable HMAC authentication and switches the writer.

Existing missing publisher metadata maps to `community`; populate title/brand from validated display fields and use an empty summary/tags only in v1-imported records. Assign one publisher row per logical resource using `pub_legacy_` plus the first 24 hex characters of SHA-256 over UTF-8 `resource_kind + ":" + resource_id`, so equal historical names are not silently grouped; only an explicit approver operation may later consolidate ownership. Do not infer `lumina` or shared publisher identity from name, brand, channel, path, or filename.

- [ ] **Step 5: Test interrupted and changed-source migration**

Inject failure before candidate DB commit, after commit/checkpoint but before promotion, after promotion but before marker, and after marker. Rerun must either resume idempotently from matching fingerprints, rebuild the complete still-shadow candidate from a newly fingerprinted JSON source, or refuse once writer state has advanced. It must never merge a new JSON write into a partially imported database or alter the live JSON writer.

Also migrate every existing revision with one verified immutable `source_package_path/source_package_sha256/source_package_bytes` record. For an approved legacy revision, the same pre-migration archive may be referenced by that source role and by one committed `v1` artifact row, with no `v2` artifact/preview, without running the live publication protocol; audit must understand this explicit typed alias and avoid double-counting physical capacity. Verify source package bytes/hash/path first, reject duplicate active envelopes or two revisions claiming one source path, and leave the source JSON implementation untouched when any record is ambiguous. Migration alone leaves `v2_projection_ready=0`: legacy envelopes remain valid for v1, but v2 cannot advertise until Task 9 republishes reviewed metadata, both representation artifacts, and previews through the durable protocol and audits every visible approved revision.

- [ ] **Step 6: Run and commit**

```bash
set -euo pipefail
.venv/bin/python -m pytest tests/test_registry_migration_v2.py -q
git add registry_service/database.py registry_service/repository.py registry_service/migrate_v2.py tests/test_registry_migration_v2.py
git commit -m "feat(storage): add transactional registry v2 metadata"
```

## Task 4: Bound Multipart Upload Intake Before Parsing

**Files:**
- Create: `registry_service/storage_capacity.py`
- Create: `registry_service/upload_intake.py`
- Create: `registry_service/source_publication.py`
- Modify: `registry_service/app.py`
- Modify: `registry_service/database.py`
- Modify: `registry_service/repository.py`
- Modify: `registry_service/store.py`
- Modify: `requirements.txt`
- Create: `tests/test_registry_upload_intake_v2.py`
- Modify: `tests/test_registry_service.py`

- [ ] **Step 1: Write request-layer limit and cleanup tests**

Drive the ASGI app with controlled `http.request` chunks instead of relying only on TestClient's eager body. Cover both material and LUT upload paths with: known `Content-Length` over the request cap; missing length with chunks over cap; declared length below cap but actual chunks over cap; duplicate/conflicting/negative/non-decimal length; Content-Length plus Transfer-Encoding ambiguity; duplicate/comma-chained/non-`chunked` transfer encoding; valid chunked/no-length input; one byte below/at/above the archive cap; multipart field over 64 KiB; second file; more than eight fields; idle timeout before first and middle chunks; slow trickle that exceeds the total deadline without hitting idle timeout; `http.disconnect`; parser error after a spool file exists; staging write `ENOSPC`; validation failure; duplicate revision; and success. Run two app/repository processes against one data root to cover max-concurrency slots, simultaneous byte/inode reservation, bytes-available-but-inodes-exhausted on POSIX, explicit inode-not-applicable behavior, stale/dead/reused-PID reservation cleanup, and a third request rejected before its receive callable is touched; Task 6 adds the reciprocal publication-versus-upload race.

Assert oversized known-length requests return before multipart parsing; receive-time breaches return `413 upload_request_too_large`; idle/total timeout returns `408 upload_receive_timeout`; disconnect returns `400 upload_interrupted`; malformed length returns `400 upload_content_length_invalid`; concurrency exhaustion returns `429 upload_capacity_busy` with bounded `Retry-After`; disk reservation failure returns `507 upload_storage_exhausted`; and all responses omit temp paths, filenames supplied by the client, token values, and tracebacks. Every failure before immutable source publication closes Starlette spools, converges capacity/slot reservations, removes the request-owned staging directory, creates no pending revision/source row/audit record, and preserves a sibling sentinel. Inject termination after source no-replace publication but before the SQLite insert: only one exact immutable unreferenced source candidate may remain, with no staging/reservation/DB/audit state; retrying the same authenticated upload must re-open/fully verify and adopt that candidate, while a different hash or owner is rejected and the candidate is never deleted. Seed live publication reservations only through matching durable `allocating`/`reserved` batches and prove upload admission subtracts both. An unauthorized under-limit request may take/release admission but must not consume its body. Keep the existing `LUMINA_REGISTRY_MAX_UPLOAD_BYTES=64` v1 test and response status compatible.

- [ ] **Step 2: Add an outer ASGI receive limiter**

Create immutable limits and typed receive errors:

```python
@dataclass(frozen=True)
class UploadLimits:
    archive_bytes: int
    request_bytes: int
    idle_timeout_seconds: float
    total_timeout_seconds: float
    max_concurrent_uploads: int
    safety_bytes: int
    safety_inodes: int


class UploadRequestTooLarge(OSError):
    pass


class UploadReceiveTimeout(OSError):
    pass


class UploadInterrupted(OSError):
    pass
```

Add `psutil>=5.9` to `requirements.txt` and derive reservation process identity from PID, `round(psutil.Process(pid).create_time() * 1_000_000)`, and `round(psutil.boot_time() * 1_000_000)`. Persist those last two values as bounded nonnegative integer microsecond identity markers, compare them only for exact equality, and never truncate them through the canonical whole-second timestamp codec. PID existence alone is never enough because reuse/reboot can make a dead reservation look live; unavailable or ambiguous markers keep capacity/destructive cleanup closed.

`UploadBodyLimitMiddleware` applies only to the two exact v1 upload paths and methods. Parse all raw `Content-Length` and `Transfer-Encoding` header occurrences before calling the app; reject multiple/comma-ambiguous/invalid forms, reject simultaneous length and transfer encoding, allow only one canonical `chunked` transfer encoding when length is absent, and reject a known oversized request without reading `receive`. Before the first receive, acquire one cross-process upload slot and a versioned `StorageCapacityManager` reservation under the validated Registry data root. Reserve declared request bytes plus the possible archive copy plus safety, or both configured maxima plus safety when length is absent; reserve spool/upload/package files and directories plus inode safety. Compare current free bytes and, when POSIX `f_favail` is meaningful, free inodes with every live upload/publication reservation under one persistent capacity lock. Reservation records carry schema, opaque ID, `owner_kind=upload|publication`, opaque request/batch owner ID, reserved/consumed/safety bytes, reserved/consumed/safety inodes, owner PID/create-time/boot identity, timestamps, and version, but no token or absolute path. Stale upload cleanup requires dead/reused owner proof and version CAS, not TTL alone; publication reservations follow Task 6's durable batch state and cannot be cleared as an upload.

Store the never-deleted lock at `{data_root}/.staging/storage-capacity.lock` and atomic reservation JSON under `{data_root}/.staging/storage-reservations/{reservation_id}.json`. Validate both ancestors as private plain directories; use exclusive no-follow temporary files, fsync record and parent on every version transition, and acquire the same lock before scanning, creating, updating, releasing, or recovering. A publication reservation is valid only when its batch exists in `allocating` or a later publication state and immutable owner/budget agree; the `allocating` recovery in Task 6 owns adoption into `reserved`. Unknown schema/owner kind, malformed records, missing/contradictory publication DB state, identity ambiguity, or cleanup failure makes write readiness false rather than ignoring reserved bytes.

Wrap `receive` to count the actual bytes in every `http.request` message, enforce a monotonic total deadline plus per-receive idle timeout, and convert `http.disconnect` to `UploadInterrupted`. The typed exceptions inherit `OSError` so Starlette `MultiPartParser` closes all spool files before re-raising; the outer middleware then sends the stable JSON error only when no response has started. Its `finally` releases slot/capacity by owner/version after the form/staged copy/store call has closed. It never buffers the body, trusts a declared length, or applies limits to catalog/package downloads.

Use `LUMINA_REGISTRY_MAX_UPLOAD_BYTES` for archive bytes, `LUMINA_REGISTRY_MAX_REQUEST_BYTES` for the full multipart body, `LUMINA_REGISTRY_UPLOAD_IDLE_TIMEOUT_S` for receive idle time, `LUMINA_REGISTRY_UPLOAD_TOTAL_TIMEOUT_S` for the full request deadline, `LUMINA_REGISTRY_MAX_CONCURRENT_UPLOADS` for cross-process slots, `LUMINA_REGISTRY_UPLOAD_SAFETY_BYTES` for unreserved byte headroom, and `LUMINA_REGISTRY_UPLOAD_SAFETY_INODES` for inode headroom. Defaults are 64 MiB archive, 65 MiB request, 30 seconds idle, 120 seconds total, two uploads, 256 MiB byte safety, and 32 inode safety; require request cap to be at least archive cap plus 64 KiB, total timeout to be at least idle timeout, concurrency in `1..8`, inode safety in `8..4096`, and all configuration to be bounded positive values. Invalid production configuration fails application startup, not the first upload.

- [ ] **Step 3: Stage one archive under the Registry data root**

At app startup, validate/create `{data_root}/.staging/spool` as a private plain directory and configure Python's tempfile spool root before any request parser creates a `SpooledTemporaryFile`; fail readiness on a symlink/reparse/special root. This keeps Starlette's spill files on the same capacity-accounted data filesystem rather than the global temp disk.

`stage_single_archive(request, data_root, limits)` runs after authorization and calls `request.form(max_files=1, max_fields=8, max_part_size=64 * 1024)`. Require exactly one `archive` UploadFile, a `.zip` filename only as a user-error check, and no unconsumed fields/files. Copy in 1 MiB chunks to `{data_root}/.staging/uploads/{request_uuid}/archive.zip` using a newly created mode-`0700` directory and exclusive no-follow mode-`0600` file; do not use the client filename or global temp directory. Count archive bytes independently of multipart bytes, flush and fsync the completed file and staging directory, and pass only this path to the existing material/LUT validators.

The request owns the UUID directory. One `finally` closes the form and removes only that verified directory after `upload_pending` has either copied/published the pending package or failed. Reject a symlink/reparse staging root, raced directory/file, special file, cleanup ambiguity, and insufficient free space before copying. A failure never unlinks a sibling or a path not proven to be owned by the request.

Extract `source_publication.py` as the only producer of committed Registry source-package paths. Given an authenticated immutable proposal, a still-open validated source handle, and a live capacity reservation, it acquires the normalized resource lock, revalidates ownership and duplicate-revision preconditions, and derives one immutable server-owned destination from kind/ID/revision plus the full source-package SHA; no client/repository filename or path participates. It publishes with the probed atomic no-replace primitive, re-opens no-follow, verifies file identity/bytes/prefixed SHA/manifest against the original handle/proposal, and fsyncs file plus parents. Its repository callback then inserts the pending/imported revision, source-package fields, revision files, and audit record in one `BEGIN IMMEDIATE` transaction. Release the reservation only after either that transaction commits or a post-publication failure is classified; current free-space accounting already includes any retained candidate bytes. `upload_pending` delegates to this primitive after applying upload ownership/status policy; Task 9 reuses it for authenticated Materials import rather than storing a checkout path.

If the deterministic destination already exists without a revision row, adopt it only during an authenticated retry whose actor/assignment can create that exact resource and whose still-open upload bytes, full hash, normalized manifest, and destination descriptor all match. A conflicting path/hash/identity becomes a safe ownership conflict and leaves both bytes untouched. A database/audit failure after destination publication returns a typed availability error and intentionally retains the source candidate for retry/audit; startup and repair classify it as `unreferenced_source_candidate`, never as an approved artifact and never delete it. Approval and every later metadata envelope build require a committed source row and never read a request staging path or infer a source from the active v1/v2 artifact.

- [ ] **Step 4: Refactor both upload routes through the same intake**

Preserve route URLs, multipart field name, role checks, accepted package schemas, success response, and v1 error statuses. Authorization still occurs before `stage_single_archive`; material and LUT differ only in the domain validator/store call. Remove `tempfile.mkstemp` and duplicated route copying. Run synchronous ZIP/content validation and `upload_pending` through `anyio.to_thread.run_sync(..., abandon_on_cancel=False)` with a process-local limiter no larger than the cross-process slot count, while retaining the request's cross-process slot until repository convergence. A client disconnect after staging cannot cancel cleanup ahead of the live thread or remove its file; the repository call converges before request-owned cleanup. The event loop never performs ZIP, NumPy, Pillow, fsync, or SQLite work directly. Keep archive validation, canonical hash checks, pending-record insertion, and audit convergence after the staged file is fully durable; a partial request never reaches the repository.

- [ ] **Step 5: Run and commit**

```bash
set -euo pipefail
.venv/bin/python -m pytest tests/test_registry_upload_intake_v2.py tests/test_registry_service.py -q
git add requirements.txt registry_service/storage_capacity.py registry_service/upload_intake.py registry_service/source_publication.py registry_service/database.py registry_service/repository.py registry_service/store.py registry_service/app.py tests/test_registry_upload_intake_v2.py tests/test_registry_service.py
git commit -m "fix(upload): bound registry multipart intake"
```

Expected: all upload-intake tests and the original 55-test baseline pass; process/temp-file inspection finds no surviving request-owned staging or open spool.

## Task 5: Freeze V1 Through Offline Independent Projections

**Files:**
- Create: `registry_service/domain_adapters.py`
- Modify: `registry_service/store.py`
- Test: `tests/test_registry_v1_contract.py`

- [ ] **Step 1: Capture exact v1 response contracts**

Generate 181 material and 181 LUT approved records with three revisions for one logical resource, including the historical `official/official`, `community/community`, and `team/team` pairs. Test no `limit` returns all matching revisions; `limit/offset/q/channel` retain current semantics; default channel remains current `official`; and field names, nullable fields, counts, URLs, legacy LUT content hash, plus existing public/restricted error statuses match the baseline app. Additive-metadata material 2.0 and LUT 1.0 envelopes must preserve every legacy-required manifest field/schema/core hash. Also approve material 2.1 and LUT 2.0 sources and prove the offline repository projector can select deterministic schema-2.0/schema-1.0 compatibility artifacts whose hash/bytes/manifest are accepted by an unchanged pre-v2 Studio build; v2 artifact paths, package hashes, canonical LUT hash, envelope query, and fields never leak into those projected v1 fixtures. This storage PR freezes only the three pre-v2 equal-value distribution pairs, leaves every live route on the current JSON reader/writer, and does not publish a `private` envelope before Task 6's scoped principal and exact-pair route authorization exist. Adapters preserve channel and visibility as distinct fields rather than normalizing one from the other, so Task 6 can add the reviewed visibility literal without rewriting the frozen projection layer.

- [ ] **Step 2: Verify tests pass against the old facade and fail against an empty repository adapter**

Run the tests once before changing `store.py`, then inject the new repository with no adapter and confirm the equality assertion fails. This proves the test detects projection drift.

- [ ] **Step 3: Implement separate domain adapters**

Define:

```python
class DomainAdapter(Protocol):
    resource_kind: Literal["material", "lut"]
    id_field: Literal["material_id", "lut_id"]
    logical_path_field: Literal["local_directory", "local_path"]

    def normalize_manifest(self, record: dict[str, Any]) -> NormalizedRevision: ...
    def project_v1(
        self,
        revision: StoredRevision,
        envelope: StoredEnvelope,
        artifact: StoredPackageArtifact,
    ) -> dict[str, Any]: ...
    def project_v2(
        self,
        revision: StoredRevision,
        envelope: StoredEnvelope,
        artifact: StoredPackageArtifact,
    ) -> dict[str, Any]: ...
    def build_envelope_manifest(
        self,
        revision: StoredRevision,
        envelope: StoredEnvelope,
        representation: Literal["v1", "v2"],
    ) -> bytes: ...
```

Implement `MaterialDomainAdapter` and `LutDomainAdapter` explicitly. Each projector rejects an artifact whose `representation` is not its exact version; no repository caller may select by “first row” or fall back across representations. LUT `project_v1` returns the legacy hash and v1 artifact for every approved source schema; LUT `project_v2` returns raw-file canonical hash, optional `legacy_content_hash`, and only the v2 artifact. Material applies the corresponding package-schema projection. `build_envelope_manifest` is deterministic and accepts no caller-selected package path/hash; tests round-trip each representation through its production consumer and prove both normalize back to the same core revision.

- [ ] **Step 4: Prepare compatibility facades without switching the live writer**

Keep constructor and public method signatures, but in this PR every live route continues to read and mutate only the current JSON implementation even when a shadow DB exists. `RegistryRepository` is reachable only from migration/parity tests and explicit offline tooling; DB existence is never a backend-selection signal. Route tests mutate each legacy operation after a shadow migration and prove JSON changes exactly once while SQLite bytes/generations/audit remain unchanged; repository projector tests independently compare the frozen v1 shapes. Task 6 performs one maintenance-mode final shadow rebuild and explicit writer-marker transition only after the complete publication protocol exists. No request dual-writes JSON and SQLite.

- [ ] **Step 5: Run v1 suites and commit**

```bash
set -euo pipefail
.venv/bin/python -m pytest tests/test_registry_v1_contract.py tests/test_registry_service.py -q
git add registry_service/domain_adapters.py registry_service/store.py tests/test_registry_v1_contract.py
git commit -m "refactor(v1): project legacy catalogs from shared records"
```

Expected: original 55 tests plus v1 contract tests pass.

Run the migration/upload failure matrix, `git diff --check`, and the token/path scan, then open the `resource-registry-storage-v2` PR with v2 explicitly disabled. Its exact-head review must confirm the online app remains wholly on JSON, the SQLite candidate is shadow/offline only, no request dual-writes, no credential-derived actor enters SQLite, and every unchanged v1 request retains its frozen response/package representation. Merge it before starting Task 6 from fresh `master`.

## Task 6: Principals, Generations, And Immutable Envelopes

**Files:**
- Modify: `registry_service/auth.py`
- Modify: `registry_service/app.py`
- Create: `registry_service/cache_invalidation.py`
- Create: `registry_service/writer_epoch.py`
- Modify: `registry_service/migrate_v2.py`
- Modify: `registry_service/repository.py`
- Modify: `registry_service/store.py`
- Modify: `registry_service/storage_capacity.py`
- Modify: `tests/test_registry_service.py`
- Modify: `tests/test_registry_migration_v2.py`
- Test: `tests/test_registry_envelopes_v2.py`
- Test: `tests/test_registry_concurrency_v2.py`
- Test: `tests/test_registry_writer_epoch_v2.py`

- [ ] **Step 1: Write authorization and envelope-state tests**

Cover anonymous public, read-token public, restricted `team/private`, historical restricted `team/team`, every one-field-public/one-field-restricted cross-product boundary, maintainer, and approver for both material and LUT adapters. Assert anonymous and under-scoped principals fail closed, while a read token succeeds only when its registry, channel, and visibility scopes all allow the exact pair. Freeze the existing v1 approve/change-channel request model and its default unknown-field-ignore behavior byte-for-byte: it still accepts only its historical `channel` field/default. For pending content, v1 approve creates only the equal pair `(channel, channel)`. V1 channel change may update both values only when the active pair is still an equal legacy pair; an asymmetric record such as `team/private` returns deterministic `409 distribution_requires_v2` with no publication work rather than silently becoming public or producing another cross-pair. Add strict, separate material/LUT admin routes under `/api/material-registry/v2/admin/.../approve` and `/distribution`; their `extra="forbid"` model requires non-null channel and visibility together and is the only HTTP path that creates or changes an asymmetric pair. Reject `private` as channel and every unknown/null/extra v2 field. Existing v1 bodies, including previously ignored extra fields, retain their exact baseline result.

For v1 catalogs, authorize the requested channel first so an anonymous explicit `team` query retains its existing generic `403`, then project only rows whose exact visibility the principal may read; an anonymous `official` query therefore omits `official/private` without leaking it. A package request requires both exact scopes and retains the existing v1 `403` denial. Any scoped write authorizes the complete affected set before lookup-dependent work: approve checks its target pair; distribution/withdraw/restore check every current and target pair; publisher disable/ban/restore and multi-resource metadata publication preflight every affected envelope pair atomically and fail the whole operation with generic `403` if one pair is outside scope. Maintainer upload scope authorizes this Registry and its configured publisher assignment but cannot approve or choose distribution. Tests prove the legacy team token reads `team/team` but not `team/private`, a scoped read token sees only its authorized subset with stable ordering/counts, scoped approvers cannot partially mutate a mixed-scope publisher, and no channel-only path bypasses visibility.

Freeze the writer transition before publication code. `LUMINA_REGISTRY_MAINTENANCE_READ_ONLY=1` rejects every upload/approve/distribution/channel/withdraw/restore HTTP mutation with one typed `503 registry_maintenance_read_only` before body receive, store construction, or filesystem/SQLite work, while v1 reads remain available. Configure `LUMINA_REGISTRY_WRITER_EPOCH_FILE` as an owner-only regular control record on a separately retained control volume outside every Registry data/package/public/backup/release root; validate its owner/mode/ACL, no-follow final handle, parent chain, one-link identity, fsync/atomic replacement, and cross-process lock exactly as other privileged policy files. Its canonical bounded JSON contains only schema, Registry authority ID, immutable DB UUID, monotonic epoch `0 | 1 | 2`, state `legacy_json | sqlite_selected | roll_forward_only`, one random transition ID, candidate fingerprint, and timestamp. It contains no path, token, package fact, or operator text. A deployment-control guardian outside the release artifact refuses to start an epoch-unaware/old binary once epoch is nonzero and keeps old JSON service generations disabled; copying/restoring any data backup cannot copy, replace, or decrement this record.

Under maintenance mode and a stopped writer, `migrate_v2 --initialize-writer-epoch` may create epoch 0 exactly once after proving the final candidate DB UUID/fingerprints and guardian identity; an existing/mismatched record fails closed. `--commit-sqlite-writer` then takes the migration/control locks, proves full v1 projection parity, no live legacy writer, stable configured auth-HMAC identities, no incomplete/quarantined batch or ambiguous reservation, exact recoverability of every migrated source/v1 typed alias, and zero internal/external epochs. It first commits a bounded DB transition intent carrying action `select_sqlite`, target epoch 1, random transition ID, DB UUID, and final candidate fingerprint while leaving JSON selected. It then CAS/fsyncs the external record `0 -> 1/sqlite_selected`, and only after re-reading both exact handles does a DB transaction set `writer_backend=sqlite`, internal epoch/state 1, retain the completed transition ID, and clear the pending intent. A crash before external CAS may clear only the matching DB intent under the same stopped proof; a crash after external CAS must converge that exact candidate forward and can never reopen JSON. It does not require v2 artifacts/previews created later. App startup selects a backend from the mutually consistent external record plus DB UUID/internal marker, never DB existence alone.

Before the first authoritative business operation handled by the Task 3 repository or any later service opens a package, reserves capacity, or mutates business rows, the repository writes a second DB intent (`enter_roll_forward`, target epoch 2, operation-class digest, random transition ID), CAS/fsyncs the external record to `2/roll_forward_only`, and commits internal epoch/state 2 plus `post_migration_write_admitted=1` and a control audit event. Only then may the authorized business transaction retry/revalidate and mutate rows. Thus even a failed/crashed first operation permanently closes the restore window; it cannot roll the external fact back with its business transaction. If external CAS fails, no internal flag/business write occurs. If external epoch 2 has the exact DB intent but internal state is 1, startup remains maintenance/read-only and may converge only that intent to flag 1 before a fresh authorized retry. Any external-ahead state without the exact DB UUID/intent/fingerprint, internal-ahead state, restored older DB, missing/decremented/replaced epoch file, or unknown combination is `registry_writer_epoch_mismatch`: all writers stay closed, JSON fallback and automatic backup restore are refused, and only an external-backup-aware operator diagnosis may proceed. A completed smoke download remains the sole reconstructible count/catalog update allowed at epoch 1/flag 0.

The only supported pre-business restore is a stopped restore of the exact post-marker SQLite checkpoint backup carrying the same DB UUID, epoch-1 marker, completed transition ID, and fingerprint while the external record remains epoch 1; it never restores/reopens a JSON writer or decrements the external record. After epoch 2, every backup restore is roll-forward disaster recovery into a new verified copy whose DB must preserve/advance that lineage. Tests cross every control-plane/cosmetic/authoritative classification, guardian refusal, old binary launch, epoch-file permission/path swap, DB-intent/external-CAS/internal-commit crash boundary for both transitions, concurrent first writers, stale JSON change, exact epoch-1 backup restore, epoch-2 restore of every older backup, DB UUID substitution, missing/decremented external state, multi-process restart, and unknown marker without dual-writing or losing a prior active package.

Close the cache window in this same PR rather than waiting for Task 8. Every v1 catalog response, including validation, authorization, not-found, and internal error responses, carries exactly one canonical `Vary: Authorization`. Anonymous successful public-only results use `Cache-Control: public, max-age=0, must-revalidate`; every Authorization-bearing result and every catalog error use `Cache-Control: private, no-store`. Both legacy package routes always use `Cache-Control: private, no-store` plus exactly one canonical `Vary: Authorization` on success and error, including public packages. These are the only additive v1 response headers; body, status, validators, filename, media type, HEAD, and Range behavior remain frozen. Raw-header tests cover route handlers plus framework-generated validation/error boundaries and prove one canonical value per field, no duplicate or comma-merged repeated value, no token-bearing public response/error, and no anonymous success/error cache entry can satisfy an authenticated request.

Create the minimal invalidation foundation in this same PR. `cache_invalidation.py` exposes one transaction-local helper that canonicalizes exactly `["registry:all"]`, inserts at most one pending global row for the new invalidation generation, and enforces the final 4,096-row/16-MiB pending-state caps before any metadata commit. It accepts no resource, publisher, channel, envelope, query, or caller-provided key and never stores a raw identifier. If a pending/failed global row already covers an equal or newer generation, the helper reuses that superset instead of growing the queue; for a newer generation it atomically inserts the new fixed-global row and removes every older pending/failed row only because the new global key is a proven superset, leaving exactly one. Task 8 may extend this module with typed derived keys, delivery, compaction, and health, but Task 6 publication/auth changes call only this bounded fixed-global API. Unit tests cover repeated changes, exact caps, crash rollback, concurrent inserts, canonical bytes, and prove no ID enters the row.

Assert ordinary upload cannot assign `lumina`; approver can. Publisher IDs are Registry-generated/assigned and cannot be selected by display name. Two equal-name ordinary uploaders without assignment keys receive isolated per-resource community publishers; one pre-provisioned assignment key groups only its explicit resources; token secret rotation with the same assignment key preserves ownership; changing/removing/reusing an assignment key without approver mapping fails closed. A different/unassigned principal uploading a new revision under an existing `(resource_kind, resource_id)` gets one deterministic ownership conflict before package persistence, while the exact assigned owner may continue the revision chain. Approve/channel/visibility/publisher/title/summary/brand/tags/compatibility/withdraw/restore each re-opens the committed immutable source archive, verifies its source path/hash/bytes/schema and normalized core revision, rewrites both v1-compatible and v2 ZIP manifest representations with the currently reviewed metadata, revokes the old active envelope, writes two new immutable package paths/hashes/byte counts when still approved, advances required generations, and makes both old representations unreadable. A metadata-only change does not mutate/recompress the source archive or allocate a new core revision. The database projection and each downloaded manifest must match after every operation and normalize to one core revision. Race publication against upload and another multi-resource publication with limited fake byte and inode budgets; only reservations whose unconsumed totals plus both safety margins fit may stage, and byte/inode exhaustion after reservation leaves prior envelopes active and recovery-owned state only.

Create two resources owned by one explicit publisher plus an equal-name resource owned by another publisher. Publisher rename/kind/ownership change, disable, ban, and restore affect only the explicit publisher ID. Equal display names never join the operation. Disable/ban revokes all its active envelopes atomically; restore and manifest-affecting changes prepare every replacement package before one metadata switch, so no catalog generation mixes old record fields with new ZIP manifests.

- [ ] **Step 2: Implement constant-time principal parsing**

Return this immutable model from `auth.py`:

```python
@dataclass(frozen=True)
class Principal:
    mode: Literal["anonymous", "read", "maintainer", "approver"]
    token_id: str | None
    scope_version: str
    registries: frozenset[str]
    channels: frozenset[str]
    visibilities: frozenset[str]
    publisher_assignment_key: str | None = field(default=None, repr=False)

    @property
    def is_authenticated(self) -> bool:
        return self.mode != "anonymous"
```

Compare configured secrets with `hmac.compare_digest`. Produce `token_id` as a purpose-separated server-secret HMAC opaque identifier, never raw SHA of the token and never the later cursor-signing key. Freeze three server-side auth inputs: `LUMINA_REGISTRY_AUTHORITY_ID` is a non-secret 1..64 lowercase-safe identifier for this deployed Registry authority; `LUMINA_REGISTRY_AUTH_HMAC_SECRET` is a secret-manager-injected, exactly 64-lowercase-hex 32-byte key used only for token/principal/actor identifiers and policy fingerprints; and `LUMINA_REGISTRY_CREDENTIALS_FILE` points to a maximum-1-MiB owner-only regular JSON policy file outside the checkout plus Registry data/package/public roots. On POSIX, walk already-open parent directory descriptors without following links, require the policy file to be owned by the effective service UID with exact `0600`, one link, regular-file type, and parent directories owned by that UID or root without group/world write; open the final file with no-follow semantics and parse bytes only from that descriptor after matching device/inode/type/size/owner/mode/link count before and after the read. On Windows, require the equivalent owner-only DACL, regular-file/reparse checks, final-handle identity, and parent-chain protection. A parent/file swap, hard link, reparse point, special file, oversized file, unsafe owner/mode/ACL, or unenforceable trust check fails startup closed.

The policy document has exact `schema_version="1.0"` plus at most 64 records containing only a `secret_env` reference, mode, scope version, registry/channel/visibility allowlists, and optional publisher assignment key; raw secret values are forbidden in the file. Each reference must match `LUMINA_REGISTRY_SCOPED_TOKEN_[A-Z0-9_]{1,48}` and resolve to one nonempty child-process environment value at startup. Reject unknown/duplicate fields, duplicate references or resolved secrets, unsafe IDs, malformed/all-zero HMAC keys and fixed documented test/default key literals, empty/wildcard scopes, unsupported literals, and any record whose registry scope omits this authority ID. Resolve the values once into repr-hidden immutable credentials and never persist, return, log, watch, or echo the policy path, environment value, environment name, HMAC key, or token; diagnostics may use only bounded record indexes and safe error codes. Tests include `0620`/`0640`/`0660`, wrong owner, hard link, oversized JSON, parent symlink/replacement races, check/use file swaps, repr/exception/log redaction, and child-process environment isolation.

V2 enabled mode, any configured scoped policy, `writer_backend=sqlite`, or any repository/import/repair mutation requires all three inputs before the app accepts traffic. A v2-disabled `writer_backend=legacy_json` startup with no scoped policy remains compatible without them: generate one process-memory HMAC key before parsing the legacy environment tokens, use it only for process-scoped opaque legacy logging/audit behavior, keep every v1 catalog/package response on the exact Step 1 revalidate-or-private cache policy, and forbid every SQLite/repository mutation or persistent authorization-policy fingerprint comparison. The fallback actor is explicitly unstable and cannot establish durable ownership, publisher assignment, migration identity, repair authority, or policy continuity; an existing legacy JSON audit entry may contain only that bounded process-scoped opaque value. Never write the fallback key, raw token, or an unkeyed/reversible token digest. The first fully configured maintenance startup must initialize the durable opaque fingerprint and its authorization/cache generations while `writer_backend=legacy_json`, before writer cutover. Once the marker is `writer_backend=sqlite` and `post_migration_write_admitted=0`, that exact fingerprint and auth-HMAC identity are frozen for the backup-restore window: any key, scope, assignment, channel-policy, or read-policy mismatch fails startup/CLI closed without changing the fingerprint, generations, snapshots, outbox, or write-admitted flag. After the epoch-2 admission protocol durably sets the flag to `1`, before the first authoritative business transaction is retried, a deliberate auth-HMAC or policy rotation is allowed and performs the normal atomic generation/invalidation transition before traffic. Tests cover first initialization, unchanged restart, every post-marker/pre-write mismatch, failed-start byte-for-byte metadata stability, failure of the first business transaction after flag convergence, and post-admission rotation. The Studio-local `source_registry` key is never sent to this parser or compared with the authority ID.

Retain the three existing environment credentials with explicit least-privilege mappings: `LUMINA_REGISTRY_TEAM_TOKEN` maps to read mode for this authority with channel/visibility exactly `team/team`; maintainer and approver tokens retain their current write roles and map to all contract distribution scopes, preserving their existing ability to read restricted team content. Access to `team/private` therefore requires an explicit scoped credential or one of those existing higher roles, never an implicit expansion of the legacy team token. A secret duplicated across legacy environment variables or resolved scoped references fails startup. Contract tests run the original 55 cases unchanged, then cross missing/wrong authority, legacy fallback versus fully configured startup, missing/weak/rotated auth-HMAC secret, auth/cursor key separation, legacy `team/team`, explicit `team/private`, direct-secret-field rejection, missing/invalid/duplicate environment references, token rotation, duplicate resolved secret, file-permission, and source-registry-confusion cases.

A configured credential may additionally carry a stable opaque `publisher_assignment_key` that is independent of the secret and token HMAC; validate it as a bounded server-side identifier and keep it out of responses/logs. An approver pre-provisions/rebinds that key to the unique `publishers.ownership_key`; ordinary uploads may only reuse the exact existing active community mapping. Without one, create an isolated Registry-generated community publisher for that logical resource, never grouping by supplied name/brand. Token rotation preserves assignment only when auth configuration deliberately keeps the same key. Package JSON, argv, headers other than the credential lookup itself, and uploader fields can never select the key or internal publisher ID.

Keep the existing `ApproveRequest` and its Pydantic extra-field behavior unchanged. Add a separate strict `DistributionRequest` for the new v2 admin routes with required channel and visibility fields; explicit null, omission, or extra fields are invalid. Parse Authorization into one `Principal` before any lookup/publication; the privileged HTTP boundary preauthorizes the complete current/target pair set from Step 1, then passes only validated distribution values and the safe HMAC actor ID into the facade. Repository/store methods never reread headers or environment and still validate the pair as data invariants, but they do not infer authority from actor text. Existing public store call sites retain their signatures; the new v2 admin facade takes both values explicitly, and any non-HTTP command establishes its own principal boundary. Catalog and package routes use the exact-pair rules frozen in Step 1. In `app.py`, add one exact legacy-route response boundary that replaces rather than appends the Step 1 cache headers after all route and framework-generated error handling; it must not broaden to unrelated endpoints. Task 8 moves that behavior into the shared cache-policy module without an intermediate response change. No browser/Studio lifecycle request can set either distribution field.

Build a canonical authorization-policy fingerprint from opaque token IDs, scope versions, registries/channels/visibilities, opaque publisher-assignment mappings, channel policy, and Registry read policy. During the pre-marker initialization state, or after `post_migration_write_admitted=1`, compare it under `BEGIN IMMEDIATE`; an admitted change increments `authorization_generation` and `cache_invalidation_generation`, removes bounded snapshots, enqueues the fixed global purge key, stores only the new opaque fingerprint, and completes before readiness. In the frozen `writer_backend=sqlite`/flag-zero state, comparison is read-only and an unequal or missing fingerprint returns `registry_authorization_policy_frozen` before opening traffic or any write transaction. Tests restart with scope change, token revoke/rotation with same/different assignment, channel policy change, unchanged config, and every writer-state boundary. No raw secret, reversible token digest, or assignment key enters SQLite snapshots, logs, ETags, or responses; only the reviewed publisher row keeps its independent opaque ownership key.

- [ ] **Step 3: Implement a recoverable filesystem/SQLite publication protocol**

Filesystem rename and SQLite commit are not one atomic transaction. Publish through these durable phases under the resource lock:

1. Validate all scoped revision records and their committed immutable source archives through one no-follow open descriptor, matching source path/schema/prefixed SHA/bytes, normalized core identity, and revision-file inventory before using reviewed database metadata to construct envelopes. Never select an active/revoked v1 or v2 artifact as the source and never require the source manifest's historical display snapshot to equal the current reviewed metadata. Compute a conservative bounded output peak: both replacement package representations per operation, deterministic preview cap, temporary ZIP overhead, exact asset/staging-directory inode peak, and byte/inode safety. Hold the resource/publisher scope lock for the complete transition. Generate a fresh batch ID and first commit the complete batch plus child-operation inventory in `allocating`, including exact source descriptor/preconditions and byte/inode budget in canonical `requested_policy_json` but null reservation columns. No asset staging or capacity write is allowed before this commit. With no SQLite transaction open, acquire one shared `StorageCapacityManager` publication reservation with `owner_kind=publication`/`owner_id=batch_id` against the same budget used by uploads. After releasing the capacity lock, enter a second `BEGIN IMMEDIATE`, re-read the unchanged preconditions, exact allocating inventory, and returned reservation owner/budget/version, then fill reservation ID plus reserved/safety byte/inode columns and advance batch/operations together to `reserved`. Capacity refusal marks the still-unbound allocating batch/operations `aborted`. After `reserved` commits, only batch recovery may release the reservation. All publication/recovery paths use scope lock -> capacity lock -> SQLite and never wait for a lower-ranked lock while holding a SQLite transaction; upload intake uses only capacity -> SQLite read where needed and never acquires a publication scope lock.
2. Build and validate every rewritten ZIP in batch-owned private same-filesystem staging directories. In the Task 6 publication PR, `expected_asset_count` is exactly two and the operation contains only `package_v1` plus `package_v2`; `v2_projection_ready` remains false. Task 8 version-bumps the publication policy so every new/republication operation has count three and adds its deterministic PNG/summary; recovery rejects a batch whose recorded policy/count does not match the implementation generation rather than guessing. Before each write, version-CAS the reservation's `consumed_bytes`; actual staged bytes may never exceed reserved bytes minus safety. Fsync each file/directory, then in `BEGIN IMMEDIATE` insert each exact asset with destination/media/hash/bytes and advance operations/batch to `prepared` only when `expected_asset_count` matches those rows. A single-resource change is a batch of one.
3. Publish every immutable asset with an atomic no-replace primitive: same-filesystem hard link where supported, Linux/macOS exclusive rename, or Windows `MoveFileExW` without replace. A platform lacking a proven primitive fails closed; check-then-`os.replace` is forbidden. Re-open each destination with no-follow semantics, verify bytes/hash/media type, fsync files and parents, then unlink only the asset-owned staging name before advancing that asset to `published`. Recovery may remove a surviving hard-link staging name only when file identity plus expected bytes/hash prove it aliases the verified destination. Mark an operation and then the batch `assets_published` only when exact operation/asset counts and hashes are complete. Prior envelopes remain active throughout this phase, and any destination raced into existence is left byte-identical and quarantines the operation.
4. In one final `BEGIN IMMEDIATE`, revalidate the complete batch preconditions and every destination, insert all new active envelopes plus exactly two `envelope_package_artifacts` rows and, only for the Task 8 three-asset policy, the matching `envelope_previews` rows; revoke all prior envelopes, update revision/publisher/policy rows, advance catalog, authorization, and cache-invalidation generations once, enqueue only the Task 6 fixed `registry:all` row through the bounded helper at that invalidation generation, and mark every asset, operation, and batch `committed` in the same commit. Then release the publication reservation by batch ID/version; a crash between commit and release is converged from committed DB/verified assets without deleting bytes. Before v2 projection readiness, an active envelope may have both package artifacts and no preview but no v2 route/capability may expose it. Task 8 extends the helper and Task 6 protocol with reviewed derived keys, then Task 9 must use the Task 8 three-asset policy to republish every such envelope with a fresh preview-bound envelope before readiness; afterward, committing or exposing an approved envelope without both package representations and exactly one preview is forbidden.

On startup and before a mutation for the same resource/publisher/channel scope, recover incomplete batches deterministically after acquiring that batch's same scope lock; successful acquisition is the proof that no prior publication process still owns the transition. An `allocating` batch with no reservation record aborts with no filesystem cleanup. If exactly one reservation record names that allocating batch and its owner/byte/inode budget match the canonical request, recovery version-CAS transfers the process owner, commits the reservation binding plus batch/operations to `reserved`, and continues; multiple, mismatched, staged-before-reserved, or identity-ambiguous records quarantine the scope. Under the capacity lock, every later state requires reservation ID, publication owner/batch ID, reserved/safety bytes, and reserved/safety inodes to match the durable batch, then reads the current record version for any CAS; a missing or contradictory binding is quarantined rather than reconstructed from filenames or process state. A `reserved` batch with no owned staging and no live scope owner aborts and releases its exact reservation; owned partial staging either resumes within the recorded budget or is retained/quarantined, never treated as a stale upload. Missing destinations plus caller-owned staging abort safely only when no destination was published; a complete verified child set advances forward; a partially published set resumes remaining no-replace publications; conflicting destination/staging/hash/count/reservation/state becomes `quarantined` and closes writes for the entire scope. Recovery reconciles consumed bytes/inodes from proven batch-owned staging/destinations without counting persisted destination objects twice against current free capacity. It never overwrites or unlinks an existing envelope path and never revokes old envelopes until the complete new batch is durable and the final metadata commit succeeds. Disable/ban without replacement packages uses one direct metadata transaction to revoke the publisher's envelopes, advance catalog/authorization/cache-invalidation generations, and enqueue only the bounded fixed-global row; restore always creates fresh envelopes through this protocol. Task 8 upgrades both publication and direct metadata transactions to the shared reviewed derived-key helper atomically.

- [ ] **Step 4: Add crash injection and real concurrency barriers**

Terminate after each Task 6 phase boundary and after each v1/v2 package asset plus the first/middle/last operation: allocating DB commit, capacity reservation file commit, reserved DB binding commit, staging write/fsync, prepared commit, destination rename/fsync, asset `published` commit, operation/batch `assets_published` commit, envelope/artifact commit, capacity release, and response acknowledgement. Restart a fresh repository and assert exactly one active envelope with exactly two representation rows, no v2-visible record while previews/readiness are absent, old-envelope readability until full-batch convergence, deterministic allocating/reservation reconciliation/forward/abort/quarantine behavior, and no v1-catalog/v1-package mismatch. Task 8 extends the same parameterized failure matrix with the preview asset and final envelope/artifact/preview commit, then requires one preview per v2-visible approved revision and no v2-exact/v2-package/preview mismatch.

Use two repository instances and `threading.Barrier` around reservation and final commits. Assert concurrent approvals yield one success/one deterministic conflict, concurrent channel changes leave one active envelope, package paths remain unique, no catalog references a revoked envelope, and download increments are not lost.

- [ ] **Step 5: Run and commit**

```bash
set -euo pipefail
.venv/bin/python -m pytest tests/test_registry_envelopes_v2.py tests/test_registry_concurrency_v2.py tests/test_registry_writer_epoch_v2.py tests/test_registry_service.py tests/test_registry_migration_v2.py -q
git add registry_service/auth.py registry_service/app.py registry_service/cache_invalidation.py registry_service/writer_epoch.py registry_service/migrate_v2.py registry_service/repository.py registry_service/store.py registry_service/storage_capacity.py tests/test_registry_service.py tests/test_registry_migration_v2.py tests/test_registry_envelopes_v2.py tests/test_registry_concurrency_v2.py tests/test_registry_writer_epoch_v2.py
git commit -m "feat(publication): make resource envelopes immutable"
```

Run `git diff --check`, the complete Task 6 crash/concurrency matrix, and unchanged-v1 install tests; open the `resource-publication-v2` PR with `v2_projection_ready=0`. Exact-head review must verify no route advertises the pre-preview envelopes and every failure leaves the prior envelope active. Merge it before Task 7.

## Task 7: Signed Snapshot Cursor Catalogs

**Files:**
- Create: `registry_service/build_identity.py`
- Create: `registry_service/cursor.py`
- Create: `registry_service/api_v2.py`
- Modify: `registry_service/repository.py`
- Test: `tests/test_registry_catalog_v2.py`

- [ ] **Step 1: Write the cursor matrix before route code**

Test both domains for default `50`, max `100`, latest-approved-only cards, `updated_desc`, `downloads_desc`, q/exact-publisher-ID/publisher-kind/brand/domain filters, equal publisher names under different IDs, 181+ records, stable pages while new revisions/downloads appear, and exact end-page invariants. Test tamper, malformed base64/JSON, expired snapshot, wrong domain, wrong principal, changed scope version, changed authorization generation, changed query/filter/sort/limit, and cursor replay across material/LUT.

Seed internal download counts at `9007199254740990`, `9007199254740991`, `9007199254740992`, and signed-64-bit max. V2 catalog/latest/exact projections emit a JSON integer saturated at `9007199254740991`, while frozen snapshot sort values retain the checked internal integer and v1 projection behavior stays unchanged. No v2 numeric field may make a JavaScript client lose integer precision.

- [ ] **Step 2: Implement opaque snapshot handles and signatures**

Use a cryptographically random 256-bit snapshot handle plus a minimal versioned URL-safe base64 payload without padding:

```python
@dataclass(frozen=True)
class CursorClaims:
    version: int
    snapshot_handle: str
    page_sequence: int
    next_position: int
    expires_at: str
```

`snapshot_handle` is lowercase URL-safe random text with at least 256 bits of entropy and is the only browser-visible snapshot identifier; it is not a database row ID derived from content. `page_sequence` and `next_position` are bounded nonnegative integers used for replay/order checks. Canonicalize JSON with sorted keys and compact separators, sign `payload_bytes` with HMAC-SHA256 using `LUMINA_REGISTRY_CURSOR_SECRET`, and validate with `hmac.compare_digest`. Load that secret once as a repr-hidden exact 64-lowercase-hex 32-byte key, reject malformed/all-zero/fixed test-default values, and fail readiness if it equals `LUMINA_REGISTRY_AUTH_HMAC_SECRET`; the two HMAC domains never call each other's helper or key. Test missing/malformed/equal/independently rotated keys and return `catalog_cursor_invalid`, `catalog_cursor_query_mismatch`, or `catalog_cursor_expired` exactly as designed without logging either value.

Store resource kind, normalized query/filter/sort/limit digest, catalog/authorization generations, policy fingerprint, principal fingerprint, frozen sort rows, current sequence, and expiry only in the bounded server-side snapshot. The query digest covers contract version, resource kind, normalized `q`, exact public publisher ID, publisher kind, brand, requested channel set, domain filter name/value, sort, and fixed limit. The principal fingerprint is a separate server-secret HMAC over token ID, scope version, registry/channel/visibility scopes, and anonymous/read mode. On every page, recompute request/principal facts and compare them to the snapshot before reading rows. Reject unknown query keys instead of silently excluding them from the digest. Cursor bytes and diagnostics contain no resource kind, query/filter/sort, token, principal/policy fingerprint, generation, result ID, tuple, publisher ownership key, or raw database identifier; HMAC integrity does not make those facts safe to disclose.

- [ ] **Step 3: Implement bounded snapshots**

On the first page, read one SQLite snapshot and build a bounded candidate of authorized normalized projections/frozen sort values without holding a write lock. Then enter `BEGIN IMMEDIATE`, recheck catalog/authorization generations and policy fingerprint, and insert the random handle plus all server-only binding facts into `catalog_snapshots` and all ordered `catalog_snapshot_items` in one transaction; retry a changed generation at most once before returning a typed convergence error. Store no raw token. Serve page one from committed rows. Later pages require the exact next sequence/position, read by immutable position, advance the server sequence only after the complete response page is materialized, and never re-sort against live download counts. Persist the consumed input sequence and position with the bounded last response; reusing that exact already-consumed Registry cursor returns the byte-identical cached page for the replay window, while any other old sequence/position gets a typed replay error and never advances twice.

Default snapshot TTL is 15 minutes. Enforce configurable hard caps with safe defaults of 50,000 items per snapshot, 1,024 live snapshots globally, 128 anonymous snapshots, 16 per authenticated principal, 64 MiB normalized projection plus one replay-page bytes per snapshot, and 1 GiB across all live snapshot/replay rows. Delete expired snapshots transactionally before capacity checks; never evict an unexpired cursor chain. Return `429 catalog_snapshot_capacity` with `Retry-After` when capacity remains exhausted and `413 catalog_snapshot_too_large` before inserting any partial rows when an authorized result exceeds per-snapshot bounds. Test exact-boundary values, concurrent first pages, lost-response replay, expiry cleanup, rollback on row/page/replay insert failure, and bounded database growth.

- [ ] **Step 4: Add v2 capability and catalog routes**

`GET /api/material-registry/v1/capabilities` always exists. Add two safe attestation fields: required `service_build_commit` and nullable `materials_source_commit`, each null or exactly 40 lowercase hex. `service_build_commit` comes from one immutable `RegistryBuildIdentity` established before app composition: release/container artifacts embed the exact source commit in their signed/immutable build manifest, a source checkout derives it only from a clean exact HEAD, and the disposable harness injects the commit whose archived bytes it starts. Browser/request/header/query data and a free-form environment override cannot establish it. `materials_source_commit` comes only from the latest fully applied/audited Materials import record in SQLite; dry-run, partial/import-failed, or conflicting documents cannot set it. Neither field contains a path, URL, token, branch, dirty suffix, or arbitrary operator text.

The endpoint reports `resource_catalog_v2=false` unless `LUMINA_REGISTRY_ENABLE_V2=1`, migration marker/DB schema are valid, `registry_meta.v2_projection_ready=1`, both build/source attestations are valid, no publication batch is incomplete/quarantined, and cursor secret is configured. Add separate `/v2/materials/catalog` and `/v2/luts/catalog` routes with the exact common envelope from the design. Direct v2 requests while the projection is not ready return typed `503 registry_v2_not_ready`, never a partial catalog. Tests launch exact archived/dirty/wrong builds, fail closed on missing identity, prove import/readiness binds the Materials commit, and assert capability bytes expose only the two safe commits.

Freeze that common envelope in code/tests with `extra="forbid"`: root fields are exactly `contract_version="2.0"`, route-matching `resource_kind`, `catalog_generation`, `authorization_generation`, `items`, and `page`. `page` is exactly `limit`, `returned`, `has_more`, and nullable `next_cursor`; `returned == len(items)`, `0 <= returned <= limit`, and `(has_more, next_cursor)` is either `(false, null)` or `(true, nonempty)`. Every item is the latest authorized approved revision for one logical ID and contains exactly contract/package kind, the active `v2` artifact schema, domain ID, revision/canonical content identity plus optional opaque legacy hash, active envelope ID, v2 relative package URL/hash/bytes, publisher ID/kind/name, title/summary/brand/tags, publication/update/download facts, channel/visibility/compatibility, one domain logical-path field, exact file records, and the one nested controlled-preview object. It contains no status, internal path, v1 artifact locator/hash, ownership key, token/principal fact, source archive hash, or duplicate preview field. Material items reject `lut_id/local_path`; LUT items reject `material_id/local_directory`.

Latest detail is the same strict item plus root `catalog_generation`, `authorization_generation`, `history`, `history_truncated`, and `history_total`; it has no page fields. `history` is a bounded newest-first list of at most 100 currently authorized approved revisions, each with exactly revision ID, canonical algorithm/hash, optional opaque legacy hash, active envelope ID, v2 artifact schema/hash/bytes (no package URL), published/updated/download facts, channel/visibility/compatibility, and preview summary/hash/bytes/dimensions without a URL. `history_truncated` is exactly `history_total > len(history)`, and `history_total` is a JavaScript-safe count of authorized revisions, so omission is never mistaken for complete history; exact historical selection always calls the exact route. Exact detail is the strict item plus `authorization_generation`, with no `catalog_generation`, page, history, or truncation fields. Strict projection tests compare every key set/nullability/order, saturate history/count bounds, and reject a record/artifact representation mismatch before serialization.

Keep database generations as nonnegative integers and serialize them on every v2 wire response as bounded opaque strings: `catalog_generation` is `cat_` followed by exactly 16 lowercase hexadecimal digits and `authorization_generation` is `auth_` followed by exactly 16 lowercase hexadecimal digits. No field accepts the other prefix. Keep the internal generation integers only in the server-side snapshot row; the signed browser cursor contains neither generation. Studio treats public generation strings as opaque equality/cache-key values and never parses or increments them. Tests reject swapped/missing prefix, case, width, sign, whitespace, and prove catalog, latest detail, exact detail, ETag, cursor invalidation, server-side snapshot binding, and cache keys all refer to the same underlying counters without disclosing either integer in cursor bytes.

- [ ] **Step 5: Run and commit**

```bash
set -euo pipefail
.venv/bin/python -m pytest tests/test_registry_catalog_v2.py tests/test_registry_v1_contract.py -q
git add registry_service/build_identity.py registry_service/cursor.py registry_service/api_v2.py registry_service/repository.py tests/test_registry_catalog_v2.py
git commit -m "feat(catalog): add signed snapshot pagination"
```

## Task 8: Detail, Exact Revision, Live Package Authorization, And Cache Policy

**Files:**
- Create: `registry_service/cache_policy.py`
- Modify: `registry_service/cache_invalidation.py`
- Create: `registry_service/previews.py`
- Modify: `registry_service/repository.py`
- Modify: `registry_service/store.py`
- Modify: `registry_service/api_v2.py`
- Modify: `registry_service/app.py`
- Test: `tests/test_registry_exact_revision_v2.py`
- Test: `tests/test_registry_auth_cache_v2.py`
- Test: `tests/test_registry_cache_invalidation_v2.py`
- Test: `tests/test_registry_previews_v2.py`

- [ ] **Step 1: Write the exact authorization matrix**

For material and LUT, cross anonymous/read/maintainer with approved public, approved restricted `team/private`, historical restricted `team/team`, each one-field restricted cross-product, pending, rejected, withdrawn, purged, unknown, disabled publisher, active envelope, and revoked envelope. Cross read principals with missing registry, channel, visibility, and scope-version authorization independently. All nonexistent/invisible/revoked/non-approved exact reads must return the same `404` body `{"code":"revision_not_found","message":"Revision not found"}` and equivalent cache/log behavior.

- [ ] **Step 2: Generate bounded controlled previews from validated content**

On approval, derive a versioned JSON preview summary and PNG bytes from the validated core payload, never from uploader HTML, scripts, remote URLs, SVG, or arbitrary image files. Material previews expose bounded swatches and parameter/validation facts. LUT previews sample bounded RGB/color-distribution cells from the loaded LUT and include color mode, base channel, color count, layer/stack summary, and calibration facts. Use fixed dimensions, deterministic ordering/encoding, and a hard output byte limit; strip metadata and reject non-finite/out-of-range values. Version the durable publication request policy explicitly as dual-package-only versus dual-package-plus-preview. Recovery must finish an interrupted Task 6 two-asset batch under its recorded policy rather than reinterpret it as missing a preview, while every batch newly allocated by Task 8 uses exactly three assets. Feed the PNG and summary into Task 6's `publication_assets` protocol before the new envelope becomes active; do not write `envelope_previews` or expose a preview in a later best-effort transaction. Tests seed a committed pre-readiness two-artifact/no-preview envelope and prove metadata republish creates a fresh three-asset envelope, revokes the old one only at final commit, and preserves its core revision/source archive.

Store preview assets under an immutable envelope-specific path and return version, summary, same-origin relative URL, `preview_media_type="image/png"`, `preview_sha256`, and `preview_bytes` bound to the active envelope. Re-approval or policy change creates new preview assets; revoked envelopes cannot read old previews. Tests compare exact summary JSON, image dimensions/mode/hash, nonblank/non-background pixels, determinism, size limits, malformed input rejection, and authorization across public/restricted/revoked states.

Catalog, latest detail, and exact detail use one nested `preview` object with exactly `preview_version`, `summary`, `preview_url`, `preview_media_type`, `preview_sha256`, `preview_bytes`, `width`, and `height`; no duplicate top-level preview fields are emitted. `preview_url` is same-origin relative and carries only the active `envelope_id`. Studio's server-side client consumes this object and never forwards the Registry URL/query to the browser.

- [ ] **Step 3: Add detail, preview, and exact routes**

Implement latest resource detail, exact revision detail, controlled preview asset, and exact package routes listed in the design. V2 detail includes all binding fields from only the active envelope's `v2` artifact and Registry-generated preview metadata/URLs; it never projects the v1 artifact hash/path/schema. Preview and package require matching `envelope_id`, reauthorize against live generation/policy, and return no redirect. Resolve only the database-owned relative path under the configured storage root; open the final regular file with no-follow semantics, verify size and SHA through that same file descriptor, seek to zero, and stream from the still-open descriptor so a path swap cannot create a verify/use race. Never load the full file into memory. Package emits exactly one `Content-Type: application/zip`, one canonical decimal `Content-Length`, zero or one `Content-Encoding: identity`, zero `Transfer-Encoding`, and exactly one `X-Lumina-Envelope-ID`; preview emits exactly one `Content-Type: image/png` with the same length/encoding/transfer rules. Raw ASGI response-header tests reject duplicate/comma-combined security-relevant headers and prove reverse-proxy middleware cannot add dynamic gzip/Brotli to these routes. V2 preview/package define `HEAD` as typed `405 method_not_allowed`; after the same live authorization/non-disclosure lookup, method dispatch takes priority over headers, so every authorized-or-undisclosed HEAD is `405` even when it also contains `Range`. Only an otherwise valid GET proceeds to header policy, where any `Range` value, including `bytes=0-`, returns typed `416 range_not_supported`; other methods use the closed method error and never become a Range oracle. No multipart/partial response is implemented. These denials never increment download count and carry no asset validators/length. Raw route tests cover HEAD alone, GET+Range, HEAD+Range, unsupported-method+Range, authorized/revoked/unknown/under-scoped combinations, and frozen v1 HEAD/Range behavior byte-for-byte.

Refactor both legacy v1 package GET routes through the same same-descriptor asset streamer after live authorization of the active envelope's exact channel/visibility pair, selecting only that envelope's `v1` artifact. Preserve their exact URLs, status/error ordering and bodies, `Content-Disposition` filename, media type, length, validators, HEAD, and Range contracts; in particular, an under-scoped restricted v1 package request remains the existing generic `403`, while only v2 exact routes use uniform `404 revision_not_found`. V1 does not gain an `envelope_id` requirement or `X-Lumina-Envelope-ID`, and no channel-only check may authorize bytes whose visibility scope is missing. Preserve the Task 6-established `Cache-Control: private, no-store` and `Vary: Authorization` as the only additive old-package headers; the common streamer must emit each once and cannot create a temporary less-restrictive response. Add a barrier that swaps the server-owned package path after authorization/verification and prove both v1 and v2 either stream the already verified open descriptor or fail, never reopen attacker-replaced bytes. Cross-wire tests deliberately pair each catalog/detail representation with the other artifact and require hash/schema rejection. V1 facade tests compare every other response header/body/range case with the baseline, explicitly allow only those two additive security headers, exercise `team/private` plus legacy `team/team` success and under-scoped `403` cases, and install new-schema-derived compatibility packages in an unchanged pre-v2 Studio.

- [ ] **Step 4: Implement response cache helpers**

Public anonymous catalog/detail when a configured surrogate-key purge backend is healthy:

```text
Cache-Control: public, max-age=60, must-revalidate
Vary: Authorization, Accept-Encoding
ETag: W/"{authorization-generation}-{representation-sha256}"
Surrogate-Key: registry:all kind:{fixed-kind} [resource:{derived-id-key} publisher:{derived-id-key} channel:{fixed-name} envelope:{derived-id-key}]
```

Authorization-bearing or restricted metadata:

```text
Cache-Control: private, no-store
Vary: Authorization
```

Default `LUMINA_REGISTRY_PUBLIC_CACHE_MODE=revalidate` instead returns `Cache-Control: public, max-age=0, must-revalidate`; this is also the automatic fallback when purge configuration/health is absent, an outbox row is pending/failed, or readiness is false. `surrogate` mode may emit `max-age=60` only when the purge worker is healthy and no invalidation through the current internal cache-invalidation generation is outstanding.

Because catalog/detail vary by `Accept-Encoding`, their validators are weak and hash the exact selected representation bytes; a compressed and identity response cannot share a strong validator. The fixed identity-only PNG preview may use a strong content hash after live authorization. Every v2 failure response, including route-generated and framework-generated `404`, `405`, `416`, `422`, and `500`, uses exactly `Cache-Control: private, no-store` and exactly one `Vary: Authorization`, never a public validator or surrogate key. Install one bounded v2 response boundary after exception translation to replace rather than append these headers, and test raw ASGI headers for unknown paths, malformed queries, method/range rejection, injected internal errors, duplicate middleware values, and both token/no-token requests. No v2 error is cacheable merely because its requested resource would have been public.

Extend Task 6's fixed-global `cache_invalidation.py` helper without changing its existing call semantics. It claims outbox rows with compare-and-set, sends only unique lowercase ASCII surrogate keys matching `[a-z0-9:_-]{1,128}` in batches of at most 128 to a configured HTTPS purge endpoint with explicit timeout/no redirects, and marks delivered or schedules bounded exponential retry with jitter. Publication and direct metadata transactions now call one shared API that always retains `registry:all` and may add only reviewed typed derived keys; migration/auth code may continue requesting the fixed-global superset. The header example above is grammar, not raw interpolation: `fixed-kind`/`fixed-name` come from closed enums, while every `derived-id-key` is produced by the canonical helper. Never interpolate a legacy/public identifier directly into a key. The helper hashes the length-prefixed UTF-8 identifier with SHA-256 and uses a fixed lowercase type prefix plus the first 32 hex characters; collisions can only over-purge because every response also carries `registry:all`, never authorize or under-purge. Every public cacheable response includes that fixed Registry-wide key, so one global purge is a proven superset of every resource key without depending on a Studio client identity. Catalog responses add only `kind` plus their bounded requested channel/publisher filter keys, never one key per returned row; resource detail/preview responses may add their one hashed resource, publisher, channel, and envelope. The serializer sorts/deduplicates and rejects any response projection above 16 keys or 2 KiB before headers are emitted, while always retaining `registry:all`; raw search/filter text never becomes a key. Configuration secret is server-side/repr-hidden and never enters SQLite/logs. App lifespan drains due rows before readiness and runs one bounded worker; shutdown joins it.

Bound undelivered outbox state to 4,096 rows and 16 MiB canonical key JSON. Every transaction that changes authorization, membership, distribution, publisher, or display metadata increments internal `cache_invalidation_generation` exactly once and inserts at least `registry:all` at that value; authorization changes independently increment `authorization_generation`, and catalog membership/sort/display/download changes independently increment `catalog_generation` as applicable. Download-count-only transactions are the explicit non-security exception: they enqueue no purge and rely on max-age/revalidation. Before another mutation would exceed either outbox limit, in the same `BEGIN IMMEDIATE` as the metadata change insert one pending global-key row at the new invalidation generation, then delete/replace all older pending/failed rows only because that durable global purge supersedes them. A racing worker may perform a duplicate purge but cannot remove the global row; zero-row delivery CAS is harmless. After successful delivery, update monotonic `delivered_invalidation_generation` in `registry_meta`. `surrogate` mode is healthy only when that high-water is at least the current invalidation generation and no pending/failed row at or below it remains. Delete delivered rows older than seven days and retain at most the newest 50,000, with the high-water mark preserving health/audit convergence. Failed global purge remains durable and forces `revalidate`; never drop an invalidation merely to satisfy a size cap.

Unit tests use a fake transport for success, timeout, 4xx permanent failure, 5xx retry, duplicate delivery, worker crash/restart, concurrent claim/compaction, uppercase/dotted maximum-length legacy ID key derivation, exact row/key-byte and response-header thresholds, global-key superset replacement, crash before/after compaction commit, delivered time/count pruning, high-water recovery, catalog/display versus authorization generation ordering, download-only no-outbox plus bounded-TTL/ETag refresh, mode downgrade/recovery, and secret-safe diagnostics.

All packages use `private, no-store`. Public preview assets may use the same health-gated policy as public detail only after live envelope authorization; restricted/token-bearing previews are `private, no-store`. A conditional public GET may return `304` only after current authorization generation and visibility are revalidated. The optional 60-second surrogate mode is explicitly a bounded-staleness policy for metadata/preview bytes that were anonymous-public when cached: a withdraw/visibility change commits a purge row and immediately makes live exact/package authorization deny, but an already cached public representation may remain observable until successful purge or its declared 60-second freshness expires. Default `revalidate` mode has no positive freshness interval. Tests prove restricted bytes are never inserted into a public cache, purge convergence removes old keys, stale public package URLs cannot download, and no response or runbook claims that previously distributed public bytes can be recalled instantly.

- [ ] **Step 5: Count only completed full downloads**

HEAD, range probes, authorization failures, missing files, stream exceptions, and disconnected partial streams do not increment. A successful full GET increments after the response iterator completes and, in the same transaction, advances catalog generation only; it does not advance authorization/cache-invalidation generation, enqueue purge work, invalidate already-created immutable snapshot pages, or alter revision/package hashes. Count is a canonical integer capped at `9223372036854775807`; at the cap it saturates without advancing catalog generation and never converts to SQLite REAL or fails an otherwise completed download. Public surrogate responses may show the prior count/order for at most their declared 60-second max-age, after which ETag revalidation observes the new catalog generation. Test the iterator completion hook, max-minus-one/max saturation, a failed count transaction after bytes have streamed, concurrent increments, no-outbox behavior, and post-TTL/forced-revalidation convergence directly.

- [ ] **Step 6: Include routers and run suites**

```bash
set -euo pipefail
.venv/bin/python -m pytest tests/test_registry_exact_revision_v2.py tests/test_registry_auth_cache_v2.py tests/test_registry_cache_invalidation_v2.py tests/test_registry_previews_v2.py tests/test_registry_service.py -q
```

Expected: all pass; v1 download URLs and statuses remain unchanged.

- [ ] **Step 7: Commit**

```bash
set -euo pipefail
git add registry_service/cache_policy.py registry_service/cache_invalidation.py registry_service/previews.py registry_service/repository.py registry_service/store.py registry_service/api_v2.py registry_service/app.py tests/test_registry_exact_revision_v2.py tests/test_registry_auth_cache_v2.py tests/test_registry_cache_invalidation_v2.py tests/test_registry_previews_v2.py
git commit -m "feat(api): serve authorized exact resource revisions"
```

Run the exact v1/v2 cross-wire, cursor, authorization, cache, preview, and invalidation suites plus secret/path scans; open the `resource-catalog-v2` PR. Capability must still remain false until the later operations/readiness stage has republished and audited all approved content. Merge this PR before Task 9.

## Task 9: Repair, Deployment, And Full Security Gate

**Files:**
- Create: `registry_service/import_metadata.py`
- Create: `scripts/probe_storage_platform.py`
- Create: `scripts/check_tracked_delta_hygiene.py`
- Modify: `registry_service/repair.py`
- Modify: `registry_service/source_publication.py`
- Modify: `README.md`
- Create: `docs/resource-registry-v2-deployment.md`
- Test: `tests/test_registry_metadata_import_v2.py`
- Test: `tests/test_registry_storage_probe_v2.py`
- Test: `tests/test_registry_hygiene_v2.py`

**Verification-only existing suites:**
- `tests/test_registry_migration_v2.py`
- `tests/test_registry_envelopes_v2.py`

- [ ] **Step 1: Implement the disposable storage capability probe**

`python scripts/probe_storage_platform.py --data-dir "$DATA_DIR" --json` creates one UUID-named probe directory below the validated data root, exercises cross-process SQLite WAL/`BEGIN IMMEDIATE`, lock exclusion/timeout, file and directory fsync, hard-link or native atomic no-replace file publication, raced existing-target preservation, and shared upload/publication capacity reservations under a bounded fake budget, then removes only its own verified probe directory. It reports filesystem type, free bytes/inodes, platform, each boolean capability, and safe error code without an absolute path. Symlink/reparse roots, unsupported network filesystems, capacity-lock/reservation ambiguity, cleanup ambiguity, or any failed capability exit nonzero and leave v2 disabled. Tests inject every failure and prove no pre-existing sibling changes.

- [ ] **Step 2: Extend repair as dry-run first**

Audit the external writer-epoch record/guardian identity against DB UUID/internal epoch/state/completed-or-pending transition/fingerprint before JSON/legacy-audit migration fingerprints, DB schema/foreign keys, append-only mutation audit convergence, every revision's immutable source-package path/hash/bytes/schema, revision/dual-package/preview bindings, active-envelope uniqueness, exact one-v1/one-v2 representation cardinality for every v2-visible envelope, revoked URLs, generation monotonicity, snapshots, download counts, invalidation outbox caps/global-superset/high-water state, publication operations/assets, shared upload/publication capacity-reservation records, and filesystem objects. A missing/decremented/replaced epoch, UUID mismatch, external-ahead state without its exact DB intent, internal-ahead state, or epoch-unaware guardian keeps every writer closed; repair can report it but cannot recreate/decrement/rebind the external lineage. Only Task 6's exact matching pending-intent convergence under the live control lock may finish forward before repair plans business actions. Bind every publication reservation to one durable allocating-or-later batch plus exact immutable owner/budget; read its current version only under the capacity lock for any CAS. Classify reservations as live-upload, stale-upload-proven, allocating-publication, live-publication, publication-recoverable, or ambiguous/quarantined. Classify physical bytes without double-counting typed aliases as source-pending/source-retained, active-v1, active-v2, active-preview, retained-revoked/non-approved, prepared/recoverable, quarantined, unreferenced-source-candidate, or other unreferenced-candidate; never call a retained old envelope or committed source archive an orphan. Report count/bytes/oldest age for each class without absolute paths. Unknown reservation schema/owner, a missing or contradictory publication batch, process-identity ambiguity, or a version-CAS conflict fails write readiness. `--apply` requires `--principal-token-stdin` and an approver principal resolved through the exact Task 6 stdin-only boundary; dry-run accepts no token.

Before opening any package/file, acquiring a capacity reservation, or beginning a mutating transaction, repair builds one bounded immutable action plan from a read-only DB snapshot. The plan enumerates the complete Registry authority plus every affected current and target channel/visibility pair and publisher mapping, including indirect rows changed by revoke/republish/global repair. It authorizes that entire set atomically against the principal; any missing registry/channel/visibility/approver scope returns one generic authorization failure and performs zero partial action. Re-read the exact plan fingerprint and affected facts under the first mutation lock/transaction before applying. Apply may version-CAS release a stale upload only after dead/reused-process proof, and may ask Task 6 batch recovery to adopt an exact allocating reservation or release a publication reservation only after that batch is durably committed or safely aborted. Repair never deletes or rewrites a publication-reservation file directly. It may rebuild a projection, invoke the same global-key outbox compaction/pruning transaction, revoke a provably bad envelope, create a fresh verified dual-artifact envelope from a committed source row, and delete expired catalog snapshots; it cannot attach an unreferenced source candidate without a fresh authenticated retry, unlink source/package/preview/publication files, overwrite a package, invent a publisher, or make a non-approved revision public. Tests reject missing/extra stdin, maintainer/read/partially scoped approver tokens, argv/environment token values, mixed-scope plans, action-plan drift, and prove token/path redaction plus zero mutation on every apply failure.

Tests place valid source-pending/source-retained archives, one migrated source/v1 typed path alias, a post-publish/pre-insert unreferenced source candidate, valid revoked assets, rejected/purged revision assets, allocating batches before reservation and after reservation-before-binding, an interrupted prepared batch with a live publication reservation, a committed batch whose reservation release crashed, a stale upload with reused PID, a malformed/foreign-version reservation, a staged-before-reserved violation, a quarantined mismatch, and a truly unreferenced sentinel beside active assets. Dry-run classifies each exactly and counts shared physical bytes once. `--apply` converges only the safe allocating cases, stale upload, and committed-batch reservation through their owning protocols, preserves source candidates plus live/ambiguous publication reservations, keeps writes disabled for ambiguity, and preserves every byte and inode/file identity outside its own newly published envelope while only expired snapshot rows may disappear.

- [ ] **Step 3: Import Materials metadata through validation and approver policy**

`python -m registry_service.import_metadata --data-dir "$DATA_DIR" --metadata "$MATERIALS_EXPORT" --repository-root "$MATERIALS_CHECKOUT"` is dry-run by default. It verifies the source repository/40-character commit/inventory hash, every package byte through the same manifest/content validators, and exact kind/ID/revision/algorithm/content hash/file records. The metadata file and package tree are not read from the mutable checkout after a clean-status check: the command resolves the requested exact commit, requires it to be reachable from the configured repository, and uses bounded `git cat-file`/`git archive` plumbing with literal pathspecs and no external filters/hooks to materialize that commit's metadata plus declared archives into a new private owner-marked temporary root outside all repositories and Registry roots. It rejects submodules, symlinks, non-regular Git modes, duplicate/casefold paths, unexpected archive paths, oversized object output, commit drift, and any exported byte not identical to the commit object. The supplied metadata document must byte/hash match the document at that commit; a concurrently edited/switched checkout is irrelevant and tested. Existing no-follow root/member, manifest, hash, and path validation then runs only against the immutable materialized root.

Every revision must contain one normalized `source_archive_path`: material is beneath exactly `packages/`, LUT beneath exactly `lut-packages/`. Open the materialized repository root once as a trusted directory handle and traverse/open each archive relative to held no-follow/reparse-safe handles; reject absolute/traversal/repeated-root/wrong-domain paths, symlink/reparse/special files, missing or duplicate references, unreferenced exported package records, and any regular archive under either package root that should be in the export but is extra. Compare the still-open archive's exact bytes/full prefixed SHA and identity before parser use; no security-sensitive caller receives an unpinned absolute path. Distribution is read only from the exact exported revision record produced by Materials' `revision_distributions[kind:id:revision]`; import never copies the latest/resource-level pair onto sibling revisions or overwrites an existing revision with another record's pair. It reports publisher-map/create/update/noop/conflict/source-reuse/source-copy counts and writes nothing. It rejects authority-bearing URL, envelope, status, absolute path, token, internal ownership/publisher ID, unknown field, missing/extra/duplicate revision distribution, or mismatched identity. A shared Registry Task 9 golden test consumes the exact merged Materials export, round-trips it through this strict parser/repository proposal, and compares every revision channel/visibility pair, source archive path, and normalized package identity; Materials itself does not depend on this later parser to merge.

`--apply` requires `--principal-token-stdin`: read exactly one token with `getpass.getpass()` on a TTY or one newline-terminated value from stdin for secret-manager automation, resolve it through existing auth configuration, and immediately discard the string after creating `Principal`. Never accept a token in argv, metadata JSON, or output. Before any archive open, source publication, capacity reservation, or write transaction, parse the bounded metadata document into an immutable proposal and derive every current/target distribution pair, Registry authority, external-key mapping, publisher consolidation, attribution, approval, source-copy/reuse, and envelope mutation it could perform. Authorize the complete set once; one under-scoped item rejects the whole document with no partial package validation/publication/write. Re-read the proposal/document SHA and all affected current facts under the first mutation transaction.

For each exact revision, reuse a committed Registry source row only when its server-owned path/schema/full hash/bytes/files/core identity all match the materialized Git object. Otherwise acquire one shared upload/publication capacity reservation for source bytes plus no-replace copy/inodes/safety and invoke Task 4's `source_publication` primitive with the still-open materialized archive. The helper derives the Registry destination, copies through handles, publishes no-replace, re-opens and full-verifies, fsyncs, and commits the revision/source/files/audit row atomically before any envelope operation may reference it. The Materials `source_archive_path` is provenance input only and is never stored in `revisions.source_package_path`. A crash after source publication but before its row retains one exact `unreferenced_source_candidate`; an authenticated rerun may adopt it only after proposal, principal, source/destination handles, hashes, bytes, manifest, and deterministic destination all match. A conflicting candidate quarantines the import without overwrite/delete. After source rows commit, removing the Materials checkout/materialized temp tree cannot affect approval, recovery, readiness, repair, or package download. Envelope publication uses separate Task 6 reservations/batches and cannot begin for a revision lacking its committed source row.

Community metadata may enter pending through maintainer policy only when the entire proposal needs no approver-only operation; only an approver may create/rebind `publisher_external_keys`, consolidate legacy publisher rows, confirm `publisher_kind=lumina`, approve, or alter channel/visibility. Reusing a Materials publisher key resolves only through the existing `(source_key="lumina-materials", external_key)` mapping; equal name/brand never selects a publisher. Existing approved metadata changes publish a fresh immutable envelope batch through Task 6 instead of mutating a ZIP or record in place. Reruns are idempotent by document SHA and exact revision binding. Tests cover dry-run byte-for-byte immutability, clean-check/read checkout races, commit switch, malicious Git modes/object-size/path output, missing/extra stdin data, partial/mixed-scope rejection with no archive open or write, ordinary principal attempting publisher-key reuse/Lumina attribution, equal-name isolation, source reuse/copy, source-copy crash before/after no-replace and DB/audit commit, exact candidate retry/conflict, deletion of the Materials checkout after apply, approved multi-resource envelope rewrite, envelope crash recovery, and no secret/path in output or logs.

After import batches converge, run one read-only readiness audit over every v2-visible approved revision: committed immutable source package present and exact, reviewed metadata present, active envelope unique, exactly one v1 and one v2 package artifact present, each manifest/record/projection exact and independently installable, both normalizing to the source's same core identity, controlled preview present/bound, source/package/preview bytes and hashes valid, publisher active, and no incomplete/quarantined publication or ambiguous capacity reservation. Run the v1 artifacts through the frozen old material/LUT consumers and the v2 artifacts through the production binder fixture harness. Only an approver `--apply-ready` run whose principal includes this Registry plus the complete contract channel set `{official, community, team}` and visibility set `{official, community, team, private}` may set `v2_projection_ready=1`; narrower authority is rejected even when current rows happen to use fewer pairs. The command performs the authority-wide scope check before package/file work, then records the audited catalog/authorization generations, document SHA, and exact 40-hex Materials source commit in the same transaction as readiness. The capability attestation reads only that committed source value. Startup performs the same audit without mutation before exposing v2; a failure keeps capability false and traffic v1-only/read-only even if a stale persisted ready bit exists. A dry-run repair remains byte-for-byte non-mutating and reports the failure; only an authorized `repair --apply` or a later readiness transaction may persist `v2_projection_ready=0` and clear the active source attestation. Ordinary pending uploads do not clear readiness. Tests prove capability remains false through migration/import interruption, startup audit failure, and dry-run repair; dry-run preserves the database bytes, partial-scope readiness performs zero mutation, a stale/different Materials document cannot retain the prior attestation, and capability becomes true only after the complete audit.

- [ ] **Step 4: Document exact rollout commands**

The deployment guide must specify this exact state machine:

1. set `LUMINA_REGISTRY_MAINTENANCE_READ_ONLY=1`, restart the old writer, prove every mutation is rejected before body/storage work, drain in-flight writers, and record data-dir disk usage while v1 reads remain available;
2. run `python scripts/probe_storage_platform.py --data-dir "$DATA_DIR" --json` for local filesystem type, free/inode space, SQLite WAL/lock behavior, file and directory fsync, and atomic no-replace publication; keep v2 disabled on unsupported/network storage;
3. stop the service, verify no process holds the data/package/public roots, and copy the full data directory outside the release path with manifest hashes;
4. configure the stable non-secret Registry authority ID, dedicated secret-manager-provided auth-HMAC and cursor secrets, owner-only token-free credentials policy, and an owner-only writer-epoch control path on a separately retained volume outside the checkout plus every Registry data/package/public/backup/release root; install/verify the supervisor guardian that refuses epoch-unaware old binaries after selection; configure scoped token environment values before any migrated service start and validate exact mappings/key separation without printing policy/epoch paths, environment names, or secrets; prove Studio `source_registry` values are not upstream auth claims;
5. run `python -m registry_service.migrate_v2 --data-dir "$DATA_DIR"`, review counts/hashes, then run `python -m registry_service.migrate_v2 --data-dir "$DATA_DIR" --apply` to rebuild the final SQLite shadow from the frozen JSON source;
6. while still stopped and read-only, finalize/checkpoint the candidate, run `python -m registry_service.migrate_v2 --data-dir "$DATA_DIR" --initialize-writer-epoch`, then `python -m registry_service.migrate_v2 --data-dir "$DATA_DIR" --commit-sqlite-writer`; verify external/internal epoch 1, exact DB UUID/transition/fingerprint, `writer_backend=sqlite`, `post_migration_write_admitted=0`, guardian enforcement, and no supported command can restore the epoch/marker to JSON. Take/hash one stopped post-marker SQLite checkpoint backup carrying that same UUID/epoch/transition; after this point the earlier JSON backup is rehearsal/disaster evidence only and cannot be started as a writer;
7. start with `LUMINA_REGISTRY_ENABLE_V2=0` and maintenance read-only still enabled; smoke v1 catalog/download/install with an unchanged pre-v2 Studio build and prove all v1 mutations remain closed;
8. keep production untouched and perform two disposable rehearsals: restore the original JSON backup and start the old build read-only only inside an isolated copy with no production epoch file; separately restore the exact post-marker SQLite checkpoint while a copied epoch-1 record/guardian binds the same DB UUID and pass v1 smoke. Discard both copies. The latter exact SQLite checkpoint is the only production restore accepted before epoch 2, and it never reopens JSON;
9. require `MATERIALS_CHECKOUT` to contain the exact merged commit and `MATERIALS_EXPORT` to be an operator-owned output path outside all checkouts and Registry roots. Record `MATERIALS_COMMIT=$(git -C "$MATERIALS_CHECKOUT" rev-parse HEAD)` as exact 40-hex and generate with `(cd "$MATERIALS_CHECKOUT" && .venv/bin/python scripts/export_registry_metadata.py --source-commit "$MATERIALS_COMMIT" --output "$MATERIALS_EXPORT")`; both exporter and importer materialize only that Git object tree. Run import dry-run, explicitly acknowledge that apply first writes the DB `enter_roll_forward` intent and advances the external writer epoch to 2 before any source open/reservation/business mutation, then run authenticated `--apply`. Converge internal epoch/flag 1 before retrying the authorized source/envelope transaction; recover every source/publication batch and from the external epoch advance onward operate roll-forward-only even if the first business transaction fails;
10. rerun v1 catalog/download/install smoke, run `python -m registry_service.import_metadata --data-dir "$DATA_DIR" --metadata "$MATERIALS_EXPORT" --repository-root "$MATERIALS_CHECKOUT"` again as the read-only full readiness audit, review exact counts/hashes, then run `python -m registry_service.import_metadata --data-dir "$DATA_DIR" --metadata "$MATERIALS_EXPORT" --repository-root "$MATERIALS_CHECKOUT" --apply-ready --principal-token-stdin` with authority-wide distribution scopes;
11. start with v2 enabled but maintenance read-only still set; keep public cache mode at `revalidate`, or configure/test the HTTPS surrogate purge backend, Authorization bypass, key invalidation, outbox health, and only then select `surrogate`; smoke capability/catalog/detail/preview/exact package for both domains and all success/error cache headers;
12. explicitly reopen HTTP writes by clearing maintenance mode and restarting once; perform one canary SQLite mutation through the approved API, require `post_migration_write_admitted=1` to remain durable, and verify publication/audit/cache convergence before wider traffic;
13. after Step 9 advances external epoch 2, the system is roll-forward-only regardless of whether the first import business transaction committed: rollback may disable v2 projections and re-enable maintenance read-only, but must keep the SQLite lineage/epoch, run repair, and deploy a corrected build; every startup/CLI refuses JSON fallback, epoch decrement, or older-backup automation;
14. document incident evidence and ownership for incomplete publication, invalidation, repair, and backup retention; never delete the SQLite DB, package roots, or old backup while the service runs.

- [ ] **Step 5: Run full tests and validators**

```bash
set -euo pipefail
.venv/bin/python -m pytest tests -q
REHEARSAL_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/lumina-registry-v2.XXXXXX")
printf '%s\n' 'lumina-registry-v2-rehearsal-v1' > "$REHEARSAL_ROOT/.owner"
cleanup_registry_rehearsal() {
  test "$(cat "$REHEARSAL_ROOT/.owner")" = 'lumina-registry-v2-rehearsal-v1'
  case "$(basename "$REHEARSAL_ROOT")" in lumina-registry-v2.??????) ;; *) return 1 ;; esac
  rm -rf -- "$REHEARSAL_ROOT"
}
trap cleanup_registry_rehearsal EXIT
.venv/bin/python scripts/probe_storage_platform.py --data-dir "$REHEARSAL_ROOT/probe" --json
.venv/bin/python -m registry_service.migrate_v2 --data-dir "$REHEARSAL_ROOT/migration"
```

Expected: tests/probe pass, the probe removes its own directory, and migration dry-run exits `0` and writes no DB.

- [ ] **Step 6: Scan tracked files and content**

Implement `scripts/check_tracked_delta_hygiene.py --base origin/master` with the same base-blob versus HEAD-blob semantics frozen by its tests: NUL-safe changed tracked entries only, forbidden runtime/config pathnames, and only newly introduced token/private-key/concrete-home/current-checkout findings. It never walks untracked/ignored agent state, compares rename/copy sources and per-rule finding multisets, bounds decoding/object size, and allows binary fixture ZIPs only on exact validated paths. Existing target-branch findings cannot fail or whitelist the PR. `tests/test_registry_hygiene_v2.py` covers every rule, baseline finding, rename/copy/delete, malicious filename, non-ancestor base, oversized/binary/symlink/special entry, and scanner self-match.

```bash
set -euo pipefail
git diff --check origin/master...HEAD
python scripts/check_tracked_delta_hygiene.py --base origin/master
```

Expected: no runtime/private/machine-local match. The scanner rejects concrete user/root home paths while its source and tests construct policy prefixes and positive samples from segments, so bare documented prefixes do not self-match. Literal environment-variable names in docs are acceptable only without assigned secret values.

- [ ] **Step 7: Commit and open the Registry operations/readiness PR**

```bash
set -euo pipefail
git add registry_service/import_metadata.py registry_service/repair.py registry_service/source_publication.py scripts/probe_storage_platform.py scripts/check_tracked_delta_hygiene.py tests/test_registry_metadata_import_v2.py tests/test_registry_storage_probe_v2.py tests/test_registry_hygiene_v2.py README.md docs/resource-registry-v2-deployment.md
git commit -m "docs(registry): add v2 migration and recovery runbook"
```

The PR body must include exact base/head, migration rehearsal evidence, v1 no-limit evidence, cursor/auth/cache matrix, concurrency result, fixture commit, and secret scan. Request exact-head independent review before merge.

- [ ] **Step 8: Re-run the release gate on the committed exact head**

After the Step 7 commit, rerun the complete Step 5 test/probe/migration block and Step 6 tracked/content scan verbatim, then require:

```bash
set -euo pipefail
git diff --check origin/master...HEAD
test -z "$(git status --short --untracked-files=no)"
```

Expected: the committed head, not the pre-commit worktree, passes every gate and the tracked tree is clean. Any formatter, generated file, documentation correction, or follow-up fix creates a new head and invalidates prior rollout evidence.

## Registry Merge Gate

Do not merge until all of the following are true:

- Fixture PR is merged and downstream repositories can vendor exact bytes.
- v1 routes pass old and new contract tests with no changed default or field.
- SQLite migration is dry-run by default, idempotent, fingerprint-guarded, backed up, and failure-injection tested.
- Online routes remain JSON through the storage PR; Task 6 alone performs the maintenance-gated final rebuild and one-way writer transition. The external epoch reaches `sqlite_selected` before SQLite service use and reaches `roll_forward_only` before the first authoritative source open, capacity reservation, or business mutation, so even a failed first operation permanently closes the epoch-1 restore window.
- The external writer-epoch record is owner-only, monotonic, separately retained outside all data/package/public/backup/release roots, bound to DB UUID/transition/fingerprint, and enforced by a supervisor guardian that rejects epoch-unaware or old binaries; restored/missing/decremented/mismatched state keeps every writer closed.
- Before epoch 2, only the exact stopped post-marker SQLite checkpoint with the matching external epoch-1 lineage is restorable; the original JSON backup is disposable rehearsal evidence only and no supported startup, CLI, repair, or automation can reopen it as a writer.
- authorization policy/HMAC identity is initialized before writer cutover and cannot rotate or mutate generations while SQLite/flag-zero preserves backup restoration.
- SQLite/repository mutations require stable authority/auth-HMAC/token-free owner-only policy configuration; legacy process-random actor IDs never establish durable ownership or policy continuity.
- Every approved revision has at most one active immutable envelope; prior URLs are inaccessible.
- Opaque random cursor handles reveal none of domain/principal/query/generation facts; the bounded server snapshot binds all of them plus sort/limit/position/expiry and enforces ordered replay.
- Authenticated/restricted/package responses are never public-cacheable; default public mode revalidates every use, and optional surrogate mode limits once-public metadata/preview staleness to successful purge or 60 seconds while live exact/package authorization already denies.
- Every v2 error is `private, no-store` with one `Vary: Authorization`; v2 package/preview HEAD is 405 and Range is 416, while frozen v1 HEAD/Range behavior is unchanged.
- after non-disclosure lookup, method dispatch precedes Range policy so HEAD+Range is always 405 and only GET+Range is 416.
- Task 6 invalidation state is a bounded fixed-global superset; Task 8 extends the same helper without an unbounded key/row window.
- Unknown, unauthorized, revoked, and non-approved exact revisions are externally indistinguishable.
- Package download revalidates authorization/envelope/hash/bytes and does not redirect.
- Publisher cannot be inferred from channel/path and ordinary upload cannot claim `lumina`.
- Publisher-wide changes use explicit internal/external-key mappings, atomically switch all affected envelopes, and never group equal display names.
- Multipart upload limits apply before form parsing, count actual chunked bytes, time out stalled receives, stage only under the validated data root, and leave no spool/staging/pending state on failure.
- Capability remains false until metadata/envelope/preview readiness audit records `v2_projection_ready=1` with no incomplete publication batch.
- capability attests the exact Registry build and fully audited Materials source commits; neither value can come from request input or a partial import.
- Concurrency tests show no lost update, duplicate active envelope, or mixed record/package projection.
- every repair/import apply derives and atomically authorizes its complete current/target distribution/publisher set before package or write work; readiness requires authority-wide approver scopes, and no CLI accepts a token value in argv/environment output.
- Materials export and Registry import independently materialize the same explicit 40-hex source commit through bounded Git-object reads; mutable checkout, index, branch, filter, hook, or smudge output cannot affect imported package bytes or attested provenance.
- metadata import opens each exact Materials `source_archive_path` relative to one held private materialized-root handle and rejects missing/duplicate/extra/wrong-root/symlink/non-regular archives.
- every imported revision commits or safely retry-adopts one fully verified server-owned source package through the no-replace/fsync/source-row-audit protocol; `source_archive_path` is provenance only, never the stored `source_package_path`, and deleting the Materials checkout cannot affect readiness, repair, approval, or download.
- Full tests, diff check, runtime-file scan, token scan, and deployment rehearsal pass.
