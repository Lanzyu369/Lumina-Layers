# Creative Workshop Context

## Purpose

Creative Workshop is Lumina Studio's installable-module system. It lets an
independent, self-contained tool prepare an image and reproducible edit
envelope, then hand that image into Lumina's existing LUT/material, layered
color, preview, and 3MF workflow.

The first official module is `lumina.bead-pattern`, maintained in the separate
`Lumina-Fuse-Bead-Studio` repository. The host repository owns the public SDK,
package trust, installation lifecycle, sandbox, storage, and converter handoff;
it must not import the official module's React source.

## Boundary map

```text
independent module repository
  -> immutable @lumina/workshop-sdk tarball
  -> one signed .lumina-workshop Release asset
  -> signed GitHub Registry or official seed
  -> core/workshop package + release + install validation
  -> /api/workshop/v1 manager endpoints
  -> Workshop manager and sandboxed iframe
  -> MessageChannel RPC with declared permissions
  -> host-validated PNG + recipe envelope
  -> existing Lumina converter path
```

### Public SDK

- `workshop-sdk/src/contracts.ts`: manifest, permissions, RPC, project, color
  library, UI state, handoff, and recipe types.
- `workshop-sdk/src/client.ts`: 10-second handshake and bounded request client.
- `workshop-sdk/src/theme.ts`: applies only allowlisted Lumina CSS tokens.
- `.github/workflows/workshop-sdk-release.yml`: immutable SDK Release pipeline.

The SDK has no dependency on React, Electron, Lumina source, or private host
objects.

### Python trust and lifecycle

- `core/workshop/models.py`: closed Pydantic models and exact SemVer/module
  identity.
- `core/workshop/package_validator.py`: fail-closed ZIP, manifest, HTML, text,
  and static-image inspection.
- `core/workshop/release_client.py`: bounded canonical GitHub Release access.
- `core/workshop/registry_client.py`: exact-byte Ed25519 verification, cache,
  snapshot fallback, compatibility, state, and revocation selection.
- `core/workshop/install_store.py`: atomic install-state document.
- `core/workshop/installer.py`: candidate install, activation, rollback,
  disable, uninstall, tombstone, and runtime-health transitions.
- `assets/workshop-registry/keys.json`: application-owned public trust roots.
- `assets/workshop-registry/registry-v1.json`: bundled verified/offline
  catalog snapshot.

Python never executes module code. Routes validate requests and translate
domain errors; installed bytes remain under `LUMINA_WORKSHOP_DATA_DIR`.

### API

`api/routers/workshop.py` exposes `/api/workshop/v1`:

- trusted catalog and installed-module listing;
- exact Registry, GitHub, and local package installation;
- candidate activation, rollback, enable/disable, uninstall, and seed restore;
- runtime health success/failure;
- safe README/license/gallery details;
- fixed-header runtime HTML and bounded static public assets.

Community runtime HTML requires the per-launch desktop token. The token is
passed only from Electron main process to the loopback backend and never enters
preload, renderer state, logs, bug reports, or response headers.

### Frontend host

- `frontend/src/api/workshop.ts`: typed manager API.
- `frontend/src/workshop/WorkshopPanel.tsx`: Installed, Discover, and Developer
  views plus lifecycle confirmations.
- `frontend/src/workshop/runtime/WorkshopFrame.tsx`: sandbox iframe,
  handshake, candidate health, and teardown.
- `frontend/src/workshop/runtime/rpcHost.ts`: identity, permission, rate,
  timeout, duplicate-request, and payload enforcement.
- `frontend/src/workshop/runtime/handlers.ts`: host-owned capability handlers.
- `frontend/src/workshop/projectStorage.ts`: module namespaces, 64 MiB record,
  256 MiB module quota, 1 MiB recipe quota, and snapshots.
- `frontend/src/workshop/converterHandoff.ts`: PNG, dimensions, physical size,
  color-library identity, replacement confirmation, and atomic converter
  handoff.
- `frontend/src/recipe/importRecipe.ts`: module-independent recipe-envelope
  validation; it never imports module implementation code.

Only manager view and active module identity persist in the Workshop shell
store. Pending recipes, diagnostics, projects, source images, credentials, and
signatures do not.

### Electron boundary

- `electron/workshop-security.cjs`: canonical custom URLs and fail-closed
  request/navigation/popup/permission/download decisions.
- `electron/main.cjs`: `lumina-workshop://` protocol proxy, per-launch token,
  frame request firewall, and renderer-process isolation check.
- `electron/preload.cjs`: exposes only the Workshop runtime-mode query.

