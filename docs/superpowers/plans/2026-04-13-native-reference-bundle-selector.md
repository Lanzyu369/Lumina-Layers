# Native Reference Bundle Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reference-style source picker for `ReferenceDB` / `ReferencePack` / `ReferenceModel` so Lumina supports `旧版 -> 单 LUT` and `新版 -> 品牌 -> 多选 DB bundle` without regressing legacy/custom LUT behavior.

**Architecture:** Keep the existing `lut_name` contract for legacy/custom flows and add a parallel `native_bundle` request path for native reference assets. The backend owns bundle catalog/discovery and request normalization; the frontend consumes a catalog and renders version/brand/DB controls while preserving the current single-LUT path under `旧版`.

**Tech Stack:** FastAPI, Pydantic, core pipeline/LUT runtime code, React 19, TypeScript, Zustand, Vitest, pytest.

---

### Task 1: Backend native bundle catalog and request normalization

**Files:**
- Modify: `E:/Lumina-Layers/LL-1296/Lumina-Layers/api/schemas/converter.py`
- Modify: `E:/Lumina-Layers/LL-1296/Lumina-Layers/api/schemas/lut.py`
- Modify: `E:/Lumina-Layers/LL-1296/Lumina-Layers/api/routers/lut.py`
- Modify: `E:/Lumina-Layers/LL-1296/Lumina-Layers/api/routers/converter/preview.py`
- Modify: `E:/Lumina-Layers/LL-1296/Lumina-Layers/api/routers/converter/generate.py`
- Modify: `E:/Lumina-Layers/LL-1296/Lumina-Layers/utils/lut_manager.py`
- Modify: `E:/Lumina-Layers/LL-1296/Lumina-Layers/core/pipeline/processing_ops/lut_loader.py`
- Test: `E:/Lumina-Layers/LL-1296/Lumina-Layers/tests/test_lut_api_unit.py`
- Test: `E:/Lumina-Layers/LL-1296/Lumina-Layers/tests/test_native_reference_compatibility_unit.py`
- Test: `E:/Lumina-Layers/LL-1296/Lumina-Layers/tests/test_converter_preview_unit.py`

- [ ] **Step 1: Write failing backend tests for native source catalog and request validation**

Add focused tests that prove:

- the LUT API exposes a native brand catalog grouped by `material_type + vendor`
- preview/generate accept `legacy_single` unchanged
- preview/generate accept `native_bundle` only when `material_type`, `vendor`, and at least one DB name are present
- mixed-brand DB names are rejected

- [ ] **Step 2: Run the focused backend tests to confirm the new expectations fail first**

Run:

```powershell
python -m pytest tests/test_lut_api_unit.py tests/test_converter_preview_unit.py tests/test_native_reference_compatibility_unit.py -q
```

Expected:

- catalog assertions fail because the new endpoint/shape does not exist yet
- `native_bundle` schema/request validation is missing

- [ ] **Step 3: Implement catalog response models and LUTManager native brand discovery**

Add backend types and helper methods for:

- listing legacy groups
- grouping native `ReferenceDB` entries by `(material_type, vendor)`
- attaching same-scope `ReferencePack` and `ReferenceModel` names
- returning default DB selections and supported modes

Keep `lut_name` lookup behavior untouched for legacy/custom sources.

- [ ] **Step 4: Implement preview/generate schema and request normalization**

Extend converter schemas/routes so both preview and generate can normalize either:

```text
legacy_single -> lut_name
native_bundle -> material_type + vendor + db_names[]
```

For native bundle requests, resolve the selected DB subset through `LUTManager`, discover same-scope pack/model assets, and pass a normalized native selection into the LUT loading path.

- [ ] **Step 5: Update LUT loading/runtime code to consume normalized native bundle selection**

Teach the LUT loader to assemble exact lookup and runtime metadata from the selected DB subset while preserving full bundle slot metadata for preview/export.

- [ ] **Step 6: Re-run focused backend tests until they pass**

Run:

```powershell
python -m pytest tests/test_lut_api_unit.py tests/test_converter_preview_unit.py tests/test_native_reference_compatibility_unit.py -q
```

Expected:

- all targeted tests pass

### Task 2: Frontend version/brand/native-DB multi-select flow

