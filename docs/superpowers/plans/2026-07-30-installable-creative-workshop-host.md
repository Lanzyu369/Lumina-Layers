# Installable Creative Workshop Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the source-integrated Workshop registry with a package-backed, capability-scoped host that can install, run, update, disable, roll back, and uninstall `.lumina-workshop` modules.

**Architecture:** Python owns package, Registry, signature, install-state, and filesystem boundaries. React owns the Workshop manager, IndexedDB project namespaces, MessageChannel RPC, converter handoff, and host-owned UI. Electron serves each module through a `lumina-workshop://<module-id>/` iframe origin, blocks module-originated network requests, and refuses community execution when process isolation is unavailable; ordinary browser mode runs only the official seed and synthetic fixtures.

**Tech Stack:** Python 3, FastAPI, Pydantic, `cryptography` Ed25519, React 19, TypeScript, Zustand, IndexedDB, MessageChannel, Electron 35, pnpm, pytest, Vitest, Node test runner

---

## Scope and delivery order

This plan applies to the `Lumina-studio` repository. It depends on the approved design:

- `docs/superpowers/specs/2026-07-30-installable-creative-workshop-design.md`

The current `MOVIBALE/feat/creative-workshop-bead-mode` branch contains the
unmerged migration reference named throughout this plan, so create the host
branch from the committed planning tip rather than silently dropping those
files by branching from `origin/dev-refactor`:

```bash
test -z "$(git status --short)"
PLANNING_BASE_SHA="$(git rev-parse MOVIBALE/feat/creative-workshop-bead-mode)"
git switch -c MOVIBALE/feat/installable-creative-workshop-host "$PLANNING_BASE_SHA"
```

The host PR still targets `dev-refactor` and therefore contains the existing
prototype history plus its package-backed replacement. If the prototype branch
is merged independently before execution, use that exact protected-branch merge
commit as the base instead and record the change in the PR.

Do not delete `frontend/src/workshop/modules/bead/` in this plan. It remains a migration reference until the external official package passes the seed integration plan. It must stop being imported by the running Workshop shell.

## File map

### Public SDK

- `workshop-sdk/package.json`: independently packable SDK metadata and scripts.
- `workshop-sdk/pnpm-lock.yaml`: frozen SDK dependency graph.
- `workshop-sdk/tsconfig.json`: SDK-only TypeScript build.
- `workshop-sdk/src/contracts.ts`: public manifest, capability, handoff, project, and RPC types.
- `workshop-sdk/src/client.ts`: iframe-side handshake and typed RPC client.
- `workshop-sdk/src/theme.ts`: applies host locale/theme tokens inside the iframe.
- `workshop-sdk/src/index.ts`: public exports.
- `workshop-sdk/README.md`: versioned public API and package-development guide.
- `workshop-sdk/LICENSE`: SDK redistribution terms.
- `workshop-sdk/test/contracts.test.mjs`: built-package contract smoke test.

### Python package and Registry boundary

- `core/workshop/__init__.py`: public core exports.
- `core/workshop/constants.py`: hard package, timeout, and compatibility limits.
- `core/workshop/errors.py`: typed domain errors.
- `core/workshop/models.py`: immutable manifest, Registry, and install-state models.
- `core/workshop/package_validator.py`: safe ZIP inspection and extraction.
- `core/workshop/registry_client.py`: Ed25519 verification, cache, snapshot, and catalog selection.
- `core/workshop/install_store.py`: atomic install-state persistence.
- `core/workshop/installer.py`: candidate install, activation, rollback, disable, and uninstall transactions.
- `api/schemas/workshop.py`: HTTP request and response schemas.
- `api/routers/workshop.py`: `/api/workshop/v1` routes and structured logging.
- `assets/workshop-registry/keys.json`: allowed Registry public-key set; empty until the Registry release plan installs the real key.
- `assets/workshop-registry/registry-v1.json`: empty offline catalog snapshot.

### Frontend host

- `frontend/src/api/workshop.ts`: Workshop HTTP client.
- `frontend/src/workshop/contracts.ts`: host-only types derived from the public SDK.
- `frontend/src/workshop/runtime/rpcHost.ts`: MessageChannel dispatcher, request limits, and identity checks.
- `frontend/src/workshop/runtime/WorkshopFrame.tsx`: sandbox iframe lifecycle.
- `frontend/src/workshop/runtime/capabilities.ts`: permission-to-method enforcement.
- `frontend/src/workshop/runtime/health.ts`: ready, crash, timeout, and three-strike state.
- `frontend/src/workshop/projectStorage.ts`: quota, snapshot, restore, and namespace persistence.
- `frontend/src/workshop/colorLibrary.ts`: normalized current LUT/material selection.
- `frontend/src/workshop/WorkshopSourceBanner.tsx`: converter-side module
  provenance, physical-size handoff, and print-library guidance.
- `frontend/src/workshop/WorkshopPanel.tsx`: Installed, Discover, and Developer views.
- `frontend/src/workshop/ModuleDetails.tsx`: source, version, permission, update, rollback, and uninstall UI.
- `frontend/src/workshop/store.ts`: manager state without module payload persistence.

### Desktop security

- `electron/workshop-security.cjs`: custom scheme, runtime token, request firewall, and testable URL decisions.
- `electron/main.cjs`: installs the security boundary before creating the main window.
- `electron/preload.cjs`: exposes only non-secret runtime status.
- `electron/__tests__/workshop-security.test.cjs`: request-firewall unit tests.

### Compatibility, docs, and tests

- `frontend/src/recipe/importRecipe.ts`: structural Workshop recipe-envelope validation without importing a module.
- `frontend/src/recipe/types.ts`: retain the v3 bounded Workshop envelope.
- `frontend/src/utils/bugReportContext.ts`: source/audit/runtime status only.
- `frontend/src/i18n/translations.ts`: all Workshop manager strings.
- `docs/workshop-module-development.md`: replace source-whitelist instructions with package/SDK instructions.
- `CONTEXT-MAP.md`: add the Workshop domain.
- `docs/context/workshop/CONTEXT.md`: authoritative implementation boundary and verification commands.
- `tests/test_workshop_package_unit.py`
- `tests/test_workshop_registry_unit.py`
- `tests/test_workshop_installer_unit.py`
- `tests/test_workshop_api_unit.py`
- `frontend/src/__tests__/workshop-rpc-host.test.ts`
- `frontend/src/__tests__/workshop-runtime.test.tsx`
- `frontend/src/__tests__/workshop-manager.test.tsx`
- `frontend/src/__tests__/workshop-project-storage.test.ts`

## Task 1: Publish one canonical SDK contract

**Files:**

- Create: `workshop-sdk/package.json`
- Create: `workshop-sdk/pnpm-lock.yaml` via the pinned pnpm install
- Create: `workshop-sdk/tsconfig.json`
- Create: `workshop-sdk/src/contracts.ts`
- Create: `workshop-sdk/src/index.ts`
- Create: `workshop-sdk/README.md`
- Create: `workshop-sdk/LICENSE`
- Create: `workshop-sdk/test/contracts.test.mjs`
- Modify: `package.json`

- [ ] **Step 1: Write the package contract test**

```js
// workshop-sdk/test/contracts.test.mjs
import assert from "node:assert/strict";
import test from "node:test";

import {
  WORKSHOP_API_VERSION,
  WORKSHOP_MANIFEST_VERSION,
  WORKSHOP_PERMISSION_NAMES,
  createRequestEnvelope,
} from "../dist/index.js";

test("exports stable v1 identities and permission names", () => {
  assert.equal(WORKSHOP_API_VERSION, "1.0.0");
  assert.equal(WORKSHOP_MANIFEST_VERSION, 1);
  assert.deepEqual(WORKSHOP_PERMISSION_NAMES, [
    "image.pick",
    "project.storage",
    "color-library.read",
    "handoff.image",
  ]);
});

test("creates a bounded protocol request envelope", () => {
  assert.deepEqual(
    createRequestEnvelope("req-1", "ui.getState", {}),
    {
      protocol: "lumina-workshop-rpc",
      version: 1,
      kind: "request",
      requestId: "req-1",
      method: "ui.getState",
      payload: {},
    },
  );
});
```

- [ ] **Step 2: Run the test and verify that the package does not exist**

Run:

```bash
pnpm --dir workshop-sdk test
```

Expected: FAIL because `workshop-sdk/package.json` and `dist/index.js` do not exist.

- [ ] **Step 3: Add the SDK package and exact public types**

`workshop-sdk/package.json`:

