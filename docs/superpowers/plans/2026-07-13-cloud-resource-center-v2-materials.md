# Cloud Resource Center V2 Materials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Lumina Materials a deterministic, explicit-metadata source for future material 2.1 and LUT 2.0 packages while preserving every existing package byte and classifying unconfirmed historical content as community shared.

**Architecture:** Vendor Registry's exact contract fixtures, centralize package/path/hash primitives inside this content repository, and make both builders consume one explicit metadata inventory. Existing immutable archives remain unchanged; metadata is exported for Registry envelope publication, while only new content revisions use the new schemas and canonical hash declarations.

**Tech Stack:** Python 3, JSON, `zipfile`, NumPy-compatible LUT source files, pytest, repository validation scripts.

---

## Repository And Branch

Repository: `lumina-layer-studio/Lumina-materials`

Required base: `master@163103130c531260bc58ba5c913cc856f1808dea`

Branch: `codex/feat/resource-package-metadata-v2`

Start only after Registry's `codex/feat/resource-contract-fixtures-v2` PR is merged. Record that exact Registry commit in `UPSTREAM.json`; never use a moving branch name as fixture provenance.

## Immutable Content Rule

The current collection contains 174 material packages and 67 LUT packages. Do not rewrite, rename, recompress, delete, or replace any checked-in ZIP. Existing LUT schema 1.0 keeps its filename-plus-file-hash identity. Existing material schema 2.0 keeps its current canonical identity.

For an existing core revision that only needs publisher/title/visibility metadata, export metadata for Registry to create a new immutable envelope. Do not create a second package in this repository with the same `(kind, resource_id, revision_id)` and different bytes. A new material 2.1 or LUT 2.0 archive is emitted only when source core bytes produce a new revision identity or when an explicit new opaque revision ID is supplied by the release workflow.

## File Structure

- Create `scripts/package_contract.py`
  - Shared safe-path, hash, deterministic ZIP, special-entry, limits, and file-record helpers used by both builders.
- Create `scripts/resource_metadata.py`
  - Load, validate, derive, and export explicit metadata without inferring publisher ownership from paths/channels/brands.
- Create `scripts/sync_registry_fixtures.py`
  - Copy exact upstream fixture bytes only when Registry commit and SHA manifest are supplied.
- Create `scripts/export_registry_metadata.py`
  - Produce a deterministic Registry import document for existing revisions.
- Create `scripts/check_repository_hygiene.py`
  - Tracked-file and content scan for runtime/private/machine-local artifacts.
- Create `schemas/resource-metadata-v2.schema.json`
  - Human-readable JSON schema for the metadata inventory.
- Create `manifests/resource-metadata-v2.json`
  - One explicit record for every material/LUT logical resource in the package collection.
- Create `tests/fixtures/registry-contract-v2/**`
  - Byte-identical Registry fixtures plus `UPSTREAM.json`.
- Create `tests/test_registry_contract_fixtures.py`
- Create `tests/test_resource_metadata_v2.py`
- Create `tests/test_package_determinism_v2.py`
- Create `tests/test_repository_hygiene.py`
- Modify `scripts/material_bundle.py`
  - Preserve 2.0 validation; build new revisions as 2.1 using explicit algorithm and metadata.
- Modify `scripts/lut_bundle.py`
  - Preserve 1.0 validation; build new revisions as 2.0 using raw LUT bytes for canonical content hash.
- Modify `scripts/build_packages.py` and `scripts/build_lut_packages.py`
  - Load metadata, enforce immutable identity collision checks, support check-only mode.
- Modify `scripts/validate_packages.py` and `scripts/validate_lut_packages.py`
  - Report schema counts and cross-check metadata inventory.
- Create `CONTRIBUTING.md`
  - Public manufacturer/user sharing workflow, metadata checklist, review semantics, and validation gates without private credentials.
- Modify `README.md`
  - Explain community/official publisher semantics, immutable archives, metadata workflow, and validation commands.

## Task 1: Vendor Registry Fixtures With Provenance

**Files:**
- Create: `scripts/sync_registry_fixtures.py`
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
- Create: `tests/test_registry_contract_fixtures.py`

- [ ] **Step 1: Write the failing upstream provenance test**

Require this shape:

```python
def test_upstream_fixture_manifest_is_exact() -> None:
    upstream = json.loads((FIXTURE_ROOT / "UPSTREAM.json").read_text("utf-8"))
    assert upstream["repository"] == "lumina-layer-studio/Lumina-material-registry"
    assert re.fullmatch(r"[0-9a-f]{40}", upstream["commit"])
    assert upstream["source_path"] == "tests/fixtures/contracts/v2"
    assert upstream["checksum_manifest_sha256"] == sha256_file(
        FIXTURE_ROOT / "SHA256SUMS.json"
    )
    assert set(upstream["files"]) == set(load_sha_manifest())
    for relative_path, expected_sha in upstream["files"].items():
        assert sha256_file(FIXTURE_ROOT / relative_path) == expected_sha
```

The test requires `checksum_manifest_sha256` to be one lowercase raw 64-hex digest and compares the vendored `SHA256SUMS.json` bytes plus every listed payload to `UPSTREAM.json`, so a locally edited fixture cannot be blessed by changing only one checksum layer.

- [ ] **Step 2: Run and verify failure**

```bash
.venv/bin/python -m pytest tests/test_registry_contract_fixtures.py -v
```

Expected: FAIL because the fixture directory is absent.

- [ ] **Step 3: Implement an explicit sync command**

The CLI accepts `--registry-checkout`, `--registry-commit`, and `--output`. It verifies `git -C "$REGISTRY_CHECKOUT" rev-parse HEAD` equals the requested 40-character commit, reads and hashes upstream `SHA256SUMS.json`, copies that manifest plus only its listed regular files, verifies every copied byte, writes its raw digest as `checksum_manifest_sha256` in `UPSTREAM.json` atomically, and refuses a dirty upstream fixture directory.

It never performs network access, never accepts a branch name, and never stores the absolute checkout path in the output.

- [ ] **Step 4: Vendor and validate exact bytes**

```bash
REGISTRY_CHECKOUT=../Lumina-material-registry
REGISTRY_FIXTURE_COMMIT=$(git -C "$REGISTRY_CHECKOUT" rev-parse HEAD)
.venv/bin/python scripts/sync_registry_fixtures.py \
  --registry-checkout "$REGISTRY_CHECKOUT" \
  --registry-commit "$REGISTRY_FIXTURE_COMMIT" \
  --output tests/fixtures/registry-contract-v2
.venv/bin/python -m pytest tests/test_registry_contract_fixtures.py -q
```

Expected: the test passes and `UPSTREAM.json` contains only repository, commit, source-relative path, and file SHA values.

- [ ] **Step 5: Commit**

```bash
git add scripts/sync_registry_fixtures.py tests/fixtures/registry-contract-v2/UPSTREAM.json tests/fixtures/registry-contract-v2/accepted/material-v2.zip tests/fixtures/registry-contract-v2/accepted/material-v2-v1-envelope.zip tests/fixtures/registry-contract-v2/accepted/lut-legacy-v1.zip tests/fixtures/registry-contract-v2/accepted/lut-v2.zip tests/fixtures/registry-contract-v2/accepted/lut-v2-v1-envelope.zip tests/fixtures/registry-contract-v2/accepted/lut-v2-community-envelope.zip tests/fixtures/registry-contract-v2/rejected/path-traversal.zip tests/fixtures/registry-contract-v2/rejected/casefold-collision.zip tests/fixtures/registry-contract-v2/rejected/symlink.zip tests/fixtures/registry-contract-v2/rejected/file-hash-mismatch.zip tests/fixtures/registry-contract-v2/rejected/record-binding-mismatch.zip tests/fixtures/registry-contract-v2/rejected/manifest-too-large.zip tests/fixtures/registry-contract-v2/rejected/manifest-duplicate-key.zip tests/fixtures/registry-contract-v2/rejected/manifest-depth-overflow.zip tests/fixtures/registry-contract-v2/rejected/npy-header-overflow.zip tests/fixtures/registry-contract-v2/rejected/npz-inner-bomb.zip tests/fixtures/registry-contract-v2/EXPECTED.json tests/fixtures/registry-contract-v2/SHA256SUMS.json tests/test_registry_contract_fixtures.py
git commit -m "test(contracts): vendor registry v2 package fixtures"
```

## Task 2: Shared Package Contract And Validator Parity

