# Fuse Bead Studio Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the approved 拼豆 analysis, correction, fused-bead rendering, and Lumina handoff workflow into the independent public `Lumina-Fuse-Bead-Studio` repository and release it as the first official `.lumina-workshop` module.

**Architecture:** A self-contained React/Vite module connects to Lumina only through `@lumina/workshop-sdk`. Pure recognition, project, reducer, and renderer code migrate from the current in-tree prototype; module UI, translations, styles, and an inline worker live in the new repository. The final package contains a manifest, one inlined HTML runtime, icon, README, and license. Its project model keeps detected source colors separate from the current Lumina LUT/material color library, and hands a source-color PNG plus bounded recipe metadata back to Lumina's existing converter path.

**Tech Stack:** React 19, TypeScript 5.8, Vite 7, `vite-plugin-singlefile`, Vitest, fast-check, Canvas 2D, Web Worker, pnpm 10, Node 22, GitHub Actions

---

## Scope, repositories, and prerequisites

This plan creates a sibling repository:

- Source reference: `/Users/min/.codex/worktrees/b9d4/Lumina-studio`
- Destination checkout: `/Users/min/CascadeProjects/Lumina-Fuse-Bead-Studio`
- GitHub repository: `https://github.com/lumina-layer-studio/Lumina-Fuse-Bead-Studio`
- Module ID: `lumina.bead-pattern`
- Initial module version: `1.0.0`
- Package asset: `lumina.bead-pattern-1.0.0.lumina-workshop`

It starts only after the host acceptance checkpoint in `docs/superpowers/plans/2026-07-30-installable-creative-workshop-host.md` passes. Create the new repository as public with no generated README, then clone it and use a fresh branch:

```bash
gh repo create lumina-layer-studio/Lumina-Fuse-Bead-Studio --public --clone=false
git clone https://github.com/lumina-layer-studio/Lumina-Fuse-Bead-Studio.git /Users/min/CascadeProjects/Lumina-Fuse-Bead-Studio
cd /Users/min/CascadeProjects/Lumina-Fuse-Bead-Studio
git switch -c main
git commit --allow-empty -m "chore: initialize repository"
git push -u origin main
git switch -c MOVIBALE/feat/initial-fuse-bead-module
```

Do not delete the in-tree prototype while executing this plan. The seed release plan removes it only after the external package passes cross-repository and Electron acceptance.

## Product invariants

- A bead remains the same physical bead. `compression` models the ironing/fusion state; it is not a second bead type.
- Default bead pitch is `2.6 mm`, matching the currently approved mainstream size.
- `compression = 0` retains a clear center hole, bead-to-bead gaps, and four-bead intersection valleys.
- Increasing compression makes neighboring bead faces bulge and squeeze together continuously.
- `compression = 100` closes the center holes and inter-bead voids without leaving artificial crosses or diamonds.
- The module does not simulate baking paper, gloss, matte finish, or material texture. Lumina continues to produce layered-color print output through its existing path.
- The input is a clear pattern image or screenshot, not an arbitrary photograph-to-pixel-art converter.
- Empty cells and transparent-support cells remain distinct from colored beads.
- Recognition must support numbered grids, hard-pixel charts, and ring/bead previews, then expose low-confidence cells for correction.
- The source palette remains authoritative for the PNG handed to Lumina. A selected LUT/material archive is a separate print-library preview and mapping layer.

## Target file map

```text
Lumina-Fuse-Bead-Studio/
├── .github/workflows/ci.yml
├── .github/workflows/release.yml
├── LICENSE
├── README.md
├── manifest.json
├── package.json
├── pnpm-lock.yaml
├── tsconfig.json
├── vite.config.ts
├── scripts/package.mjs
├── public/assets/icon.png
├── src/main.tsx
├── src/app/BeadWorkshopModule.tsx
├── src/app/BeadCalibrationStep.tsx
├── src/app/BeadEditorStep.tsx
├── src/app/BeadHandoffConfirmDialog.tsx
├── src/app/BeadMatrixCanvas.tsx
├── src/app/BeadSourceCanvas.tsx
├── src/domain/types.ts
├── src/domain/project.ts
├── src/domain/recognition.ts
├── src/domain/renderer.ts
├── src/domain/editorReducer.ts
├── src/host/hostAdapter.ts
├── src/host/colorMapping.ts
├── src/i18n/translations.ts
├── src/ui/Button.tsx
├── src/ui/Checkbox.tsx
├── src/ui/HelpDot.tsx
├── src/ui/Slider.tsx
├── src/ui/CropModal.tsx
├── src/ui/panelPrimitives.ts
├── src/ui/theme.css
├── src/worker/beadWorker.ts
├── src/worker/workerClient.ts
├── src/worker/workerProtocol.ts
├── src/vite-env.d.ts
├── test/helpers/beadFixtures.ts
├── test/helpers/sdkHarness.ts
└── test/*.test.ts(x)
```

## Task 1: Scaffold the independent, reproducible module repository

**Files:**

- Create: `package.json`
- Create: `tsconfig.json`
- Create: `vite.config.ts`
- Create: `src/vite-env.d.ts`
- Create: `src/main.tsx`
- Create: `manifest.json`
- Create: `README.md`
- Create: `LICENSE`
- Create: `public/assets/icon.png`
- Create: `.gitignore`
- Create: `test/package-contract.test.ts`

- [ ] **Step 1: Write a failing package-contract test**

```ts
// test/package-contract.test.ts
import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";

describe("module package contract", () => {
  it("uses the stable identity and only public Workshop permissions", async () => {
    const manifest = JSON.parse(
      await readFile(new URL("../manifest.json", import.meta.url), "utf8"),
    );
    expect(manifest).toEqual({
      manifestVersion: 1,
      id: "lumina.bead-pattern",
      version: "1.0.0",
      name: { "zh-CN": "拼豆工作台", "en-US": "Fuse Bead Studio" },
      description: {
        "zh-CN": "识别、校正并模拟熨烫融合后的拼豆图纸",
        "en-US": "Recognize, correct, and render iron-fused bead patterns",
      },
      publisher: "Lumina Studio",
      workshopApi: { min: "1.0.0", maxExclusive: "2.0.0" },
      luminaVersion: { min: "2.0.0" },
      entrypoints: { ui: "ui/index.html" },
      permissions: [
        { name: "image.pick", reason: "选择并读取拼豆图纸或截图" },
        { name: "project.storage", reason: "保存可继续编辑的拼豆工程" },
        { name: "color-library.read", reason: "预览当前 LUT 或耗材档案色库" },
        { name: "handoff.image", reason: "将确认后的源色 PNG 交给 Lumina 转换" },
      ],
    });
  });
});
```