```json
{
  "name": "@lumina/workshop-sdk",
  "version": "1.0.0",
  "type": "module",
  "packageManager": "pnpm@10.33.2",
  "files": ["dist", "README.md", "LICENSE"],
  "exports": {
    ".": {
      "types": "./dist/index.d.ts",
      "import": "./dist/index.js"
    }
  },
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "pnpm run build && node --test test/*.test.mjs",
    "pack:release": "pnpm run test && pnpm pack --pack-destination dist-package"
  },
  "devDependencies": {
    "typescript": "~5.8.3"
  }
}
```

`workshop-sdk/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "Bundler",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "declaration": true,
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "skipLibCheck": true
  },
  "include": ["src/**/*.ts"]
}
```

```ts
// workshop-sdk/src/contracts.ts
export const WORKSHOP_API_VERSION = "1.0.0" as const;
export const WORKSHOP_MANIFEST_VERSION = 1 as const;
export const WORKSHOP_RPC_VERSION = 1 as const;

export const WORKSHOP_PERMISSION_NAMES = [
  "image.pick",
  "project.storage",
  "color-library.read",
  "handoff.image",
] as const;

export type WorkshopPermissionName =
  (typeof WORKSHOP_PERMISSION_NAMES)[number];

export interface LocalizedText {
  "zh-CN": string;
  "en-US": string;
}

export interface WorkshopManifestV1 {
  manifestVersion: typeof WORKSHOP_MANIFEST_VERSION;
  id: string;
  version: string;
  name: LocalizedText;
  description: LocalizedText;
  publisher: string;
  workshopApi: {
    min: string;
    maxExclusive: string;
  };
  luminaVersion: {
    min: string;
  };
  entrypoints: {
    ui: "ui/index.html";
  };
  permissions: Array<{
    name: WorkshopPermissionName;
    reason: string;
  }>;
}

export interface WorkshopRaster {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

export interface WorkshopPickedImage {
  name: string;
  mimeType: string;
  bytes: ArrayBuffer;
  raster: WorkshopRaster;
}

export interface WorkshopRecipeSource {
  manifestSchemaVersion: 1;
  moduleId: string;
  moduleVersion: string;
  projectSchemaVersion: string;
  renderSchemaVersion: string;
  payload: Record<string, unknown>;
}

export interface WorkshopSquareGridLayout {
  kind: "square-grid";
  rows: number;
  columns: number;
  pitchMm: number;
}

export interface WorkshopImageHandoff {
  moduleId: string;
  moduleVersion: string;
  projectId: string;
  pngBytes: ArrayBuffer;
  pixelWidth: number;
  pixelHeight: number;
  recommendedWidthMm: number;
  recommendedHeightMm: number;
  preserveCanvasBounds: true;
  layout?: WorkshopSquareGridLayout;
  colorLibraryId: string | null;
  recipeSource: WorkshopRecipeSource;
}

export interface WorkshopProjectRecord<T = unknown> {
  projectId: string;
  schemaVersion: string;
  createdAt: string;
  updatedAt: string;
  project: T;
}

export interface WorkshopColorEntry {
  id: string;
  label: string;
  hex: string;
  materialId: string | null;
}

export interface WorkshopColorLibrary {
  id: string;
  label: string;
  sourceKind: "lut" | "material-archive" | "native-bundle";
  colors: WorkshopColorEntry[];
}

export interface WorkshopUiState {
  locale: "zh-CN" | "en-US";
  theme: "light" | "dark";
  tokens: Record<string, string>;
}

export type WorkshopRpcMethod =
  | "image.pick"
  | "project.save"
  | "project.load"
  | "project.latest"
  | "project.remove"
  | "colorLibrary.read"
  | "handoff.image"
  | "ui.getState"
  | "status.progress"
  | "status.error"
  | "status.diagnostics"
  | "lifecycle.ready";

export interface WorkshopRpcRequest {
  protocol: "lumina-workshop-rpc";
  version: typeof WORKSHOP_RPC_VERSION;
  kind: "request";
  requestId: string;
  method: WorkshopRpcMethod;
  payload: unknown;
}

export interface WorkshopRpcResponse {
  protocol: "lumina-workshop-rpc";
  version: typeof WORKSHOP_RPC_VERSION;
  kind: "response";
  requestId: string;
  ok: boolean;
  result?: unknown;
  error?: {
    code: string;
    message: string;
    retryable: boolean;
  };
}

export function createRequestEnvelope(
  requestId: string,
  method: WorkshopRpcMethod,
  payload: unknown,
): WorkshopRpcRequest {
  return {
    protocol: "lumina-workshop-rpc",
    version: WORKSHOP_RPC_VERSION,
    kind: "request",
    requestId,
    method,
    payload,
  };
}
```

```ts
// workshop-sdk/src/index.ts
export * from "./contracts.js";
export * from "./client.js";
export * from "./theme.js";
```

Add the root script:

```json
"build:workshop-sdk": "pnpm --dir workshop-sdk run build"
```

- [ ] **Step 4: Run the SDK test**

Run:

```bash
pnpm --dir workshop-sdk install
pnpm --dir workshop-sdk test
```

Expected: both Node tests PASS and `workshop-sdk/dist/index.d.ts` exists.

- [ ] **Step 5: Commit the contract**

```bash
git add package.json workshop-sdk
git commit -m "feat(workshop): publish v1 SDK contracts"
```

## Task 2: Implement iframe-side connection and theme helpers

**Files:**

- Create: `workshop-sdk/src/client.ts`
- Create: `workshop-sdk/src/theme.ts`
- Modify: `workshop-sdk/test/contracts.test.mjs`

- [ ] **Step 1: Add a failing connection test using a fake parent window**

```js
test("connects only after the host transfers a MessagePort", async () => {
  const channel = new MessageChannel();
  const posted = [];
  const fakeWindow = {
    parent: {
      postMessage(message) {
        posted.push(message);
      },
    },
    addEventListener(_name, listener) {
      queueMicrotask(() => listener({
        data: {
          type: "lumina.workshop.connect",
          sessionId: "session-1",
        },
        ports: [channel.port2],
      }));
    },
    removeEventListener() {},
  };

  const client = await connectWorkshop({
    moduleId: "fixture.hello",
    moduleVersion: "1.0.0",
    windowObject: fakeWindow,
  });

  assert.equal(posted[0].type, "lumina.workshop.ready");
  assert.equal(client.sessionId, "session-1");
  client.close();
});
```

- [ ] **Step 2: Run the test and verify the missing export**

Run:

```bash
pnpm --dir workshop-sdk test
```

Expected: FAIL because `connectWorkshop` is not exported.

- [ ] **Step 3: Implement the ready/connect handshake and typed client**

`client.ts` must:

- send `lumina.workshop.ready` with module ID, module version, and API version;
- accept only `lumina.workshop.connect` with exactly one transferred port;
- reject after 10 seconds;
- generate monotonic request IDs;
- map responses by request ID;
- use 30-second default and 120-second handoff timeouts;
- expose `image`, `projects`, `colorLibrary`, `handoff`, `ui`, `status`, and `lifecycle` methods;
- transfer image and PNG `ArrayBuffer` values instead of base64;
- reject malformed or duplicate responses with `WorkshopClientError`.

Use this public shape:

```ts
export interface WorkshopClient {
  readonly sessionId: string;
  image: {
    pick(): Promise<WorkshopPickedImage | null>;
  };
  projects: {
    save<T>(record: WorkshopProjectRecord<T>): Promise<void>;
    load<T>(projectId: string): Promise<WorkshopProjectRecord<T> | null>;
    latest<T>(): Promise<WorkshopProjectRecord<T> | null>;
    remove(projectId: string): Promise<void>;
  };
  colorLibrary: {
    read(): Promise<WorkshopColorLibrary | null>;
  };
  handoff: {
    image(value: WorkshopImageHandoff): Promise<
      { status: "needs-confirmation" | "completed" }
    >;
  };
  ui: {
    getState(): Promise<WorkshopUiState>;
  };
  status: {
    progress(value: {
      phase: string;
      completed: number;
      total: number;
    } | null): Promise<void>;
    error(value: {
      code: string;
      message: string;
      retryable: boolean;
    } | null): Promise<void>;
    diagnostics(value: Record<string, string | number | boolean | null>): Promise<void>;
  };
  lifecycle: {
    ready(): Promise<void>;
  };
  close(): void;
}
```

`theme.ts` must apply only the host-provided public token map:

```ts
export function applyWorkshopUiState(
  state: WorkshopUiState,
  root: HTMLElement = document.documentElement,
): void {
  root.lang = state.locale;
  root.dataset.theme = state.theme;
  for (const [name, value] of Object.entries(state.tokens)) {
    if (/^--lumina-[a-z0-9-]+$/.test(name)) {
      root.style.setProperty(name, value);
    }
  }
}
```

- [ ] **Step 4: Re-run the SDK tests**