**Files:**
- Create: `requirements-dev.txt`
- Create: `scripts/package_contract.py`
- Modify: `scripts/material_bundle.py`
- Modify: `scripts/lut_bundle.py`
- Test: `tests/test_registry_contract_fixtures.py`
- Test: `tests/test_package_manifest.py`
- Test: `tests/test_lut_package_manifest.py`

- [ ] **Step 1: Add cross-validator fixture tests**

Run every accepted Registry fixture through the correct Materials validator and assert the complete normalized record equals vendored `EXPECTED.json`. Run each rejected fixture and assert the expected stable rejection category. Legacy LUT v1 must expose both its legacy hash and canonical v2 raw-file hash without changing the manifest field.

- [ ] **Step 2: Verify the tests detect current drift**

```bash
.venv/bin/python -m pytest tests/test_registry_contract_fixtures.py -k validator -v
```

Expected: at least material 2.1/LUT 2.0 or a hardened unsafe fixture fails before the shared contract is implemented.

- [ ] **Step 3: Implement the shared primitives**

Create these stable APIs in `scripts/package_contract.py`:

```python
MATERIAL_HASH_ALGORITHM = "lumina-material-required-files-v1"
LUT_HASH_ALGORITHM = "lumina-lut-file-bytes-v1"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
LUT_FILE_EXTENSIONS = frozenset({".json", ".npy", ".npz", ".msgpack"})
_HEX64 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 64 * 1024 * 1024
    max_entries: int = 128
    max_member_bytes: int = 64 * 1024 * 1024
    max_expanded_bytes: int = 128 * 1024 * 1024
    max_compression_ratio: int = 200


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


def canonical_material_hash(material_payload: bytes, stage_payload: bytes) -> str:
    material_sha = hashlib.sha256(material_payload).hexdigest()
    stage_sha = hashlib.sha256(stage_payload).hexdigest()
    identity = (
        f"material.json:{material_sha}\n"
        f"stage_A_parameters.json:{stage_sha}"
    ).encode("ascii")
    return sha256_prefixed(identity)


def canonical_lut_hash(payload: bytes) -> str:
    return sha256_prefixed(payload)
```

Also provide `safe_zip_path`, `is_local_only`, `reject_special_entry`, `scan_archive`, and `write_deterministic_member`. Paths canonicalize to NFC POSIX form, cap segments at 255 UTF-8 bytes and the whole path at 512, and reject absolute/drive/UNC/dot/empty segments, NUL/control/backslash ambiguity, colons/NTFS alternate streams, trailing dot/space, and Windows device basenames including extensions. Duplicate detection covers raw names plus NFC `casefold()`; payload entries must be declared; only regular files/directories are accepted. Do not add a permissive `normalize_sha256`: new-schema validators must call `require_raw_sha256` or `require_prefixed_sha256` according to the field matrix, while legacy representation handling remains isolated in the v1 validator/adapter.

Copy Registry's manifest-specific parser boundary and master counting semantics exactly into the shared primitives: UTF-8 JSON at most 1 MiB; decoder-time rejection of BOM/non-UTF-8, non-finite constants, and duplicate raw object keys; then a pre-model walk capped at depth 12, 8,192 aggregate nodes, 2,048 aggregate object keys, 1,024 items in one array, 128 UTF-8 bytes per key, and 4,096 UTF-8 bytes per string. Root depth/node is 1, every JSON value including null/bool counts one node, keys count only toward the key total, and byte lengths use strict decoded UTF-8. The walk rejects NFC/casefold-colliding keys within one object, while schema-specific field limits remain tighter. Return the same stable `manifest_too_large`, `manifest_duplicate_key`, and `manifest_structure_invalid` categories, exercise exact and one-over boundaries in both package validators, and use vendored Registry rejected fixtures so a content repository cannot publish a manifest that Registry or Studio would reject.

Encode the same archive/runtime path bijection in builders and validators. For material `local_directory=D`, require archive members `materials/{D}/material.json` and `materials/{D}/stage_A_parameters.json` with the exact roles, and define their Studio revision paths as the two basenames. For LUT `local_path=P`, require the sole payload member `luts/{P}` and define its revision path as `basename(P)`. Reject duplicated `materials/`, `luts/`, `lut-preset/`, or `Cloud/` prefixes and any logical/member/role mismatch. `files[].path` always remains the archive member path; no metadata input supplies the revision-relative destination.