- [ ] **Step 2: Run the test and confirm the missing scaffold**

```bash
corepack enable
pnpm test --run test/package-contract.test.ts
```

Expected: FAIL because `package.json` and `manifest.json` do not exist.

- [ ] **Step 3: Add the exact package, compiler, and build configuration**

`package.json`:

```json
{
  "name": "@lumina-layer-studio/fuse-bead-studio",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "packageManager": "pnpm@10.33.2",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest",
    "test:run": "vitest run",
    "package": "pnpm run test:run && pnpm run build && node scripts/package.mjs"
  },
  "dependencies": {
    "@lumina/workshop-sdk": "https://github.com/lumina-layer-studio/Lumina-studio/releases/download/workshop-sdk-v1.0.0/lumina-workshop-sdk-1.0.0.tgz",
    "react": "^19.1.0",
    "react-dom": "^19.1.0"
  },
  "devDependencies": {
    "@types/node": "^22.15.0",
    "@types/react": "^19.1.8",
    "@types/react-dom": "^19.1.6",
    "@vitejs/plugin-react": "^4.5.2",
    "fast-check": "^4.2.0",
    "fflate": "^0.8.2",
    "jsdom": "^26.1.0",
    "typescript": "~5.8.3",
    "vite": "^7.0.0",
    "vite-plugin-singlefile": "^2.2.0",
    "vitest": "^3.2.4"
  }
}
```

`vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

export default defineConfig({
  plugins: [react(), viteSingleFile()],
  base: "./",
  build: {
    outDir: "dist/ui",
    emptyOutDir: true,
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    include: ["test/**/*.test.ts", "test/**/*.test.tsx"],
  },
});
```

`manifest.json` must exactly match the test. `src/main.tsx` may initially render a static loading state. Add the MIT license and a neutral official icon whose source file is committed; do not fetch an icon during the build.

- [ ] **Step 4: Install with the lockfile and verify the contract**

```bash
pnpm install
pnpm test:run test/package-contract.test.ts
pnpm build
test -f dist/ui/index.html
test "$(find dist/ui -type f | wc -l | tr -d ' ')" = "1"
```

Expected: test PASS, build PASS, and `dist/ui` contains only `index.html`.

- [ ] **Step 5: Commit the scaffold**

```bash
git add .
git commit -m "feat(module): scaffold fuse bead studio"
```

## Task 2: Migrate and pin the pure bead domain behavior

**Files:**

- Create: `src/domain/types.ts`
- Create: `src/domain/project.ts`
- Create: `src/domain/recognition.ts`
- Create: `src/domain/renderer.ts`
- Create: `src/domain/editorReducer.ts`
- Create: `test/helpers/beadFixtures.ts`
- Create: `test/helpers/chartFixtures.ts`
- Create: `test/bead-project.test.ts`
- Create: `test/bead-project.property.test.ts`
- Create: `test/bead-recognition.test.ts`
- Create: `test/bead-recognition.property.test.ts`
- Create: `test/bead-renderer.test.ts`
- Create: `test/bead-renderer.property.test.ts`
- Create: `test/bead-editor-reducer.test.ts`
- Create: `test/bead-editor-reducer.property.test.ts`
- Create: `test/bead-recognition-corpus.test.ts`
- Create: `docs/recognition-contract.md`

- [ ] **Step 1: Copy the current behavior tests before implementation**

From the new repository:

```bash
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/helpers/beadFixtures.ts test/helpers/beadFixtures.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/bead-project.test.ts test/bead-project.test.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/bead-project.property.test.ts test/bead-project.property.test.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/bead-recognition.test.ts test/bead-recognition.test.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/bead-recognition.property.test.ts test/bead-recognition.property.test.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/bead-renderer.test.ts test/bead-renderer.test.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/bead-renderer.property.test.ts test/bead-renderer.property.test.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/bead-editor-reducer.test.ts test/bead-editor-reducer.test.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/bead-editor-reducer.property.test.ts test/bead-editor-reducer.property.test.ts
```

Change only import roots from `../workshop/modules/bead/*` to `../src/domain/*` and from `./helpers/*` to `./helpers/*`. Preserve every assertion.

- [ ] **Step 2: Add explicit terminal-fusion and physical-size regressions**

Extend `test/bead-renderer.test.ts`:

```ts
it("closes holes and four-bead valleys only at terminal compression", () => {
  const project = makeSolidProject({ rows: 2, columns: 2 });
  const ninetyNine = renderBeadProject(project, { compression: 99, scale: 32 });
  const terminal = renderBeadProject(project, { compression: 100, scale: 32 });

  expect(sampleCenterHole(ninetyNine, 0, 0)).toBeTransparent();
  expect(sampleFourBeadIntersection(ninetyNine)).toBeTransparent();
  expect(sampleCenterHole(terminal, 0, 0)).toMatchProjectColor(project, 0);
  expect(sampleFourBeadIntersection(terminal)).toMatchOneOfNeighborColors(project);
});
```

Extend `test/bead-project.test.ts`:

```ts
it("uses one 2.6 mm pitch per cell independent of compression", () => {
  const project = makeProject({ rows: 12, columns: 20, beadPitchMm: 2.6 });
  expect(calculatePhysicalSize(project, 2.6)).toEqual({
    widthMm: 52,
    heightMm: 31.2,
  });
  expect(calculatePhysicalSize({ ...project, compression: 100 }, 2.6)).toEqual({
    widthMm: 52,
    heightMm: 31.2,
  });
});
```

Create `test/helpers/chartFixtures.ts` as a deterministic, project-owned chart
generator. It produces exact expected matrices for:

- numbered grids with thin/thick lines, coordinate labels, per-cell numbers,
  white beads on white backgrounds, and a diagonal synthetic watermark;
- hard-pixel charts at 1×, 8×, and 16× integer scale with solid/transparent
  backgrounds and external titles;