**Files:**
- Modify: `E:/Lumina-Layers/LL-1296/Lumina-Layers/frontend/src/api/types.ts`
- Modify: `E:/Lumina-Layers/LL-1296/Lumina-Layers/frontend/src/api/converter.ts`
- Modify: `E:/Lumina-Layers/LL-1296/Lumina-Layers/frontend/src/stores/converter/store.ts`
- Modify: `E:/Lumina-Layers/LL-1296/Lumina-Layers/frontend/src/components/sections/BasicSettings.tsx`
- Modify: `E:/Lumina-Layers/LL-1296/Lumina-Layers/frontend/src/i18n/translations.ts`
- Test: `E:/Lumina-Layers/LL-1296/Lumina-Layers/frontend/src/__tests__/BasicSettings.test.tsx`
- Test: `E:/Lumina-Layers/LL-1296/Lumina-Layers/frontend/src/stores/__tests__/converterStore.test.ts`

- [ ] **Step 1: Write failing frontend tests for old/new source selection behavior**

Cover:

- `旧版` renders the current single-LUT selector
- `新版` renders a native brand selector and DB multi-select
- switching brand resets selected DBs to that brand defaults
- legacy `lut_name` persistence still works under `旧版`

- [ ] **Step 2: Run the targeted frontend tests to confirm the new UX expectations fail**

Run:

```powershell
cd frontend
npx vitest --run src/__tests__/BasicSettings.test.tsx src/stores/__tests__/converterStore.test.ts
```

Expected:

- missing native catalog/store fields and UI controls cause failures

- [ ] **Step 3: Extend API types and converter store for native bundle state**

Add:

- `source_selection_mode`
- `selected_native_brand_key`
- `selected_native_db_names`
- native source catalog state

Persist the new native selection state separately from `lut_name`.

- [ ] **Step 4: Update request builders to send either legacy or native bundle payloads**

Preview/generate client code should send:

```text
legacy_single -> lut_name
native_bundle -> material_type + vendor + db_names[]
```

without breaking the current legacy request path.

- [ ] **Step 5: Replace the BasicSettings source picker UI**

Implement:

- `版本` selector
- `品牌` selector
- native DB multi-select list for `新版`
- source summary panel for the assembled native brand

All user-facing strings must come from translations.

- [ ] **Step 6: Re-run focused frontend tests until they pass**

Run:

```powershell
cd frontend
npx vitest --run src/__tests__/BasicSettings.test.tsx src/stores/__tests__/converterStore.test.ts
```

Expected:

- targeted store/UI tests pass

### Task 3: End-to-end regression and native bundle verification

**Files:**
- Modify as needed from Tasks 1-2 only
- Test: `E:/Lumina-Layers/LL-1296/Lumina-Layers/tests/test_reference_layer_images_unit.py`
- Test: `E:/Lumina-Layers/LL-1296/Lumina-Layers/tests/test_s09_export_3mf_unit.py`
- Test: `E:/Lumina-Layers/LL-1296/Lumina-Layers/frontend/src/__tests__/lut-manager-panel.test.tsx`

- [ ] **Step 1: Add or update regression tests for assembled native bundle behavior**

Prove that:

- a native bundle request preserves layer preview compatibility
- export metadata still reflects the bundle scope
- legacy/custom LUT behavior remains unchanged

- [ ] **Step 2: Run the combined focused backend/frontend regression set**

Run:

```powershell
python -m pytest tests/test_lut_api_unit.py tests/test_converter_preview_unit.py tests/test_native_reference_compatibility_unit.py tests/test_reference_layer_images_unit.py tests/test_s09_export_3mf_unit.py -q
cd frontend
npx vitest --run src/__tests__/BasicSettings.test.tsx src/stores/__tests__/converterStore.test.ts src/__tests__/lut-manager-panel.test.tsx
```

Expected:

- all targeted tests pass

- [ ] **Step 3: Perform a manual smoke using one native brand**

Validate one real bundle, for example `PLA / BambuLab`:

- `新版` brand selector loads the BambuLab brand
- DB list defaults to all selected
- preview succeeds
- layer preview succeeds
- generated 3MF keeps native bundle filament metadata

- [ ] **Step 4: Record any deviations and fix them before closing**

Only close the task once:

- native bundle selection is functional
- legacy/custom single-select is unchanged
- no new deterministic blocker remains in the focused flow
