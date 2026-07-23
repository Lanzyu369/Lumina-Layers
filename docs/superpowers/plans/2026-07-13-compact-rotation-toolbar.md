# Compact Rotation Toolbar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the tall model and artwork rotation popovers with one shared compact two-row toolbar that can snap to the true top edge of the 3D preview.

**Architecture:** Keep the existing shared `RotationPanel` behavior and drag persistence. Change only its presentation to a responsive horizontal grid, and make rotation-panel positioning use the same 12px safe inset as the primary surface toolbar.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Vitest, Testing Library.

---

### Task 1: Lock the compact layout contract

**Files:**
- Modify: `frontend/src/__tests__/ModelSurfaceSelector3D.test.tsx`

- [x] Add a regression test asserting the shared panel exposes a compact horizontal layout, consistent numeric cells, and a single inline action row for both model and artwork modes.
- [x] Run the focused test with `.venv/bin/python scripts/run_vitest.py run src/__tests__/ModelSurfaceSelector3D.test.tsx` and verify it fails before production changes.

### Task 2: Implement the shared two-row toolbar

**Files:**
- Modify: `frontend/src/components/ModelSurfaceSelector3D.tsx`

- [x] Replace the vertical label/input grid with a horizontal header-and-values strip.
- [x] Keep model X/Y/Z values and artwork Z-only values driven by the existing `axisDefs` data.
- [x] Place quick rotation and reset/done actions in one compact second row with uniform 28px controls.
- [x] Preserve every existing accessible name, tooltip, callback, and state transition.

### Task 3: Restore true top-edge snapping

**Files:**
- Modify: `frontend/src/components/modelSurface/overlayLayout.tsx`
- Test: `frontend/src/__tests__/ModelSurfaceSelector3D.test.tsx`

- [x] Remove the rotation-only 76px top reservation so top anchors use the standard 12px scene inset.
- [x] Update the snap regression expectation from `top: 76px` to `top: 12px`.
- [x] Verify drag clamping still keeps the full measured toolbar inside all six snap anchors.

### Task 4: Verify behavior and visuals

**Files:**
- Test: `frontend/src/__tests__/ModelSurfaceSelector3D.test.tsx`

- [x] Run the shared 3D frontend regression suite and require zero failures.
- [x] Run targeted ESLint and the Vite production build.
- [x] In Chrome, verify model and artwork rotation panels at top-left, top-center, and top-right; check numeric alignment, quick actions, drag snapping, completion, and camera unlock.
