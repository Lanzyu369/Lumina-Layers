# Build Plate Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a slicer-native build-plate selector whose validated choice is persisted and written into every generated 3MF.

**Architecture:** Extend the versioned machine registry with build-plate definitions and per-machine support, expose resolved choices through the existing system API, and persist selections by slicer plus machine. Resolve the selected ID at the 3MF writer boundary and update project, plate XML, and slicer-specific sidecars from one validated adapter object.

**Tech Stack:** Python 3, FastAPI/Pydantic, React 19, TypeScript, Zustand, Tailwind, pytest, Vitest, Bambu-family 3MF ZIP metadata.

---

### Task 1: Registry schema and source importer

**Files:**
- Modify: `core/machine_registry.py`
- Modify: `tools/machine_adapter/import_profiles.py`
- Modify: `machine_registry/registry.json`
- Create: `machine_registry/BUILD_PLATE_SOURCES.md`
- Test: `tests/test_machine_registry_unit.py`
- Test: `tests/test_machine_adapter_import_cli_unit.py`
- Test: `tests/test_machine_registry_bundle_unit.py`

- [ ] Add failing tests for slicer build-plate definitions, per-machine support/default IDs, duplicate references, missing assets, and pinned source metadata.
- [ ] Run the focused registry/import tests and confirm the new assertions fail.
- [ ] Add immutable build-plate dataclasses and lookup indexes to the registry loader.
- [ ] Declare the version-scoped plate vocabulary, labels, and project/plate/sidecar metadata in `build_plates.py`, verify it against native projects/profiles, and derive only per-machine support/default IDs plus per-nozzle capability intersections from pinned profiles; keep the exact Kobra S1 Engineering slice exclusion scoped by slicer version and machine.
- [ ] Generate the six shared Lumina-owned neutral plate images deterministically with `tools/machine_adapter/build_plates.py`; record Lumina source versions and revisions without copying or redistributing vendor plate artwork.
- [ ] Re-run the focused registry/import tests to PASS.

### Task 2: System API and persisted settings

**Files:**
- Modify: `api/schemas/system.py`
- Modify: `api/routers/system.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/stores/settingsStore.ts`
- Test: `tests/test_settings_api_unit.py`
- Test: `frontend/src/__tests__/settings-store-hydration.test.ts`
- Test: `frontend/src/__tests__/settings-store.property.test.ts`

- [ ] Add failing API tests for resolved plate lists/defaults and settings round trips.
- [ ] Add failing frontend tests for per-slicer-machine memory and stale-selection fallback.
- [ ] Expose build plates on device profiles and persist the selection map plus current ID.
- [ ] Implement deterministic selection resolution without changing legacy behavior when data is absent.
- [ ] Run focused backend and frontend tests to PASS.

### Task 3: Horizontal settings UI

**Files:**
- Create: `frontend/src/components/settings/BuildPlateSelector.tsx`
- Modify: `frontend/src/components/SettingsPanel.tsx`
- Modify: `frontend/src/i18n/translations.ts`
- Test: `frontend/src/components/__tests__/SettingsPanel.machineAdapter.test.tsx`
- Test: `frontend/src/components/__tests__/SettingsPanel.layout.test.tsx`

- [ ] Add failing tests for wide horizontal layout, overflow scrolling, selection, keyboard behavior, and exact image containment.
- [ ] Implement the focused selector component using theme tokens and translated UI labels.
- [ ] Wire it below the device card with loading, empty, and fallback notice states.
- [ ] Run focused component tests to PASS.

### Task 4: Validated 3MF metadata writer

**Files:**
- Modify: `utils/bambu_3mf_writer.py`
- Modify: `utils/merged_bambu_3mf_writer.py`
- Modify: `tests/helpers_threemf_manifest.py`
- Test: `tests/test_bambu_3mf_writer_unit.py`
- Test: `tests/test_3mf_template_matrix_unit.py`
- Test: `tests/test_puzzle_3mf_unit.py`

- [ ] Add failing tests selecting a non-default plate and asserting project, model plate, and sidecar metadata.
- [ ] Add a registry resolver that validates the ID against the selected machine and returns project/plate native values.
- [ ] Apply the resolved values to `curr_bed_type`, plate `bed_type`, and supported sidecars.
- [ ] Preserve template defaults when the registry has no plate data.
- [ ] Run focused writer and matrix tests to PASS.

### Task 5: Propagate through every export workflow

**Files:**
- Modify: relevant request schemas under `api/schemas/`
- Modify: relevant routers and workers under `api/routers/` and `api/workers/`
- Modify: common export calls under `core/`
- Modify: frontend request construction under `frontend/src/stores/`, `frontend/src/recipe/`, and Workshop handoff code
- Test: focused converter, vector, puzzle, calibration, single-stage, five-color, recipe, batch, and Workshop tests

- [ ] Add failing payload tests for each 3MF-producing entry point.
- [ ] Thread optional `build_plate_id` beside `device_profile_id` through each request and worker boundary.
- [ ] Pass the value to the common writer without duplicating metadata logic.
- [ ] Include the value in bug-report reproduction context and optional share-card recipe semantics while keeping it out of geometry semantics.
- [ ] Run all focused workflow tests to PASS.

### Task 6: Product warnings, docs, and automated verification

**Files:**
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `frontend/src/data/announcements.ts`
- Modify: bug-report context files and tests
- Modify: build-plate source documentation

- [ ] Add tests for stale selection and material compatibility warning copy.
- [ ] Implement non-blocking PLA/PETG compatibility warnings and one-time fallback notice.
- [ ] Add bilingual release announcement and reproducibility context.
- [ ] Run UTF-8/mojibake scans on every touched non-ASCII file.
- [ ] Run backend focused tests, frontend focused tests, build, lint, and smoke gates.

### Task 7: Native slicer acceptance

**Files:**
- Create: `progress/build-plate-slicer-acceptance.md`
- Create only ephemeral generated 3MF fixtures outside tracked source directories.

- [ ] Generate non-default-plate PLA and PETG 3MF fixtures for each installed slicer.
- [ ] Open fixtures in Bambu Studio, OrcaSlicer, Snapmaker Orca, and ElegooSlicer when runnable.
- [ ] Confirm native plate selection, device/nozzle/material identity, absence of corruption warnings, and successful slicing.
- [ ] Record versions, selected native values, observed results, and any unavailable slicer limitation.
- [ ] Stop all test/dev processes and verify the worktree diff before completion.