- ring previews whose center holes must never be sampled as bead color;
- transparent-support cells;
- JPEG near-ties and controlled compression artifacts;
- two-pattern canvases that require cropping;
- unrecoverable white-on-white pixels with no grid/alpha evidence;
- oblique and non-square inputs that must return a supported, user-visible
  “manual calibration/unsupported” result instead of a confident matrix.

Add `test/bead-recognition-corpus.test.ts` with table-driven assertions. Use
observed grid sizes including 23×17, 37×37, 52×52, 78×78, and 104×104 without
checking third-party artwork into Git. For every fixture, assert classification,
geometry, occupancy, source RGB, transparent support, low-confidence reasons,
and exact cells that require manual review.

- [ ] **Step 3: Run the migrated tests before copying implementation**

```bash
pnpm test:run \
  test/bead-project.test.ts \
  test/bead-project.property.test.ts \
  test/bead-recognition.test.ts \
  test/bead-recognition.property.test.ts \
  test/bead-renderer.test.ts \
  test/bead-renderer.property.test.ts \
  test/bead-editor-reducer.test.ts \
  test/bead-editor-reducer.property.test.ts \
  test/bead-recognition-corpus.test.ts
```

Expected: FAIL because `src/domain/*` does not exist.

- [ ] **Step 4: Copy the pure implementations and remove host imports**

```bash
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/types.ts src/domain/types.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/project.ts src/domain/project.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/recognition.ts src/domain/recognition.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/renderer.ts src/domain/renderer.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/editorReducer.ts src/domain/editorReducer.ts
```

Replace the old `RecognitionRequest.source` import with a module-owned transport type:

```ts
export interface Raster {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

export interface RecognitionRequest {
  source: Raster;
  mode: BeadInputMode;
  rows: number;
  columns: number;
  geometry: BeadGridGeometry;
  emptySelection: BeadEmptySelection;
  transparentSupportSampleCellIndex: number | null;
  orientation: BeadOrientation;
}
```

Keep these constants unchanged:

```ts
export const BEAD_MODULE_ID = "lumina.bead-pattern" as const;
export const BEAD_MODULE_VERSION = "1.0.0" as const;
export const BEAD_PROJECT_SCHEMA_VERSION = "bead-project/v1" as const;
export const BEAD_RENDER_SCHEMA_VERSION = "bead-render/v1" as const;
export const BEAD_RECIPE_PAYLOAD_VERSION = "bead-recipe/v1" as const;
export const DEFAULT_BEAD_PITCH_MM = 2.6;
export const DEFAULT_BEAD_COMPRESSION = 50;
export const MAX_BEAD_GRID_SIZE = 128;
```

Do not add image quantization, automatic photo pixelation, paper texture, or a second “ironed bead” entity.

- [ ] **Step 5: Document and implement the recognition contract**

`docs/recognition-contract.md` records the supported evidence for each input
mode:

- numbered grids separate occupancy from color, mask grid lines/high-gradient
  text, and sample corners/low-gradient pixels instead of the cell center;
- hard-pixel mode detects integer runs and explicitly reports information loss
  when foreground and background pixels are identical;
- ring mode samples the annulus and ignores the center hole;
- watermark/noise is never auto-removed or “repaired” from neighbors;
- uncertain classification remains user-overridable;
- perspective photos, lighting correction, OCR, and brand bead-code mapping
  remain unsupported in v1.

The document may link to the approved public research sources but must not copy
third-party charts, watermarks, artwork, or screenshots into this repository.
Implementation changes are complete only when a generated corpus fixture pins
the behavior.

- [ ] **Step 6: Run domain, corpus, and type gates**

```bash
pnpm test:run test/bead-project.test.ts test/bead-project.property.test.ts test/bead-recognition.test.ts test/bead-recognition.property.test.ts test/bead-recognition-corpus.test.ts test/bead-renderer.test.ts test/bead-renderer.property.test.ts test/bead-editor-reducer.test.ts test/bead-editor-reducer.property.test.ts
pnpm exec tsc --noEmit
```

Expected: all migrated assertions and the new terminal-fusion assertions PASS.

- [ ] **Step 7: Commit the domain migration**

```bash
git add src/domain test docs/recognition-contract.md
git commit -m "feat(bead): migrate recognition and fused rendering"
```

## Task 3: Inline the recognition worker into the single HTML runtime

**Files:**

- Create: `src/worker/beadWorker.ts`
- Create: `src/worker/workerClient.ts`
- Create: `src/worker/workerProtocol.ts`
- Modify: `src/vite-env.d.ts`
- Create: `test/bead-worker-client.test.ts`
- Create: `test/inline-worker-build.test.mjs`
- Create: `test/worker-cancellation.test.ts`
- Create: `scripts/benchmark.mjs`
- Create: `benchmarks/ci-budget.json`

- [ ] **Step 1: Migrate the worker test and add a production-construction assertion**

Copy the existing worker test:

```bash
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/bead-worker-client.test.ts test/bead-worker-client.test.ts
```

Update imports to `../src/worker/*`. Add:

```ts
it("constructs the worker from the build-inlined module", () => {
  const worker = createBeadWorker();
  expect(worker).toBeInstanceOf(Worker);
  worker.terminate();
});
```

- [ ] **Step 2: Run the focused test**

```bash
pnpm test:run test/bead-worker-client.test.ts
```

Expected: FAIL because the worker modules are absent.

- [ ] **Step 3: Copy the protocol and implementation, then use Vite's inline worker constructor**

```bash
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/beadWorker.ts src/worker/beadWorker.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/workerClient.ts src/worker/workerClient.ts
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/workerProtocol.ts src/worker/workerProtocol.ts
```

Use an injectable factory in `workerClient.ts`:

```ts
import InlineBeadWorker from "./beadWorker?worker&inline";

export type WorkerFactory = () => Worker;

export function createBeadWorker(
  factory: WorkerFactory = () => new InlineBeadWorker(),
): Worker {
  return factory();
}
```

Add the declaration to `src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />

declare module "*?worker&inline" {
  const WorkerConstructor: {
    new (): Worker;
  };
  export default WorkerConstructor;
}
```

- [ ] **Step 4: Prove the built HTML has no worker asset dependency**

`test/inline-worker-build.test.mjs` uses Node's test runner, reads
`dist/ui/index.html` after `pnpm build`, and asserts:

```ts
expect(html).not.toMatch(/<script[^>]+src=/i);
expect(html).not.toMatch(/new Worker\\([\"'][^\"']+\\.js/i);
expect(html).not.toMatch(
  /<(?:script|link|img)[^>]+(?:src|href)=[\"']https?:\\/\\//i,
);
```

`test/worker-cancellation.test.ts` must prove that every classify, recognize,
and render request carries a monotonic task ID; a later task cancels or
supersedes the earlier result, and a stale worker response can never overwrite
new calibration, matrix, or compression state.

Run:

```bash
pnpm test:run test/bead-worker-client.test.ts test/worker-cancellation.test.ts
pnpm build
node --test test/inline-worker-build.test.mjs
find dist/ui -type f -maxdepth 1 -print
```

Expected: tests PASS and the only output is `dist/ui/index.html`.

- [ ] **Step 5: Add reproducible performance measurements**

`scripts/benchmark.mjs` generates fixtures rather than loading copyrighted
charts. It records:

- time until the first 52×52 drag-preview response;
- 104×104 full render time at 32 pixels per cell;
- main-thread task slices;
- peak transferred bytes and released worker/Blob counts.

The reference desktop targets are preview start within 100 ms, full render
within 3 seconds, and no main-thread calculation slice over 50 ms.
`benchmarks/ci-budget.json` contains explicitly looser runner ceilings so CI
catches catastrophic regressions without pretending shared runners are the
reference desktop. Final acceptance records the strict values on the current
desktop Chrome/Electron environment.

Run:

```bash
node scripts/benchmark.mjs --json artifacts/benchmark.json
```

Expected: valid bounded JSON with all four metrics. Do not commit a machine
specific result as a universal baseline.

- [ ] **Step 6: Commit**

```bash
git add src/worker src/vite-env.d.ts test scripts/benchmark.mjs benchmarks/ci-budget.json
git commit -m "feat(bead): inline recognition worker"
```

## Task 4: Give the module its own UI, translations, and host theme adapter

**Files:**

- Create: `src/ui/Button.tsx`
- Create: `src/ui/Checkbox.tsx`
- Create: `src/ui/HelpDot.tsx`
- Create: `src/ui/Slider.tsx`
- Create: `src/ui/CropModal.tsx`
- Create: `src/ui/panelPrimitives.ts`
- Create: `src/ui/theme.css`
- Create: `src/i18n/translations.ts`
- Create: `src/app/BeadCalibrationStep.tsx`
- Create: `src/app/BeadEditorStep.tsx`
- Create: `src/app/BeadHandoffConfirmDialog.tsx`
- Create: `src/app/BeadMatrixCanvas.tsx`
- Create: `src/app/BeadSourceCanvas.tsx`
- Create: `test/bead-calibration-step.test.tsx`
- Create: `test/bead-editor-step.test.tsx`
- Create: `test/module-boundary.test.ts`

- [ ] **Step 1: Copy the UI behavior tests, then pin the repository boundary**

```bash
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/bead-calibration-step.test.tsx test/bead-calibration-step.test.tsx
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/bead-editor-step.test.tsx test/bead-editor-step.test.tsx
```

Update only the component import roots. Add `test/module-boundary.test.ts`:

```ts
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

async function sourceFiles(root: string): Promise<string[]> {
  const entries = await readdir(root, { withFileTypes: true });
  return (
    await Promise.all(
      entries.map(async (entry) => {
        const file = path.join(root, entry.name);
        return entry.isDirectory() ? sourceFiles(file) : [file];
      }),
    )
  ).flat();
}

it("depends on Lumina only through the public Workshop SDK", async () => {
  const files = (await sourceFiles("src")).filter((file) => /\.tsx?$/.test(file));
  const text = (await Promise.all(files.map((file) => readFile(file, "utf8")))).join("\n");
  expect(text).not.toMatch(/Lumina-studio|frontend\\/src|\\.\\.\\/\\.\\.\\/components|\\.\\.\\/\\.\\.\\/store/);
  expect(text).not.toMatch(/from [\"']@lumina\\/(?!workshop-sdk)/);
});
```

Extend the UI tests to cover every matrix tool (brush, eraser, eyedropper,
connected fill, transparent support, undo, redo), previous/next
low-confidence navigation, source/matrix/fusion view switching, the fixed local
inspection zoom, and clickable compression anchors at 0, 50, and 100. Assert
that changing compression never changes the logical matrix or physical pitch.

- [ ] **Step 2: Run the tests and confirm missing module-owned UI**

```bash
pnpm test:run test/bead-calibration-step.test.tsx test/bead-editor-step.test.tsx test/module-boundary.test.ts
```

Expected: FAIL because the destination UI files do not exist.

- [ ] **Step 3: Copy only the bead presentation components, then replace shared UI imports**

```bash
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/BeadCalibrationStep.tsx src/app/BeadCalibrationStep.tsx
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/BeadEditorStep.tsx src/app/BeadEditorStep.tsx
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/BeadHandoffConfirmDialog.tsx src/app/BeadHandoffConfirmDialog.tsx
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/BeadMatrixCanvas.tsx src/app/BeadMatrixCanvas.tsx
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/workshop/modules/bead/BeadSourceCanvas.tsx src/app/BeadSourceCanvas.tsx
```

Implement small module-owned versions of `Button`, `Checkbox`, `HelpDot`, `Slider`, and `CropModal`. Do not copy Lumina's general component library or Tailwind configuration. Convert the existing bead `panelPrimitives` class strings into semantic module classes in `theme.css`.

`theme.css` must use only public tokens with safe fallbacks:

```css
:root {
  color-scheme: light dark;
  font-family: var(--lumina-font-sans, ui-sans-serif, system-ui, sans-serif);
  color: var(--lumina-text-primary, #172033);
  background: var(--lumina-surface-canvas, #f4f7fb);
}

:root[data-theme="dark"] {
  color: var(--lumina-text-primary, #edf2f7);
  background: var(--lumina-surface-canvas, #111827);
}

.panel {
  border: 1px solid var(--lumina-border-subtle, rgba(100, 116, 139, 0.28));
  border-radius: var(--lumina-radius-panel, 16px);
  background: var(--lumina-surface-panel, rgba(255, 255, 255, 0.82));
}

button:focus {
  outline: none;
}

button:focus-visible,
input:focus-visible {
  outline: 3px solid var(--lumina-focus-ring, rgba(59, 130, 246, 0.42));
  outline-offset: 2px;
}
```