Each module is loaded as:

```text
lumina-workshop://<module-id>/<exact-semver>/ui/index.html
```

The iframe uses `sandbox="allow-scripts"` without `allow-same-origin`.
Backend CSP denies all by default and permits only inline script/style and
explicit `data:`/`blob:` worker/image/font/media resources. If the committed
module frame shares the top renderer process, Electron clears it, records
`runtime-isolation-unavailable`, and keeps subsequent module loads in safe
mode.

## Invariants

1. A module ID is permanently bound to one product and reviewed repository.
2. Official and community packages use the same package inspection, install
   transaction, sandbox, RPC, quota, health, rollback, and uninstall paths.
3. A module receives only permissions declared in its exact manifest version.
4. No v1 module has general network, filesystem-path, clipboard, popup, or
   parent-DOM authority.
5. Registry signatures cover exact index bytes; Release asset SHA-256 covers
   exact package bytes. Failed remote verification never replaces trusted
   cache or snapshot state.
6. Updates are candidates until handshake succeeds. Permission expansion
   requires confirmation; repeated startup failures preserve rollback.
7. Uninstall keeps projects by default. An official-uninstalled tombstone
   prevents silent seed restoration after restart.
8. Recipe schema remains v3. A Workshop envelope is JSON, at most 1 MiB, and
   structurally validated without loading module code.
9. Missing, disabled, or incompatible modules never block restoration of the
   converter image and parameters.
10. Bug reports contain only module identity, install source, audit status,
    runtime mode, and a stable error code. They exclude project payloads,
    matrices, image bytes, paths, tokens, and signatures.
11. Image handoff is the only module-to-converter path and is revalidated by
    the host.

## Glossary

| Term | Meaning | Avoid |
| --- | --- | --- |
| module | Independently released installable Workshop tool | plugin when referring to the package contract |
| package | One `<id>-<version>.lumina-workshop` validated ZIP asset | arbitrary ZIP or source checkout |
| Registry | Signed reviewed catalog of repositories and exact Release assets | mutable download list |
| seed | Exact official package embedded for offline first install/recovery | special trusted runtime |
| candidate | Installed version not active until a successful sandbox start | partially active update |
| active version | Version currently opened by the host | newest downloaded version |
| previous version | Rollback target retained by installer | backup archive |
| recipe envelope | Bounded generic JSON allowing a module to restore editing | project database or source image |
| color library | Host-normalized LUT/material/native palette snapshot | raw LUT or material filesystem |
| handoff | Host-validated image and metadata transition into converter | direct store mutation |
| browser restricted mode | Mode that runs official seed/fixtures only | secure community runtime |
| unsafe development mode | Explicit local-package mode using synthetic data | production browser sandbox |

## Focused verification

Run from the repository root:

```bash
CI=true pnpm --dir workshop-sdk test
PYTHONPATH=/private/tmp/lumina-workshop-python-deps \
  .venv/bin/python -m pytest \
  tests/test_workshop_package_unit.py \
  tests/test_workshop_registry_unit.py \
  tests/test_workshop_installer_unit.py \
  tests/test_workshop_api_unit.py -v
.venv/bin/python scripts/run_vitest.py run \
  src/__tests__/workshop-rpc-host.test.ts \
  src/__tests__/workshop-runtime.test.tsx \
  src/__tests__/workshop-manager.test.tsx \
  src/__tests__/workshop-project-storage.test.ts \
  src/__tests__/workshop-handoff.test.ts \
  src/__tests__/recipe-import.test.ts \
  src/__tests__/recipe-export.test.ts
CI=true pnpm --dir electron test
CI=true pnpm --dir frontend build
```

The repository may not have a local `.venv`; use the configured project Python
environment without changing test semantics. Non-watch frontend tests must run
through `scripts/run_vitest.py`.

Automated tests and HTTP success are not complete acceptance. Desktop QA must
also verify install, open, project save/reload, handoff, permission expansion
refusal, update, rollback, disable, uninstall with retained projects, offline
open, crash safe mode, and seed restore in Chinese/English and light/dark.

## Related documents

- `docs/workshop-module-development.md`
- `docs/superpowers/specs/2026-07-30-installable-creative-workshop-design.md`
- `docs/superpowers/plans/2026-07-30-installable-creative-workshop-host.md`
- `docs/superpowers/plans/2026-07-30-fuse-bead-studio-module.md`
- `docs/superpowers/plans/2026-07-30-workshop-registry-and-seed-release.md`
- `docs/bug-report-reproducibility.md`
