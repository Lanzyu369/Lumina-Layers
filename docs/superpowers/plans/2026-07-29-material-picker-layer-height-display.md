# Material Picker Layer Height Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each material archive's calibration layer height in the existing material picker without changing filtering, selection, or conversion behavior.

**Architecture:** Keep formatting local to `MaterialPickerDialog.tsx` because this is presentation-only data. Reuse the existing `layer_height_mm` field, summarize only `displayProfiles ?? profiles`, and verify behavior through the existing component test suite.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Vitest, Testing Library

---

### Task 1: Add calibration layer-height presentation

**Files:**
- Modify: `frontend/src/components/ui/MaterialPickerDialog.tsx`
- Test: `frontend/src/__tests__/material-picker.test.tsx`

- [ ] **Step 1: Write failing component tests**

Add coverage that renders:

```tsx
const alice = {
  ...PROFILE_MATERIALS[0],
  layer_height_mm: 0.1,
};
const bob = {
  ...PROFILE_MATERIALS[1],
  layer_height_mm: 0.04,
};
```

Assert that:

```tsx
expect(redCard).toHaveTextContent("JAYO · PLA · 0.04 / 0.10 mm");
expect(aliceRow).toHaveTextContent("0.10 mm");
expect(bobRow).toHaveTextContent("0.04 mm");
```

Extend the existing favorites regression so hidden profiles do not contribute to
the summary, and add a single-profile case where `layer_height_mm: null` produces
no `mm` placeholder.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python scripts/run_vitest.py run src/__tests__/material-picker.test.tsx -t "calibration layer height|hidden sibling profiles"
```

Expected: FAIL because the picker does not yet render layer-height text.

- [ ] **Step 3: Add minimal local formatters**

In `MaterialPickerDialog.tsx`, add presentation-only helpers:

```tsx
function validLayerHeightMm(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : null;
}

function formatLayerHeightMm(value: number | null | undefined): string | null {
  const valid = validLayerHeightMm(value);
  return valid === null ? null : `${valid.toFixed(2)} mm`;
}

function formatLayerHeightSummary(
  profiles: SavedMaterialLibraryItem[],
): string | null {
  const heights = Array.from(
    new Set(
      profiles
        .map((profile) => validLayerHeightMm(profile.layer_height_mm))
        .filter((value): value is number => value !== null),
    ),
  ).sort((left, right) => left - right);
  if (heights.length === 0) return null;
  return `${heights.map((height) => height.toFixed(2)).join(" / ")} mm`;
}
```

- [ ] **Step 4: Render the values in the three approved locations**

Append `formatLayerHeightMm(profile.layer_height_mm)` to the single-card subtitle.
Append `formatLayerHeightSummary(displayProfiles)` to the grouped-card subtitle.
Append `formatLayerHeightMm(profile.layer_height_mm)` to each expanded author
row's quality information.

Do not add state, filters, warnings, translations, API fields, or selection
branches.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
python scripts/run_vitest.py run src/__tests__/material-picker.test.tsx -t "calibration layer height|hidden sibling profiles"
```

Expected: all selected tests PASS.

### Task 2: Verify and hand off

**Files:**
- Verify: `frontend/src/components/ui/MaterialPickerDialog.tsx`
- Verify: `frontend/src/__tests__/material-picker.test.tsx`

- [ ] **Step 1: Run related component regression tests**

```bash
python scripts/run_vitest.py run src/__tests__/material-picker-model.test.ts src/__tests__/material-picker-preferences.test.ts src/__tests__/material-picker.test.tsx src/__tests__/BasicSettings.test.tsx src/__tests__/material-library-panel.test.tsx
```

Expected: all tests PASS.

- [ ] **Step 2: Run static and production gates**

```bash
cd frontend
pnpm lint
pnpm build
```

Expected: both commands exit `0`.

- [ ] **Step 3: Perform browser QA**

Open the material picker with single-profile, grouped-profile, favorites-only,
and missing-height fixtures. Check desktop two-column and narrow one-column
layouts in light and dark themes. Confirm text remains readable and selection,
favorites, and Done behavior are unchanged.

- [ ] **Step 4: Inspect and commit the scoped diff**

```bash
git diff --check
git status --short
git add frontend/src/components/ui/MaterialPickerDialog.tsx frontend/src/__tests__/material-picker.test.tsx
git commit -m "feat(frontend): show material calibration layer heights"
```

Expected: runtime diff is limited to the picker component and its existing
component test.