The fallback colors live only inside the external module; Lumina's host still supplies light/dark tokens. Selection uses a single quiet whole-control signal and does not combine a checkmark, thick outline, and layout shift.

- [ ] **Step 4: Copy only bead-specific translation values into a local typed table**

`src/i18n/translations.ts`:

```ts
export const messages = {
  "zh-CN": {
    "app.name": "拼豆工作台",
    "compression.label": "熨烫压合",
    "compression.open": "孔隙清晰",
    "compression.closed": "完全压合",
  },
  "en-US": {
    "app.name": "Fuse Bead Studio",
    "compression.label": "Ironing compression",
    "compression.open": "Open gaps",
    "compression.closed": "Fully fused",
  },
} as const;

export type Locale = keyof typeof messages;
export type MessageKey = keyof (typeof messages)["zh-CN"];

export function translate(locale: Locale, key: MessageKey): string {
  return messages[locale][key] ?? messages["en-US"][key];
}
```

Move every `workshop.bead.*` string actually used by the migrated components into this table. Keep Chinese and English key sets equal with a compile-time test.

- [ ] **Step 5: Run UI, boundary, and accessibility smoke tests**

```bash
pnpm test:run test/bead-calibration-step.test.tsx test/bead-editor-step.test.tsx test/module-boundary.test.ts
pnpm exec tsc --noEmit
```

Expected: tests PASS, and no source import resolves outside this repository except `@lumina/workshop-sdk`.

- [ ] **Step 6: Commit**

```bash
git add src/app src/ui src/i18n test
git commit -m "feat(ui): make bead editor self contained"
```

## Task 5: Connect the app exclusively through the Workshop SDK

**Files:**

- Create: `src/host/hostAdapter.ts`
- Create: `src/app/BeadWorkshopModule.tsx`
- Modify: `src/main.tsx`
- Create: `test/helpers/sdkHarness.ts`
- Create: `test/bead-workshop-module.test.tsx`
- Create: `test/sdk-integration.test.tsx`

- [ ] **Step 1: Migrate the complete workflow test onto an SDK harness**

Copy:

```bash
cp /Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/bead-workshop-module.test.tsx test/bead-workshop-module.test.tsx
```

Replace direct `WorkshopHostServices` mocks with `test/helpers/sdkHarness.ts`, which creates a real `MessageChannel`, accepts `lumina.workshop.ready`, replies with `lumina.workshop.connect`, and records typed RPC requests. Do not mock `hostAdapter.ts`.

Add an integration assertion:

```ts
it("reports ready only after restoring the latest project and rendering", async () => {
  const harness = createSdkHarness({
    latestProject: makeStoredProject(),
    uiState: makeUiState("zh-CN", "dark"),
  });
  render(<ModuleEntry connect={harness.connect} />);

  await screen.findByText("熨烫压合");
  expect(harness.methods()).toEqual(
    expect.arrayContaining(["ui.getState", "project.latest", "lifecycle.ready"]),
  );
  expect(harness.indexOf("lifecycle.ready")).toBeGreaterThan(
    harness.indexOf("project.latest"),
  );
});
```

- [ ] **Step 2: Run the tests before implementing the adapter**

```bash
pnpm test:run test/bead-workshop-module.test.tsx test/sdk-integration.test.tsx
```

Expected: FAIL because `hostAdapter.ts` and `BeadWorkshopModule.tsx` do not exist.

- [ ] **Step 3: Adapt SDK transports without leaking browser objects into storage**

`hostAdapter.ts` owns these conversions:

```ts
import type {
  WorkshopClient,
  WorkshopPickedImage,
  WorkshopProjectRecord,
} from "@lumina/workshop-sdk";

export async function pickBeadSource(
  client: WorkshopClient,
): Promise<BeadProjectSource | null> {
  const picked: WorkshopPickedImage | null = await client.image.pick();
  if (!picked) return null;
  return {
    fileName: picked.name,
    mimeType: picked.mimeType,
    blob: new Blob([picked.bytes], { type: picked.mimeType }),
    pixelWidth: picked.raster.width,
    pixelHeight: picked.raster.height,
  };
}

export async function saveBeadProject(
  client: WorkshopClient,
  project: BeadProject,
): Promise<void> {
  const record: WorkshopProjectRecord<BeadProject> = {
    projectId: project.projectId,
    schemaVersion: project.schemaVersion,
    createdAt: project.createdAt,
    updatedAt: project.updatedAt,
    project,
  };
  await client.projects.save(record);
}
```

Structured-clone the recipe payload before sending it. Do not retain `FileSystemHandle`, absolute path, Lumina store object, or host token.

- [ ] **Step 4: Build the module entry lifecycle**

`src/main.tsx`:

```tsx
import React from "react";
import { createRoot } from "react-dom/client";
import {
  applyWorkshopUiState,
  connectWorkshop,
  type WorkshopClient,
} from "@lumina/workshop-sdk";
import { BeadWorkshopModule } from "./app/BeadWorkshopModule";
import "./ui/theme.css";

async function start(): Promise<void> {
  const client: WorkshopClient = await connectWorkshop({
    moduleId: "lumina.bead-pattern",
    moduleVersion: "1.0.0",
  });
  const ui = await client.ui.getState();
  applyWorkshopUiState(ui);

  const root = createRoot(document.getElementById("root")!);
  root.render(<BeadWorkshopModule client={client} locale={ui.locale} />);
}

void start();
```

`BeadWorkshopModule` must:

1. restore and validate `project.latest()` before rendering the editor;
2. show a module-owned recovery error if a project is invalid;
3. report bounded diagnostics only after validation;
4. call `lifecycle.ready()` after the usable screen commits;
5. close the client on `pagehide`;
6. never fetch its own update, Registry, or package.

Use an injectable `connect` only in `ModuleEntry` tests; production `main.tsx` imports the real SDK.

- [ ] **Step 5: Run workflow and SDK integration tests**

```bash
pnpm test:run test/bead-workshop-module.test.tsx test/sdk-integration.test.tsx
pnpm exec tsc --noEmit
```

