# Workshop Registry and Official Seed Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a signed, auditable GitHub Registry for installable Workshop modules, register the real `lumina.bead-pattern` release, embed that exact package as Lumina's official seed, and remove the obsolete in-tree bead implementation after cross-repository acceptance.

**Architecture:** `Lumina-Workshop-Registry` stores reviewed source entries, schemas, and deterministic build tools; GitHub Actions validates immutable release assets, builds exact index bytes, signs them with an Ed25519 key held outside Git, and deploys the index and detached signature to GitHub Pages. `Lumina-studio` pins the actual bead Release asset and SHA-256 in a seed lock, downloads it during desktop packaging, verifies it through the same package installer used for community modules, and respects a persistent user-uninstalled tombstone.

**Tech Stack:** Python 3.12, Pydantic, `cryptography` Ed25519, `httpx`, pytest, JSON Schema, GitHub Actions, GitHub Releases, GitHub Pages, Electron Builder, PyInstaller, React/Vitest

---

## Scope, repositories, and release order

Repositories:

- Host: `https://github.com/lumina-layer-studio/Lumina-studio`
- Official module: `https://github.com/lumina-layer-studio/Lumina-Fuse-Bead-Studio`
- Registry: `https://github.com/lumina-layer-studio/Lumina-Workshop-Registry`
- Registry index: `https://lumina-layer-studio.github.io/Lumina-Workshop-Registry/registry-v1.json`
- Registry signature: `https://lumina-layer-studio.github.io/Lumina-Workshop-Registry/registry-v1.sig`

The release order is strict:

1. complete the host plan and publish `workshop-sdk-v1.0.0`;
2. complete the external module plan, merge it, and publish immutable `v1.0.0`;
3. create and sign the Registry index containing the real module bytes and hashes;
4. update the host's embedded verification key and offline Registry snapshot;
5. generate the seed lock from the same real Release asset;
6. pass cross-repository, packaged-Electron, offline, rollback, and uninstall tests;
7. remove the in-tree bead source and publish the user-visible announcement.

Before execution, register the Registry and seed work in the online tracking spreadsheet. Never commit a private signing key, GitHub token, fabricated digest, downloaded credential, or mutable `latest` URL.

## Registry trust invariants

- A module ID is permanently bound to its approved GitHub repository unless a separately reviewed ownership-transfer process succeeds.
- Registry source PRs cannot introduce their own verification keys.
- Every version points to one non-draft, non-prerelease GitHub Release tag and one exact `.lumina-workshop` asset.
- The Registry stores the asset byte count, SHA-256, manifest SHA-256, permissions, compatibility range, and state.
- Valid states are `active`, `deprecated`, and `blocked`; blocked versions are never install candidates.
- Index signatures cover the exact downloaded `registry-v1.json` bytes.
- The app-owned key set is changed only by a Lumina release.
- Invalid remote data never overwrites the last verified local cache.
- The bundled Registry snapshot and seed lock are generated from reviewed signed data, not hand-edited hashes.
- Official packages pass the same download, digest, archive, manifest, permission, install, handshake, health, rollback, and uninstall path as third-party packages.

## Target Registry file map

```text
Lumina-Workshop-Registry/
├── .github/CODEOWNERS
├── .github/pull_request_template.md
├── .github/workflows/pull-request.yml
├── .github/workflows/scan-releases.yml
├── .github/workflows/publish-pages.yml
├── LICENSE
├── README.md
├── requirements.in
├── requirements-dev.in
├── requirements.lock
├── schemas/module-source-v1.schema.json
├── schemas/registry-v1.schema.json
├── modules/lumina.bead-pattern.json
├── scripts/build_registry.py
├── scripts/canonical_json.py
├── scripts/generate_signing_key.py
├── scripts/inspect_release.py
├── scripts/sign_registry.py
├── scripts/validate_sources.py
├── src/workshop_registry/__init__.py
├── src/workshop_registry/models.py
├── src/workshop_registry/ownership.py
├── src/workshop_registry/package.py
├── src/workshop_registry/release.py
└── tests/
```

## Task 1: Scaffold the Registry with strict source and output schemas

**Files in `Lumina-Workshop-Registry`:**

- Create: `pyproject.toml`
- Create: `requirements.in`
- Create: `requirements-dev.in`
- Create: `requirements.lock`
- Create: `src/workshop_registry/__init__.py`
- Create: `src/workshop_registry/models.py`
- Create: `schemas/module-source-v1.schema.json`
- Create: `schemas/registry-v1.schema.json`
- Create: `scripts/validate_sources.py`
- Create: `tests/test_models.py`
- Create: `README.md`
- Create: `LICENSE`
- Create: `.gitignore`

- [ ] **Step 1: Create the public repository and topic branch**

```bash
gh repo create lumina-layer-studio/Lumina-Workshop-Registry --public --clone=false
git clone https://github.com/lumina-layer-studio/Lumina-Workshop-Registry.git /Users/min/CascadeProjects/Lumina-Workshop-Registry
cd /Users/min/CascadeProjects/Lumina-Workshop-Registry
git switch -c main
git commit --allow-empty -m "chore: initialize repository"
git push -u origin main
git switch -c MOVIBALE/feat/signed-workshop-registry
```

- [ ] **Step 2: Write failing model tests**

```python
# tests/test_models.py
from pydantic import ValidationError
import pytest

from workshop_registry.models import ModuleSource, RegistryIndex


def test_source_rejects_unknown_fields(valid_source: dict) -> None:
    valid_source["unexpected"] = True
    with pytest.raises(ValidationError):
        ModuleSource.model_validate(valid_source)


def test_version_requires_exact_release_identity(valid_source: dict) -> None:
    version = valid_source["versions"][0]
    assert version == {
        "version": "1.0.0",
        "releaseTag": "v1.0.0",
        "assetName": "lumina.bead-pattern-1.0.0.lumina-workshop",
        "assetBytes": 12345,
        "sha256": "a" * 64,
        "manifestSha256": "b" * 64,
        "workshopApi": {"min": "1.0.0", "maxExclusive": "2.0.0"},
        "luminaVersion": {"min": "2.0.0"},
        "permissions": [
            {"name": "image.pick", "reason": "选择并读取拼豆图纸或截图"},
        ],
        "state": "active",
        "revocation": None,
    }


def test_registry_rejects_duplicate_module_versions(valid_index: dict) -> None:
    valid_index["modules"].append(valid_index["modules"][0])
    with pytest.raises(ValueError, match="duplicate module"):
        RegistryIndex.model_validate(valid_index)
```

Also test lowercase 64-character hashes, full SemVer only, HTTPS GitHub repositories only, exact release asset naming, known permissions, non-empty permission reasons, state/revocation consistency, strictly increasing versions, and no duplicate module IDs.

- [ ] **Step 3: Run the model tests**

Create `requirements.in`:

```text
cryptography>=44,<46
httpx>=0.28,<1
jsonschema>=4.24,<5
Pillow>=11,<13
pydantic>=2.11,<3
```

Create `requirements-dev.in`:

```text
-r requirements.in
pip-tools==7.5.1
pytest>=8.4,<9
PyYAML>=6.0,<7
respx>=0.22,<1
ruff>=0.12,<1
```

Then generate and install the locked graph:

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install pip-tools==7.5.1
./.venv/bin/python -m piptools compile \
  --generate-hashes \
  --strip-extras \
  --output-file requirements.lock \
  requirements-dev.in