Preserve the 174 existing material 2.0 archives by accepting their frozen bundle-manifest top-level `material_count=1` plus optional nonempty opaque `exported_at` of at most 128 UTF-8 bytes alongside `kind/schema_version/packages`; all current archives contain both. When present, require the count to equal the exact one-package cardinality and permit `exported_at` only with that legacy count. Preserve its spelling without parsing/normalizing it and exclude both fields from canonical content identity and reviewed discovery metadata. Material 2.1 and a schema-2.0 compatibility artifact derived from it omit both fields. Separately classify the one top-level `lumina_material_export.json` as schema-owned auxiliary metadata rather than undeclared payload. Require `kind="lumina_material_export"`, `schema_version="1.0"`, `material_count=1`, and exactly one `directory_names` entry equal to `D`; parse it through the same 1 MiB safe JSON helper, preserve its own optional historical `exported_at` spelling under the same 128-byte bound without normalizing it, and exclude it from canonical content hash and exported `files[]`. Material 2.1 builders emit the descriptor with those deterministic fields but no `exported_at`, so unchanged v1 Studio imports remain valid without introducing a wall-clock build input. Apart from the domain manifest and this material-only descriptor, every regular member must appear exactly once in `files[]`; LUT packages have no auxiliary exception. Tests run all 174 material and 67 LUT packages through these exact rules before regeneration.

- [ ] **Step 4: Make both validators consume the shared primitives**

Material validator accepts 2.0 and 2.1, with 2.1 requiring `content_hash_algorithm`. LUT validator accepts 1.0 and 2.0; 1.0 verifies its legacy filename-based hash and calculates `canonical_content_hash`, while 2.0 requires the raw-byte algorithm/hash. Mirror Registry's NPY-header and NPZ-inner-directory allocation preflight plus bounded JSON/msgpack rules before any production loader call; vendored malicious inner-archive/header cases must produce the same rejection category. Preserve existing public function names and return keys used by scripts/tests.

Create `requirements-dev.txt` with the repository's explicit test/validator runtime (`pytest>=8,<9`, NumPy, and msgpack) and require CI/maintainer validation to install it. Missing NumPy/msgpack is a setup failure reported before package scanning, never a per-resource skip or `content_unloadable` result. Keep this content repository independent of Studio/Registry application dependencies.

Require new/v2 aggregate `content_hash` and exported `package_sha256` to be lowercase `sha256:` plus 64 hex with no surrounding whitespace; keep every `files[].sha256` and `UPSTREAM.json`/`SHA256SUMS.json` checksum as lowercase raw 64-hex. Existing package/v1 validator return fields retain their historical encoding; expose separate explicitly named normalized v2 fields rather than changing an old key. Treat `legacy_content_hash` as opaque schema output and never compare it to the canonical LUT bytes hash without the legacy adapter. Add tests proving uppercase, whitespace, raw-vs-prefixed swaps, and duplicate prefixes are rejected rather than silently rewritten.

- [ ] **Step 5: Run parity and old-package validation**

```bash
.venv/bin/python -m pytest tests/test_registry_contract_fixtures.py tests/test_package_manifest.py tests/test_lut_package_manifest.py -q
.venv/bin/python scripts/validate_packages.py --packages packages
.venv/bin/python scripts/validate_lut_packages.py --packages lut-packages
```