Run:

```bash
pnpm --dir workshop-sdk test
```

Expected: PASS, including timeout cleanup and `close()` rejecting pending requests.

- [ ] **Step 5: Commit**

```bash
git add workshop-sdk
git commit -m "feat(workshop): add sandbox RPC client"
```

## Task 3: Validate manifests and ZIP packages without executing them

**Files:**

- Create: `core/workshop/__init__.py`
- Create: `core/workshop/constants.py`
- Create: `core/workshop/errors.py`
- Create: `core/workshop/models.py`
- Create: `core/workshop/package_validator.py`
- Create: `tests/test_workshop_package_unit.py`

- [ ] **Step 1: Write failing tests for valid packages and archive attacks**

The test helper must create ZIPs in memory and cover:

```python
def test_valid_package_is_inspected_without_execution(tmp_path: Path) -> None:
    archive = write_workshop_zip(
        tmp_path,
        manifest=valid_manifest(),
        files={
            "ui/index.html": b"<!doctype html><html><head></head><body>ok</body></html>",
            "assets/icon.png": PNG_1X1,
            "README.md": b"# Fixture",
            "LICENSE": b"MIT",
        },
    )
    inspected = inspect_workshop_package(archive)
    assert inspected.manifest.id == "fixture.hello"
    assert inspected.entry_html == "ui/index.html"
    assert inspected.compressed_bytes == archive.stat().st_size


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("../escape.txt", "unsafe archive path"),
        ("/absolute.txt", "unsafe archive path"),
        ("UI/index.html", "case-insensitive duplicate"),
    ],
)
def test_archive_paths_fail_closed(
    tmp_path: Path,
    name: str,
    message: str,
) -> None:
    archive = write_raw_zip(tmp_path, [("ui/index.html", b"ok"), (name, b"x")])
    with pytest.raises(WorkshopPackageError, match=message):
        inspect_workshop_package(archive)


def test_zip_bomb_ratio_is_rejected(tmp_path: Path) -> None:
    archive = write_raw_zip(
        tmp_path,
        [("ui/index.html", b"0" * (2 * 1024 * 1024))],
    )
    with pytest.raises(WorkshopPackageError, match="compression ratio"):
        inspect_workshop_package(archive, max_ratio=2)
```

Also test symlink `external_attr`, 2,001 files, 101 MiB declared file size, 301 MiB aggregate declared size, missing fixed files, extra manifest fields, invalid SemVer, unknown permission, blank permission reason, non-single-file HTML references, and executable files outside `ui/index.html`.
Add media/document abuse cases: oversized manifest, icon, README, or license;
non-PNG icon; animated PNG; decompression-bomb dimensions; SVG/HTML in gallery;
more than 20 gallery images; and malformed UTF-8 docs.

- [ ] **Step 2: Run the focused test**

Run:

```bash
./.venv/bin/python -m pytest tests/test_workshop_package_unit.py -v
```

Expected: FAIL on missing `core.workshop`.

- [ ] **Step 3: Add exact v1 constants and safe extraction**

```python
# core/workshop/constants.py
WORKSHOP_API_VERSION = "1.0.0"
WORKSHOP_MANIFEST_VERSION = 1
MAX_PACKAGE_BYTES = 100 * 1024 * 1024
MAX_UNPACKED_BYTES = 300 * 1024 * 1024
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_FILE_COUNT = 2_000
MAX_COMPRESSION_RATIO = 100.0
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_EDGE = 16_384
MAX_IMAGE_PIXELS = 64_000_000
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ICON_BYTES = 2 * 1024 * 1024
MAX_ICON_PIXELS = 1_048_576
MAX_GALLERY_FILES = 20
MAX_GALLERY_FILE_BYTES = 5 * 1024 * 1024
MAX_GALLERY_PIXELS = 16_000_000
MAX_TEXT_DOCUMENT_BYTES = 1024 * 1024
REQUIRED_PACKAGE_FILES = frozenset(
    {"manifest.json", "ui/index.html", "assets/icon.png", "README.md", "LICENSE"}
)
ALLOWED_PERMISSION_NAMES = frozenset(
    {"image.pick", "project.storage", "color-library.read", "handoff.image"}
)
```

`models.py` must use frozen Pydantic models with `extra="forbid"` and aliases that match `manifest.json` exactly. `package_validator.py` must:

1. reject any input larger than `MAX_PACKAGE_BYTES` before opening ZIP;
2. normalize every member with `PurePosixPath`;
3. reject absolute, `..`, empty, backslash, device, symlink, and case-fold duplicate paths;
4. check declared and actual sizes before extraction;
5. require only `ui/index.html` as an executable entry;
6. require `<head>` before the first `<script>`;
7. reject `src=`, `href=`, `url(`, `eval`, and dynamic `import(` references to HTTP(S) or package files in the runtime HTML;
8. allow optional gallery files only below `assets/gallery/` with PNG, JPEG, or
   WebP signatures; reject SVG, animation, metadata-driven external references,
   excessive decoded dimensions, and more than 20 entries;
9. require a static PNG icon with bounded encoded/decoded size and require
   manifest/README/license to meet their per-file limits and UTF-8 text rules;
10. extract into a caller-supplied temporary directory only after all static
    checks pass.

The module also exposes a read-only CLI:

```bash
./.venv/bin/python -m core.workshop.package_validator path/to/module.lumina-workshop
```

It prints bounded JSON containing module ID, version, manifest digest, archive
digest, compressed bytes, and unpacked bytes. It never extracts, executes, or
prints HTML/package contents.

The public functions are:

```python
def inspect_workshop_package(
    archive_path: str | Path,
    *,
    max_ratio: float = MAX_COMPRESSION_RATIO,
) -> InspectedWorkshopPackage:
    """Inspect one Workshop package without executing module code.
    在不执行模块代码的前提下检查一个创意工坊安装包。
    """


def extract_inspected_package(
    inspected: InspectedWorkshopPackage,
    destination: str | Path,
) -> Path:
    """Extract an already-inspected package into an empty directory.
    将已检查的安装包解压到空目录。
    """
```

- [ ] **Step 4: Run package tests and encoding checks**

Run:

```bash
./.venv/bin/python -m pytest tests/test_workshop_package_unit.py -v
git diff --check
```

Expected: PASS; no archive member is written outside the temporary directory.

- [ ] **Step 5: Commit**

```bash
git add core/workshop tests/test_workshop_package_unit.py
git commit -m "feat(workshop): validate installable packages"
```

## Task 4: Verify and cache a signed Registry index

**Files:**

- Create: `core/workshop/registry_client.py`
- Create: `assets/workshop-registry/keys.json`
- Create: `assets/workshop-registry/registry-v1.json`
- Create: `tests/test_workshop_registry_unit.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write failing Registry tests**

Use `cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey.generate()` inside tests. Verify:

```python
def test_verified_index_replaces_cache(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = canonical_registry_bytes(registry_fixture())
    signature = private_key.sign(payload)
    client = RegistryClient(
        keys={"test-key": private_key.public_key()},
        cache_dir=tmp_path,
        snapshot_path=write_snapshot(tmp_path),
        fetch_bytes=fake_fetch(payload, signature),
    )
    result = client.refresh()
    assert result.source == "remote"
    assert result.verified is True
    assert (tmp_path / "registry-v1.json").read_bytes() == payload


def test_bad_signature_keeps_previous_verified_cache(tmp_path: Path) -> None:
    cached = write_verified_cache(tmp_path, registry_fixture(version="1.0.0"))
    client = client_with_invalid_remote(tmp_path)
    result = client.refresh()
    assert result.source == "cache"
    assert result.index == cached
```

Also test unknown `keyId`, malformed JSON, duplicate module/version, invalid SHA-256, blocked/deprecated states, ETag `304`, no network with snapshot fallback, and that a blocked version is never selected for installation.

- [ ] **Step 2: Run the focused tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_workshop_registry_unit.py -v
```

Expected: FAIL because `RegistryClient` does not exist.

- [ ] **Step 3: Add Ed25519 verification and atomic cache writes**

Add:

```text
cryptography>=44.0.0,<46.0.0
```

`RegistryClient.refresh()` must:

- fetch `registry-v1.json` and `registry-v1.sig` with a 15-second connection timeout and 60-second inactivity timeout;
- canonicalize only by accepting the exact downloaded JSON bytes covered by the signature;
- parse detached signature metadata with exactly `algorithm`, `keyId`, and
  `signature` fields; require `algorithm == "Ed25519"` and a base64 value that
  decodes to exactly 64 signature bytes;
- verify against the app-owned key set;
- write JSON, signature, ETag, and verification timestamp to temporary siblings and `os.replace()` them;
- keep the previous verified cache on any remote error;
- use the bundled snapshot only when no verified cache exists;
- never let the Registry file add or replace trusted public keys.

Commit an empty bootstrap configuration:

`assets/workshop-registry/keys.json`:

```json
{
  "schemaVersion": 1,
  "keys": []
}
```

`assets/workshop-registry/registry-v1.json`:

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-07-30T00:00:00Z",
  "modules": []
}
```

Read both files from `assets/workshop-registry/`.

- [ ] **Step 4: Run Registry and frozen-resource tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_workshop_registry_unit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt assets/workshop-registry core/workshop tests
git commit -m "feat(workshop): verify signed registry indexes"
```

