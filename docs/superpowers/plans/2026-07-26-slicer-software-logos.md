# Slicer Software Logos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show locally bundled slicer application logos in the Settings slicer dropdown and the post-generation slicer action without changing selection, persistence, detection, or launch behavior.

**Architecture:** A shared branding resolver normalizes existing settings/detected slicer IDs and maps them to local assets. A focused `SlicerLogo` component owns the fixed visual slot and fallback, while the generic `Dropdown` gains an optional leading node that remains unused by existing text-only callers.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Vite static assets, Vitest, Testing Library

---

## File Map

- Create `frontend/src/assets/slicer-logos/`: official local logo assets plus `SOURCES.md`.
- Create `frontend/src/utils/slicerBranding.ts`: shared ID-to-logo resolution.
- Create `frontend/src/components/slicer/SlicerLogo.tsx`: fixed 28px logo plate, loading state, and generic fallback.
- Create `frontend/src/__tests__/slicer-branding.test.tsx`: branding and fallback regressions.
- Modify `frontend/src/components/ui/Dropdown.tsx`: optional `leading` node for trigger and rows.
- Modify `frontend/src/__tests__/ui-components.test.tsx`: generic dropdown leading-node coverage.
- Modify `frontend/src/components/SettingsPanel.tsx`: add logos to slicer options.
- Modify `frontend/src/components/__tests__/SettingsPanel.machineAdapter.test.tsx`: settings logo coverage.
- Modify `frontend/src/components/sections/SlicerSelector.tsx`: add the shared logo plate to the action and menu.
- Modify `frontend/src/__tests__/slicer-selector.test.tsx`: action, menu, and loading-state coverage.

### Task 1: Add local assets and shared branding

**Files:**
- Create: `frontend/src/assets/slicer-logos/*`
- Create: `frontend/src/utils/slicerBranding.ts`
- Create: `frontend/src/components/slicer/SlicerLogo.tsx`
- Create: `frontend/src/__tests__/slicer-branding.test.tsx`

- [ ] **Step 1: Write the failing branding/component tests**

Add tests that require both settings and detected IDs to resolve to the same asset and unknown IDs to render the generic fallback:

```tsx
expect(getSlicerLogoSource("BambuStudio")).toBe(getSlicerLogoSource("bambu_studio"));
expect(getSlicerLogoSource("AnycubicSlicerNext")).toMatch(/anycubic-slicer-next/);
render(<SlicerLogo slicerId="unknown_slicer" />);
expect(screen.getByTestId("slicer-logo-fallback")).toBeInTheDocument();
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 scripts/run_vitest.py run frontend/src/__tests__/slicer-branding.test.tsx
```

Expected: FAIL because the branding module and component do not exist.

- [ ] **Step 3: Add official assets and provenance**

Bundle Bambu Studio, OrcaSlicer, Snapmaker Orca, ElegooSlicer, Anycubic Slicer Next, Flash Studio Desktop, PrusaSlicer, and UltiMaker Cura assets under `frontend/src/assets/slicer-logos/`. Record the official source, original filename, retrieval date, and license/trademark context in `SOURCES.md`; no runtime URL is permitted.

- [ ] **Step 4: Implement the shared resolver**

Create `slicerBranding.ts` with static imports and existing ID normalization:

```ts
const SLICER_LOGOS: Readonly<Record<string, string>> = {
  BambuStudio: bambuStudioLogo,
  OrcaSlicer: orcaSlicerLogo,
  SnapmakerOrca: snapmakerOrcaLogo,
  ElegooSlicer: elegooSlicerLogo,
  AnycubicSlicerNext: anycubicSlicerNextLogo,
  FlashStudio: flashStudioLogo,
  PrusaSlicer: prusaSlicerLogo,
  Cura: curaLogo,
};

export function resolveSlicerBrandingId(value: string): string {
  return getSoftwareIdForDetectedSlicerId(value) ?? normalizeSlicerOptionId(value);
}

export function getSlicerLogoSource(value: string): string | null {
  return SLICER_LOGOS[resolveSlicerBrandingId(value)] ?? null;
}
```

- [ ] **Step 5: Implement the fixed logo plate**

Create `SlicerLogo` with `variant: "surface" | "onBrand"` and `loading?: boolean`. Render a `28 × 28px` plate, a contained `20px` image, an in-slot spinner while loading, and an inline generic layers icon after an unknown ID or image error. The image is `aria-hidden` because adjacent text provides the name.