Expected: tests pass and counts remain exactly 174 materials and 67 LUTs.

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.txt scripts/package_contract.py scripts/material_bundle.py scripts/lut_bundle.py tests/test_registry_contract_fixtures.py tests/test_package_manifest.py tests/test_lut_package_manifest.py
git commit -m "refactor(packages): align validators with registry contracts"
```

## Task 3: Explicit Resource Metadata Inventory

**Files:**
- Create: `schemas/resource-metadata-v2.schema.json`
- Create: `scripts/resource_metadata.py`
- Create: `manifests/resource-metadata-v2.json`
- Test: `tests/test_resource_metadata_v2.py`

- [ ] **Step 1: Write inventory completeness and semantics tests**

Build the expected key set from all validated packages as `material:{material_id}` and `lut:{lut_id}`. Assert the inventory has exactly that set, no duplicate ID, no missing resource, and no unreferenced resource. Every record must have non-empty `publisher_key`, `publisher_name`, `title`, `summary`, `brand`, normalized tags, a bounded explicit compatibility object, and explicit validated `channel`/`visibility` distribution values.

Assert all existing LUT records use `publisher_kind="community"`, `channel="community"`, and `visibility="community"`. Assert any record with `publisher_kind="lumina"` also has `lumina_approval.reference` and `lumina_approval.approved_at`; do not infer approval from `official/`, channel, visibility, brand, filename, or source directory. A community publisher may retain a legacy public material distribution channel; tests prove channel never changes the source badge.

- [ ] **Step 2: Define the inventory schema**

Use this stable top-level structure:

```json
{
  "schema_version": "2.0",
  "generated_from": {
    "material_package_count": 174,
    "lut_package_count": 67
  },
  "resources": {
    "lut:lut_example": {
      "resource_kind": "lut",
      "resource_id": "lut_example",
      "publisher_key": "legacy-0123456789abcdef01234567",
      "publisher_kind": "community",
      "publisher_name": "Lumina Community",
      "title": "Example LUT",
      "summary": "Community-shared LUT for 4-Color RYBW workflows.",
      "brand": "Example",
      "tags": ["LUT", "4-Color RYBW"],
      "compatibility": {"color_modes": ["4-color-rybw"]},
      "channel": "community",
      "visibility": "community",
      "source_policy": "existing_repository_content"
    }
  }
}
```

`publisher_key` is a repository-local opaque slug used only for an explicitly reviewed Registry publisher mapping; it is not a badge or proof by itself. `publisher_name="Lumina Community"` is a neutral migration label, not an ownership claim. Brand remains a separate display/search field. Future contributors must supply their explicit publisher key and display name in metadata.

- [ ] **Step 3: Implement deterministic inventory generation**

`resource_metadata.py bootstrap` reads validated package display/compatibility/distribution facts only. It sets every unconfirmed publisher to community and assigns a unique per-resource key using `legacy-` plus the first 24 hex characters of SHA-256 over UTF-8 `resource_kind + ":" + resource_id`; equal names therefore never group ownership. It derives title from explicit display title/name then logical filename, derives brand from display manufacturer/brand then `Unknown brand`, creates a factual kind/compatibility summary, and sorts keys/tags. Existing LUT distribution is normalized explicitly to `community/community`; material channel/visibility is copied only from the validated immutable manifest and remains independent of publisher kind. It never sets `lumina`, rewrites package bytes, or treats brand/channel/path as publisher.

The loader normalizes metadata to NFC and enforces the cross-repository UTF-8 byte limits exactly: publisher/title/brand `1..128`, summary `0..1024`, at most 32 unique casefold-safe tags of `1..64`, and JSON-only compatibility depth `4`, aggregate nodes `128`, keys `64`, key bytes `64`, and string-value bytes `256`. Strict numeric compatibility values must be finite integers/floats with absolute value at most `1_000_000_000`, and booleans must not pass an integer branch. Every new approval/group/source timestamp uses the master contract's exact `YYYY-MM-DDTHH:MM:SSZ` UTC form with a valid `1970..9999` date; offsets, fractions, leap seconds, impossible dates, and whitespace are rejected rather than normalized. It rejects empty required strings, HTML/script content, control/bidi-override characters, dedicated external preview/package/authority URL fields, unknown fields, duplicate normalized keys/tags, out-of-range/non-finite numbers, unsupported publisher kind, unsupported channel/visibility, malformed publisher key, and mismatched kind/ID; plain summary text is never interpreted as HTML or an executable link. Publisher keys are 1-64 lowercase ASCII characters matching `[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?`. The checked-in v2.0 `channel` allowlist is exactly `official`, `community`, and `team`; the `visibility` allowlist is exactly `official`, `community`, `team`, and `private`. A record is ordinary public content only when both values are official/community. Any other allowed pair is restricted, including design `team/private` and historical `team/team`; metadata tooling preserves that exact pair and never normalizes `private` to `team` or changes publisher attribution. Multiple records may share a publisher key only when kind/name are identical and a checked-in `publisher_group_approval` gives a nonempty public reference plus approval timestamp; `lumina` additionally requires `lumina_approval`. The Registry still independently authorizes and records the external-key mapping and may apply an approver-reviewed envelope policy without changing source package bytes.

- [ ] **Step 4: Generate and review the complete inventory**

```bash
.venv/bin/python -m scripts.resource_metadata bootstrap \
  --materials packages \
  --luts lut-packages \
  --output manifests/resource-metadata-v2.json
.venv/bin/python -m pytest tests/test_resource_metadata_v2.py -q
```

Expected: all 241 package entries map to their logical resource keys; every current LUT is community publisher plus community channel/visibility; no empty user-facing or distribution metadata remains.

- [ ] **Step 5: Commit**

```bash
git add schemas/resource-metadata-v2.schema.json scripts/resource_metadata.py manifests/resource-metadata-v2.json tests/test_resource_metadata_v2.py
git commit -m "feat(metadata): declare resource publisher and discovery fields"
```

## Task 4: New-Schema Deterministic Builders Without Archive Mutation

**Files:**
- Modify: `scripts/material_bundle.py`
- Modify: `scripts/lut_bundle.py`
- Modify: `scripts/build_packages.py`
- Modify: `scripts/build_lut_packages.py`
- Create: `tests/test_package_determinism_v2.py`

- [ ] **Step 1: Write failing deterministic-build tests**

For a new material revision and each allowed LUT extension, build twice in separate roots with different source mtimes, `TZ`, locale, and `PYTHONHASHSEED`, then assert exact ZIP bytes match. Assert material output schema is 2.1 with `content_hash_algorithm=lumina-material-required-files-v1`; LUT output schema is 2.0 with raw-file canonical hash. At first creation, assert the immutable manifest's proposed display snapshot matches the then-current inventory, package paths are POSIX relative, and no wall-clock time, checkout path, hostname, locale, or random iteration order enters the archive. Then change only title/publisher/display/channel/visibility metadata in a copied inventory and assert the existing archive remains valid/unchanged, `--check` reports metadata-envelope drift rather than package conflict, and the export carries the new reviewed proposal against the same source package SHA/revision.

For existing material 2.0 and LUT 1.0 identities, rerun the full builders against unchanged source and assert they validate core payload parity, report `legacy_existing`, and leave every archive byte/mtime unchanged rather than attempting to emit the new schema under the old revision. Change one source payload while retaining the old revision and assert the builder refuses with `new revision required`. Pre-create a new-schema archive with the same kind/ID/revision but different bytes and assert exact deterministic collision refusal without changing either file.

- [ ] **Step 2: Verify current material nondeterminism and schema failures**

```bash
.venv/bin/python -m pytest tests/test_package_determinism_v2.py -v
```

Expected: FAIL because the material builder uses current timestamps/schema 2.0 and LUT builds schema 1.0.

- [ ] **Step 3: Implement manifest constructors**

Material 2.1 archives contain exactly one package record with algorithm, canonical hash, channel, visibility, local directory, display/compatibility, and exactly one required record for each material role. LUT 2.0 archives contain exactly one LUT record with algorithm, raw-byte hash, one LUT role, local path without `lut-preset/` or duplicated `Cloud/`, display, and compatibility. Bulk builds emit multiple immutable archives; neither builder creates a multi-resource envelope.

Use deterministic member order: payload records sorted by normalized path, then manifest last. Open the archive with explicit `ZIP_DEFLATED`, `compresslevel=9`, and strict timestamps; every member uses the fixed timestamp/mode and canonical compact JSON uses a final newline. New manifests omit `exported_at` and every other wall-clock/build-machine field. CI's supported Python/zlib matrix runs the exact-byte test; any runtime that produces drift is rejected for publishing instead of replacing an existing revision.

Both top-level builders expose the same explicit CLI shape used by the gate: `--check`, `--source PATH`, and `--packages PATH`. Defaults remain their current repository directories for maintainer compatibility; supplied paths must be repository-relative or validated test-temp roots and may not escape through symlinks. `--check` never changes archives, manifests, source files, or mtimes.

- [ ] **Step 4: Add immutable collision handling and check-only mode**

Before writing, scan all current archives and map `(kind,id,revision)` to validated schema, package SHA, canonical core identity, immutable manifest display snapshot, and exact payload file records. For any existing legacy or new-schema key, compare current source required payload bytes/roles and canonical core identity to that immutable archive; exact core parity returns `legacy_existing` or `new_existing` without reconstructing/recompressing from the mutable metadata inventory, while any core change raises `immutable revision changed; allocate a new revision`. A display/inventory difference is reported separately as `metadata_envelope_change` and is valid input to Registry metadata export, never a package-byte conflict. An explicit reproducibility test may reconstruct a new-schema archive from the archive's own frozen manifest snapshot and must obtain byte-identical SHA; it must not substitute today's inventory. A missing key uses the new schema plus current inventory snapshot, writes to a sibling temporary file, validates, fsyncs, and performs atomic no-replace publication only to a previously absent destination.

`--check` validates existing core parity and computes only missing new-schema outputs in a temporary directory, reporting `legacy_existing`/`new_existing`/`metadata_envelope_change`/`create`/`conflict` without modifying the repository. Run the repository-wide build/check command over all 174 material and 67 LUT packages in tests and assert zero core conflict, zero archive change, and no accidental schema rewrite; metadata-envelope changes are listed deterministically and do not make the command fail.

- [ ] **Step 5: Run tests and prove existing bytes did not change**

Before implementation, save tracked ZIP hashes outside the repo:

```bash
git ls-files -z 'packages/*.zip' 'packages/**/*.zip' 'lut-packages/*.zip' 'lut-packages/**/*.zip' | xargs -0 shasum -a 256 > /tmp/lumina-materials-before.sha256
```

After implementation:

```bash
.venv/bin/python -m pytest tests/test_package_determinism_v2.py tests/test_package_manifest.py tests/test_lut_package_manifest.py -q
.venv/bin/python scripts/build_packages.py --check --source materials-src --packages packages
.venv/bin/python scripts/build_lut_packages.py --check --source luts-src --packages lut-packages
git ls-files -z 'packages/*.zip' 'packages/**/*.zip' 'lut-packages/*.zip' 'lut-packages/**/*.zip' | xargs -0 shasum -a 256 > /tmp/lumina-materials-after.sha256
diff /tmp/lumina-materials-before.sha256 /tmp/lumina-materials-after.sha256
```

Expected: tests pass; both check commands report 174/67 existing identities with zero conflict/create; `diff` prints nothing.

- [ ] **Step 6: Commit**

```bash
git add scripts/material_bundle.py scripts/lut_bundle.py scripts/build_packages.py scripts/build_lut_packages.py tests/test_package_determinism_v2.py
git commit -m "feat(packages): build immutable material and LUT v2 revisions"
```

## Task 5: Registry Metadata Export

**Files:**
- Create: `scripts/export_registry_metadata.py`
- Test: `tests/test_resource_metadata_v2.py`

- [ ] **Step 1: Write an exact export-shape test**

Require top-level `source_repository="lumina-layer-studio/Lumina-materials"`, the exact 40-character source commit, inventory schema/hash, and package count. For every package revision, require one deterministic record containing kind, ID, revision, schema, canonical algorithm/hash, optional opaque legacy hash, `package_sha256`, `package_bytes`, logical path, publisher key/kind/name plus public approval references, display fields, channel, visibility, compatibility, and file records. Canonical content/package hashes use the v2 prefixed encoding; file hashes remain raw 64-hex. It must not contain package URL, token, local absolute path, Registry approval status, ownership key, internal publisher ID, or active envelope ID.

Here `package_sha256/package_bytes` identify the immutable Materials source archive only. They never claim to be either Registry envelope artifact: approval revalidates this source and deterministically publishes separate v1-compatible and v2 package representations with Registry-owned paths/hashes/bytes. The export carries no artifact representation, envelope ID, or derived compatibility-package hash. Contract tests use the vendored pair to prove Registry projection changes transport representation without changing the normalized core identity.

- [ ] **Step 2: Implement export from validated facts**

The exporter joins immutable package validation records to the current `resource-metadata-v2.json` by kind/ID. It requires package core identity/file facts to match the source revision but deliberately overlays the inventory's current reviewed display/publisher/distribution proposal; those mutable fields need not equal the source archive's frozen display snapshot and never change `package_sha256`, revision ID, or canonical content hash. It obtains the source commit with `git rev-parse HEAD`, refuses a dirty metadata/package tree, missing metadata, or core identity/hash mismatch, and writes sorted UTF-8 JSON atomically. Registry treats the external publisher key as an untrusted mapping request and the resource as pending metadata input; it still revalidates source package bytes and requires Registry approver authorization before creating/reusing an external-key mapping or applying approver-only fields.

- [ ] **Step 3: Run a deterministic export comparison**

```bash
.venv/bin/python scripts/export_registry_metadata.py --output /tmp/resources-a.json
.venv/bin/python scripts/export_registry_metadata.py --output /tmp/resources-b.json
cmp /tmp/resources-a.json /tmp/resources-b.json
```

Expected: `cmp` exits `0`.

- [ ] **Step 4: Commit**

```bash
git add scripts/export_registry_metadata.py tests/test_resource_metadata_v2.py
git commit -m "feat(metadata): export validated registry resource records"
```

## Task 6: Repository Validation, Hygiene, And Documentation

**Files:**
- Create: `scripts/check_repository_hygiene.py`
- Create: `tests/test_repository_hygiene.py`
- Modify: `scripts/validate_packages.py`
- Modify: `scripts/validate_lut_packages.py`
- Create: `CONTRIBUTING.md`
- Modify: `README.md`

- [ ] **Step 1: Add tracked-file and text-content guards**

Reject tracked `.env`, tokens/private keys/config, `user_settings.json`, SQLite/database files, logs, reports generated by local runs, `.idea`, `.vscode`, `__pycache__`, `.pytest_cache`, `.DS_Store`, POSIX/macOS or Windows user-home absolute paths, and literal assignments to sensitive `LUMINA_*TOKEN`, `*SECRET`, or `*KEY` variables. Ignore binary ZIP payload scanning, but validate their manifests and paths through package validators.

- [ ] **Step 2: Extend validation summaries**

Material validator prints total and schema counts; LUT validator prints total and schema counts. Both load metadata and report resource count, publisher-kind count, missing/unreferenced metadata, duplicate identity, and immutable collision. A nonzero mismatch exits nonzero.

- [ ] **Step 3: Document the public Share resource flow**

`CONTRIBUTING.md` and README must state:

- user-facing terms are `Lumina official` and `Community shared`;
- ordinary/vendor/community content defaults to community even after review;
- only explicit approver evidence permits `lumina`;
- channel/visibility do not determine the badge;
- existing ZIPs are immutable;
- source changes create a new revision;
- metadata-only publication creates a Registry envelope;
- one Registry package contains exactly one material or LUT logical resource;
- all validation/hygiene commands required before PR.

The guide gives manufacturers and individual users separate examples that converge on the same public package/metadata contract. It links to a public issue/template or public form configured by Studio, explains pending/review/revision outcomes without using `Submit`/`Contribution`/competition wording, and requires no Registry token, private endpoint, server path, or operator configuration. Maintainer-only upload/approval steps stay in Registry deployment documentation rather than the contributor guide.

- [ ] **Step 4: Run the complete gate**

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python scripts/validate_packages.py --packages packages
.venv/bin/python scripts/validate_lut_packages.py --packages lut-packages
.venv/bin/python scripts/check_repository_hygiene.py
git diff --check origin/master...HEAD
```

Expected: all commands exit `0`; package totals remain 174 and 67; existing ZIP checksum comparison remains empty.

- [ ] **Step 5: Commit and open the PR**

```bash
git add scripts/check_repository_hygiene.py tests/test_repository_hygiene.py scripts/validate_packages.py scripts/validate_lut_packages.py CONTRIBUTING.md README.md
git commit -m "chore(validation): gate resource content releases"
```

The PR body must include Registry fixture commit/SHA evidence, package before/after checksum diff, metadata counts, publisher counts, deterministic build proof, validation output, and hygiene scan.

## Materials Merge Gate

Do not merge until:

- vendored fixture bytes match the merged Registry fixture commit exactly;
- both local validators agree with Registry expected projections;
- all 174 material and 67 LUT existing packages still validate and have unchanged bytes;
- metadata covers every logical resource exactly once and every existing LUT is community;
- every publisher key is explicit; bootstrap keys are per-resource, grouped keys have public approval evidence, and equal names never imply shared ownership;
- no resource becomes `lumina` from path/channel/brand inference;
- material 2.1 and LUT 2.0 builds are byte-deterministic and collision-safe;
- legacy LUT v1 identity remains intact while canonical v2 projection is available;
- Registry metadata export contains no authority-bearing URL/token/envelope/status fields;
- full tests, validators, diff check, and repository hygiene scan pass;
- exact-head independent review has no blocking finding.
