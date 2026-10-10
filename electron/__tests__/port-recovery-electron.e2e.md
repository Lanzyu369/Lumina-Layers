# Port-origin recovery: real Electron regression

This is a source-level desktop regression, not a runtime build or publication.
It uses Electron **35.7.5**, Node.js, esbuild, and the actual frontend
`IndexedDbWorkshopProjectStorage`. No Python backend or Vite server is needed.
All renderer modules are served from the same loopback origin with
`webSecurity: true`. The test profile must be a new, disposable directory.

Run from the repository root. `ELECTRON_BINARY` and `ESBUILD_BINARY` below are
absolute paths to installed tools; they are not package-manager commands. The
project's package manager is pnpm.

```sh
PORT_TEST_ROOT=$(mktemp -d /tmp/lumina-port-e2e.XXXXXX)
"$ESBUILD_BINARY" frontend/src/workshop/projectStorage.ts --bundle --format=esm --platform=browser --outfile="$PORT_TEST_ROOT/project-storage.js"
for PORT_TEST_PHASE in seed recover restart return empty; do
  LUMINA_PORT_E2E_ROOT="$PORT_TEST_ROOT" \
  LUMINA_PORT_E2E_MODULE="$PORT_TEST_ROOT/project-storage.js" \
  LUMINA_PORT_E2E_PHASE="$PORT_TEST_PHASE" \
    "$ELECTRON_BINARY" electron/__tests__/port-recovery-electron.e2e.cjs || break
done
```

Equivalent PowerShell invocation (set the two tool paths first):

```powershell
$portTestRoot = Join-Path ([IO.Path]::GetTempPath()) ("lumina-port-e2e-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $portTestRoot | Out-Null
& $esbuildBinary frontend/src/workshop/projectStorage.ts --bundle --format=esm --platform=browser "--outfile=$portTestRoot/project-storage.js"
if ($LASTEXITCODE -ne 0) { throw "Storage bundle failed" }
$env:LUMINA_PORT_E2E_ROOT = $portTestRoot
$env:LUMINA_PORT_E2E_MODULE = Join-Path $portTestRoot "project-storage.js"
foreach ($portTestPhase in @("seed", "recover", "restart", "return", "empty")) {
  $env:LUMINA_PORT_E2E_PHASE = $portTestPhase
  # Start-Process -Wait waits for the ENTIRE Electron main process on Windows.
  $portTestProcess = Start-Process -FilePath $electronBinary -ArgumentList @("electron/__tests__/port-recovery-electron.e2e.cjs") -Wait -PassThru -NoNewWindow
  if ($portTestProcess.ExitCode -ne 0) { throw "Electron phase failed: $portTestPhase" }
}
```

Each phase must exit completely before the next starts; all phases share the
isolated `user-data` directory. Expected output is one JSON line with `ok:true`
per process:

- `seed`: source A, version-1 port state, settings, projects, snapshot and metadata.
- `recover`: a real foreign listener occupies A; select B, prove owned health,
  replace stale B, commit, then read/edit/save through the actual storage class.
  A deliberately incompatible destination database first forces a real import
  failure: A must remain committed and interception must be removed. Remove
  only that isolated test fixture, then retry from unchanged A. Delete a project,
  snapshot and setting at B after successful recovery.
- `restart`: a new Electron process reuses B and reads/edits/saves again.
- `return`: occupy B and move back to preserved, stale A. Deleted records and
  settings must not reappear; projects and typed values still save. Empty A at
  the end to exercise the next authoritative transfer.
- `empty`: occupy A and move its empty source to stale B. All application
  settings and the three database stores must now be empty.

For every transfer, the foreign listener remains alive and receives **zero
HTTP requests**. Blob, ArrayBuffer, typed array, Date, Map, Set, BigInt and RegExp
must survive; the only IndexedDB database remains `lumina-workshop` version 2.
The source port never commits before transfer succeeds, and protocol interception
must be removed before any usable renderer is opened. Windows testing should
record process exit codes and output for all phases, not just the last process.

The ordinary legacy regression remains separate:
`electron/__tests__/storage-migration-electron.e2e.cjs`. It additionally covers
non-overwriting partial-import retries. This new test does not replace it.