- [ ] **Step 6: Run the focused test and verify it passes**

Run the Task 1 command again. Expected: PASS.

### Task 2: Teach Dropdown to render an optional leading node

**Files:**
- Modify: `frontend/src/components/ui/Dropdown.tsx`
- Modify: `frontend/src/__tests__/ui-components.test.tsx`

- [ ] **Step 1: Write the failing dropdown regression**

Pass `leading: <span data-testid="mode-logo" />` to one option, open the menu, and assert two instances: one in the selected trigger and one in the list option. Also retain the existing pure-text dropdown test.

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 scripts/run_vitest.py run frontend/src/__tests__/ui-components.test.tsx
```

Expected: TypeScript/test failure because `DropdownOption` has no `leading` property and the node is not rendered.

- [ ] **Step 3: Implement optional leading content**

Change the option type to:

```ts
interface DropdownOption {
  label: string;
  value: string;
  leading?: ReactNode;
}
```

Render `selectedOption?.leading` before the trigger label and `opt.leading` before each option label. Use fixed flex slots and leave role, selection, portal, and close behavior unchanged.

- [ ] **Step 4: Run the focused test and verify it passes**

Run the Task 2 command again. Expected: PASS.

### Task 3: Integrate both slicer surfaces and verify

**Files:**
- Modify: `frontend/src/components/SettingsPanel.tsx`
- Modify: `frontend/src/components/__tests__/SettingsPanel.machineAdapter.test.tsx`
- Modify: `frontend/src/components/sections/SlicerSelector.tsx`
- Modify: `frontend/src/__tests__/slicer-selector.test.tsx`

- [ ] **Step 1: Add failing integration assertions**

Require the Settings combobox and open options to contain Bambu/Orca logo test IDs. Require the generated action to contain the active Orca logo, the open menu to contain each detected logo, and loading to replace the logo image with the in-slot spinner.

- [ ] **Step 2: Run the integration tests and verify they fail**

Run:

```bash
python3 scripts/run_vitest.py run \
  frontend/src/components/__tests__/SettingsPanel.machineAdapter.test.tsx \
  frontend/src/__tests__/slicer-selector.test.tsx
```

Expected: FAIL because neither surface renders `SlicerLogo`.

- [ ] **Step 3: Add Settings integration**

Import `SlicerLogo` and pass the following for each slicer option:

```tsx
leading: <SlicerLogo slicerId={s.id} />,
```

Do not change the option value or `handleSlicerChange`.

- [ ] **Step 4: Add generated-action integration**

Render:

```tsx
<SlicerLogo
  slicerId={activeSlicerId ?? ""}
  variant="onBrand"
  loading={isLaunching || isAutoGenerating || isDownloading}
/>
```

before the main button label when an active slicer exists. Replace each menu color dot with `<SlicerLogo slicerId={slicer.id} />`; keep the download row icon unchanged. Re-export existing brand-style helpers if moved.

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
python3 scripts/run_vitest.py run \
  frontend/src/__tests__/slicer-branding.test.tsx \
  frontend/src/__tests__/ui-components.test.tsx \
  frontend/src/components/__tests__/SettingsPanel.machineAdapter.test.tsx \
  frontend/src/__tests__/slicer-selector.test.tsx
cd frontend && pnpm build
cd frontend && pnpm lint
```

Expected: all tests PASS, TypeScript/Vite build succeeds, and ESLint exits successfully.

- [ ] **Step 6: Browser-check the real Settings page**

Start the normal Lumina backend/frontend, open Settings in a browser, verify light/dark layout and the generated slicer action, capture a screenshot, then stop all started Lumina/Vite processes.

- [ ] **Step 7: Commit the implementation**

```bash
git add frontend/src/assets/slicer-logos frontend/src/utils/slicerBranding.ts \
  frontend/src/components/slicer/SlicerLogo.tsx frontend/src/components/ui/Dropdown.tsx \
  frontend/src/components/SettingsPanel.tsx frontend/src/components/sections/SlicerSelector.tsx \
  frontend/src/__tests__/slicer-branding.test.tsx frontend/src/__tests__/ui-components.test.tsx \
  frontend/src/components/__tests__/SettingsPanel.machineAdapter.test.tsx \
  frontend/src/__tests__/slicer-selector.test.tsx
git commit -m "feat(settings): add slicer software logos"
```