./.venv/bin/python -m pip install --require-hashes -r requirements.lock
./.venv/bin/python -m pytest tests/test_models.py -v
```

Expected: FAIL because `workshop_registry.models` does not exist.

- [ ] **Step 4: Add exact source and generated-index models**

Use Pydantic models with `ConfigDict(extra="forbid", frozen=True)`. The reviewed source shape is:

```json
{
  "schemaVersion": 1,
  "moduleId": "lumina.bead-pattern",
  "repository": "https://github.com/lumina-layer-studio/Lumina-Fuse-Bead-Studio",
  "official": true,
  "publisher": "Lumina Studio",
  "versions": []
}
```

Each generated Registry module adds localized display fields from the verified
package manifest. Define each version with this strict model:

```python
class RegistryVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: SemVer
    release_tag: str = Field(alias="releaseTag")
    asset_name: str = Field(alias="assetName")
    download_url: AnyHttpUrl = Field(alias="downloadUrl")
    asset_bytes: int = Field(alias="assetBytes", gt=0, le=100 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(
        alias="manifestSha256",
        pattern=r"^[0-9a-f]{64}$",
    )
    workshop_api: ApiRange = Field(alias="workshopApi")
    lumina_version: LuminaRange = Field(alias="luminaVersion")
    permissions: tuple[Permission, ...]
    state: Literal["active", "deprecated", "blocked"]
    revocation: Revocation | None
```

The builder derives `downloadUrl`; the source file never supplies an arbitrary
download host. `revocation` is either `null` or:

```json
{
  "reasonCode": "malware",
  "severity": "critical",
  "message": {
    "zh-CN": "此版本已被阻止。",
    "en-US": "This version has been blocked."
  }
}
```

Generate JSON schemas from the Pydantic models in a checked test and compare them with `schemas/*.schema.json`; schema drift fails CI.

- [ ] **Step 5: Add the source validator and run the tests**

`scripts/validate_sources.py`:

```python
def main() -> int:
    source_paths = sorted(Path("modules").glob("*.json"))
    modules = [
        ModuleSource.model_validate_json(path.read_text(encoding="utf-8"))
        for path in source_paths
    ]
    validate_unique_id_ownership(modules)
    return 0
```

Run:

```bash
./.venv/bin/python -m pytest tests/test_models.py -v
./.venv/bin/python scripts/validate_sources.py
```

Expected: PASS with an empty `modules/` directory.

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat(registry): define signed catalog schemas"
```

## Task 2: Enforce module-ID ownership and reviewed repository changes

**Files in `Lumina-Workshop-Registry`:**

- Create: `src/workshop_registry/ownership.py`
- Create: `scripts/check_ownership_diff.py`
- Create: `tests/fixtures/base-sources/fixture.hello.json`
- Create: `tests/fixtures/head-sources/fixture.hello.json`
- Create: `tests/test_ownership.py`
- Create: `.github/CODEOWNERS`
- Create: `.github/pull_request_template.md`

- [ ] **Step 1: Write failing ownership-diff tests**

```python
def test_existing_module_cannot_change_repository_in_normal_pr(
    base_sources: Path,
    head_sources: Path,
) -> None:
    rewrite_repository(
        head_sources / "fixture.hello.json",
        "https://github.com/attacker/takeover",
    )
    with pytest.raises(OwnershipError, match="ownership transfer"):
        compare_ownership(base_sources, head_sources)


def test_existing_versions_are_append_only(
    base_sources: Path,
    head_sources: Path,
) -> None:
    mutate_existing_hash(head_sources / "fixture.hello.json")
    with pytest.raises(OwnershipError, match="immutable version"):
        compare_ownership(base_sources, head_sources)
```

Also reject deletion of an active module, a changed `official` flag, a changed publisher on an existing ID, changed release tag/asset/hash for a historical version, and version reordering. Allow a state transition to `blocked` only with a complete revocation record.

- [ ] **Step 2: Run the focused tests**

```bash
./.venv/bin/python -m pytest tests/test_ownership.py -v
```

Expected: FAIL because `ownership.py` does not exist.

- [ ] **Step 3: Implement base/head comparison**

`check_ownership_diff.py` receives explicit directories:

```bash
./.venv/bin/python scripts/check_ownership_diff.py \
  --base-dir /tmp/registry-base/modules \
  --head-dir modules
```

It must not trust a PR-provided “approved transfer” Boolean. A repository transfer requires a separate maintainer workflow or CODEOWNER-reviewed commit that updates an allowlisted transfer record; v1 may reject all transfers and require Registry maintainers to perform the exceptional change directly after evidence review.

Set:

```text
/modules/ @lumina-layer-studio/workshop-registry-maintainers
/schemas/ @lumina-layer-studio/workshop-registry-maintainers
/.github/ @lumina-layer-studio/workshop-registry-maintainers
```

Enable required CODEOWNER review and dismiss stale approvals in branch protection before publishing.

- [ ] **Step 4: Run ownership tests and commit**

```bash
./.venv/bin/python -m pytest tests/test_ownership.py -v
git add src scripts tests .github
git commit -m "feat(registry): protect module identity ownership"
```

## Task 3: Inspect exact GitHub Release assets without executing modules

**Files in `Lumina-Workshop-Registry`:**

- Create: `src/workshop_registry/package.py`
- Create: `src/workshop_registry/release.py`
- Create: `scripts/inspect_release.py`
- Create: `tests/test_package.py`
- Create: `tests/test_release.py`

- [ ] **Step 1: Write failing package and Release tests**

```python
def test_release_inspection_pins_actual_bytes(
    release_server: ReleaseServer,
    valid_package: bytes,
) -> None:
    release_server.add_release(
        tag="v1.0.0",
        draft=False,
        prerelease=False,
        assets={"fixture.hello-1.0.0.lumina-workshop": valid_package},
    )
    inspected = inspect_release(
        repository="https://github.com/example/fixture-hello",
        tag="v1.0.0",
        expected_module_id="fixture.hello",
    )
    assert inspected.asset_bytes == len(valid_package)
    assert inspected.sha256 == hashlib.sha256(valid_package).hexdigest()
    assert inspected.manifest_sha256 == hashlib.sha256(
        exact_manifest_bytes(valid_package),
    ).hexdigest()
```

Also test draft, prerelease, missing/duplicate assets, redirects outside `github.com` and `objects.githubusercontent.com`, more than 100 MiB while streaming, stalled reads, digest mismatch on a second fetch, package path attacks, unsupported manifest, ID/version/tag mismatch, and permission mismatch.
Mirror the host's manifest/icon/README/license limits and static gallery checks,
including encoded bytes, decoded pixels, animation, media signatures, UTF-8,
and gallery count.

- [ ] **Step 2: Run the focused tests**

```bash
./.venv/bin/python -m pytest tests/test_package.py tests/test_release.py -v
```

Expected: FAIL because release inspection is absent.

- [ ] **Step 3: Implement bounded download and static package inspection**

Use the hash-locked Pydantic, HTTPX, cryptography, Pillow, and test dependencies
created in Task 1; do not add an unlocked CI install path.

The Registry inspector duplicates the small static package-format boundary intentionally so Registry CI does not import unpublished host internals. Keep a cross-repository fixture contract in Task 9 to detect divergence.

`download_release_asset()` must stream to a temporary file with:

- 15-second connect timeout;
- 60-second read timeout;
- 10-minute total deadline;
- 100 MiB hard limit before writing the next chunk;
- explicit allowed redirect hosts;
- no authorization header for public module assets;
- SHA-256 computed during streaming;
- deletion of partial bytes on every failure.

`inspect_package()` must validate the same v1 limits and manifest contract as the host, but never extract or execute `ui/index.html`.

- [ ] **Step 4: Add a command that emits one reviewed version candidate**

```bash
./.venv/bin/python scripts/inspect_release.py \
  --repository https://github.com/lumina-layer-studio/Lumina-Fuse-Bead-Studio \
  --tag v1.0.0 \
  --module-id lumina.bead-pattern \
  --output /tmp/lumina.bead-pattern-v1.0.0.json
```

The output contains real hashes from the downloaded asset but does not modify `modules/` without an explicit `--apply` flag. `--apply` appends a new version only; it cannot rewrite an existing version.

- [ ] **Step 5: Run tests and commit**

```bash
./.venv/bin/python -m pytest tests/test_package.py tests/test_release.py -v
git add requirements.in requirements-dev.in requirements.lock src scripts tests
git commit -m "feat(registry): inspect immutable release assets"
```

## Task 4: Build deterministic index bytes and detached Ed25519 signatures

**Files in `Lumina-Workshop-Registry`:**

- Create: `scripts/canonical_json.py`
- Create: `scripts/build_registry.py`
- Create: `scripts/sign_registry.py`
- Create: `scripts/generate_signing_key.py`
- Create: `tests/test_build_registry.py`
- Create: `tests/test_sign_registry.py`
- Create: `dist/.gitignore`

- [ ] **Step 1: Write failing deterministic-build and signature tests**

```python
def test_build_is_deterministic(tmp_path: Path, source_dir: Path) -> None:
    first = build_registry(
        source_dir,
        generated_at="2026-07-30T00:00:00Z",
    )
    second = build_registry(
        source_dir,
        generated_at="2026-07-30T00:00:00Z",
    )
    assert first == second
    assert first.endswith(b"\n")


def test_signature_covers_exact_index_bytes(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    index_bytes = b'{"schemaVersion":1,"generatedAt":"2026-07-30T00:00:00Z","modules":[]}\n'
    signature_bytes = sign_index(index_bytes, private_key, key_id="test-2026-01")
    verify_detached_signature(index_bytes, signature_bytes, private_key.public_key())
    with pytest.raises(InvalidSignature):
        verify_detached_signature(index_bytes + b" ", signature_bytes, private_key.public_key())
```

Also test lexical module/version order, UTF-8 without escaped Chinese, a single trailing newline, no floating numbers, public-key raw-byte encoding, unknown key ID, malformed PEM, and signature metadata with extra fields.

- [ ] **Step 2: Run the tests**

```bash
./.venv/bin/python -m pytest tests/test_build_registry.py tests/test_sign_registry.py -v
```

Expected: FAIL because the build and signing tools do not exist.

- [ ] **Step 3: Implement canonical output**

The canonical writer uses:

```python
json.dumps(
    value,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8") + b"\n"
```

`build_registry.py` accepts `--generated-at`; CI passes the current commit timestamp:

```bash
GENERATED_AT="$(git show -s --format=%cI HEAD)"
./.venv/bin/python scripts/build_registry.py \
  --modules modules \
  --generated-at "$GENERATED_AT" \
  --output dist/registry-v1.json
```

The builder validates sources, ownership invariants available in the checkout,
output schema, and rejects zero or repeated-character synthetic hashes before
writing atomically.

- [ ] **Step 4: Implement key generation and detached signing**

`generate_signing_key.py` writes:

- an Ed25519 private PEM only to an explicit `--private-out` path;
- a public JSON record to `--public-out`;
- no private bytes, seed, fingerprint material, or PEM content to stdout/stderr.

The public record has exactly `keyId`, `algorithm`, and `publicKey`. Require
`keyId == "registry-2026-01"`, `algorithm == "Ed25519"`, and a canonical base64
value that decodes to 32 raw public-key bytes.

`sign_registry.py` reads the private PEM from
`REGISTRY_ED25519_PRIVATE_KEY`, signs the exact file bytes, and writes a strict
record with `algorithm`, `keyId`, and `signature`. The signature must decode to
64 bytes. Output uses canonical UTF-8 with one trailing newline and never
rewrites the index.

- [ ] **Step 5: Run tests and commit**

```bash
./.venv/bin/python -m pytest tests/test_build_registry.py tests/test_sign_registry.py -v
git add scripts tests dist/.gitignore
git commit -m "feat(registry): build and sign deterministic indexes"
```

## Task 5: Add PR validation, release scanning, and signed GitHub Pages publishing

**Files in `Lumina-Workshop-Registry`:**

- Create: `.github/workflows/pull-request.yml`
- Create: `.github/workflows/scan-releases.yml`
- Create: `.github/workflows/publish-pages.yml`
- Modify: `README.md`
- Create: `docs/review-policy.md`
- Create: `docs/key-rotation.md`
- Create: `tests/test_workflow_contract.py`

- [ ] **Step 1: Pin workflow behavior in a static contract test**

```python
def test_publish_only_signs_protected_main() -> None:
    text = Path(".github/workflows/publish-pages.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text.replace("\non:", "\n'on':", 1))
    assert workflow["on"] == {"push": {"branches": ["main"]}, "workflow_dispatch": None}
    job = workflow["jobs"]["publish"]
    assert job["environment"]["name"] == "registry-production"
    assert job["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }
```

Also assert PR workflows receive no signing secret, all third-party actions are pinned to full commit SHAs, source validation runs before build, Pages uploads only the two public files plus a minimal index page, and scan workflows cannot publish directly.

Use this reviewed action allowlist throughout all three workflows:

```text
actions/checkout@11d5960a326750d5838078e36cf38b85af677262              # v4
actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065          # v5
actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02       # v4
actions/configure-pages@983d7736d9b0ae728b81ab479565c72886d7745b       # v5
actions/upload-pages-artifact@56afc609e74202658d3ffba0e8f6dda462b719fa   # v3
actions/deploy-pages@d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e          # v4
```

The scanner uses the runner's `git` and `gh` CLI instead of a third-party PR
action.

- [ ] **Step 2: Add the pull-request workflow**

The PR workflow:

1. checks out full base/head history;
2. installs Python 3.12 dependencies only with
   `pip install --require-hashes -r requirements.lock`;
3. checks formatting and tests;
4. validates JSON schemas;
5. materializes the base branch `modules/` into a temp directory;
6. runs ownership diff;
7. redownloads and inspects every new version;
8. fetches each new asset twice and requires stable bytes;
9. builds the unsigned index twice and compares bytes;
10. uploads the candidate index for reviewer inspection.

It has only `contents: read`.

- [ ] **Step 3: Add the scheduled release scanner**

`.github/workflows/scan-releases.yml`:

- runs weekly and on `workflow_dispatch`;
- reads only registered public repositories;
- ignores draft/prerelease releases;
- accepts only a tag whose version exactly matches the asset and manifest;
- creates or updates one bot PR with appended version records;
- never changes repository ownership, `official`, an existing version, or a state;
- never auto-merges permission expansion, compatibility expansion, or new executable entry type;
- labels safe no-permission-change updates for optional reviewed auto-merge;
- uses `contents: write` and `pull-requests: write` only in this workflow.

- [ ] **Step 4: Add protected signed Pages publishing**

The publish workflow:

1. triggers only on protected `main` or explicit dispatch;
2. uses the `registry-production` GitHub Environment with required reviewers;
3. checks out and repeats full tests;
4. builds `dist/registry-v1.json` with the commit timestamp;
5. signs it using the environment secret;
6. verifies the signature with the committed public test record supplied by the release operator;
7. constructs `pages/registry-v1.json`, `pages/registry-v1.sig`, and a non-executable `pages/index.html`;
8. deploys through the exact official GitHub Pages action SHAs above;
9. downloads the deployed bytes and verifies them again before success.

The secret must never be passed to a pull-request job, shell trace, artifact, cache, step output, or Pages content.

- [ ] **Step 5: Run workflow tests and commit**

```bash
./.venv/bin/python -m pytest tests -v
./.venv/bin/python scripts/validate_sources.py
git diff --check
git add .github README.md docs tests
git commit -m "ci(registry): validate releases and publish signed pages"
```

- [ ] **Step 6: Push a draft bootstrap PR without merging it yet**

```bash
git push -u origin MOVIBALE/feat/signed-workshop-registry
gh pr create \
  --draft \
  --base main \
  --head MOVIBALE/feat/signed-workshop-registry \
  --title "feat: bootstrap the signed Workshop Registry" \
  --body-file /tmp/workshop-registry-bootstrap-pr.md
```

Use the draft to inspect workflow permissions and configure branch protection,
CODEOWNERS, Pages, and the `registry-production` Environment. Keep it unmerged
until Task 6 adds the real public key and its secret-backed signing check passes.

## Task 6: Generate the production key without exposing private material

**Files in `Lumina-Workshop-Registry`:**

- Create by command, then commit only: `keys/registry-2026-01.public.json`
- Modify: `.gitignore`
- Modify: `docs/key-rotation.md`

**Files in `Lumina-studio`:**

- Create: `scripts/sync_workshop_registry_key.py`
- Create: `tests/test_workshop_registry_key_sync_unit.py`
- Modify: `assets/workshop-registry/keys.json`
- Modify: `tests/test_workshop_registry_unit.py`

- [ ] **Step 1: Confirm repository protections before generating a key**

Verify:

- Registry `main` requires passing PR checks and CODEOWNER approval;
- `registry-production` requires maintainer approval;
- Pages deploys only from the protected workflow;
- Actions logs and artifacts are private to repository collaborators;
- secret scanning and push protection are enabled.

Do not generate the key until these controls are visible in GitHub settings.

- [ ] **Step 2: Generate into a private temporary directory**

```bash
cd /Users/min/CascadeProjects/Lumina-Workshop-Registry
REGISTRY_KEY_DIR="$(mktemp -d)"
export REGISTRY_KEY_DIR
chmod 700 "$REGISTRY_KEY_DIR"
./.venv/bin/python scripts/generate_signing_key.py \
  --key-id registry-2026-01 \
  --private-out "$REGISTRY_KEY_DIR/registry-ed25519.pem" \
  --public-out keys/registry-2026-01.public.json
chmod 600 "$REGISTRY_KEY_DIR/registry-ed25519.pem"
gh secret set REGISTRY_ED25519_PRIVATE_KEY \
  --repo lumina-layer-studio/Lumina-Workshop-Registry \
  --env registry-production \
  < "$REGISTRY_KEY_DIR/registry-ed25519.pem"
```

Execute the rest of Task 6 in this same guarded shell session so the exact
temporary directory remains available for narrow cleanup.

Verify only the secret metadata:

```bash
gh secret list \
  --repo lumina-layer-studio/Lumina-Workshop-Registry \
  --env registry-production
```

Do not print or copy the private PEM. Stop and rotate the key if the private
bytes appear in terminal output, shell history, clipboard history, logs, or
artifacts.

- [ ] **Step 3: Commit the public key to the Registry repository**

`.gitignore` rejects:

```text
*.pem
*.key
keys/*.private.*
```

Run a secret scan, commit the public half onto the draft bootstrap PR, and push:

```bash
git add .gitignore keys/registry-2026-01.public.json docs/key-rotation.md
git commit -m "chore(registry): add production verification key"
git push
```

- [ ] **Step 4: Merge the bootstrap PR and verify a signed empty Registry**

Mark the existing draft ready only after its checks pass, obtain review, and
merge it. Approve the `registry-production` deployment, then download and verify
the exact deployed bytes:

```bash
gh pr ready MOVIBALE/feat/signed-workshop-registry \
  --repo lumina-layer-studio/Lumina-Workshop-Registry
gh pr checks MOVIBALE/feat/signed-workshop-registry \
  --repo lumina-layer-studio/Lumina-Workshop-Registry \
  --watch
gh pr merge MOVIBALE/feat/signed-workshop-registry \
  --repo lumina-layer-studio/Lumina-Workshop-Registry \
  --merge \
  --delete-branch
PUBLISH_RUN_ID="$(gh run list \
  --repo lumina-layer-studio/Lumina-Workshop-Registry \
  --workflow publish-pages.yml \
  --branch main \
  --event push \
  --limit 1 \
  --json databaseId \
  --jq '.[0].databaseId')"
gh run watch "$PUBLISH_RUN_ID" \
  --repo lumina-layer-studio/Lumina-Workshop-Registry \
  --exit-status
curl --fail --location \
  --output /tmp/registry-v1.json \
  https://lumina-layer-studio.github.io/Lumina-Workshop-Registry/registry-v1.json
curl --fail --location \
  --output /tmp/registry-v1.sig \
  https://lumina-layer-studio.github.io/Lumina-Workshop-Registry/registry-v1.sig
./.venv/bin/python scripts/sign_registry.py \
  --public-key keys/registry-2026-01.public.json \
  --verify-only /tmp/registry-v1.json /tmp/registry-v1.sig
```

Expected: signature PASS and the index contains zero modules. Only after this
verification, remove the exact private file and now-empty temporary directory:

```bash
test -n "$REGISTRY_KEY_DIR"
test -f "$REGISTRY_KEY_DIR/registry-ed25519.pem"
rm "$REGISTRY_KEY_DIR/registry-ed25519.pem"
rmdir "$REGISTRY_KEY_DIR"
unset REGISTRY_KEY_DIR
```

Do not use a recursive, broad, globbed, or unresolved delete target.

- [ ] **Step 5: Install the same public key in a fresh Lumina topic branch**

Start from the merged host rather than reusing its retired feature branch:

```bash
cd /Users/min/.codex/worktrees/b9d4/Lumina-studio
git fetch origin dev-refactor
test -z "$(git status --short)"
git switch -c MOVIBALE/feat/workshop-registry-seed origin/dev-refactor
```

`scripts/sync_workshop_registry_key.py` reads the Registry public record,
rejects private fields or non-Ed25519 data, verifies the key ID and 32-byte
decoded length, and atomically writes the host `schemaVersion: 1` key set. Run:

```bash
./.venv/bin/python scripts/sync_workshop_registry_key.py \
  --public-key /Users/min/CascadeProjects/Lumina-Workshop-Registry/keys/registry-2026-01.public.json \
  --output assets/workshop-registry/keys.json
./.venv/bin/python -m pytest tests/test_workshop_registry_key_sync_unit.py tests/test_workshop_registry_unit.py tests/test_desktop_build_contract_unit.py -v
git diff --check
git add scripts/sync_workshop_registry_key.py assets/workshop-registry/keys.json tests/test_workshop_registry_key_sync_unit.py tests/test_workshop_registry_unit.py
git commit -m "feat(workshop): trust the production Registry key"
```

The test reads both checked-out public files and asserts byte-decoded values are
identical. It also proves an unknown replacement key is rejected. No
Registry-controlled runtime file may add a trusted key.

## Task 7: Register the real official bead Release and publish the first signed index

**Files in `Lumina-Workshop-Registry`:**

- Create: `modules/lumina.bead-pattern.json`
- Modify: `README.md`
- Create: `tests/test_official_bead_entry.py`

- [ ] **Step 1: Confirm the module Release is immutable and public**

In the module repository:

```bash
gh release view v1.0.0 \
  --repo lumina-layer-studio/Lumina-Fuse-Bead-Studio \
  --json isDraft,isPrerelease,tagName,assets,url
```

Expected:

- `isDraft` is `false`;
- `isPrerelease` is `false`;
- tag is `v1.0.0`;
- exactly one `.lumina-workshop` and its `.sha256` companion exist;
- the standard package asset name is exact.

Enable GitHub immutable releases for the official module repository before using the asset. If immutability is unavailable on the repository plan, retain the Registry SHA-256 as the enforcement boundary and document the platform limitation.

- [ ] **Step 2: Generate the source entry from the actual asset**

```bash
cd /Users/min/CascadeProjects/Lumina-Workshop-Registry
git fetch origin main
test -z "$(git status --short)"
git switch -c MOVIBALE/feat/register-official-bead origin/main
./.venv/bin/python scripts/inspect_release.py \
  --repository https://github.com/lumina-layer-studio/Lumina-Fuse-Bead-Studio \
  --tag v1.0.0 \
  --module-id lumina.bead-pattern \
  --official \
  --publisher "Lumina Studio" \
  --apply
```

The command writes real `assetBytes`, `sha256`, and `manifestSha256`; do not edit them manually.

- [ ] **Step 3: Add official-entry tests**

```python
def test_official_bead_entry_matches_live_release() -> None:
    source = load_source("lumina.bead-pattern")
    release = inspect_release(
        repository=source.repository,
        tag="v1.0.0",
        expected_module_id=source.module_id,
    )
    assert source.versions[0].sha256 == release.sha256
    assert source.versions[0].permissions == release.manifest.permissions
    assert source.versions[0].state == "active"
```

The network-backed test runs only in Registry CI with an explicit marker. A local unit fixture covers the same comparison without network.

- [ ] **Step 4: Open, review, and merge the Registry PR**

```bash
git add modules/lumina.bead-pattern.json tests/test_official_bead_entry.py README.md
git commit -m "feat(registry): register official Fuse Bead Studio"
git push -u origin MOVIBALE/feat/register-official-bead
gh pr create \
  --base main \
  --head MOVIBALE/feat/register-official-bead \
  --title "feat: register the official Fuse Bead Studio module" \
  --body-file /tmp/register-official-bead-pr.md
```

PR evidence includes the module Release URL, two-fetch stable digest, manifest digest, permission list, schema checks, ownership review, signature test, and Pages review controls.

- [ ] **Step 5: Publish and verify the signed Pages output**

After required review, merge and approve the production deployment:

```bash
gh pr checks MOVIBALE/feat/register-official-bead \
  --repo lumina-layer-studio/Lumina-Workshop-Registry \
  --watch
gh pr merge MOVIBALE/feat/register-official-bead \
  --repo lumina-layer-studio/Lumina-Workshop-Registry \
  --merge \
  --delete-branch
git fetch origin main
git switch main
git merge --ff-only origin/main
GENERATED_AT="$(git show -s --format=%cI HEAD)"
./.venv/bin/python scripts/build_registry.py \
  --modules modules \
  --generated-at "$GENERATED_AT" \
  --output dist/registry-v1.json
PUBLISH_RUN_ID="$(gh run list \
  --repo lumina-layer-studio/Lumina-Workshop-Registry \
  --workflow publish-pages.yml \
  --branch main \
  --event push \
  --limit 1 \
  --json databaseId \
  --jq '.[0].databaseId')"
gh run watch "$PUBLISH_RUN_ID" \
  --repo lumina-layer-studio/Lumina-Workshop-Registry \
  --exit-status
curl --fail --location \
  --output /tmp/registry-v1.json \
  https://lumina-layer-studio.github.io/Lumina-Workshop-Registry/registry-v1.json
curl --fail --location \
  --output /tmp/registry-v1.sig \
  https://lumina-layer-studio.github.io/Lumina-Workshop-Registry/registry-v1.sig
./.venv/bin/python scripts/sign_registry.py \
  --public-key keys/registry-2026-01.public.json \
  --verify-only /tmp/registry-v1.json /tmp/registry-v1.sig
cmp /tmp/registry-v1.json dist/registry-v1.json
```

Expected: signature PASS and deployed bytes equal the reviewed build artifact.

## Task 8: Generate a real host snapshot and official seed lock

**Files in `Lumina-studio`:**

- Create: `scripts/sync_workshop_registry.py`
- Create: `scripts/sync_workshop_seed.py`
- Modify: `assets/workshop-registry/registry-v1.json`
- Create: `assets/workshop-registry/registry-v1.sig`
- Create: `assets/workshop-seed/seed-lock.json`
- Create: `tests/test_workshop_seed_sync_unit.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing sync tests with a local signed Registry server**

```python
def test_seed_lock_comes_from_verified_registry_bytes(
    tmp_path: Path,
    signed_registry_server: SignedRegistryServer,
) -> None:
    result = sync_seed(
        module_id="lumina.bead-pattern",
        version="1.0.0",
        registry_url=signed_registry_server.index_url,
        signature_url=signed_registry_server.signature_url,
        output_dir=tmp_path,
    )
    assert result.lock["moduleId"] == "lumina.bead-pattern"
    assert result.lock["version"] == "1.0.0"
    assert result.lock["releaseAsset"] == "lumina.bead-pattern-1.0.0.lumina-workshop"
    assert result.lock["sha256"] == hashlib.sha256(result.package_path.read_bytes()).hexdigest()


def test_bad_registry_signature_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(InvalidSignature):
        sync_seed_from_invalid_registry(tmp_path)
    assert list(tmp_path.iterdir()) == []
```

Also test blocked/deprecated selection, explicit missing version, asset byte mismatch, digest mismatch, package identity mismatch, redirect escape, partial download cleanup, and atomic replacement of an existing snapshot.

- [ ] **Step 2: Run the focused tests**

```bash
./.venv/bin/python -m pytest tests/test_workshop_seed_sync_unit.py -v
```

Expected: FAIL because the sync scripts do not exist.

- [ ] **Step 3: Implement Registry and seed synchronization**

`sync_workshop_registry.py` uses the same `RegistryClient` verification code as runtime and atomically writes exact verified bytes to:

- `assets/workshop-registry/registry-v1.json`
- `assets/workshop-registry/registry-v1.sig`

`sync_workshop_seed.py`:

1. reads the verified index;
2. selects the explicit module ID and version;
3. requires `official: true` and `state: active`;
4. downloads the exact release asset with host limits;
5. verifies byte count, SHA-256, manifest SHA-256, package identity, compatibility, and permissions;
6. writes a temporary lock from the verified record;
7. writes the package only to an explicit build-cache directory;
8. atomically publishes the lock after every check passes.

Define the lock with a frozen, extra-forbidden model containing
`schemaVersion`, `moduleId`, `version`, `repository`, `releaseTag`,
`releaseAsset`, `downloadUrl`, `assetBytes`, `sha256`, and
`manifestSha256`. Require schema version 1, a positive byte count, full SemVer,
the exact standard asset name, an immutable Release URL derived from the
Registry record, and lowercase 64-character hashes. The sync script serializes
that model; no digest field is hand-written.

Add a test that fails if the committed lock contains zero, repeated-character
hashes, prose, localhost, a branch URL, or a mutable asset URL.

- [ ] **Step 4: Generate from deployed signed data**

```bash
./.venv/bin/python scripts/sync_workshop_registry.py \
  --index-url https://lumina-layer-studio.github.io/Lumina-Workshop-Registry/registry-v1.json \
  --signature-url https://lumina-layer-studio.github.io/Lumina-Workshop-Registry/registry-v1.sig
WORKSHOP_SEED_CACHE="/Users/min/.cache/lumina-workshop-release/bead-v1.0.0"
mkdir -p "$WORKSHOP_SEED_CACHE"
./.venv/bin/python scripts/sync_workshop_seed.py \
  --module-id lumina.bead-pattern \
  --version 1.0.0 \
  --registry assets/workshop-registry/registry-v1.json \
  --signature assets/workshop-registry/registry-v1.sig \
  --lock-output assets/workshop-seed/seed-lock.json \
  --package-output "$WORKSHOP_SEED_CACHE/lumina.bead-pattern-1.0.0.lumina-workshop"
```

The sync script also writes the adjacent
`lumina.bead-pattern-1.0.0.lumina-workshop.sha256` file from the verified
download bytes.

Verify without printing private data:

```bash
pushd "$WORKSHOP_SEED_CACHE"
shasum -a 256 -c lumina.bead-pattern-1.0.0.lumina-workshop.sha256
popd
./.venv/bin/python -m core.workshop.package_validator \
  "$WORKSHOP_SEED_CACHE/lumina.bead-pattern-1.0.0.lumina-workshop"
```

The cache directory is outside Git and may be deleted after the desktop build copies and verifies it. Do not commit the binary package unless a later distribution requirement explicitly changes this design.

- [ ] **Step 5: Run tests and commit real public metadata**

```bash
./.venv/bin/python -m pytest tests/test_workshop_seed_sync_unit.py tests/test_workshop_registry_unit.py -v
git diff --check
git add scripts/sync_workshop_registry.py scripts/sync_workshop_seed.py assets/workshop-registry assets/workshop-seed/seed-lock.json tests/test_workshop_seed_sync_unit.py .gitignore
git commit -m "build(workshop): pin official bead seed release"
```

## Task 9: Bundle the seed in desktop installers without a parallel install path

**Files in `Lumina-studio`:**

- Modify: `scripts/build_desktop.py`
- Modify: `electron/package.json`
- Create: `electron/resources/workshop-seed/.gitignore`
- Modify: `electron/main.cjs`
- Modify: `tests/test_desktop_build_contract_unit.py`
- Create: `tests/test_workshop_seed_bundle_unit.py`

- [ ] **Step 1: Write failing build-contract tests**

```python
def test_desktop_builder_requires_a_verified_workshop_seed() -> None:
    source = Path("scripts/build_desktop.py").read_text(encoding="utf-8")
    assert "--workshop-seed-path" in source
    assert "verify_workshop_seed" in source


def test_electron_bundles_workshop_seed_as_extra_resource() -> None:
    package = json.loads(Path("electron/package.json").read_text(encoding="utf-8"))
    assert {
        "from": "resources/workshop-seed",
        "to": "workshop-seed",
    } in package["build"]["extraResources"]
```

Test that a wrong hash stops before Electron Builder, stale seed assets are removed when no path is supplied, and only the lock-named asset is copied.

- [ ] **Step 2: Run the focused tests**

```bash
./.venv/bin/python -m pytest tests/test_workshop_seed_bundle_unit.py tests/test_desktop_build_contract_unit.py -v
```

Expected: FAIL because the desktop build does not know about Workshop seed packages.

- [ ] **Step 3: Add an explicit build input and verification function**

Extend `parse_args()`:

```python
parser.add_argument(
    "--workshop-seed-path",
    default=os.environ.get("WORKSHOP_SEED_PATH", ""),
    help="Required official .lumina-workshop seed for release desktop builds.",
)
```

Add:

```python
def verify_workshop_seed(seed_path: Path, lock_path: Path) -> dict[str, object]:
    """Verify one seed asset against its committed lock.
    对照已提交的锁文件校验一个预装模块安装包。
    """
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if seed_path.name != lock["releaseAsset"]:
        raise ValueError("Workshop seed asset name does not match lock")
    digest = hashlib.sha256(seed_path.read_bytes()).hexdigest()
    if not hmac.compare_digest(digest, lock["sha256"]):
        raise ValueError("Workshop seed SHA-256 does not match lock")
    inspect_workshop_package(seed_path)
    return lock
```

Use streaming hash calculation in the final implementation. Copy the verified asset plus `seed-lock.json` into `electron/resources/workshop-seed/`. A release build without `--workshop-seed-path` fails; an explicit development-only flag may omit it, but release CI must never use that flag.

- [ ] **Step 4: Pass the packaged seed directory to the backend**

In packaged mode, `electron/main.cjs` sets:

```js
LUMINA_WORKSHOP_SEED_DIR: path.join(process.resourcesPath, "workshop-seed")
```

In development, set it only when a verified resource directory exists. Do not pass the package bytes or path through `preload.cjs` to the renderer.

Add to `electron/package.json`:

```json
{
  "from": "resources/workshop-seed",
  "to": "workshop-seed"
}
```

- [ ] **Step 5: Run build-contract tests and a dry-run copy**

```bash
WORKSHOP_SEED_CACHE="/Users/min/.cache/lumina-workshop-release/bead-v1.0.0"
test -f "$WORKSHOP_SEED_CACHE/lumina.bead-pattern-1.0.0.lumina-workshop"
./.venv/bin/python -m pytest tests/test_workshop_seed_bundle_unit.py tests/test_desktop_build_contract_unit.py -v
./.venv/bin/python scripts/build_desktop.py \
  --workshop-seed-path "$WORKSHOP_SEED_CACHE/lumina.bead-pattern-1.0.0.lumina-workshop" \
  --materials-seed-path ""
```

Expected: the exact locked asset and lock appear under the built `workshop-seed` resource and Electron packaging starts only after verification. Do not leave generated installer resources staged.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_desktop.py electron/package.json electron/main.cjs electron/resources/workshop-seed/.gitignore tests
git commit -m "build(workshop): bundle verified official seed"
```

## Task 10: Install, update, restore, and tombstone the official seed

**Files in `Lumina-studio`:**

- Create: `api/workshop_seed.py`
- Modify: `api/app.py`
- Modify: `core/workshop/install_store.py`
- Modify: `core/workshop/installer.py`
- Modify: `api/routers/workshop.py`
- Create: `tests/test_workshop_seed_lifecycle_unit.py`
- Modify: `tests/test_workshop_installer_unit.py`
- Modify: `tests/test_logging_exception_governance_unit.py`

- [ ] **Step 1: Write failing seed lifecycle tests**

```python
def test_first_start_installs_seed_as_candidate_through_normal_installer(
    seed_dir: Path,
    installer: RecordingInstaller,
) -> None:
    result = converge_workshop_seed(seed_dir=seed_dir, installer=installer)
    assert result.status == "candidate-installed"
    assert installer.calls == [
        InstallCandidateCall(
            source="seed",
            package=seed_dir / "lumina.bead-pattern-1.0.0.lumina-workshop",
            expected_sha256=read_seed_lock(seed_dir)["sha256"],
        ),
    ]


def test_user_uninstall_tombstone_prevents_resurrection(
    seed_dir: Path,
    installer: Installer,
) -> None:
    install_and_activate_seed(installer, seed_dir)
    installer.uninstall("lumina.bead-pattern", delete_projects=False)
    restarted = installer_from_same_state(installer)
    result = converge_workshop_seed(seed_dir=seed_dir, installer=restarted)
    assert result.status == "user-uninstalled"
    assert restarted.get("lumina.bead-pattern").active_version is None
```

Also test:

- missing seed directory is non-fatal in source development;
- release desktop mode treats missing/invalid seed as a packaging fault;
- same installed version is a no-op;
- a newer bundled seed becomes a candidate but does not replace active before ready;
- an older seed never downgrades a newer active version;
- a blocked cached Registry version cannot be restored;
- “从安装包恢复” clears the tombstone only after explicit user action;
- project data survives uninstall/reinstall;
- first handshake failure keeps the previous active version;
- three consecutive failures disable the bad candidate and enter module safe mode.

- [ ] **Step 2: Run focused tests**

```bash
./.venv/bin/python -m pytest tests/test_workshop_seed_lifecycle_unit.py tests/test_workshop_installer_unit.py -v
```

Expected: FAIL because seed convergence is absent.

- [ ] **Step 3: Add idempotent startup convergence**

`api/workshop_seed.py`:

```python
def converge_workshop_seed(
    *,
    seed_dir: str | Path | None,
    installer: WorkshopInstaller,
) -> SeedConvergenceResult:
    """Converge the bundled official module without overriding user intent.
    在不覆盖用户选择的前提下收敛预装官方模块状态。
    """
```

It must:

1. resolve and validate only the explicit seed directory;
2. parse lock with `extra="forbid"`;
3. compare the package through constant-time SHA-256;
4. inspect it through `inspect_workshop_package()`;
5. check module/version/permissions against the lock;
6. return without install when `official_uninstalled` is true;
7. call the normal `install_candidate()` with source `seed`;
8. leave activation to the normal ready/health transaction;
9. log one bounded success or error event with no path or package bytes.

Call convergence from application lifecycle after logging and install-store initialization, before the Workshop API reports installed modules.

- [ ] **Step 4: Add explicit restore semantics**

The existing restore route accepts:

```json
{
  "source": "bundled-seed"
}
```

It requires user action, revalidates the package, installs it as a candidate, and clears `official_uninstalled` only after candidate files are committed. It never deletes projects or bypasses permission confirmation when the seed requests more permissions than the last accepted version.

Register structured events:

- `workshop_seed_converged`
- `workshop_seed_converge_failed`
- `workshop_seed_restore_done`

Follow the current logging governance whitelist and INFO budget.

- [ ] **Step 5: Run lifecycle and logging gates**

```bash
./.venv/bin/python -m pytest tests/test_workshop_seed_lifecycle_unit.py tests/test_workshop_installer_unit.py tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v
./.venv/bin/python scripts/log_quality_check.py --mode fast
```

Expected: PASS without a raw traceback or duplicate INFO event.

- [ ] **Step 6: Commit**

```bash
git add api core/workshop tests
git commit -m "feat(workshop): converge official seed lifecycle"
```

## Task 11: Add cross-repository contract and supply-chain gates

**Files in `Lumina-studio`:**

- Create: `scripts/verify_workshop_release_chain.py`
- Create: `tests/test_workshop_release_chain_unit.py`
- Create: `.github/workflows/workshop-release-chain.yml`
- Modify: `docs/workshop-module-development.md`

**Files in `Lumina-Workshop-Registry`:**

- Create: `tests/fixtures/host-package-contract.json`
- Modify: `.github/workflows/pull-request.yml`

- [ ] **Step 1: Write a failing complete-chain test**

```python
def test_release_chain_requires_one_identity(release_chain: ReleaseChain) -> None:
    result = verify_release_chain(
        sdk_tarball=release_chain.sdk_tarball,
        registry=release_chain.registry,
        signature=release_chain.signature,
        seed_lock=release_chain.seed_lock,
        module_package=release_chain.module_package,
        trusted_keys=release_chain.trusted_keys,
    )
    assert result == {
        "workshopApi": "1.0.0",
        "moduleId": "lumina.bead-pattern",
        "moduleVersion": "1.0.0",
        "packageSha256": release_chain.package_sha256,
        "registryKeyId": "registry-2026-01",
    }
```

Mutation tests independently alter SDK API version, manifest version, module ID, package version, package bytes, Registry hash, lock hash, permission order, and public key; every mutation must fail with a specific error.

- [ ] **Step 2: Run the test before adding the verifier**

```bash
./.venv/bin/python -m pytest tests/test_workshop_release_chain_unit.py -v
```

Expected: FAIL because the verifier does not exist.

- [ ] **Step 3: Implement a read-only chain verifier**

The script accepts only explicit local files. It:

1. inspects the SDK tarball package metadata;
2. verifies Registry exact bytes and signature;
3. locates the exact module/version record;
4. checks the seed lock is a projection of that record;
5. hashes and statically inspects the module archive;
6. verifies manifest permissions and API ranges;
7. emits bounded JSON facts without source paths or package content.

It does not download, install, execute, sign, mutate, or publish.

- [ ] **Step 4: Add an explicit cross-repository GitHub workflow**

`.github/workflows/workshop-release-chain.yml` runs on:

- seed-lock changes;
- public SDK tag publication;
- `workflow_dispatch` with explicit module version.

It downloads exact immutable Release assets, verifies their GitHub API metadata, runs the read-only verifier, installs the module into an isolated temporary Workshop root, launches the synthetic host harness, waits for `lifecycle.ready`, reads the color library, performs a small PNG handoff, and cleans the temporary root.

Pin every action to a full SHA. Give the job `contents: read` only. Do not run external module code on a privileged GitHub-hosted environment before static package validation; the runtime harness uses the same sandbox and no-network restrictions as the product.

- [ ] **Step 5: Run unit and local chain tests**

```bash
SDK_RELEASE_CACHE="/Users/min/.cache/lumina-workshop-release/sdk-v1.0.0"
WORKSHOP_SEED_CACHE="/Users/min/.cache/lumina-workshop-release/bead-v1.0.0"
./.venv/bin/python -m pytest tests/test_workshop_release_chain_unit.py -v
./.venv/bin/python scripts/verify_workshop_release_chain.py \
  --sdk "$SDK_RELEASE_CACHE/lumina-workshop-sdk-1.0.0.tgz" \
  --registry assets/workshop-registry/registry-v1.json \
  --signature assets/workshop-registry/registry-v1.sig \
  --keys assets/workshop-registry/keys.json \
  --seed-lock assets/workshop-seed/seed-lock.json \
  --module-package "$WORKSHOP_SEED_CACHE/lumina.bead-pattern-1.0.0.lumina-workshop"
```

Expected: one JSON result with the exact API, module identity, package hash, and key ID.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify_workshop_release_chain.py tests/test_workshop_release_chain_unit.py .github/workflows/workshop-release-chain.yml docs/workshop-module-development.md
git commit -m "test(workshop): verify cross-repository release chain"
```

## Task 12: Remove the in-tree bead implementation after external acceptance

**Files in `Lumina-studio`:**

- Delete: `frontend/src/workshop/modules/bead/`
- Delete: `frontend/src/__tests__/bead-calibration-step.test.tsx`
- Delete: `frontend/src/__tests__/bead-editor-reducer.property.test.ts`
- Delete: `frontend/src/__tests__/bead-editor-reducer.test.ts`
- Delete: `frontend/src/__tests__/bead-editor-step.test.tsx`
- Delete: `frontend/src/__tests__/bead-project.property.test.ts`
- Delete: `frontend/src/__tests__/bead-project.test.ts`
- Delete: `frontend/src/__tests__/bead-recognition.property.test.ts`
- Delete: `frontend/src/__tests__/bead-recognition.test.ts`
- Delete: `frontend/src/__tests__/bead-renderer.property.test.ts`
- Delete: `frontend/src/__tests__/bead-renderer.test.ts`
- Delete: `frontend/src/__tests__/bead-worker-client.test.ts`
- Delete: `frontend/src/__tests__/bead-workshop-module.test.tsx`
- Delete: `frontend/src/__tests__/helpers/beadFixtures.ts`
- Delete: `frontend/src/__tests__/fixtures/beadRecipeSource.ts`
- Modify: `frontend/src/workshop/registry.ts`
- Modify: `frontend/src/workshop/types.ts`
- Modify: `frontend/src/workshop/WorkshopPanel.tsx`
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `frontend/src/__tests__/workshop-manager.test.tsx`
- Modify: `frontend/src/__tests__/recipe-import.test.ts`
- Modify: `frontend/src/__tests__/recipe-export.test.ts`
- Modify: `docs/superpowers/plans/2026-07-30-creative-workshop-bead-mode.md`
- Modify: `docs/context/workshop/CONTEXT.md`

- [ ] **Step 1: Prove the external package replaces every required behavior**

Before deleting anything, require:

```bash
SDK_RELEASE_CACHE="/Users/min/.cache/lumina-workshop-release/sdk-v1.0.0"
WORKSHOP_SEED_CACHE="/Users/min/.cache/lumina-workshop-release/bead-v1.0.0"
gh run list \
  --repo lumina-layer-studio/Lumina-Fuse-Bead-Studio \
  --branch main \
  --limit 5
gh run list \
  --repo lumina-layer-studio/Lumina-Workshop-Registry \
  --branch main \
  --limit 5
./.venv/bin/python scripts/verify_workshop_release_chain.py \
  --sdk "$SDK_RELEASE_CACHE/lumina-workshop-sdk-1.0.0.tgz" \
  --registry assets/workshop-registry/registry-v1.json \
  --signature assets/workshop-registry/registry-v1.sig \
  --keys assets/workshop-registry/keys.json \
  --seed-lock assets/workshop-seed/seed-lock.json \
  --module-package "$WORKSHOP_SEED_CACHE/lumina.bead-pattern-1.0.0.lumina-workshop"
```

Expected: latest module and Registry runs PASS, and the local chain verifier PASS.

- [ ] **Step 2: Update host tests so they know only public contracts**

Before deletion, change host tests to use:

- synthetic `fixture.hello` for generic host/RPC/install behavior;
- downloaded locked package for external bead integration;
- plain structural `WorkshopRecipeSource` fixtures for recipe round-trip;
- no bead renderer, recognition, reducer, UI, or module manifest import.

Run these tests and confirm they pass while the old source still exists but is unused:

```bash
./.venv/bin/python scripts/run_vitest.py run \
  frontend/src/__tests__/workshop-manager.test.tsx \
  frontend/src/__tests__/workshop-rpc-host.test.ts \
  frontend/src/__tests__/workshop-handoff.test.ts \
  frontend/src/__tests__/recipe-import.test.ts \
  frontend/src/__tests__/recipe-export.test.ts
```

- [ ] **Step 3: Delete only the superseded source and duplicated tests**

Use `git rm` with the exact paths listed above. Do not delete:

- generic Workshop host tests;
- the share-card Workshop envelope tests;
- external release-chain fixtures;
- seed lifecycle tests;
- project namespace and quota tests;
- bug-report Workshop diagnostics tests.

Remove any direct bead manifest registration. The Installed view now derives `lumina.bead-pattern` entirely from installer state.

- [ ] **Step 4: Mark the old implementation plan as historical**

At the top of `docs/superpowers/plans/2026-07-30-creative-workshop-bead-mode.md`, add:

```markdown
> Historical prototype plan. Do not execute. The package-based replacement is
> `2026-07-30-installable-creative-workshop-host.md`,
> `2026-07-30-fuse-bead-studio-module.md`, and
> `2026-07-30-workshop-registry-and-seed-release.md`.
```

Update Workshop context docs to state that bead business logic lives in the external repository and that host changes must not reintroduce direct module imports.

- [ ] **Step 5: Run deletion and boundary gates**

```bash
rg -n "modules/bead|BEAD_WORKSHOP_DEFINITION|OFFICIAL_WORKSHOP_MODULES|BeadWorkshopModule" frontend/src
./.venv/bin/python scripts/run_vitest.py run \
  frontend/src/__tests__/workshop-manager.test.tsx \
  frontend/src/__tests__/workshop-rpc-host.test.ts \
  frontend/src/__tests__/workshop-runtime.test.tsx \
  frontend/src/__tests__/workshop-project-storage.test.ts \
  frontend/src/__tests__/workshop-handoff.test.ts \
  frontend/src/__tests__/workshop-source-banner.test.tsx \
  frontend/src/__tests__/recipe-import.test.ts \
  frontend/src/__tests__/recipe-export.test.ts \
  frontend/src/utils/__tests__/bugReportContext.test.ts
pnpm --dir frontend build
git diff --check
```

Expected: `rg` returns no direct bead source import; all host and recipe gates PASS.

- [ ] **Step 6: Commit**

```bash
git add -u frontend docs
git add frontend docs
git commit -m "refactor(workshop): remove in-tree bead module"
```

## Task 13: Announce the installable Workshop and run packaged acceptance

**Files in `Lumina-studio`:**

- Modify: `frontend/src/data/announcements.ts`
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `docs/context/workshop/CONTEXT.md`
- Modify: `CONTEXT-MAP.md`
- Create: `docs/release-checklists/workshop-v1.md`

- [ ] **Step 1: Read the announcement rules at execution time**

Re-read:

```text
docs/announcement-maintenance.md
```

Use the actual Beijing publish date. If no existing category fits, add the bilingual category `创意工坊` / `Creative Workshop` once, preserving the documented category order. User-facing copy describes:

- the new installable Creative Workshop;
- the preinstalled 拼豆工作台;
- image-chart analysis, cell correction, live fusion preview, and handoff to existing image conversion;
- installing, disabling, updating, rolling back, and uninstalling modules.

Do not mention RPC, iframe, registry schema, seed lock, reducer, endpoint, or internal repositories in announcement copy.

- [ ] **Step 2: Add a release checklist with evidence slots filled during execution**

`docs/release-checklists/workshop-v1.md` records:

- exact host commit;
- SDK Release URL and SHA-256;
- module Release URL and SHA-256;
- Registry commit, key ID, deployed URL, and verified signature result;
- seed-lock hash equality;
- Windows/macOS packaged build identifiers;
- light/dark and Chinese/English screenshots;
- offline start;
- update/rollback;
- uninstall/restart/no-resurrection;
- explicit bundled-seed restore;
- safe-mode recovery;
- converter handoff and share-card round-trip.

The checklist may not say PASS without attached command or human-flow evidence.

- [ ] **Step 3: Run announcement and complete automated gates**

```bash
pnpm --dir frontend exec tsc --noEmit
./.venv/bin/python scripts/run_vitest.py run \
  frontend/src/__tests__/useAnnouncement.test.ts \
  frontend/src/__tests__/announcement-dialog.test.tsx
./.venv/bin/python -m pytest \
  tests/test_workshop_package_unit.py \
  tests/test_workshop_registry_unit.py \
  tests/test_workshop_installer_unit.py \
  tests/test_workshop_api_unit.py \
  tests/test_workshop_seed_sync_unit.py \
  tests/test_workshop_seed_bundle_unit.py \
  tests/test_workshop_seed_lifecycle_unit.py \
  tests/test_workshop_release_chain_unit.py \
  tests/test_desktop_build_contract_unit.py \
  tests/test_logging_exception_governance_unit.py \
  tests/test_structured_logging_unit.py \
  tests/test_logger_unit.py -v
./.venv/bin/python scripts/log_quality_check.py --mode fast
pnpm --dir electron test
pnpm --dir frontend build
git diff --check
```

Expected: every command PASS.

- [ ] **Step 4: Build and test real packaged applications**

Build with the already verified seed asset:

```bash
WORKSHOP_SEED_CACHE="/Users/min/.cache/lumina-workshop-release/bead-v1.0.0"
test -f "$WORKSHOP_SEED_CACHE/lumina.bead-pattern-1.0.0.lumina-workshop"
./.venv/bin/python scripts/build_desktop.py \
  --workshop-seed-path "$WORKSHOP_SEED_CACHE/lumina.bead-pattern-1.0.0.lumina-workshop"
```

On both a signed/notarized macOS build and a signed Windows build, verify:

1. first launch shows the official module installed from seed;
2. first open performs sandbox handshake and activation;
3. a clear chart reaches calibration, editing, fusion preview, save, refresh, and converter handoff;
4. the module process is isolated from the top frame;
5. module-originated HTTP, HTTPS, WebSocket, popup, download, cross-module, and navigation attempts are blocked;
6. offline relaunch opens the installed module;
7. a broken candidate rolls back to 1.0.0 with projects intact;
8. uninstall retains projects by default;
9. app restart does not reinstall an explicitly uninstalled official module;
10. “从安装包恢复” reinstalls it offline only after explicit confirmation;
11. three start failures enter safe mode without breaking Settings, image conversion, or vectorization;
12. 1280×720 keeps Installed/Discover cards and permission controls visible and clickable;
13. Chinese/English and light/dark content has no clipping, duplicate selection signals, or persistent mouse focus ring.

Stop all local launchers and test helpers after acceptance:

```bash
./.venv/bin/python start_all.py --kill
```

- [ ] **Step 5: Commit, push, and open the host PR**

```bash
git add frontend/src/data/announcements.ts frontend/src/i18n/translations.ts docs CONTEXT-MAP.md
git commit -m "docs(workshop): announce installable official modules"
git push -u origin MOVIBALE/feat/workshop-registry-seed
gh pr create \
  --base dev-refactor \
  --head MOVIBALE/feat/workshop-registry-seed \
  --title "feat: ship the signed Workshop Registry and official seed" \
  --body-file /tmp/workshop-registry-seed-pr.md
```

The PR body is English first and Chinese second. It links all three repository PRs/releases, distinguishes automated from packaged-human evidence, lists signing/notarization status, and marks any untested platform as `partial`, `fix_not_verified`, or `regression_risk`.

## Final release checkpoint

Release only when:

- the production Registry key is outside Git and only its public half is bundled;
- deployed Registry bytes verify with the bundled public key;
- Registry, seed lock, downloaded package, and module manifest agree on identity, version, permissions, sizes, and hashes;
- the SDK dependency and Workshop API range are immutable and compatible;
- the official package installs through the normal installer and activates only after ready;
- offline seed restore works, while automatic resurrection after user uninstall does not;
- the external module owns every bead-specific source and test;
- the main repository has no direct bead implementation import;
- source-color PNG handoff and existing Lumina conversion/share-card round-trip pass;
- packaged Electron isolation and network-blocking acceptance pass on every claimed platform;
- the release checklist contains fresh command and human-flow evidence.