## Task 5: Make installation and version switching transactional

**Files:**

- Create: `core/workshop/install_store.py`
- Create: `core/workshop/installer.py`
- Create: `tests/test_workshop_installer_unit.py`
- Modify: `config.py`

- [ ] **Step 1: Write failing install lifecycle tests**

Cover:

```python
def test_candidate_install_does_not_replace_active_version(tmp_path: Path) -> None:
    installer = installer_for(tmp_path)
    installer.install_candidate(package("fixture.hello", "1.0.0"))
    installer.activate("fixture.hello", "1.0.0")
    installer.install_candidate(package("fixture.hello", "1.1.0"))

    state = installer.get("fixture.hello")
    assert state.active_version == "1.0.0"
    assert state.candidate_version == "1.1.0"


def test_activation_keeps_one_rollback_version(tmp_path: Path) -> None:
    installer = installer_for(tmp_path)
    install_and_activate(installer, "1.0.0")
    install_and_activate(installer, "1.1.0")
    assert installer.get("fixture.hello").previous_version == "1.0.0"
    installer.rollback("fixture.hello")
    assert installer.get("fixture.hello").active_version == "1.0.0"


def test_interrupted_extract_leaves_active_version_untouched(tmp_path: Path) -> None:
    installer = installer_for(tmp_path, fail_after_extract=True)
    install_and_activate(installer, "1.0.0")
    with pytest.raises(WorkshopInstallError):
        installer.install_candidate(package("fixture.hello", "1.1.0"))
    assert installer.get("fixture.hello").active_version == "1.0.0"
```

Also test uninstall preserving projects, explicit project deletion flag, official uninstall tombstone, enable/disable, candidate cleanup, cross-device rename rejection, and concurrent per-module locking.

