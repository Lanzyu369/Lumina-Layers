# LUT Details Empty Manufacturer Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the LUT details manufacturer dropdown stay unselected while still auto-selecting the first matching LUT, without regressing metadata-first manufacturer resolution.

**Architecture:** Keep the backend contract unchanged and fix the selection semantics in the frontend store. Use TDD: add failing store tests for the empty-manufacturer state, then minimally adjust selection resolution so manufacturer filtering and LUT auto-selection are decoupled.

**Tech Stack:** React 19, TypeScript, Zustand, Vitest, Python pytest

---

### Task 1: Cover the empty-manufacturer state with failing store tests

**Files:**
- Modify: `frontend/src/__tests__/lut-details-store.test.ts`
- Verify against: `frontend/src/stores/lutDetailsStore.ts`

- [ ] **Step 1: Write the failing tests**

```ts
  it("keeps manufacturer empty while auto-selecting the first matching LUT", async () => {
    mockFetchLutDetailsCatalog.mockResolvedValue({ groups: CATALOG });
    mockFetchLutDetails.mockResolvedValue({
      name: "Bambu Lab - PLA - RYBW",
      path: "/fake/a.json",
      fingerprint: "fp-a",
      manufacturer: "Bambu Lab",
      manufacturer_source: "metadata",
      material_type: "PLA",
      material_source: "folder",
      color_mode: "4-Color (RYBW)",
      color_count: 4,
      source_kind: "legacy_lookup",
      schema_version: "1.0",
      capabilities: ["legacy_lookup"],
      supported_modes: [],
      raw_metadata: {},
      palette: [],
      coverage_stats: {
        entry_count: 4,
        plotted_point_count: 4,
        l_range: { min: 0, max: 100 },
        a_range: { min: -40, max: 60 },
        b_range: { min: -50, max: 50 },
        r_range: { min: 0, max: 255 },
        g_range: { min: 0, max: 255 },
        b_rgb_range: { min: 0, max: 255 },
      },
      lab_points: [],
      lab_hull: [],
      rgb_points: [],
      max_color_layers: 5,
      layer_height_mm: 0.08,
      line_width_mm: 0.42,
      base_layers: 10,
      base_channel_idx: 0,
      layer_order: "Top2Bottom",
    });

    await useLutDetailsStore.getState().fetchCatalog();

    const state = useLutDetailsStore.getState();
    expect(state.selectedManufacturer).toBe("");
    expect(state.selectedLutName).toBe("Bambu Lab - PLA - RYBW");
  });

  it("keeps manufacturer empty when selecting a LUT from the all-manufacturers view", async () => {
    useLutDetailsStore.setState({
      catalog: CATALOG,
      selectedManufacturer: "",
      selectedLutName: "",
      query: "",
      detail: null,
      detailLoading: false,
      error: null,
      errorKind: null,
      catalogLoading: false,
    });

    mockFetchLutDetails.mockResolvedValue({
      name: "Aliz - PETG - CMYW",
      path: "/fake/b.json",
      fingerprint: "fp-b",
      manufacturer: "Aliz",
      manufacturer_source: "folder",
      material_type: "PETG",
      material_source: "folder",
      color_mode: "4-Color (CMYW)",
      color_count: 4,
      source_kind: "legacy_lookup",
      schema_version: "1.0",
      capabilities: ["legacy_lookup"],
      supported_modes: [],
      raw_metadata: {},
      palette: [],
      coverage_stats: {
        entry_count: 4,
        plotted_point_count: 4,
        l_range: { min: 0, max: 100 },
        a_range: { min: -40, max: 60 },
        b_range: { min: -50, max: 50 },
        r_range: { min: 0, max: 255 },
        g_range: { min: 0, max: 255 },
        b_rgb_range: { min: 0, max: 255 },
      },
      lab_points: [],
      lab_hull: [],
      rgb_points: [],
      max_color_layers: 5,
      layer_height_mm: 0.08,
      line_width_mm: 0.42,
      base_layers: 10,
      base_channel_idx: 0,
      layer_order: "Top2Bottom",
    });

    useLutDetailsStore.getState().selectLut("Aliz - PETG - CMYW");
    await Promise.resolve();

    const state = useLutDetailsStore.getState();
    expect(state.selectedManufacturer).toBe("");
    expect(state.selectedLutName).toBe("Aliz - PETG - CMYW");
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n env npx vitest --run src/__tests__/lut-details-store.test.ts`
Expected: FAIL because the current store promotes the empty manufacturer filter to the first manufacturer and `selectLut()` backfills `selectedManufacturer` from the chosen LUT.

### Task 2: Decouple manufacturer filtering from LUT auto-selection

**Files:**
- Modify: `frontend/src/stores/lutDetailsStore.ts`
- Verify against: `frontend/src/components/LutDetailsPanel.tsx`

- [ ] **Step 3: Write the minimal implementation**

```ts
function resolveSelection(...) {
  const filtered = filterGroups(catalog, query, selectedManufacturer);
  const manufacturer =
    selectedManufacturer && filtered.manufacturers.includes(selectedManufacturer)
      ? selectedManufacturer
      : "";

  const itemsForSelection = manufacturer
    ? filtered.items.filter((item) => item.manufacturer === manufacturer)
    : filtered.items;

  const lutName =
    selectedLutName && itemsForSelection.some((item) => item.name === selectedLutName)
      ? selectedLutName
      : itemsForSelection[0]?.name ?? "";

  return { manufacturer, lutName, filtered };
}

selectLut: (name: string) => {
  const item = findItemByName(get().catalog, name);
  if (!item) {
    ...
  }

  set((state) => ({
    selectedManufacturer: state.selectedManufacturer,
    selectedLutName: item.name,
    detail: null,
    detailLoading: true,
    error: null,
    errorKind: null,
  }));
  void loadDetail(item.name);
},
```

Keep `filterLutDetailsCatalog()` behavior unchanged: empty manufacturer still means "do not restrict by manufacturer". The only logic shift is that auto-selection now derives the current LUT from the available item list without inventing a manufacturer selection.

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n env npx vitest --run src/__tests__/lut-details-store.test.ts`
Expected: PASS. The new tests should stay green, and the pre-existing query/manufacturer selection tests should continue to pass.

### Task 3: Verify UI placeholder behavior and backend manufacturer-source confidence

**Files:**
- Verify against: `frontend/src/components/LutDetailsPanel.tsx`
- Verify against: `tests/test_lut_details_unit.py`

- [ ] **Step 5: Run focused regression checks**

Run:
- `conda run -n env npx vitest --run src/__tests__/lut-details-panel.test.tsx src/__tests__/lut-details-store.test.ts`
- `conda run -n env python -m pytest tests/test_lut_details_unit.py -v`

Expected:
- frontend tests PASS, confirming the panel still renders correctly with the updated store semantics
- backend LUT details tests PASS, confirming manufacturer resolution still prefers LUT metadata when present

- [ ] **Step 6: Self-review the touched files**

Confirm:
- `frontend/src/stores/lutDetailsStore.ts` preserves explicit manufacturer filtering and only changes empty-filter behavior
- `frontend/src/__tests__/lut-details-store.test.ts` retains the existing in-progress test additions in this worktree
- no unrelated LUT scatter chart files or untracked preset assets were modified