Expected: tests PASS and the harness records only manifest-declared methods.

- [ ] **Step 6: Commit**

```bash
git add src/main.tsx src/app/BeadWorkshopModule.tsx src/host test
git commit -m "feat(module): connect through Workshop SDK"
```

## Task 6: Keep source colors and Lumina print-library mapping separate

**Files:**

- Create: `src/host/colorMapping.ts`
- Modify: `src/domain/types.ts`
- Modify: `src/domain/project.ts`
- Modify: `src/app/BeadEditorStep.tsx`
- Modify: `src/app/BeadWorkshopModule.tsx`
- Create: `test/color-mapping.test.ts`
- Modify: `test/bead-project.test.ts`
- Modify: `test/bead-workshop-module.test.tsx`

- [ ] **Step 1: Write failing color-library separation tests**

```ts
// test/color-mapping.test.ts
it("maps previews without overwriting recognized source colors", () => {
  const project = makeProject({
    palette: [[250, 20, 30], [10, 220, 80]],
  });
  const library = makeLibrary({
    id: "material-archive:official-pla:2026-07",
    colors: [
      { id: "red", label: "官方红", hex: "#E3212A", materialId: "official-red" },
      { id: "green", label: "官方绿", hex: "#25A55F", materialId: "official-green" },
    ],
  });

  const mapped = mapProjectToColorLibrary(project, library);

  expect(mapped.sourcePalette).toEqual(project.palette);
  expect(mapped.printMapping.libraryId).toBe(library.id);
  expect(mapped.printMapping.entries).toEqual([
    { sourcePaletteIndex: 0, colorEntryId: "red" },
    { sourcePaletteIndex: 1, colorEntryId: "green" },
  ]);
  expect(project.palette).toEqual([[250, 20, 30], [10, 220, 80]]);
});
```

Also test:

- no current library returns `null` mapping and keeps source preview;
- repeated mapping is deterministic;
- equal-distance ties follow source library order without hiding either brand;
- manually chosen mapping persists by stable `colorEntryId`;
- changing library marks old mapping stale rather than silently remapping;
- transparent and empty cells never receive material mapping.

- [ ] **Step 2: Run the focused tests**

```bash
pnpm test:run test/color-mapping.test.ts test/bead-project.test.ts
```

Expected: FAIL because `printMapping` and `colorMapping.ts` do not exist.

- [ ] **Step 3: Add the versioned, optional print-mapping field**

```ts
export interface BeadPrintMapping {
  libraryId: string;
  libraryLabel: string;
  entries: Array<{
    sourcePaletteIndex: number;
    colorEntryId: string;
  }>;
}

export interface BeadProject {
  // Existing v1 fields remain unchanged.
  printMapping?: BeadPrintMapping | null;
}
```

Because the field is optional, existing `bead-project/v1` data remains valid. Serialization must omit `undefined` and preserve explicit `null`. The source `palette` is never replaced by LUT/material hex values.

Implement CIE Lab nearest-color mapping with deterministic tie-breaking. Reuse no Lumina-internal color helper; keep the math and tests in this repository. Treat the host-provided library as presentation data, not trusted executable input.

- [ ] **Step 4: Expose source/print preview as one explicit toggle**

The editor adds:

- “图纸原色 / Source colors”
- “当前打印色库 / Current print library”

The print option is disabled with a short explanation when `colorLibrary.read()` returns `null`. A library change displays a stale-mapping action; it does not auto-select, rank, deduplicate, or hide material brands. Manual mapping uses stable entry IDs and includes all provided entries.

- [ ] **Step 5: Run mapping and UI tests**

```bash
pnpm test:run test/color-mapping.test.ts test/bead-project.test.ts test/bead-workshop-module.test.tsx
pnpm exec tsc --noEmit
```

Expected: tests PASS, and a project created without a library still round-trips as `bead-project/v1`.

- [ ] **Step 6: Commit**

```bash
git add src test
git commit -m "feat(bead): add non-destructive print color mapping"
```

## Task 7: Preserve recipe compatibility and hand a source-color PNG to Lumina

**Files:**

- Modify: `src/domain/project.ts`
- Modify: `src/app/BeadWorkshopModule.tsx`
- Modify: `src/host/hostAdapter.ts`
- Create: `test/recipe-compatibility.test.ts`
- Create: `test/handoff.test.ts`
- Create: `test/fixtures/bead-recipe-v1.json`

- [ ] **Step 1: Pin the existing recipe envelope with a checked-in fixture**

Copy the current external envelope content from:

```text
/Users/min/.codex/worktrees/b9d4/Lumina-studio/frontend/src/__tests__/fixtures/beadRecipeSource.ts
```

Convert it to deterministic JSON at `test/fixtures/bead-recipe-v1.json`, then test:

```ts
it("restores the in-tree bead-recipe/v1 payload without migration loss", async () => {
  const source = JSON.parse(
    await readFile("test/fixtures/bead-recipe-v1.json", "utf8"),
  );
  const restored = restoreBeadProjectFromRecipeSource(source, {
    projectId: "restored",
    now: "2030-01-01T00:00:00.000Z",
  });
  expect(createRecipeSource(restored).payload).toEqual(source.payload);
});
```

Add invalid payload tests for mismatched module ID, unsupported payload version, grid/product mismatch, out-of-range palette index, invalid pitch, invalid compression, and payload over 1 MiB.

- [ ] **Step 2: Write the source-color handoff test**

```ts
it("hands off source colors while naming the previewed print library", async () => {
  const project = makeProjectWithDifferentSourceAndPrintColors();
  const client = createRecordingClient();

  await handoffBeadProject(client, project);

  const handoff = client.lastImageHandoff();
  const decoded = decodePng(handoff.pngBytes);
  expect(sampleBeadFace(decoded, 0)).toEqual(project.palette[0]);
  expect(handoff.colorLibraryId).toBe(project.printMapping?.libraryId);
  expect(handoff.layout).toEqual({
    kind: "square-grid",
    rows: project.rows,
    columns: project.columns,
    pitchMm: project.beadPitchMm,
  });
  expect(handoff.recipeSource.projectSchemaVersion).toBe("bead-project/v1");
  expect(handoff.recipeSource.renderSchemaVersion).toBe("bead-render/v1");
  expect(handoff.recipeSource.payload.payloadVersion).toBe("bead-recipe/v1");
});
```