- [ ] **Step 2: Run the focused tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_workshop_installer_unit.py -v
```

Expected: FAIL on missing installer.

- [ ] **Step 3: Implement paths, state, and transactions**

Add a writable root resolver:

```python
def get_workshop_data_dir() -> str:
    """Return the mutable Workshop package root.
    返回创意工坊模块的可写数据目录。
    """
    override = os.environ.get("LUMINA_WORKSHOP_DATA_DIR", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(_desktop_user_data_dir(), "workshop")
```

Use this disk layout:

```text
workshop/
  install-state.json
  cache/registry-v1.json
  modules/<module-id>/<version>/
  staging/<transaction-id>/
```

`install-state.json` records:

```python
class InstalledModuleState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    module_id: str
    source: Literal["registry", "github", "local", "seed"]
    source_repository: str
    official: bool
    enabled: bool
    active_version: str | None
    previous_version: str | None
    candidate_version: str | None
    versions: tuple[str, ...]
    official_uninstalled: bool
    consecutive_start_failures: int
```

Every state write uses UTF-8 canonical JSON, `flush()`, `os.fsync()`, and `os.replace()`. Candidate extraction occurs under `staging/`, then one atomic rename moves the complete version directory into `modules/`. No operation overwrites an active directory.

- [ ] **Step 4: Run installer tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_workshop_installer_unit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py core/workshop tests/test_workshop_installer_unit.py
git commit -m "feat(workshop): add transactional module installer"
```

## Task 6: Expose a bounded Workshop API

**Files:**

- Create: `api/schemas/workshop.py`
- Create: `api/routers/workshop.py`
- Create: `tests/test_workshop_api_unit.py`
- Modify: `api/routers/__init__.py`
- Modify: `api/app.py`
- Modify: `tests/test_logging_exception_governance_unit.py`

- [ ] **Step 1: Write failing API tests**

Test these routes:

```text
GET    /api/workshop/v1/catalog
GET    /api/workshop/v1/modules
POST   /api/workshop/v1/install/registry
POST   /api/workshop/v1/install/github
POST   /api/workshop/v1/install/local
POST   /api/workshop/v1/modules/{module_id}/activate
POST   /api/workshop/v1/modules/{module_id}/rollback
PATCH  /api/workshop/v1/modules/{module_id}/enabled
DELETE /api/workshop/v1/modules/{module_id}
GET    /api/workshop/v1/modules/{module_id}/{version}/runtime
GET    /api/workshop/v1/modules/{module_id}/{version}/assets/{asset_path:path}
```

Required assertions include:

```python
def test_local_install_rejects_oversize_upload(client, monkeypatch) -> None:
    monkeypatch.setattr(workshop_router, "MAX_PACKAGE_BYTES", 1024)
    response = client.post(
        "/api/workshop/v1/install/local",
        files={"archive": ("bad.lumina-workshop", b"x" * 1025, "application/zip")},
    )
    assert response.status_code == 413


def test_community_runtime_requires_desktop_token(client, installed_community) -> None:
    response = client.get(
        f"/api/workshop/v1/modules/{installed_community.id}/1.0.0/runtime",
    )
    assert response.status_code == 403


def test_runtime_response_has_fixed_security_headers(
    client,
    installed_official,
) -> None:
    response = client.get(
        f"/api/workshop/v1/modules/{installed_official.id}/1.0.0/runtime",
    )
    assert response.headers["content-security-policy"].startswith(
        "default-src 'none';"
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
```

The test imports `api.routers.workshop` as `workshop_router`. Production keeps
the 100 MiB constant; this test lowers only the route's pre-buffer limit so the
suite does not allocate a 100 MiB request body.

- [ ] **Step 2: Run the API tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_workshop_api_unit.py -v
```

Expected: FAIL with route not found.

- [ ] **Step 3: Add schemas, routes, and governed log events**

Use typed requests:

```python
class RegistryInstallRequest(BaseModel):
    module_id: str = Field(min_length=3, max_length=200)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")


class GithubInstallRequest(BaseModel):
    repository_url: AnyHttpUrl
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")


class ModuleEnabledRequest(BaseModel):
    enabled: bool


class ModuleUninstallRequest(BaseModel):
    delete_projects: bool = False
```

Rules:

- accept only `https://github.com/<owner>/<repo>` for manual GitHub installs;
- resolve a full, non-draft, non-prerelease Release and exact standard asset;
- stream downloads with the design limits instead of buffering unbounded bytes;
- return only relative asset/runtime URLs;
- require `X-Lumina-Workshop-Desktop-Token` for non-official runtime HTML;
- inject the fixed CSP before the first module script;
- never expose package disk paths;
- map core errors to deterministic `400/403/404/409/413/422/502/503`;
- register `workshop_router` in `api/routers/__init__.py` and `api/app.py`.

Add these literal INFO events to the governance whitelist:

```python
"workshop_catalog_refresh_done",
"workshop_module_install_done",
"workshop_module_activate_done",
"workshop_module_rollback_done",
"workshop_module_enabled_done",
"workshop_module_uninstall_done",
```

Every WARNING/ERROR includes `error_type`, `error_message`, `module_id`, and `version` when known.

- [ ] **Step 4: Run API and logging governance tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_workshop_api_unit.py tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api core/workshop tests
git commit -m "feat(workshop): expose module management API"
```

## Task 7: Add quota-aware project storage and rollback snapshots

**Files:**

- Modify: `frontend/src/workshop/projectStorage.ts`
- Modify: `frontend/src/__tests__/workshop-project-storage.test.ts`

- [ ] **Step 1: Add failing quota and snapshot tests**

Add tests that assert:

```ts
it("rejects a write above the configured module quota", async () => {
  const first = recordWithPayload("fixture.hello", "one", new Uint8Array(32));
  const second = recordWithPayload("fixture.hello", "two", new Uint8Array(48));
  const firstBytes = estimateStructuredCloneBytes(first);
  const secondBytes = estimateStructuredCloneBytes(second);
  const storage = new IndexedDbWorkshopProjectStorage(
    new IDBFactory(),
    "quota-test",
    {
      moduleQuotaBytes: firstBytes + secondBytes - 1,
      recordQuotaBytes: Math.max(firstBytes, secondBytes),
    },
  );
  await storage.save(first);
  await expect(storage.save(second)).rejects.toMatchObject({
    code: "project-quota-exceeded",
  });
});

it("restores a pre-update snapshot without touching another module", async () => {
  await storage.save(recordWithPayload("fixture.hello", "p1", "before"));
  await storage.save(recordWithPayload("other.module", "p1", "foreign"));
  const snapshotId = await storage.snapshotModule("fixture.hello", "1.0.0");
  await storage.save(recordWithPayload("fixture.hello", "p1", "after"));
  await storage.restoreSnapshot("fixture.hello", snapshotId);
  expect((await storage.load("fixture.hello", "p1"))?.project).toBe("before");
  expect((await storage.load("other.module", "p1"))?.project).toBe("foreign");
});
```

Production defaults remain 256 MiB per module, 64 MiB per record, and 1 MiB
per recipe envelope. Also test each production boundary, atomic snapshot
replacement, uninstall preserving projects, explicit module-project deletion,
and byte estimation for `Blob`, `ArrayBuffer`, typed arrays, strings, arrays,
and records.

- [ ] **Step 2: Run the storage test**

Run:

```bash
./.venv/bin/python scripts/run_vitest.py run frontend/src/__tests__/workshop-project-storage.test.ts
```

Expected: FAIL because quota and snapshot APIs are missing.

- [ ] **Step 3: Upgrade IndexedDB to version 2**

Add object stores:

```text
projects    keyPath=key
snapshots   keyPath=key
metadata    keyPath=key
```

Add fixed defaults:

```ts
export const WORKSHOP_MODULE_QUOTA_BYTES = 256 * 1024 * 1024;
export const WORKSHOP_RECORD_QUOTA_BYTES = 64 * 1024 * 1024;
export const WORKSHOP_RECIPE_QUOTA_BYTES = 1 * 1024 * 1024;
```

Expose:

```ts
snapshotModule(moduleId: string, version: string): Promise<string>;
restoreSnapshot(moduleId: string, snapshotId: string): Promise<void>;
deleteSnapshot(moduleId: string, snapshotId: string): Promise<void>;
deleteModuleProjects(moduleId: string): Promise<void>;
estimateStoredBytes(value: unknown): number;
```

The snapshot and restore operations use one read-write transaction across all affected stores. Reject cyclic values and non-cloneable objects before opening the transaction.

- [ ] **Step 4: Run storage tests**

Run:

```bash
./.venv/bin/python scripts/run_vitest.py run frontend/src/__tests__/workshop-project-storage.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/workshop/projectStorage.ts frontend/src/__tests__/workshop-project-storage.test.ts
git commit -m "feat(workshop): enforce project quotas and snapshots"
```

## Task 8: Build the host-side RPC dispatcher

**Files:**

- Create: `frontend/src/workshop/contracts.ts`
- Create: `frontend/src/workshop/runtime/capabilities.ts`
- Create: `frontend/src/workshop/runtime/rpcHost.ts`
- Create: `frontend/src/__tests__/workshop-rpc-host.test.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml`

- [ ] **Step 1: Add failing permission, identity, size, and rate tests**

Use a fake `MessagePort` and assert:

```ts
it("denies an undeclared method before calling the handler", async () => {
  const handler = vi.fn();
  const host = createWorkshopRpcHost({
    identity: { moduleId: "fixture.hello", moduleVersion: "1.0.0" },
    permissions: new Set(),
    handlers: { "image.pick": handler },
  });
  const response = await host.dispatch(request("image.pick", {}));
  expect(response).toMatchObject({
    ok: false,
    error: { code: "permission-denied" },
  });
  expect(handler).not.toHaveBeenCalled();
});

it("rejects a control payload above 1 MiB", async () => {
  const response = await host.dispatch(
    request("project.save", { value: "x".repeat(1024 * 1024 + 1) }),
  );
  expect(response).toMatchObject({
    ok: false,
    error: { code: "rpc-payload-too-large" },
  });
});

it("uses a 30 per second sustained and 60 burst token bucket", async () => {
  const results = await Promise.all(
    Array.from({ length: 61 }, (_, index) =>
      host.dispatch(request("ui.getState", { index })),
    ),
  );
  expect(results.at(-1)).toMatchObject({
    ok: false,
    error: { code: "rpc-rate-limited" },
  });
});
```

Also test duplicate request ID, unknown method, wrong protocol version, 30-second timeout, 120-second handoff timeout, cancellation on frame close, binary payload above 64 MiB, and baseline UI/status methods without manifest permission entries.

- [ ] **Step 2: Run the RPC tests**

Run:

```bash
./.venv/bin/python scripts/run_vitest.py run frontend/src/__tests__/workshop-rpc-host.test.ts
```

Expected: FAIL because the dispatcher is missing.

- [ ] **Step 3: Implement the dispatcher and permission table**

Install the local SDK as a frontend dependency:

```json
"@lumina/workshop-sdk": "file:../workshop-sdk"
```

Use this exact permission map:

```ts
export const METHOD_PERMISSION = {
  "image.pick": "image.pick",
  "project.save": "project.storage",
  "project.load": "project.storage",
  "project.latest": "project.storage",
  "project.remove": "project.storage",
  "colorLibrary.read": "color-library.read",
  "handoff.image": "handoff.image",
  "ui.getState": null,
  "status.progress": null,
  "status.error": null,
  "status.diagnostics": null,
  "lifecycle.ready": null,
} as const satisfies Record<
  WorkshopRpcMethod,
  WorkshopPermissionName | null
>;
```

`createWorkshopRpcHost()` must accept immutable identity, declared permissions, handler functions, a monotonic clock, and a scheduler. It returns `dispatch()`, `attach(port)`, and `close()`. It must never pass the raw module payload to Zustand or converter stores before method-specific validation.

- [ ] **Step 4: Run SDK, RPC, and TypeScript tests**

Run:

```bash
pnpm --dir workshop-sdk test
./.venv/bin/python scripts/run_vitest.py run frontend/src/__tests__/workshop-rpc-host.test.ts
pnpm --dir frontend build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/workshop frontend/src/__tests__/workshop-rpc-host.test.ts
git commit -m "feat(workshop): enforce sandbox RPC capabilities"
```

## Task 9: Normalize color libraries and converter handoff

**Files:**

- Create: `frontend/src/workshop/colorLibrary.ts`
- Create: `frontend/src/workshop/WorkshopSourceBanner.tsx`
- Create: `frontend/src/__tests__/workshop-color-library.test.ts`
- Create: `frontend/src/__tests__/workshop-source-banner.test.tsx`
- Modify: `frontend/src/workshop/converterHandoff.ts`
- Modify: `frontend/src/__tests__/workshop-handoff.test.ts`
- Modify: `frontend/src/components/sections/BasicSettings.tsx`

- [ ] **Step 1: Add failing normalization tests**

Test legacy LUT, native bundle, and material archive selections. Required assertions:

```ts
it("returns only public material fields and no local paths", () => {
  const library = buildWorkshopColorLibrary(materialStateFixture());
  expect(library?.sourceKind).toBe("material-archive");
  expect(JSON.stringify(library)).not.toMatch(
    /directory_name|archive_path|cache_file_path|stage_a_params_path/,
  );
  expect(library?.colors.every((entry) => /^#[0-9A-F]{6}$/.test(entry.hex))).toBe(true);
});

it("keeps source colors out of the selected print library", () => {
  const library = buildWorkshopColorLibrary(lutStateFixture());
  expect(library?.id).toMatch(/^lut:/);
  expect(library?.colors).toEqual([
    { id: "slot:0", label: "White", hex: "#FFFFFF", materialId: null },
    { id: "slot:1", label: "Red", hex: "#FF0000", materialId: null },
  ]);
});
```

Add handoff tests for 64 MiB, 16,384 edge, 64 MP, PNG signature, decoded
dimensions, transparent image, physical-size consistency, 1 MiB recipe
envelope, current `colorLibraryId` mismatch, and preserving the converter's
selected LUT/material source.

When `layout.kind === "square-grid"`, validate rows/columns as integers from 1
through 16,384, `pitchMm` as a finite value from 0.01 through 9,999, and each
recommended physical dimension from 0.5 through 9,999 mm. Require width and
height to equal `columns × pitchMm` and `rows × pitchMm` within 1e-6 mm.
Generic non-grid modules omit `layout`.

- [ ] **Step 2: Run focused tests**

Run:

```bash
./.venv/bin/python scripts/run_vitest.py run frontend/src/__tests__/workshop-color-library.test.ts frontend/src/__tests__/workshop-handoff.test.ts
```

Expected: FAIL on missing normalizer and new limits.

- [ ] **Step 3: Add a read-only color snapshot and generic image handoff**

`buildWorkshopColorLibrary()` reads a snapshot of `useConverterStore` through `resolveConverterSourceSelection()`. It must:

- return `null` when the current converter source is not ready;
- generate a stable ID from source kind plus public fingerprints/IDs;
- return display names, uppercase hex values, and public material IDs only;
- preserve selection order;
- never mutate the converter selection.

Update handoff to create a browser `File` from `pngBytes`, run the existing converter load action, attach `recipeSource`, and keep source and print colors separate. The module-provided PNG remains the source-color image; `colorLibraryId` proves which current print library the module previewed.

Do not create a Workshop-only preview/generation pipeline. After handoff:

- keep the current LUT or material-archive selection unchanged;
- initialize width/height from the module recommendation without locking them;
- let the existing analysis and auto-preview path converge normally, including
  its persisted material-cache preflight;
- accept a stale/missing `colorLibraryId` because the PNG is still source
  color, but show a non-blocking “打印色库已变化” notice;
- keep the converter usable when no color library is selected.

Render `WorkshopSourceBanner` above the converter's source settings only while
`workshopSource` is present. It resolves the installed module's localized name
with module ID fallback and shows:

- source module and version;
- grid rows × columns and pitch when supplied;
- handed-off physical width × height;
- “当前图像保留图纸原色”;
- “下方 LUT/耗材档案决定最终叠色，切换不会修改图纸原色”;
- an action to return to the installed module when available.

All copy comes from `translations.ts`. The banner is informational, compact at
1280×720, does not push the LUT/material controls below the viewport, and does
not duplicate the converter's active-selection signal.

- [ ] **Step 4: Run handoff tests**

Run:

```bash
./.venv/bin/python scripts/run_vitest.py run frontend/src/__tests__/workshop-color-library.test.ts frontend/src/__tests__/workshop-handoff.test.ts frontend/src/__tests__/workshop-source-banner.test.tsx
```

Expected: PASS. In the handoff integration test, wait for the existing
analysis/preview state to settle before asserting the source banner, preserved
color selection, target dimensions, and generated preview.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/workshop frontend/src/components/sections/BasicSettings.tsx frontend/src/i18n/translations.ts frontend/src/__tests__
git commit -m "feat(workshop): bridge color libraries and handoff"
```

## Task 10: Render packages in a sandboxed iframe

**Files:**

- Create: `frontend/src/workshop/runtime/WorkshopFrame.tsx`
- Create: `frontend/src/workshop/runtime/health.ts`
- Create: `frontend/src/__tests__/workshop-runtime.test.tsx`

- [ ] **Step 1: Add a failing real-frame lifecycle test**

The test must render a frame with a mocked runtime descriptor and assert:

```ts
it("accepts ready only from the current iframe window and matching identity", async () => {
  render(<WorkshopFrame module={installedFixture()} />);
  const iframe = screen.getByTitle("Fixture Hello");
  postReady(window, { moduleId: "other.module", moduleVersion: "1.0.0" });
  expect(connectPort).not.toHaveBeenCalled();
  postReady(iframe.contentWindow, {
    moduleId: "fixture.hello",
    moduleVersion: "1.0.0",
  });
  await waitFor(() => expect(connectPort).toHaveBeenCalledTimes(1));
});

it("terminates a frame that misses the ten second handshake", () => {
  vi.useFakeTimers();
  render(<WorkshopFrame module={installedFixture()} />);
  vi.advanceTimersByTime(10_001);
  expect(screen.getByText("模块启动超时")).toBeInTheDocument();
});
```

Also verify `sandbox="allow-scripts"`, no `allow-same-origin`, no module HTML in `localStorage`, one active port, cleanup on unmount, progress rendering, three start failures disabling the version, and candidate activation only after `lifecycle.ready`.

- [ ] **Step 2: Run the runtime test**

Run:

```bash
./.venv/bin/python scripts/run_vitest.py run frontend/src/__tests__/workshop-runtime.test.tsx
```

Expected: FAIL on missing frame.

- [ ] **Step 3: Implement desktop and browser runtime selection**

Desktop iframe source:

```ts
export function desktopModuleUrl(moduleId: string, version: string): string {
  const host = encodeURIComponent(moduleId);
  return `lumina-workshop://${host}/${encodeURIComponent(version)}/ui/index.html`;
}
```

Browser rules:

- official seed and repository fixture may receive server-provided `srcDoc`
  only after the host injects the same CSP as the Electron runtime before the
  first script;
- Registry and GitHub modules render a “desktop required” state;
- explicit unsafe development mode may open a local package, but handlers replace image, project, and color-library data with synthetic fixtures;
- each frame uses `referrerPolicy="no-referrer"` and `sandbox="allow-scripts"`;
- the parent verifies `event.source === iframe.contentWindow`;
- opaque-origin messages are accepted only after identity and API-range validation;
- candidate launch snapshots projects first and activates only after `lifecycle.ready`;
- three consecutive startup failures call the disable endpoint and expose rollback.

- [ ] **Step 4: Run runtime and manager-adjacent tests**

Run:

```bash
./.venv/bin/python scripts/run_vitest.py run frontend/src/__tests__/workshop-runtime.test.tsx frontend/src/__tests__/workshop-rpc-host.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/workshop/runtime frontend/src/__tests__
git commit -m "feat(workshop): run modules in sandbox frames"
```

## Task 11: Add the Installed, Discover, and Developer manager views

**Files:**

- Create: `frontend/src/api/workshop.ts`
- Create: `frontend/src/workshop/ModuleDetails.tsx`
- Modify: `frontend/src/workshop/WorkshopPanel.tsx`
- Modify: `frontend/src/workshop/store.ts`
- Modify: `frontend/src/i18n/translations.ts`
- Replace: `frontend/src/__tests__/workshop-panel.test.tsx`
- Create: `frontend/src/__tests__/workshop-manager.test.tsx`

- [ ] **Step 1: Write failing manager-flow tests**

Cover:

1. Installed list shows official/community/unreviewed source, enabled state, active version, update, rollback, and retained project status.
2. Discover reads only the verified Registry catalog.
3. Developer accepts a local `.lumina-workshop` file or canonical GitHub repository URL.
4. Permission expansion presents old/new diff and cannot auto-confirm.
5. Official uninstall stays uninstalled after reload and offers offline seed restore.
6. Uninstall preserves projects by default; the destructive checkbox is explicit.
7. Browser mode disables “Open” for community/unreviewed packages.
8. Module details render README as sanitized Markdown, never raw HTML.

Example:

```ts
it("does not activate an update until the candidate frame reports ready", async () => {
  mockInstallUpdate({ candidateVersion: "1.1.0" });
  renderManager();
  await user.click(screen.getByRole("button", { name: "更新" }));
  expect(api.activateModule).not.toHaveBeenCalled();
  emitLifecycleReady("fixture.hello", "1.1.0");
  await waitFor(() =>
    expect(api.activateModule).toHaveBeenCalledWith(
      "fixture.hello",
      "1.1.0",
    ),
  );
});
```

- [ ] **Step 2: Run manager tests**

Run:

```bash
./.venv/bin/python scripts/run_vitest.py run frontend/src/__tests__/workshop-panel.test.tsx frontend/src/__tests__/workshop-manager.test.tsx
```

Expected: FAIL because the panel still imports `modules/bead/manifest`.

- [ ] **Step 3: Rewrite the shell around installed package records**

`WorkshopPanel.tsx` must not import:

```text
./modules/bead/manifest
WorkshopModuleDefinition
React ComponentType module entries
```

Store only:

```ts
interface WorkshopManagerState {
  view: "installed" | "discover" | "developer";
  activeModule: { moduleId: string; version: string } | null;
  catalogStatus: "idle" | "loading" | "ready" | "error";
  runtimeMode: "desktop-secure" | "browser-restricted" | "unsafe-development";
  pendingRecipeSource: WorkshopRecipeSource | null;
  diagnostics: WorkshopDiagnosticSummary | null;
}
```

Persist only `view` and the last active module identity. Never persist recipe payloads, diagnostics, tokens, runtime HTML, permissions awaiting confirmation, or install paths.

All visible strings go into `translations.ts`, including source badges, audit states, permission names, browser restrictions, offline/cache status, update diff, rollback, retained projects, seed restore, and safe mode.

- [ ] **Step 4: Run manager, theme, and build checks**

Run:

```bash
./.venv/bin/python scripts/run_vitest.py run frontend/src/__tests__/workshop-panel.test.tsx frontend/src/__tests__/workshop-manager.test.tsx frontend/src/__tests__/theme.property.test.ts
pnpm --dir frontend build
```

Expected: PASS; the production bundle contains no direct bead-module import from `WorkshopPanel`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/workshop.ts frontend/src/workshop frontend/src/i18n/translations.ts frontend/src/__tests__
git commit -m "feat(workshop): add installable module manager"
```

## Task 12: Enforce the Electron runtime boundary

**Files:**

- Create: `electron/workshop-security.cjs`
- Create: `electron/__tests__/workshop-security.test.cjs`
- Modify: `electron/main.cjs`
- Modify: `electron/preload.cjs`
- Modify: `electron/package.json`

- [ ] **Step 1: Write failing Electron security tests**

```js
const {
  createWorkshopSessionToken,
  isAllowedWorkshopRequest,
  resolveWorkshopRuntimeRequest,
} = require("../workshop-security.cjs");

test("creates a non-empty per-launch token", () => {
  const first = createWorkshopSessionToken();
  const second = createWorkshopSessionToken();
  assert.match(first, /^[A-Za-z0-9_-]{43}$/);
  assert.notEqual(first, second);
});

test("blocks network requests initiated by a module origin", () => {
  assert.equal(
    isAllowedWorkshopRequest({
      initiator: "null",
      frameUrl: "lumina-workshop://fixture.hello/1.0.0/ui/index.html",
      resourceType: "fetch",
      url: "https://example.com/collect",
    }),
    false,
  );
});

test("allows the host to create a module frame but blocks module navigation", () => {
  assert.equal(
    isAllowedWorkshopRequest({
      initiator: "http://127.0.0.1:4174",
      frameUrl: "http://127.0.0.1:4174/",
      resourceType: "subFrame",
      url: "lumina-workshop://fixture.hello/1.0.0/ui/index.html",
    }),
    true,
  );
  assert.equal(
    isAllowedWorkshopRequest({
      initiator: "null",
      frameUrl: "lumina-workshop://fixture.hello/1.0.0/ui/index.html",
      resourceType: "subFrame",
      url: "lumina-workshop://fixture.hello/1.0.0/ui/index.html",
    }),
    false,
  );
  assert.equal(
    isAllowedWorkshopRequest({
      initiator: "null",
      frameUrl: "lumina-workshop://fixture.hello/1.0.0/ui/index.html",
      resourceType: "subFrame",
      url: "lumina-workshop://other.module/1.0.0/ui/index.html",
    }),
    false,
  );
});

test("allows only non-network inline worker and image resources", () => {
  assert.equal(
    isAllowedWorkshopRequest({
      initiator: "null",
      frameUrl: "lumina-workshop://fixture.hello/1.0.0/ui/index.html",
      resourceType: "worker",
      url: "blob:null/9fcd0b53-69a4-4d35-97ca-a19d61bc9c40",
    }),
    true,
  );
  assert.equal(
    isAllowedWorkshopRequest({
      initiator: "null",
      frameUrl: "lumina-workshop://fixture.hello/1.0.0/ui/index.html",
      resourceType: "other",
      url: "blob:null/9fcd0b53-69a4-4d35-97ca-a19d61bc9c40",
    }),
    false,
  );
});
```

- [ ] **Step 2: Run Electron tests**

Run:

```bash
pnpm --dir electron test
```

Expected: FAIL on missing security module.

- [ ] **Step 3: Register the custom scheme and firewall before window creation**

`main.cjs` must import `crypto`, `protocol`, and `net`, then call:

```js
protocol.registerSchemesAsPrivileged([
  {
    scheme: "lumina-workshop",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: false,
      corsEnabled: false,
    },
  },
]);
```

At process start:

```js
const workshopSessionToken = createWorkshopSessionToken();
```

Pass these backend environment variables in both development and packaged starts:

```js
LUMINA_WORKSHOP_DATA_DIR: path.join(app.getPath("userData"), "workshop"),
LUMINA_WORKSHOP_DESKTOP_TOKEN: workshopSessionToken,
```

Inside `app.whenReady()`:

1. register `protocol.handle("lumina-workshop", ...)`;
2. translate the module hostname/version into the backend runtime endpoint;
3. use main-process `net.fetch()` with the desktop token header;
4. return the backend body and security headers without exposing the token;
5. register `session.defaultSession.webRequest.onBeforeRequest()` and classify
   module requests from the committed requesting `frame.url`, not only
   `initiator` (the sandbox serializes its origin as `null`);
6. deny HTTP, HTTPS, WebSocket, file, cross-module, navigation, form,
   download, object, and arbitrary custom-scheme requests from a module frame;
7. allow only same-module initial custom-scheme loading plus `blob:`/`data:`
   resources for the explicit `worker`, `image`, `media`, or `font` types needed
   by the self-contained runtime;
8. attach `will-frame-navigate`, `will-redirect`, `setWindowOpenHandler`,
   permission-request, and download guards so a missing `initiator` cannot
   bypass the request filter.

The backend-injected CSP is:

```text
default-src 'none';
script-src 'unsafe-inline';
style-src 'unsafe-inline';
img-src data: blob:;
font-src data:;
worker-src data: blob:;
media-src data: blob:;
connect-src 'none';
object-src 'none';
frame-src 'none';
base-uri 'none';
form-action 'none';
```

Keep it on one response-header value in production. Inline workers are allowed
because their bytes already live in the validated package HTML; they do not
create network authority.

Expose only:

```js
getWorkshopRuntimeMode: () =>
  ipcRenderer.invoke("get-workshop-runtime-mode")
```

The result is:

```js
{
  mode: "desktop-secure",
  safeMode: false
}
```

Never expose the desktop token or module filesystem path to the renderer.

- [ ] **Step 4: Run Electron tests**

Run:

```bash
pnpm --dir electron test
```

Expected: PASS. Add tests for opaque `initiator`, absent frame identity,
`blob:` download denial, `data:` top-frame navigation denial, popup denial,
permission denial, redirect denial, and host-frame requests remaining
unaffected. Add a source desktop smoke assertion that the module iframe’s
`processId` differs from the top frame; if it does not, community module opening
must fail closed with `runtime-isolation-unavailable`.

- [ ] **Step 5: Commit**

```bash
git add electron
git commit -m "feat(workshop): isolate desktop module runtimes"
```

## Task 13: Preserve recipes, bug reports, docs, and release diagnostics

**Files:**

- Modify: `frontend/src/recipe/importRecipe.ts`
- Modify: `frontend/src/recipe/exportRecipe.ts`
- Modify: `frontend/src/recipe/types.ts`
- Modify: `frontend/src/__tests__/recipe-import.test.ts`
- Modify: `frontend/src/__tests__/recipe-export.test.ts`
- Modify: `frontend/src/utils/bugReportContext.ts`
- Modify: `frontend/src/utils/__tests__/bugReportContext.test.ts`
- Modify: `frontend/src/api/feedback.ts`
- Modify: `docs/workshop-module-development.md`
- Create: `CONTEXT-MAP.md`
- Create: `docs/context/workshop/CONTEXT.md`

- [ ] **Step 1: Read governed docs and add failing compatibility tests**

Read:

```text
docs/bug-report-reproducibility.md
docs/announcement-maintenance.md
DESIGN.md
```

Add tests asserting:

- recipe schema stays at v3 because the Workshop envelope shape remains compatible;
- envelope JSON above 1 MiB degrades to converter-only import;
- import never imports `modules/bead/manifest`;
- missing module keeps converter restoration working and presents install guidance;
- bug context includes module ID, version, install source, audit status, runtime mode, and stable error code only;
- no project payload, matrix, image bytes, package path, GitHub token, Registry signature, or desktop token enters feedback.

- [ ] **Step 2: Run compatibility tests**

Run:

```bash
./.venv/bin/python scripts/run_vitest.py run frontend/src/__tests__/recipe-import.test.ts frontend/src/__tests__/recipe-export.test.ts frontend/src/utils/__tests__/bugReportContext.test.ts
```

Expected: FAIL because import still uses `OFFICIAL_WORKSHOP_MODULES`.

- [ ] **Step 3: Make recipe validation module-independent**

Replace module execution during import with a structural validator:

```ts
export function validateWorkshopRecipeEnvelope(
  value: unknown,
): WorkshopRecipeSource | null {
  if (!isRecord(value)) return null;
  const serialized = JSON.stringify(value);
  if (new TextEncoder().encode(serialized).byteLength > 1024 * 1024) {
    return null;
  }
  if (
    value.manifestSchemaVersion !== 1 ||
    !isModuleId(value.moduleId) ||
    !isSemver(value.moduleVersion) ||
    !isNonEmptyString(value.projectSchemaVersion) ||
    !isNonEmptyString(value.renderSchemaVersion) ||
    !isRecord(value.payload)
  ) {
    return null;
  }
  return structuredClone(value) as WorkshopRecipeSource;
}
```

The installed module validates and migrates its payload after sandbox startup. A missing module cannot block converter restoration.

Rewrite `docs/workshop-module-development.md` around the SDK tarball, manifest, single-file package, GitHub Release, permissions, browser restriction, project quota, handoff, and test fixture. `docs/context/workshop/CONTEXT.md` records the core/API/frontend/Electron boundary and focused verification commands. `CONTEXT-MAP.md` links the Workshop context without claiming other domains are complete.

- [ ] **Step 4: Run the complete host verification set**

Run:

```bash
pnpm --dir workshop-sdk test
./.venv/bin/python -m pytest tests/test_workshop_package_unit.py tests/test_workshop_registry_unit.py tests/test_workshop_installer_unit.py tests/test_workshop_api_unit.py tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v
./.venv/bin/python scripts/run_vitest.py run frontend/src/__tests__/workshop-rpc-host.test.ts frontend/src/__tests__/workshop-runtime.test.tsx frontend/src/__tests__/workshop-manager.test.tsx frontend/src/__tests__/workshop-project-storage.test.ts frontend/src/__tests__/workshop-handoff.test.ts frontend/src/__tests__/workshop-source-banner.test.tsx frontend/src/__tests__/recipe-import.test.ts frontend/src/__tests__/recipe-export.test.ts frontend/src/utils/__tests__/bugReportContext.test.ts
pnpm --dir electron test
pnpm --dir frontend build
./.venv/bin/python scripts/log_quality_check.py --mode fast
git diff --check
```

Expected: all commands PASS. The old bead source may still exist, but no runtime host, recipe importer, or Workshop manager imports it.

- [ ] **Step 5: Commit**

```bash
git add frontend docs CONTEXT-MAP.md
git commit -m "docs(workshop): document installable host contract"
```

## Task 14: Publish the immutable v1 SDK before module extraction

**Files:**

- Create: `.github/workflows/workshop-sdk-release.yml`
- Create: `tests/test_workshop_sdk_release_contract_unit.py`
- Modify: `workshop-sdk/package.json`
- Modify: `workshop-sdk/README.md`

- [ ] **Step 1: Write a failing SDK release-contract test**

```python
def test_sdk_release_identity_is_exact() -> None:
    package = json.loads(
        Path("workshop-sdk/package.json").read_text(encoding="utf-8"),
    )
    assert package["name"] == "@lumina/workshop-sdk"
    assert package["version"] == "1.0.0"
    assert package["files"] == ["dist", "README.md", "LICENSE"]


def test_sdk_tarball_contains_no_host_implementation(tmp_path: Path) -> None:
    tarball = build_sdk_tarball(tmp_path)
    members = set(list_tgz_members(tarball))
    assert "package/dist/index.js" in members
    assert "package/dist/index.d.ts" in members
    assert "package/README.md" in members
    assert "package/LICENSE" in members
    assert not any(
        part in member
        for member in members
        for part in ("frontend/", "core/", "api/", "electron/", "node_modules/")
    )
```

Also assert the tarball contains no source map with local paths, no package
install script, no dependency on React/Lumina internals, and no file outside
the npm package prefix.

- [ ] **Step 2: Run the focused test**

```bash
./.venv/bin/python -m pytest tests/test_workshop_sdk_release_contract_unit.py -v
```

Expected: FAIL because the release workflow/helper fixture does not exist.

- [ ] **Step 3: Make the packed filename and release workflow deterministic**

Keep `pack:release` as the only packaging command:

```json
{
  "scripts": {
    "pack:release": "pnpm run test && pnpm pack --pack-destination dist-package"
  }
}
```

The expected output is:

```text
workshop-sdk/dist-package/lumina-workshop-sdk-1.0.0.tgz
```

`.github/workflows/workshop-sdk-release.yml`:

- triggers only on `workshop-sdk-v*` tags;
- checks that the tag suffix exactly equals `workshop-sdk/package.json`
  version;
- uses Node 22 and pnpm 10.33.2 with the lockfile frozen;
- runs the SDK tests and release-contract pytest;
- packs once, computes lowercase SHA-256, and writes
  `lumina-workshop-sdk-1.0.0.tgz.sha256`;
- fails if `git status --short` contains an unexpected tracked change;
- publishes exactly the tarball and checksum to a GitHub Release whose tag is
  `workshop-sdk-v1.0.0`;
- never publishes a mutable `latest` asset or npm registry package.

Use these reviewed immutable action commits:

```text
actions/checkout@11d5960a326750d5838078e36cf38b85af677262          # v4
pnpm/action-setup@b906affcce14559ad1aafd4ab0e942779e9f58b1       # v4
actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020      # v4
```

The release step uses the runner's preinstalled `gh` CLI with
`contents: write`; all earlier steps use read-only repository access.

- [ ] **Step 4: Run SDK packaging and host gates locally**

```bash
pnpm --dir workshop-sdk install --frozen-lockfile
pnpm --dir workshop-sdk run pack:release
./.venv/bin/python -m pytest tests/test_workshop_sdk_release_contract_unit.py -v
tar -tzf workshop-sdk/dist-package/lumina-workshop-sdk-1.0.0.tgz
git diff --check
```

Expected: PASS, and the tar listing contains only public SDK package files.

- [ ] **Step 5: Commit, push, and open the host-only PR**

```bash
git add .github/workflows/workshop-sdk-release.yml workshop-sdk tests/test_workshop_sdk_release_contract_unit.py
git commit -m "ci(workshop): publish immutable SDK releases"
git push -u origin MOVIBALE/feat/installable-creative-workshop-host
gh pr create \
  --base dev-refactor \
  --head MOVIBALE/feat/installable-creative-workshop-host \
  --title "feat: add the installable Creative Workshop host" \
  --body-file /tmp/installable-workshop-host-pr.md
```

The PR description includes package/RPC limits,
Electron isolation evidence, browser restrictions, project quota, rollback,
share-card compatibility, and 1280×720 human-flow evidence. Do not merge with a
failed or missing host acceptance item.

- [ ] **Step 6: Tag the reviewed merge commit and verify public assets**

After the PR is merged, fetch the exact protected-branch merge commit and
confirm the release workflow file is present there:

```bash
git fetch origin dev-refactor --tags
HOST_PR_NUMBER="$(gh pr view MOVIBALE/feat/installable-creative-workshop-host \
  --repo lumina-layer-studio/Lumina-studio \
  --json number \
  --jq .number)"
HOST_MERGE_SHA="$(gh pr view "$HOST_PR_NUMBER" \
  --repo lumina-layer-studio/Lumina-studio \
  --json mergeCommit \
  --jq .mergeCommit.oid)"
git show "$HOST_MERGE_SHA":.github/workflows/workshop-sdk-release.yml >/dev/null
git tag -a workshop-sdk-v1.0.0 "$HOST_MERGE_SHA" \
  -m "Workshop SDK v1.0.0"
git push origin workshop-sdk-v1.0.0
gh release view workshop-sdk-v1.0.0 \
  --repo lumina-layer-studio/Lumina-studio \
  --json tagName,isDraft,isPrerelease,assets,url
```

Download and verify the exact dependency later used by
`Lumina-Fuse-Bead-Studio`:

```bash
SDK_RELEASE_CACHE="/Users/min/.cache/lumina-workshop-release/sdk-v1.0.0"
mkdir -p "$SDK_RELEASE_CACHE"
gh release download workshop-sdk-v1.0.0 \
  --repo lumina-layer-studio/Lumina-studio \
  --pattern "lumina-workshop-sdk-1.0.0.tgz*" \
  --dir "$SDK_RELEASE_CACHE"
cd "$SDK_RELEASE_CACHE"
shasum -a 256 -c lumina-workshop-sdk-1.0.0.tgz.sha256
```

Expected: the Release is neither draft nor prerelease, contains exactly the
tarball and checksum, and the checksum PASSes. Do not start the external module
plan before this checkpoint.

## Host acceptance checkpoint

Do not start the official bead-repository migration until all of these are demonstrated:

- a generated fixture `.lumina-workshop` installs as a candidate;
- the candidate handshakes in a sandbox and activates only after ready;
- project save/load and snapshot rollback work within quota;
- color-library reads contain no internal paths;
- PNG handoff reaches the existing converter and round-trips through a v3 share card;
- permission expansion requires confirmation;
- failed update rolls back without losing projects;
- browser mode refuses community/unreviewed execution;
- Electron blocks module-originated HTTP, HTTPS, WebSocket, cross-module, popup, download, and navigation attempts;
- the top frame remains responsive after terminating a crashing isolated module;
- Installed, Discover, and Developer flows pass at 1280×720 in Chinese/English and light/dark themes.
- the host-only PR is merged and `workshop-sdk-v1.0.0` is publicly downloadable
  with a verified checksum.
