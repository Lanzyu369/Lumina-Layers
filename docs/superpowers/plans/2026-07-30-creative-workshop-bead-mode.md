# Creative Workshop and Bead Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned Creative Workshop host and an official bead-pattern module that recognizes clear digital bead charts, supports matrix correction, renders deterministic neighbour-aware ironing pressure, and hands an exact-size transparent PNG into the existing Lumina converter.

**Architecture:** Keep recognition, matrix editing, RLE serialization, and pressure rendering as pure TypeScript domain modules under `frontend/src/workshop/`. Run image analysis and rendering through one cancellable Web Worker, while React components only manage workflow and presentation. The workshop host owns file access, IndexedDB persistence, converter handoff, module validation, and error isolation; the official bead module receives those services through the same public contract reserved for future signed modules.

**Tech Stack:** React 19, TypeScript 5.8, Zustand 5, Canvas/ImageData, Web Workers, IndexedDB, Tailwind CSS, Vitest 4, Testing Library, fast-check, FastAPI/Pydantic for bounded bug-report context

---

## File map

### Workshop host

- Create `frontend/src/workshop/types.ts`: public manifest, capability, host-service, project, raster, handoff, and module-definition contracts.
- Create `frontend/src/workshop/registry.ts`: manifest/version/capability/whitelist validation and built-in module registry.
- Create `frontend/src/workshop/store.ts`: active module, last project, and pending share-card restore state.
- Create `frontend/src/workshop/projectStorage.ts`: module-scoped IndexedDB storage with atomic writes.
- Create `frontend/src/workshop/browserFiles.ts`: image picker, decode, object-URL lifecycle, and PNG encoding.
- Create `frontend/src/workshop/host.ts`: scoped service construction and guarded converter handoff.
- Create `frontend/src/workshop/WorkshopPanel.tsx`: module gallery, resume/new actions, module boundary, and module mounting.

### Official bead module

- Create `frontend/src/workshop/modules/bead/types.ts`: bead project, grid, calibration, recognition, tool, and render types.
- Create `frontend/src/workshop/modules/bead/project.ts`: defaults, validation, trimming, physical size, share-card RLE, and project migration.
- Create `frontend/src/workshop/modules/bead/recognition.ts`: crop, classifier, grid suggestion, mode-specific sampling, palette construction, and confidence issues.
- Create `frontend/src/workshop/modules/bead/editorReducer.ts`: patch-based paint/erase/eyedropper/fill/support and undo/redo logic.
- Create `frontend/src/workshop/modules/bead/renderer.ts`: deterministic binary-alpha neighbour-aware pressure field.
- Create `frontend/src/workshop/modules/bead/workerProtocol.ts`: typed worker messages and request IDs.
- Create `frontend/src/workshop/modules/bead/beadWorker.ts`: recognition and rendering worker entry point.
- Create `frontend/src/workshop/modules/bead/workerClient.ts`: stale-result rejection, cancellation, and worker cleanup.
- Create `frontend/src/workshop/modules/bead/BeadSourceCanvas.tsx`: source image, calibrated grid overlay, and sample-cell picking.
- Create `frontend/src/workshop/modules/bead/BeadMatrixCanvas.tsx`: matrix editing, rendered preview, and magnifier painting.
- Create `frontend/src/workshop/modules/bead/BeadCalibrationStep.tsx`: input-type override, crop, rows/columns, orientation, empty sample, and support sample.
- Create `frontend/src/workshop/modules/bead/BeadEditorStep.tsx`: tools, palette, confidence navigation, view switcher, pressure slider, save, and handoff.
- Create `frontend/src/workshop/modules/bead/BeadWorkshopModule.tsx`: upload → calibration → recognition → edit workflow orchestration.
- Create `frontend/src/workshop/modules/bead/manifest.ts`: official localized manifest and module definition.

### Existing integrations

- Modify `frontend/src/types/widget.ts`, `frontend/src/stores/widgetStore.ts`, `frontend/src/components/widget/TabNavBar.tsx`, and `frontend/src/App.tsx`: add the `workshop` tab between vectorizer and settings.
- Modify `frontend/src/stores/converter/store.ts`: add an atomic `loadWorkshopImageIntoConverter` action and nullable workshop source state.
- Modify `frontend/src/recipe/types.ts`, `migration.ts`, `exportRecipe.ts`, `importRecipe.ts`, and `importFlow.ts`: schema v3 workshop source round-trip.
- Modify `frontend/src/components/ui/ImportConfirmDialog.tsx` and `frontend/src/components/sections/BasicSettings.tsx`: offer “import and continue in workshop”.
- Modify `frontend/src/api/feedback.ts`, `frontend/src/utils/bugReportContext.ts`, `api/routers/feedback.py`, and `api/feedback_index.py`: bounded non-image workshop diagnostics.
- Modify `frontend/src/i18n/translations.ts` and `frontend/src/data/announcements.ts`: bilingual UI and release copy.
- Create `docs/workshop-module-development.md`: developer-facing manifest and host bridge documentation.

---

### Task 1: Define and validate the public workshop module contract

**Files:**
- Create: `frontend/src/workshop/types.ts`
- Create: `frontend/src/workshop/registry.ts`
- Test: `frontend/src/__tests__/workshop-registry.test.ts`

- [ ] **Step 1: Write failing registry contract tests**

Cover a valid built-in manifest plus duplicate ID, unknown capability, manifest version,
minimum Lumina version, and whitelist rejection:

```ts
const validManifest: WorkshopModuleManifest = {
  manifestSchemaVersion: 1,
  id: "lumina.bead-pattern",
  name: { zh: "拼豆模式", en: "Bead Pattern" },
  description: { zh: "读取拼豆图纸", en: "Read bead patterns" },
  author: "Lumina Studio",
  version: "1.0.0",
  icon: "bead-grid",
  minLuminaVersion: "2.0.0",
  inputKinds: ["image/png", "image/jpeg", "image/webp"],
  outputKinds: ["image/png"],
  capabilities: [
    "file.pick-image",
    "project.read-write",
    "handoff.image",
    "ui.theme",
    "ui.locale",
    "status.progress",
    "status.error",
  ],
};

const definition = (
  manifest: WorkshopModuleManifest,
): WorkshopModuleDefinition => ({
  manifest,
  Component: () => null,
});

expect(validateWorkshopModules([definition(validManifest)], {
  appVersion: "2.0.0",
  whitelist: new Set(["lumina.bead-pattern"]),
})).toEqual([
  expect.objectContaining({ enabled: true }),
]);
```

Assert disabled records contain stable reason codes:

```ts
expect(result[0].reason).toBe("duplicate-id");
expect(result[0].reason).toBe("unknown-capability");
expect(result[0].reason).toBe("app-version-too-old");
expect(result[0].reason).toBe("not-whitelisted");
```