- [ ] **Step 3: Run the focused tests**

```bash
pnpm test:run test/recipe-compatibility.test.ts test/handoff.test.ts
```

Expected: FAIL until the external adapter emits the SDK `WorkshopImageHandoff`.

- [ ] **Step 4: Implement bounded handoff**

The handoff path must:

1. render the source palette at the selected compression;
2. preserve the full rectangular canvas and transparent empty cells;
3. encode a real PNG, not a data URL;
4. set physical size to `columns * beadPitchMm` by `rows * beadPitchMm`;
5. include the matching `square-grid` layout with rows, columns, and pitch;
6. include the current `colorLibraryId` only as mapping provenance;
7. include the complete `bead-recipe/v1` payload under the 1 MiB host limit;
8. show a module confirmation summary before calling `client.handoff.image()`;
9. handle `needs-confirmation` without assuming Lumina replaced its current image;
10. report a stable, localized error code when the host rejects size or quota.

Do not call Lumina preview/generate endpoints from the module. A successful SDK handoff enters Lumina's existing image-conversion flow, where the user chooses LUT/material archive, size, and layered-color generation.

- [ ] **Step 5: Run compatibility, handoff, and full module tests**

```bash
pnpm test:run test/recipe-compatibility.test.ts test/handoff.test.ts test/bead-workshop-module.test.tsx
pnpm exec tsc --noEmit
```

Expected: PASS, including exact restoration of the checked-in v1 fixture.

- [ ] **Step 6: Commit**

```bash
git add src test
git commit -m "feat(handoff): preserve bead recipe and source colors"
```

## Task 8: Build and validate a deterministic `.lumina-workshop` archive

**Files:**

- Create: `scripts/package.mjs`
- Modify: `package.json`
- Create: `test/package-output.test.mjs`
- Create: `.gitignore`

- [ ] **Step 1: Write a failing archive-content test**

```js
// test/package-output.test.mjs
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { unzipSync } from "fflate";

test("contains only the fixed v1 package surface", async () => {
  const bytes = await readFile(
    "artifacts/lumina.bead-pattern-1.0.0.lumina-workshop",
  );
  const entries = Object.keys(unzipSync(bytes)).sort();
  assert.deepEqual(entries, [
    "LICENSE",
    "README.md",
    "assets/icon.png",
    "manifest.json",
    "ui/index.html",
  ]);
});
```

Add a second test that packages twice and asserts identical SHA-256.

- [ ] **Step 2: Run the test before adding the packager**

```bash
node --test test/package-output.test.mjs
```

Expected: FAIL because `artifacts/*.lumina-workshop` does not exist.

- [ ] **Step 3: Implement deterministic packaging**

`scripts/package.mjs` must:

- parse `manifest.json` and require its version to equal `package.json`;
- require the exact five files in the test;
- read bytes without line-ending transformation;
- sort entry names lexically;
- set the ZIP modification time to `2000-01-01T00:00:00Z`;
- use a fixed compression level;
- refuse a total package over 100 MiB;
- write the archive atomically under `artifacts/`;
- write `<asset>.sha256` with lowercase hex and the asset basename;
- never edit the manifest during packaging.

Core structure:

```js
import { createHash } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { zipSync } from "fflate";

const assetName = "lumina.bead-pattern-1.0.0.lumina-workshop";
const entries = [
  ["LICENSE", await readFile("LICENSE")],
  ["README.md", await readFile("README.md")],
  ["assets/icon.png", await readFile("public/assets/icon.png")],
  ["manifest.json", await readFile("manifest.json")],
  ["ui/index.html", await readFile("dist/ui/index.html")],
].sort(([left], [right]) => left.localeCompare(right));

const archive = zipSync(
  Object.fromEntries(
    entries.map(([name, bytes]) => [
      name,
      [bytes, { mtime: new Date("2000-01-01T00:00:00.000Z") }],
    ]),
  ),
  { level: 9 },
);
```

Complete error handling and atomic rename around this core.

At this task, change the package script to:

```json
{
  "scripts": {
    "package": "pnpm run test:run && pnpm run build && node --test test/inline-worker-build.test.mjs && node scripts/package.mjs && node --test test/package-output.test.mjs"
  }
}
```

The package-output test uses Node's test runner, so the normal Vitest run does
not require a pre-existing generated artifact.

- [ ] **Step 4: Package twice and validate with the host validator**

```bash
pnpm package
cp artifacts/lumina.bead-pattern-1.0.0.lumina-workshop /tmp/bead-first.lumina-workshop
pnpm package
cmp /tmp/bead-first.lumina-workshop artifacts/lumina.bead-pattern-1.0.0.lumina-workshop
node --test test/package-output.test.mjs
cd /Users/min/.codex/worktrees/b9d4/Lumina-studio
./.venv/bin/python -m core.workshop.package_validator /Users/min/CascadeProjects/Lumina-Fuse-Bead-Studio/artifacts/lumina.bead-pattern-1.0.0.lumina-workshop
```

Expected: byte-for-byte comparison PASS, module test PASS, and host validator prints a valid identity without executing the module.

- [ ] **Step 5: Commit**

```bash
cd /Users/min/CascadeProjects/Lumina-Fuse-Bead-Studio
git add scripts package.json test .gitignore
git commit -m "build(module): package deterministic Workshop archive"
```

## Task 9: Add CI, release assets, documentation, and real UI acceptance

**Files:**

- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`
- Modify: `README.md`
- Create: `docs/testing.md`
- Create: `docs/security.md`

- [ ] **Step 1: Add CI that proves source, build, and package boundaries**

`.github/workflows/ci.yml`:

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - uses: pnpm/action-setup@b906affcce14559ad1aafd4ab0e942779e9f58b1 # v4
        with:
          version: 10.33.2
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4
        with:
          node-version: 22
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - run: pnpm test:run
      - run: pnpm exec tsc --noEmit
      - run: node scripts/benchmark.mjs --check-regression
      - run: pnpm package
      - run: git diff --exit-code
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        with:
          name: fuse-bead-workshop-package
          path: |
            artifacts/*.lumina-workshop
            artifacts/*.sha256
```

- [ ] **Step 2: Add a tag-gated release workflow**