- [ ] **Step 2: Run the registry test and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/workshop-registry.test.ts
```

Expected: FAIL because `workshop/types.ts` and `workshop/registry.ts` do not exist.

- [ ] **Step 3: Add the serializable manifest and host contracts**

Define the public types in `workshop/types.ts`:

```ts
export const WORKSHOP_MANIFEST_SCHEMA_VERSION = 1 as const;

export type WorkshopCapability =
  | "file.pick-image"
  | "project.read-write"
  | "handoff.image"
  | "ui.theme"
  | "ui.locale"
  | "status.progress"
  | "status.error";

export interface WorkshopLocalizedText {
  zh: string;
  en: string;
}

export interface WorkshopModuleManifest {
  manifestSchemaVersion: typeof WORKSHOP_MANIFEST_SCHEMA_VERSION;
  id: string;
  name: WorkshopLocalizedText;
  description: WorkshopLocalizedText;
  author: string;
  version: string;
  icon: string;
  minLuminaVersion: string;
  inputKinds: string[];
  outputKinds: string[];
  capabilities: WorkshopCapability[];
}

export interface WorkshopRaster {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

export interface WorkshopRecipeSource {
  manifestSchemaVersion: 1;
  moduleId: string;
  moduleVersion: string;
  projectSchemaVersion: string;
  renderSchemaVersion: string;
  payload: Record<string, unknown>;
}

export interface WorkshopImageHandoff {
  moduleId: string;
  moduleVersion: string;
  projectId: string;
  file: File;
  pixelWidth: number;
  pixelHeight: number;
  recommendedWidthMm: number;
  recommendedHeightMm: number;
  rows: number;
  columns: number;
  beadPitchMm: number;
  preserveCanvasBounds: true;
  recipeSource: WorkshopRecipeSource;
}

export interface WorkshopDiagnosticSummary {
  projectSchemaVersion: string;
  inputMode: string | null;
  rows: number | null;
  columns: number | null;
  compression: number | null;
  errorCode: string | null;
}
```

Also define `WorkshopProjectStorage`, `WorkshopHostServices`,
`WorkshopModuleProps`, `WorkshopModuleDefinition`, and a bounded
`WorkshopDiagnosticSummary`. The status service accepts only that summary and
adds the scoped module ID/version itself. Modules receive every service through
props and never import converter state.

- [ ] **Step 4: Implement deterministic registry validation**

In `workshop/registry.ts`, keep a fixed known-capability set, validate strict
`x.y.z` numeric versions, and return one record per definition:

```ts
export type WorkshopModuleDisabledReason =
  | "duplicate-id"
  | "invalid-manifest"
  | "unsupported-manifest"
  | "unknown-capability"
  | "app-version-too-old"
  | "not-whitelisted";

export interface RegisteredWorkshopModule {
  definition: WorkshopModuleDefinition;
  enabled: boolean;
  reason: WorkshopModuleDisabledReason | null;
}
```

Duplicate IDs disable every conflicting definition instead of selecting one by
registration order. Unknown capabilities fail closed.

- [ ] **Step 5: Run the focused test and commit**

```bash
python scripts/run_vitest.py run src/__tests__/workshop-registry.test.ts
git add frontend/src/workshop/types.ts frontend/src/workshop/registry.ts frontend/src/__tests__/workshop-registry.test.ts
git commit -m "feat(workshop): define versioned module contract"
```

Expected: registry tests PASS and the commit contains only contract, validator,
and tests.

---

### Task 2: Add bead project data, RLE serialization, and module-scoped persistence

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml`
- Create: `frontend/src/workshop/projectStorage.ts`
- Create: `frontend/src/workshop/modules/bead/types.ts`
- Create: `frontend/src/workshop/modules/bead/project.ts`
- Test: `frontend/src/__tests__/workshop-project-storage.test.ts`
- Test: `frontend/src/__tests__/bead-project.test.ts`
- Test: `frontend/src/__tests__/bead-project.property.test.ts`

- [ ] **Step 1: Install the locked frontend dependencies and IndexedDB test adapter**

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm add --save-dev --save-exact fake-indexeddb@6.2.5
```

Expected: `frontend/node_modules` exists and only `package.json` plus
`pnpm-lock.yaml` change for the new exact dev dependency.

- [ ] **Step 2: Write failing project and storage tests**

Use `fake-indexeddb/auto` and verify:

```ts
const storage = new IndexedDbWorkshopProjectStorage(indexedDB);
await storage.save("lumina.bead-pattern", record);
expect(await storage.load("lumina.bead-pattern", record.projectId)).toEqual(record);
expect(await storage.load("other.module", record.projectId)).toBeNull();
expect((await storage.latest("lumina.bead-pattern"))?.projectId).toBe(record.projectId);
```

For bead data, assert:

```ts
expect(trimEmptyBorder(project).rows).toBe(2);
expect(calculatePhysicalSize(trimmed, 2.6)).toEqual({
  widthMm: 5.2,
  heightMm: 5.2,
});
expect(decodeBeadCellsRle(encodeBeadCellsRle(cells), cells.length)).toEqual(cells);
```

Property-test arbitrary grids up to 128×128 so RLE round-trip preserves
`empty`, palette indices, and transparent support.

- [ ] **Step 3: Run focused tests and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/workshop-project-storage.test.ts src/__tests__/bead-project.test.ts src/__tests__/bead-project.property.test.ts
```

Expected: FAIL because project types, codecs, and storage are absent.

- [ ] **Step 4: Implement the bead project schema and validators**

Use explicit cell tokens:

```ts
export type RgbColor = readonly [number, number, number];
export type BeadCell =
  | { kind: "empty" }
  | { kind: "color"; paletteIndex: number }
  | { kind: "transparent-support" };

export interface BeadProject {
  schemaVersion: "bead-project/v1";
  renderSchemaVersion: "bead-render/v1";
  projectId: string;
  moduleId: "lumina.bead-pattern";
  moduleVersion: string;
  createdAt: string;
  updatedAt: string;
  source: BeadProjectSource;
  calibration: BeadCalibration;
  rows: number;
  columns: number;
  palette: RgbColor[];
  cells: BeadCell[];
  confidenceIssues: BeadConfidenceIssue[];
  beadPitchMm: number;
  compression: number;
}
```

`validateBeadProject` rejects non-integer dimensions, dimensions outside 1–128,
wrong cell count, invalid palette indices, non-RGB palette entries, pitch outside
0.5–10 mm, and compression outside integer 0–100.

Encode RLE with `-1` for empty, `-2` for support, and `0..n` for palette indices:

```ts
export type BeadCellRun = readonly [token: number, count: number];
```

`trimEmptyBorder` removes only all-empty outer rows/columns; support cells count
as occupied. Add `createBeadRecipeSource(project)` and
`restoreBeadProjectFromRecipeSource(source)` as the single validated conversion
boundary for share-card restore. The restored form intentionally has no source
image and opens directly in matrix view.

- [ ] **Step 5: Implement atomic IndexedDB storage**

Use database `lumina-workshop`, version `1`, and object store `projects` keyed by
`key = moduleId + ":" + projectId`, with an `updatedAt` index. `save` performs
one readwrite transaction and resolves only after `transaction.oncomplete`.
`latest(moduleId)` filters by stored `moduleId`, so a module cannot read another
namespace.

Store project data and source `Blob` via structured clone. When IndexedDB is
unavailable, expose a memory implementation for the current session and return a
non-fatal `persistence-unavailable` status through the host.

- [ ] **Step 6: Run tests and commit**

```bash
python scripts/run_vitest.py run src/__tests__/workshop-project-storage.test.ts src/__tests__/bead-project.test.ts src/__tests__/bead-project.property.test.ts
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/workshop/projectStorage.ts frontend/src/workshop/modules/bead/types.ts frontend/src/workshop/modules/bead/project.ts frontend/src/__tests__/workshop-project-storage.test.ts frontend/src/__tests__/bead-project.test.ts frontend/src/__tests__/bead-project.property.test.ts
git commit -m "feat(workshop): persist versioned bead projects"
```

Expected: all focused tests PASS.

---

### Task 3: Add the Creative Workshop tab, shell, and official lighthouse module

**Files:**
- Modify: `frontend/src/types/widget.ts`
- Modify: `frontend/src/stores/widgetStore.ts`
- Modify: `frontend/src/components/widget/TabNavBar.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/i18n/translations.ts`
- Create: `frontend/src/workshop/store.ts`
- Create: `frontend/src/workshop/browserFiles.ts`
- Create: `frontend/src/workshop/host.ts`
- Create: `frontend/src/workshop/WorkshopPanel.tsx`
- Create: `frontend/src/workshop/modules/bead/manifest.ts`
- Create: `frontend/src/workshop/modules/bead/BeadWorkshopModule.tsx`
- Modify: `frontend/src/__tests__/app-tabs.test.tsx`
- Modify: `frontend/src/__tests__/layout.test.tsx`
- Modify: `frontend/src/__tests__/tab-switch-layout.property.test.ts`
- Modify: `frontend/src/__tests__/tab-filter.property.test.ts`
- Test: `frontend/src/__tests__/workshop-panel.test.tsx`

- [ ] **Step 1: Write failing navigation and shell tests**

Assert the primary order:

```ts
const tabs = screen.getAllByRole("button")
  .filter((button) => button.dataset.testid?.startsWith("tab-"))
  .map((button) => button.dataset.testid);

expect(tabs.slice(-3)).toEqual([
  "tab-vectorizer",
  "tab-workshop",
  "tab-settings",
]);
```

Click `tab-workshop`, expect an official card, open it, expect the module upload
intro, return home, and verify no widget toggles appear. Add `"workshop"` to the
two tab property arbitraries.

- [ ] **Step 2: Run tests and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/app-tabs.test.tsx src/__tests__/layout.test.tsx src/__tests__/tab-switch-layout.property.test.ts src/__tests__/tab-filter.property.test.ts src/__tests__/workshop-panel.test.tsx
```

Expected: FAIL because `workshop` is not a `TabId` and no panel exists.

- [ ] **Step 3: Add `workshop` to the existing navigation model**

Update:

```ts
export type TabId =
  | "converter"
  | "calibration"
  | "extractor"
  | "gradient-card-generate"
  | "gradient-card-extract"
  | "material-library"
  | "material-cloud-sync"
  | "material-recipe"
  | "lut-library"
  | "lut-manager"
  | "lut-cloud-sync"
  | "lut-details"
  | "lut-compare"
  | "five-color"
  | "vectorizer"
  | "workshop"
  | "settings";
```

Add `workshop: []` to `TAB_WIDGET_MAP`, add a workshop icon and primary entry
immediately after vectorizer, import `WorkshopPanel` in `App.tsx`, and render:

```tsx
{activeTab === "workshop" && <WorkshopPanel />}
```

- [ ] **Step 4: Implement shell state and host browser services**

Persist only non-sensitive shell state in Zustand/localStorage:

```ts
interface WorkshopShellState {
  activeModuleId: string | null;
  lastProjectIds: Record<string, string>;
  pendingRecipeSource: WorkshopRecipeSource | null;
  diagnostics: WorkshopDiagnosticSummary | null;
  openModule(moduleId: string): void;
  returnHome(): void;
  rememberProject(moduleId: string, projectId: string): void;
  openRecipe(source: WorkshopRecipeSource): void;
  clearPendingRecipe(): void;
  setDiagnostics(summary: WorkshopDiagnosticSummary | null): void;
}
```

Configure Zustand `partialize` so localStorage contains only
`activeModuleId` and `lastProjectIds`. Pending recipe payloads and diagnostics
remain memory-only.

In `browserFiles.ts`, implement a click-triggered picker restricted to PNG,
JPEG, and WebP; decode with `createImageBitmap` and a canvas, falling back to an
`Image` object URL. Keep URL creation/revocation and `canvas.toBlob("image/png")`
inside this host file service.

- [ ] **Step 5: Register and mount the official module through the contract**

Build `BEAD_WORKSHOP_MANIFEST` from translation source entries, register only
`lumina.bead-pattern`, and whitelist that ID. `WorkshopPanel` renders enabled and
disabled cards from registry results, creates module-scoped host services, and
mounts the selected definition inside an error boundary.

The initial `BeadWorkshopModule` renders the approved description and calls
`host.files.pickImage()` from its upload button. It must not import
`useConverterStore`, `useWidgetStore`, `indexedDB`, or network clients.

- [ ] **Step 6: Add all bilingual shell and initial module strings**

Use the `tab.workshop` and `workshop.*` namespaces in
`translations.ts`. Include labels for official status, open, continue, new
project, return, upload, disabled reasons, local persistence warning, and module
error recovery.

- [ ] **Step 7: Run tests and commit**

```bash
python scripts/run_vitest.py run src/__tests__/app-tabs.test.tsx src/__tests__/layout.test.tsx src/__tests__/tab-switch-layout.property.test.ts src/__tests__/tab-filter.property.test.ts src/__tests__/workshop-panel.test.tsx
git add frontend/src/types/widget.ts frontend/src/stores/widgetStore.ts frontend/src/components/widget/TabNavBar.tsx frontend/src/App.tsx frontend/src/i18n/translations.ts frontend/src/workshop/store.ts frontend/src/workshop/browserFiles.ts frontend/src/workshop/host.ts frontend/src/workshop/WorkshopPanel.tsx frontend/src/workshop/modules/bead/manifest.ts frontend/src/workshop/modules/bead/BeadWorkshopModule.tsx frontend/src/__tests__/app-tabs.test.tsx frontend/src/__tests__/layout.test.tsx frontend/src/__tests__/tab-switch-layout.property.test.ts frontend/src/__tests__/tab-filter.property.test.ts frontend/src/__tests__/workshop-panel.test.tsx
git commit -m "feat(workshop): add creative workshop shell"
```

Expected: navigation, registry adoption, shell, and tests PASS.

---

### Task 4: Implement clear-pattern classification, calibration suggestions, and recognition

**Files:**
- Create: `frontend/src/workshop/modules/bead/recognition.ts`
- Test: `frontend/src/__tests__/bead-recognition.test.ts`
- Test: `frontend/src/__tests__/bead-recognition.property.test.ts`

- [ ] **Step 1: Write failing synthetic recognition tests**

Build raster fixtures in test code rather than committing third-party images:

```ts
const numbered = makeNumberedGridFixture({
  rows: 4,
  columns: 5,
  gridLineWidth: 2,
  watermarkCells: [7],
  whiteBeadCells: [1],
});
const hardPixel = makeHardPixelFixture({ rows: 3, columns: 4, scale: 16 });
const rings = makeRingFixture({ rows: 3, columns: 3, holeRadius: 4 });
```

Assert classification mode, suggested rows/columns, exact palette colors,
white-bead occupancy, annulus sampling, transparent support matching, and a
low-confidence issue for the watermark cell.

Add failure cases for oblique/non-square calibration and a property test that
recognized output always has `rows * columns` valid cells with palette indices
in bounds.

- [ ] **Step 2: Run recognition tests and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/bead-recognition.test.ts src/__tests__/bead-recognition.property.test.ts
```

Expected: FAIL because recognition functions are absent.

- [ ] **Step 3: Implement pure raster utilities and classifier**

Expose:

```ts
export function cropRaster(source: WorkshopRaster, crop: CropRect): WorkshopRaster;
export function classifyPattern(source: WorkshopRaster): PatternClassification;
export function suggestGrid(source: WorkshopRaster, mode: BeadInputMode): GridSuggestion;
export function recognizeBeadPattern(request: RecognitionRequest): RecognitionResult;
```

Classification scores:

- numbered grid: repeated horizontal/vertical projection peaks;
- ring preview: periodic dark or transparent centres with coloured annuli;
- hard pixel: low within-block variance and repeated run lengths;
- ambiguous top scores within `0.08`: return `mode: "ambiguous"` so the UI asks.

- [ ] **Step 4: Implement mode-specific cell sampling**

For `numbered-grid`, ignore the outer 12% grid border, exclude high-gradient
text pixels, and select the most frequent low-gradient corner cluster. Determine
occupancy separately from color by comparing structure and color distance to the
chosen empty sample.

For `hard-pixel`, take the robust median of the inner 60% block.

For `ring-preview`, sample only normalized radii `0.22..0.43` from the cell
centre and ignore the central hole.

Use deterministic integer RGB distance. Mark issues with stable codes:

```ts
type BeadConfidenceReason =
  | "high-color-variance"
  | "occupancy-color-conflict"
  | "grid-misalignment"
  | "overlay-obstruction"
  | "jpeg-near-tie";
```

Never alter a cell based only on neighbour plausibility.

- [ ] **Step 5: Run tests and commit**

```bash
python scripts/run_vitest.py run src/__tests__/bead-recognition.test.ts src/__tests__/bead-recognition.property.test.ts
git add frontend/src/workshop/modules/bead/recognition.ts frontend/src/__tests__/bead-recognition.test.ts frontend/src/__tests__/bead-recognition.property.test.ts
git commit -m "feat(workshop): recognize clear bead patterns"
```

Expected: all recognition tests PASS without external fixture files.

---

### Task 5: Implement patch-based matrix editing and confidence review

**Files:**
- Create: `frontend/src/workshop/modules/bead/editorReducer.ts`
- Test: `frontend/src/__tests__/bead-editor-reducer.test.ts`
- Test: `frontend/src/__tests__/bead-editor-reducer.property.test.ts`

- [ ] **Step 1: Write failing editor behavior tests**

Verify paint, erase, support, fill, eyedropper selection, undo/redo, and issue
resolution:

```ts
state = beadEditorReducer(state, {
  type: "apply-tool",
  tool: "paint",
  cellIndex: 3,
  paletteIndex: 1,
});
expect(state.present.cells[3]).toEqual({ kind: "color", paletteIndex: 1 });

state = beadEditorReducer(state, { type: "undo" });
expect(state.present.cells[3]).toEqual({ kind: "empty" });
```

Property-test random valid action sequences so dimensions and palette indices
remain valid and undo followed by redo restores the exact matrix.

- [ ] **Step 2: Run tests and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/bead-editor-reducer.test.ts src/__tests__/bead-editor-reducer.property.test.ts
```

Expected: FAIL because the reducer is absent.

- [ ] **Step 3: Implement sparse edit patches**

Use:

```ts
interface BeadCellPatch {
  index: number;
  before: BeadCell;
  after: BeadCell;
}

interface BeadEditorState {
  present: BeadProject;
  past: BeadCellPatch[][];
  future: BeadCellPatch[][];
  activeTool: BeadEditorTool;
  activePaletteIndex: number;
  selectedCellIndex: number | null;
  selectedIssueIndex: number | null;
}
```

Flood fill uses four-neighbour connectivity and records one patch batch.
Eyedropper changes selection but does not create undo history. Applying a tool
to an unchanged cell creates no history entry. Any new edit clears `future`.

- [ ] **Step 4: Run tests and commit**

```bash
python scripts/run_vitest.py run src/__tests__/bead-editor-reducer.test.ts src/__tests__/bead-editor-reducer.property.test.ts
git add frontend/src/workshop/modules/bead/editorReducer.ts frontend/src/__tests__/bead-editor-reducer.test.ts frontend/src/__tests__/bead-editor-reducer.property.test.ts
git commit -m "feat(workshop): add reversible bead matrix editing"
```

Expected: reducer and property tests PASS.

---

### Task 6: Implement deterministic neighbour-aware pressure rendering

**Files:**
- Create: `frontend/src/workshop/modules/bead/renderer.ts`
- Test: `frontend/src/__tests__/bead-renderer.test.ts`
- Test: `frontend/src/__tests__/bead-renderer.property.test.ts`

- [ ] **Step 1: Write failing geometry and color-invariant tests**

Use 1×1, 2×2, and 3×3 fixtures at compression 0, 50, and 100:

```ts
const light = renderBeadProject(project, { compression: 0, pixelsPerCell: 32 });
const standard = renderBeadProject(project, { compression: 50, pixelsPerCell: 32 });
const tight = renderBeadProject(project, { compression: 100, pixelsPerCell: 32 });

expect(alphaAt(light, singleCellCentre)).toBe(0);
expect(alphaAt(tight, singleCellCentre)).toBe(255);
expect(alphaAt(standard, fourCellJunction)).toBe(0);
expect(alphaAt(tight, fourCellJunction)).toBe(255);
```

Assert same-color neighbours have no seam at 100, different colors preserve
one of the two exact RGB values, support cells affect contact shape but output
alpha 0, and all alpha bytes are only 0 or 255.

Property-test determinism and:

```ts
expect(outputRgbSet(rendered)).toBeSubsetOf(inputPaletteSet(project));
```

- [ ] **Step 2: Run tests and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/bead-renderer.test.ts src/__tests__/bead-renderer.property.test.ts
```

Expected: FAIL because `renderBeadProject` does not exist.

- [ ] **Step 3: Implement normalized pressure geometry**

For each output sample, evaluate nearby occupied cells only. Use a compression
parameter `p = compression / 100`, an outer radius that grows monotonically, and
a hole radius that reaches zero only at 100:

```ts
const outerRadius = 0.43 + 0.13 * p;
const holeRadius = compression === 100
  ? 0
  : 0.19 * Math.pow(1 - p, 0.72);
const junctionRelief = compression === 100
  ? 0
  : 0.075 * Math.pow(1 - p, 1.35);
```

Bias the signed distance toward occupied cardinal and diagonal neighbours so
contact faces expand more than open edges. Assign overlap ownership by weighted
distance to cell centre; break exact ties by row-major cell index.

For compression `0..99`, subtract `junctionRelief` from diagonal contact lobes
so the four-cell intersection remains visibly open. At exactly `100`, replace
the rounded outer test with the occupied cell's half-open Voronoi square and set
the centre-hole test to filled. This explicit terminal rule guarantees that an
occupied 2×2 block covers its shared junction without gaps instead of relying on
a radius that cannot reach the corner.

Resolve same-color ownership as one union before seam evaluation. For
different-color overlap, choose one exact palette owner using weighted distance
and the row-major tie break. Treat support cells as occupied geometry during
field evaluation but skip them when writing RGB/alpha.

- [ ] **Step 4: Write palette-exact binary output**

Return:

```ts
export interface BeadRenderResult extends WorkshopRaster {
  palette: RgbColor[];
  compression: number;
  pixelsPerCell: number;
}
```

Write only palette bytes and alpha `255`, or zero RGB and alpha `0`. Do not use
canvas antialiasing inside the renderer.

- [ ] **Step 5: Run tests and commit**

```bash
python scripts/run_vitest.py run src/__tests__/bead-renderer.test.ts src/__tests__/bead-renderer.property.test.ts
git add frontend/src/workshop/modules/bead/renderer.ts frontend/src/__tests__/bead-renderer.test.ts frontend/src/__tests__/bead-renderer.property.test.ts
git commit -m "feat(workshop): render bead ironing pressure"
```

Expected: geometry anchors, palette invariants, and properties PASS.

---

### Task 7: Run recognition and rendering through a cancellable worker

**Files:**
- Create: `frontend/src/workshop/modules/bead/workerProtocol.ts`
- Create: `frontend/src/workshop/modules/bead/beadWorker.ts`
- Create: `frontend/src/workshop/modules/bead/workerClient.ts`
- Test: `frontend/src/__tests__/bead-worker-client.test.ts`

- [ ] **Step 1: Write failing stale-result and cleanup tests**

Inject a fake worker, issue request IDs 1 and 2, deliver response 1 last, and
assert it cannot replace request 2. Verify `dispose()` rejects outstanding work
with `worker-disposed` and calls `terminate()` once.

- [ ] **Step 2: Run the worker-client test and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/bead-worker-client.test.ts
```

Expected: FAIL because protocol and client do not exist.

- [ ] **Step 3: Define the discriminated protocol**

```ts
export type BeadWorkerRequest =
  | { id: number; type: "classify"; raster: WorkshopRaster }
  | { id: number; type: "recognize"; request: RecognitionRequest }
  | { id: number; type: "render"; project: BeadProject; compression: number; pixelsPerCell: number };

export type BeadWorkerResponse =
  | { id: number; ok: true; type: "classify"; result: PatternClassification }
  | { id: number; ok: true; type: "recognize"; result: RecognitionResult }
  | { id: number; ok: true; type: "render"; result: BeadRenderResult }
  | { id: number; ok: false; errorCode: string; message: string };
```

Transfer raster/output buffers rather than copying them where ownership is not
needed by the sender.

- [ ] **Step 4: Implement worker and client lifecycle**

Create the production worker with:

```ts
new Worker(new URL("./beadWorker.ts", import.meta.url), { type: "module" });
```

The client increments request IDs, stores one promise per request, ignores
responses for unknown/cancelled IDs, exposes `cancelBefore(id)`, and terminates
on module unmount.

- [ ] **Step 5: Run tests and commit**

```bash
python scripts/run_vitest.py run src/__tests__/bead-worker-client.test.ts
git add frontend/src/workshop/modules/bead/workerProtocol.ts frontend/src/workshop/modules/bead/beadWorker.ts frontend/src/workshop/modules/bead/workerClient.ts frontend/src/__tests__/bead-worker-client.test.ts
git commit -m "feat(workshop): process bead images in a worker"
```

Expected: worker lifecycle tests PASS.

---

### Task 8: Build calibration, matrix editing, live preview, and local resume UI

**Files:**
- Modify: `frontend/src/workshop/modules/bead/BeadWorkshopModule.tsx`
- Create: `frontend/src/workshop/modules/bead/BeadSourceCanvas.tsx`
- Create: `frontend/src/workshop/modules/bead/BeadMatrixCanvas.tsx`
- Create: `frontend/src/workshop/modules/bead/BeadCalibrationStep.tsx`
- Create: `frontend/src/workshop/modules/bead/BeadEditorStep.tsx`
- Modify: `frontend/src/i18n/translations.ts`
- Test: `frontend/src/__tests__/bead-calibration-step.test.tsx`
- Test: `frontend/src/__tests__/bead-editor-step.test.tsx`
- Test: `frontend/src/__tests__/bead-workshop-module.test.tsx`

- [ ] **Step 1: Write failing component-flow tests with an injected host and worker**

Cover:

```text
upload → crop/use original → classification override → rows/columns
→ choose empty sample → optional support sample → recognize
→ review low-confidence cell → edit → undo/redo
→ switch original/matrix/pressure views → compression 0/50/100
→ autosave → remount → resume
```

Use a fake host returning a 4×4 synthetic raster and a fake worker engine so
component tests do not depend on browser Worker or Canvas encoders.

- [ ] **Step 2: Run UI tests and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/bead-calibration-step.test.tsx src/__tests__/bead-editor-step.test.tsx src/__tests__/bead-workshop-module.test.tsx
```

Expected: FAIL because the workflow components are missing.

- [ ] **Step 3: Implement source calibration UI**

Reuse `CropModal` for a single pattern crop. `BeadSourceCanvas` draws the
cropped raster and calibrated square grid, maps pointer positions to row-major
cell indices, and supports modes:

```ts
type CalibrationPickMode = "none" | "empty" | "transparent-support";
```

Rows and columns are integer inputs clamped to 1–128. Orientation buttons apply
0/90/180/270 degrees and horizontal/vertical flip to logical mapping. “No empty
cells” is mutually exclusive with an empty sample.

Disable recognition until geometry is valid and either an empty sample or
explicit no-empty choice exists.

- [ ] **Step 4: Implement matrix editor and preview surfaces**

`BeadMatrixCanvas` paints:

- matrix view as palette-exact cells plus optional grid;
- pressure view from `BeadRenderResult`;
- no source pixels in pressure view;
- pointer-to-cell editing without out-of-bounds writes.

`BeadEditorStep` exposes paint, erase, eyedropper, fill, support, undo, redo,
confidence previous/next, grid toggle, original/matrix/pressure views, palette,
and a color input. A fixed magnifier redraws a bounded region around the
selected cell with smoothing disabled.

- [ ] **Step 5: Implement debounced two-resolution live rendering**

On matrix or compression change:

1. request 12 px/cell preview immediately;
2. cancel older requests;
3. after 180 ms without another change, request 32 px/cell;
4. accept only the latest request ID.

Render preset buttons for 0, 50, and 100 plus `Slider` with integer step 1 and a
visible `HelpDot` tooltip.

- [ ] **Step 6: Implement project autosave and resume**

After a valid project change, debounce `host.projects.save` by 300 ms. Persist
the original source `Blob`, calibration, matrix, issues, pitch, and pressure.
Save failures show a non-blocking banner and preserve in-memory state.

On mount, consume a pending share-card source first; otherwise load the remembered
project ID, then the latest module project. Consume pending data only through
`restoreBeadProjectFromRecipeSource`; clear it after success or a reported
validation error. A share-card project without source image opens directly in
matrix view and hides recalibration/original-image actions.

- [ ] **Step 7: Add bilingual module strings**

Add `workshop.bead.*` keys for every heading, mode, tool, tooltip, issue,
calibration instruction, validation message, view, pressure preset, save state,
replacement confirmation, and handoff result. No literal Chinese/English UI
copy remains in the components.

- [ ] **Step 8: Run UI tests and commit**

```bash
python scripts/run_vitest.py run src/__tests__/bead-calibration-step.test.tsx src/__tests__/bead-editor-step.test.tsx src/__tests__/bead-workshop-module.test.tsx
git add frontend/src/workshop/modules/bead/BeadWorkshopModule.tsx frontend/src/workshop/modules/bead/BeadSourceCanvas.tsx frontend/src/workshop/modules/bead/BeadMatrixCanvas.tsx frontend/src/workshop/modules/bead/BeadCalibrationStep.tsx frontend/src/workshop/modules/bead/BeadEditorStep.tsx frontend/src/i18n/translations.ts frontend/src/__tests__/bead-calibration-step.test.tsx frontend/src/__tests__/bead-editor-step.test.tsx frontend/src/__tests__/bead-workshop-module.test.tsx
git commit -m "feat(workshop): add bead analysis editor"
```

Expected: component flow and persistence-resume tests PASS.

---

### Task 9: Add atomic converter handoff with exact decimal dimensions

**Files:**
- Modify: `frontend/src/stores/converter/store.ts`
- Modify: `frontend/src/workshop/host.ts`
- Modify: `frontend/src/workshop/modules/bead/BeadEditorStep.tsx`
- Modify: `api/schemas/converter.py`
- Test: `frontend/src/__tests__/workshop-handoff.test.ts`
- Test: `frontend/src/stores/__tests__/converterStore.test.ts`
- Test: `frontend/src/__tests__/bead-editor-step.test.tsx`
- Modify: `tests/test_api_schemas_properties.py`

- [ ] **Step 1: Write failing atomic handoff tests**

Assert:

```ts
useConverterStore.getState().loadWorkshopImageIntoConverter({
  file,
  pixelWidth: 1024,
  pixelHeight: 768,
  targetWidthMm: 83.2,
  targetHeightMm: 62.4,
  source,
});

const state = useConverterStore.getState();
expect(state.imageFile).toBe(file);
expect(state.target_width_mm).toBe(83.2);
expect(state.target_height_mm).toBe(62.4);
expect(state.aspectRatio).toBeCloseTo(4 / 3);
expect(state.cropModalOpen).toBe(false);
expect(state.workshopSource).toEqual(source);
```

Verify a normal `setImageFile`, vectorizer load, batch replacement, or clear
resets `workshopSource`. Verify host handoff returns `needs-confirmation` without
mutation when a converter image exists. Add schema assertions that
`target_width_mm=0.5` is accepted and values below `0.5` are rejected; this
covers exact handoff for a one-cell project while the ordinary converter UI
continues to clamp manual width controls to its existing 10 mm minimum.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/workshop-handoff.test.ts src/stores/__tests__/converterStore.test.ts src/__tests__/bead-editor-step.test.tsx
python -m pytest tests/test_api_schemas_properties.py -v
```

Expected: FAIL because converter state has no workshop source/action and backend
schemas still reject widths below 10 mm.

- [ ] **Step 3: Add atomic converter action**

Add:

```ts
interface WorkshopConverterLoad {
  file: File;
  pixelWidth: number;
  pixelHeight: number;
  targetWidthMm: number;
  targetHeightMm: number;
  source: WorkshopRecipeSource;
}

loadWorkshopImageIntoConverter(input: WorkshopConverterLoad): void;
```

The action cancels preview work, revokes the previous blob URL, resets session
artifacts, disables the crop modal for this load, exits batch mode, uses
high-fidelity mode when current mode is vector, sets exact decimal dimensions
without ratio rounding, and stores `workshopSource`.

Keep `enableCrop` preference unchanged. Add `workshopSource: null` to
`DEFAULT_STATE` and clear it in every non-workshop image ownership path.

- [ ] **Step 4: Permit exact small-width workshop output at the API boundary**

Define one shared minimum target-width constant of `0.5` mm in
`api/schemas/converter.py` and use it for preview, generate, and large-format
schemas. Update the constrained-field property table and add explicit boundary
examples. Do not lower the ordinary converter UI slider/input minimum; this
schema expansion exists so a validated workshop handoff can preserve a small
logical grid exactly.

- [ ] **Step 5: Guard and complete host handoff**

Validate module ID/version, PNG MIME, positive integer pixels, final
`pixelWidth === columns * 32` and `pixelHeight === rows * 32`, finite
`0.5–400` mm target sizes, rows/columns 1–128, 0.5–10 mm pitch, and
`preserveCanvasBounds === true`. Recompute `columns * beadPitchMm` and
`rows * beadPitchMm` and reject target dimensions that differ beyond floating
point epsilon. Decode the submitted PNG through the host file service, compare
its actual dimensions with the declared dimensions, and reject it if every
alpha byte is zero. The bead editor also rejects a matrix with no colored cells
before spending time on full-resolution rendering and PNG encoding.

Return:

```ts
type WorkshopHandoffResult =
  | { status: "needs-confirmation" }
  | { status: "completed" };
```

When `replaceExisting` is true, call the atomic converter action and switch to
`converter`. The bead editor shows a confirmation dialog only for the first
result and retries with explicit replacement.

- [ ] **Step 6: Run tests and commit**

```bash
python scripts/run_vitest.py run src/__tests__/workshop-handoff.test.ts src/stores/__tests__/converterStore.test.ts src/__tests__/bead-editor-step.test.tsx
python -m pytest tests/test_api_schemas_properties.py -v
git add frontend/src/stores/converter/store.ts frontend/src/workshop/host.ts frontend/src/workshop/modules/bead/BeadEditorStep.tsx api/schemas/converter.py frontend/src/__tests__/workshop-handoff.test.ts frontend/src/stores/__tests__/converterStore.test.ts frontend/src/__tests__/bead-editor-step.test.tsx tests/test_api_schemas_properties.py
git commit -m "feat(workshop): hand bead images to converter"
```

Expected: exact-size handoff, sub-10 mm backend acceptance, and replacement
protection tests PASS.

---

### Task 10: Round-trip workshop source through share-card schema v3

**Files:**
- Modify: `frontend/src/recipe/types.ts`
- Modify: `frontend/src/recipe/migration.ts`
- Modify: `frontend/src/recipe/exportRecipe.ts`
- Modify: `frontend/src/recipe/importRecipe.ts`
- Modify: `frontend/src/recipe/importFlow.ts`
- Modify: `frontend/src/components/ui/ImportConfirmDialog.tsx`
- Modify: `frontend/src/components/sections/BasicSettings.tsx`
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `frontend/src/__tests__/recipe-export.test.ts`
- Modify: `frontend/src/__tests__/recipe-import.test.ts`
- Modify: `frontend/src/__tests__/recipe-integration.test.ts`
- Modify: `frontend/src/__tests__/recipe-roundtrip.property.test.ts`
- Modify: `frontend/src/__tests__/recipe-import-flow.test.ts`
- Modify: `frontend/src/__tests__/import-confirm-dialog.test.tsx`

- [ ] **Step 1: Write failing v3 round-trip and degraded-import tests**

Build a bead source containing palette, RLE cells, support, orientation, pitch,
and compression. Assert `buildFullRecipe` embeds it, PNG/JSON integrity includes
it, restore preserves it, and “import and continue editing” opens
`lumina.bead-pattern`.

Also assert:

- v1/v2 without `workshop` import unchanged;
- malformed payload adds `recipe_import_workshop_degraded` and restores the main
  PNG/converter settings;
- unknown module disables the edit action but does not block import.

- [ ] **Step 2: Run focused recipe tests and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/recipe-export.test.ts src/__tests__/recipe-import.test.ts src/__tests__/recipe-integration.test.ts src/__tests__/recipe-roundtrip.property.test.ts src/__tests__/recipe-import-flow.test.ts src/__tests__/import-confirm-dialog.test.tsx
```

Expected: FAIL because schema version is 2 and `recipe.workshop` is absent.

- [ ] **Step 3: Add schema v3 and migration**

In `recipe/types.ts`:

```ts
export interface LuminaRecipe {
  format: "lumina-recipe";
  schema_version: number;
  app_version: string;
  created_at: string;
  source: RecipeSource;
  cover: RecipeCover;
  asset: RecipeAssets;
  recipe: {
    converter?: ConverterRecipe;
    workshop?: WorkshopRecipeSource;
  };
  integrity: RecipeIntegrity;
  compat: RecipeCompat;
  warnings: string[];
}

export const RECIPE_SCHEMA_VERSION = 3;
```

Import `WorkshopRecipeSource` with `import type` from `workshop/types.ts` so
recipe serialization shares the public envelope without introducing a runtime
dependency cycle.

Migration from v2 to v3 is an optional-field migration: preserve all existing
fields and leave `workshop` undefined. Future versions continue the existing
forward-compatible warning behavior.

- [ ] **Step 4: Export, validate, and restore workshop source**

Change `buildFullRecipe` to accept an optional fourth argument and include a
deep-cloned workshop source before hashing. Both share-card and sidecar export
pass `converterState.workshopSource`.

At import, validate generic envelope fields first, then ask the module registry
whether the source is restorable. Invalid/unavailable data sets
`workshopSource: null` and appends the localized degradation warning. A valid
source enters converter partial state. The bead registry validator delegates its
payload check to `restoreBeadProjectFromRecipeSource`, so project restore and
recipe import cannot disagree about valid RLE, palette, dimensions, support
cells, pitch, or compression.

- [ ] **Step 5: Add the import destination action**

Extend `applyImport` with:

```ts
interface ApplyImportOptions {
  destination?: "converter" | "workshop";
}
```

Always restore the converter first. For destination `workshop`, call
`useWorkshopStore.getState().openRecipe(source)` and switch to `workshop`;
otherwise retain the existing converter destination.

Show a second dialog button only when the source is valid and available:
“导入并继续编辑 / Import and continue editing”.

- [ ] **Step 6: Run recipe tests and commit**

```bash
python scripts/run_vitest.py run src/__tests__/recipe-export.test.ts src/__tests__/recipe-import.test.ts src/__tests__/recipe-integration.test.ts src/__tests__/recipe-roundtrip.property.test.ts src/__tests__/recipe-import-flow.test.ts src/__tests__/import-confirm-dialog.test.tsx
git add frontend/src/recipe/types.ts frontend/src/recipe/migration.ts frontend/src/recipe/exportRecipe.ts frontend/src/recipe/importRecipe.ts frontend/src/recipe/importFlow.ts frontend/src/components/ui/ImportConfirmDialog.tsx frontend/src/components/sections/BasicSettings.tsx frontend/src/i18n/translations.ts frontend/src/__tests__/recipe-export.test.ts frontend/src/__tests__/recipe-import.test.ts frontend/src/__tests__/recipe-integration.test.ts frontend/src/__tests__/recipe-roundtrip.property.test.ts frontend/src/__tests__/recipe-import-flow.test.ts frontend/src/__tests__/import-confirm-dialog.test.tsx
git commit -m "feat(workshop): preserve bead projects in share cards"
```

Expected: v1/v2 compatibility and v3 workshop round-trip tests PASS.

---

### Task 11: Add bounded bug-report context, developer docs, and announcement

**Files:**
- Modify: `frontend/src/api/feedback.ts`
- Modify: `frontend/src/utils/bugReportContext.ts`
- Modify: `frontend/src/utils/__tests__/bugReportContext.test.ts`
- Modify: `api/routers/feedback.py`
- Modify: `api/feedback_index.py`
- Modify: `tests/test_feedback_router_unit.py`
- Modify: `tests/test_feedback_index_unit.py`
- Create: `docs/workshop-module-development.md`
- Modify: `frontend/src/data/announcements.ts`
- Modify: `frontend/src/__tests__/useAnnouncement.test.ts`

- [ ] **Step 1: Write failing privacy-bounded context tests**

When workshop is active, assert only:

```json
{
  "module_id": "lumina.bead-pattern",
  "module_version": "1.0.0",
  "project_schema_version": "bead-project/v1",
  "input_mode": "numbered-grid",
  "rows": 52,
  "columns": 52,
  "compression": 50,
  "error_code": null
}
```

Assert serialized context does not contain source image bytes, file names,
palette entries, cell RLE, object URLs, or local paths. Backend tests verify
ranges, string limits, ticket persistence, index rendering, and omission for
older clients.

- [ ] **Step 2: Run focused frontend/backend tests and verify RED**

```bash
python scripts/run_vitest.py run src/utils/__tests__/bugReportContext.test.ts
python -m pytest tests/test_feedback_router_unit.py tests/test_feedback_index_unit.py -v
```

Expected: FAIL because workshop context is not modeled or rendered.

- [ ] **Step 3: Implement the bounded context model**

Add matching frontend and Pydantic models with optional `workshop`:

```ts
export interface WorkshopBugReportContext {
  module_id: string;
  module_version: string;
  project_schema_version: string;
  input_mode: "numbered-grid" | "hard-pixel" | "ring-preview" | null;
  rows: number | null;
  columns: number | null;
  compression: number | null;
  error_code: string | null;
}
```

Use Pydantic limits: strings ≤128, rows/columns 1–128 or null, compression
0–100 or null. `collectBugReportContext` reads only the bead module's bounded
diagnostic summary from workshop shell state. Modules publish the summary only
through `host.status.reportDiagnostics`; leaving the module clears it. Add it to
`index.md` and Chinese summary without exposing matrix content.

- [ ] **Step 4: Write developer documentation**

`docs/workshop-module-development.md` must contain:

- manifest v1 JSON example;
- stable ID and semver rules;
- all seven capabilities and denial behavior;
- host service method signatures;
- project namespace and schema migration rules;
- handoff validation and replacement behavior;
- error contract and module boundary;
- source-level whitelist limitation in v1;
- future signature/sandbox boundary;
- official bead module as the lighthouse implementation.

- [ ] **Step 5: Add the bilingual announcement**

Follow `docs/announcement-maintenance.md`. Prepend a Beijing-date
`2026-07-30` entry under `新功能 / New` describing the visible Creative Workshop,
bead chart correction, pressure preview, and Lumina handoff in plain language.
Do not use internal terms such as store, schema, worker, or endpoint.

- [ ] **Step 6: Run tests and commit**

```bash
python scripts/run_vitest.py run src/utils/__tests__/bugReportContext.test.ts src/__tests__/useAnnouncement.test.ts src/__tests__/announcement-dialog.test.tsx
python -m pytest tests/test_feedback_router_unit.py tests/test_feedback_index_unit.py -v
git add frontend/src/api/feedback.ts frontend/src/utils/bugReportContext.ts frontend/src/utils/__tests__/bugReportContext.test.ts api/routers/feedback.py api/feedback_index.py tests/test_feedback_router_unit.py tests/test_feedback_index_unit.py docs/workshop-module-development.md frontend/src/data/announcements.ts frontend/src/__tests__/useAnnouncement.test.ts
git commit -m "docs(workshop): document and announce bead mode"
```

Expected: privacy, backend persistence, index rendering, and announcement tests
PASS.

---

### Task 12: Run full verification and real browser flow

**Files:**
- Verify: all files changed by Tasks 1–11
- Update only if a verified defect is found: focused implementation or test file

- [ ] **Step 1: Run all workshop and recipe frontend tests**

```bash
python scripts/run_vitest.py run src/__tests__/workshop-registry.test.ts src/__tests__/workshop-project-storage.test.ts src/__tests__/bead-project.test.ts src/__tests__/bead-project.property.test.ts src/__tests__/workshop-panel.test.tsx src/__tests__/bead-recognition.test.ts src/__tests__/bead-recognition.property.test.ts src/__tests__/bead-editor-reducer.test.ts src/__tests__/bead-editor-reducer.property.test.ts src/__tests__/bead-renderer.test.ts src/__tests__/bead-renderer.property.test.ts src/__tests__/bead-worker-client.test.ts src/__tests__/bead-calibration-step.test.tsx src/__tests__/bead-editor-step.test.tsx src/__tests__/bead-workshop-module.test.tsx src/__tests__/workshop-handoff.test.ts src/__tests__/recipe-export.test.ts src/__tests__/recipe-import.test.ts src/__tests__/recipe-integration.test.ts src/__tests__/recipe-roundtrip.property.test.ts src/__tests__/recipe-import-flow.test.ts src/__tests__/import-confirm-dialog.test.tsx src/__tests__/app-tabs.test.tsx src/__tests__/layout.test.tsx src/__tests__/tab-switch-layout.property.test.ts src/__tests__/tab-filter.property.test.ts
```

Expected: all selected tests PASS.

- [ ] **Step 2: Run static and production frontend gates**

```bash
cd frontend
pnpm exec tsc --noEmit
pnpm lint
pnpm build
```

Expected: all commands exit 0. Do not fix unrelated pre-existing lint debt; if
the repository baseline fails, compare the same command on `origin/dev-refactor`
and document the delta.

- [ ] **Step 3: Run backend feedback and logging governance gates**

```bash
python -m pytest tests/test_feedback_router_unit.py tests/test_feedback_index_unit.py tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v
python scripts/log_quality_check.py --mode fast
```

Expected: all tests and the fast log-quality gate PASS.

- [ ] **Step 4: Perform real Chrome human-flow validation**

Start Lumina with the project-supported launcher, then verify:

```text
Creative Workshop tab order
→ official bead module
→ numbered-grid fixture
→ crop and grid calibration
→ white bead plus transparent support sample
→ low-confidence correction
→ every edit tool and undo/redo
→ 0/50/100 pressure and magnifier
→ handoff at exact 2.6 mm pitch
→ converter preview
→ return and re-edit
→ export share card
→ refresh and import
→ continue editing matrix without original screenshot
```

Repeat upload/recognition with one hard-pixel and one ring-preview fixture.
Check light/dark, Chinese/English, 390 px narrow width, and converter replacement
cancel/confirm. Inspect generated PNG pixels to confirm alpha is binary and RGB
belongs to the source palette.

- [ ] **Step 5: Measure the approved performance budgets**

In Chrome performance measurements:

- 52×52 drag preview begins updating within 100 ms;
- 104×104 at 32 px/cell finishes within 3 seconds after settling;
- no main-thread task from recognition/rendering exceeds 50 ms;
- stale worker results never replace a newer slider value.

Record the measured values in the final handoff. If a budget misses, profile and
fix the responsible worker or UI transfer before completion.

- [ ] **Step 6: Stop processes and inspect the final diff**

```bash
python start_all.py --kill
git diff --check
git status --short
git log --oneline origin/dev-refactor..HEAD
```

Expected: no Lumina/Vite/Vitest helper remains, `git diff --check` is clean, and
only planned files are changed.

- [ ] **Step 7: Commit any final verified integration corrections**

If Step 4 or 5 required a correction, inspect `git status --short`, stage each
corrected path explicitly from the File map without using `git add -A`, and
commit with `git commit -m "fix(workshop): complete bead mode integration"`.

If no correction was needed, do not create an empty commit.