`.github/workflows/release.yml` runs only for `v[0-9]+.[0-9]+.[0-9]+`, repeats the frozen install/test/type/package steps, verifies the tag without `v` equals manifest and package versions, and publishes exactly:

- `lumina.bead-pattern-1.0.0.lumina-workshop`
- `lumina.bead-pattern-1.0.0.lumina-workshop.sha256`

Reuse the exact checkout, pnpm, and setup-node SHAs from `ci.yml`, then use
the runner's `gh release create` with `contents: write`; this avoids a separate
third-party release action. Do not publish mutable `latest.lumina-workshop`
assets.

- [ ] **Step 3: Document the real product and trust boundary**

`README.md` must cover:

- the three supported input chart modes;
- grid calibration and low-confidence correction;
- fusion slider examples at 0, 50, 80, and 100;
- 2.6 mm physical sizing;
- source-color versus print-library preview;
- the fact that final layered 3D-print output remains Lumina's responsibility;
- local development through the host's Developer view;
- package permissions and no-network runtime;
- project/recipe schema compatibility policy.

`docs/security.md` states that the module does not receive filesystem paths, registry credentials, update credentials, Electron APIs, or general network access.

- [ ] **Step 4: Run the complete module gate**

```bash
pnpm install --frozen-lockfile
pnpm test:run
pnpm exec tsc --noEmit
node scripts/benchmark.mjs --check-regression
pnpm package
git diff --check
git status --short
```

Expected: all gates PASS; only intentionally generated ignored `artifacts/` files may remain untracked.

- [ ] **Step 5: Install the package through the host Developer view**

Start Lumina only for this acceptance session:

```bash
cd /Users/min/.codex/worktrees/b9d4/Lumina-studio
./.venv/bin/python start_all.py
```

At 1280×720, verify in Chinese and English, light and dark:

1. Developer installs the local `.lumina-workshop`.
2. Permission confirmation names all four requested permissions.
3. The module becomes ready inside the sandbox.
4. A numbered-grid screenshot, a hard-pixel chart, and a ring preview each reach calibration and correction.
5. Empty and transparent-support cells remain distinguishable.
6. Compression 0, 50, 80, 99, and 100 update live without freezing the host.
7. At 100, center holes and four-bead valleys close; at 99, residual openings remain visible.
8. Source-color and current LUT/material-library previews differ without mutating the source palette.
9. The handoff confirmation sends the source-color PNG into Lumina's existing converter.
10. Refresh restores the latest project.
11. A malformed recipe shows a module error while Lumina remains usable.
12. No HTTP, WebSocket, popup, download, or cross-module request escapes the sandbox.

Capture screenshots for 0/50/100 compression and the converter handoff. Then stop every process:

```bash
cd /Users/min/.codex/worktrees/b9d4/Lumina-studio
./.venv/bin/python start_all.py --kill
```

Expected: no `api_server.py`, `start_all.py`, Vite, Vitest, or module dev-server process remains.

- [ ] **Step 6: Commit, push, and open the module PR**

```bash
cd /Users/min/CascadeProjects/Lumina-Fuse-Bead-Studio
git add .github README.md docs
git commit -m "ci(module): verify and release Workshop package"
git push -u origin MOVIBALE/feat/initial-fuse-bead-module
gh pr create \
  --base main \
  --head MOVIBALE/feat/initial-fuse-bead-module \
  --title "feat: publish the official Fuse Bead Studio module" \
  --body-file /tmp/fuse-bead-module-pr.md
```

The PR description includes the exact SDK release dependency, package hash from CI, host validator result, browser/Electron acceptance evidence, and remaining seed-release dependency.

- [ ] **Step 7: Tag the reviewed merge commit and verify immutable assets**

After the PR is reviewed and merged:

```bash
MODULE_PR_NUMBER="$(gh pr view MOVIBALE/feat/initial-fuse-bead-module \
  --repo lumina-layer-studio/Lumina-Fuse-Bead-Studio \
  --json number \
  --jq .number)"
MODULE_MERGE_SHA="$(gh pr view "$MODULE_PR_NUMBER" \
  --repo lumina-layer-studio/Lumina-Fuse-Bead-Studio \
  --json mergeCommit \
  --jq .mergeCommit.oid)"
git fetch origin main --tags
git show "$MODULE_MERGE_SHA":.github/workflows/release.yml >/dev/null
git tag -a v1.0.0 "$MODULE_MERGE_SHA" -m "Fuse Bead Studio v1.0.0"
git push origin v1.0.0
```

Wait for the tag workflow, then:

```bash
gh release view v1.0.0 \
  --repo lumina-layer-studio/Lumina-Fuse-Bead-Studio \
  --json tagName,isDraft,isPrerelease,assets,url
BEAD_RELEASE_CACHE="/Users/min/.cache/lumina-workshop-release/bead-v1.0.0"
mkdir -p "$BEAD_RELEASE_CACHE"
gh release download v1.0.0 \
  --repo lumina-layer-studio/Lumina-Fuse-Bead-Studio \
  --pattern "lumina.bead-pattern-1.0.0.lumina-workshop*" \
  --dir "$BEAD_RELEASE_CACHE"
cd "$BEAD_RELEASE_CACHE"
shasum -a 256 -c lumina.bead-pattern-1.0.0.lumina-workshop.sha256
```

Expected: the Release is neither draft nor prerelease, contains exactly the
package and checksum, and verification PASSes. Enable GitHub immutable releases
for the official repository before Registry admission; if the account cannot
enable it, record that platform limitation and rely on the signed Registry hash
as the hard client boundary.

## Module acceptance checkpoint

Do not register or seed `v1.0.0` until all of these are true:

- the independent repository imports Lumina only through `@lumina/workshop-sdk`;
- all migrated behavior and property tests pass;
- a deterministic archive contains only the five allowed files;
- the main repository's package validator accepts the archive;
- the worker and all assets are contained in `ui/index.html`;
- project and recipe schemas restore existing `bead-project/v1` and `bead-recipe/v1` fixtures;
- the output PNG uses source colors and physical size remains `pitch × grid`;
- the print-library mapping never mutates or hides source/library identities;
- compression 100 closes holes and four-bead voids while 99 retains a residual opening;
- full Developer-view acceptance passes in the real Electron security boundary;
- the module PR is merged and the immutable GitHub Release asset exists.
