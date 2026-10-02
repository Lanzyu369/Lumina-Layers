# Model-surface consistency implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> This task executed the implementation inline with `test-driven-development` and `verification-before-completion`, and used `requesting-code-review` for independent read-only reviews.

**Goal:** Make the selected surface, 2D artwork, 3D inspection, and generated pocket agree, including bottom faces and restored model poses.

**Architecture:** Keep the existing local U/V frame and actual printable footprint. The converter store owns model rotation. A new selection gets one face-up correction and one front-side inspection with local V as screen up; manual rotation and navigation do not trigger this transition. Keep the pocket as a native Manifold solid through subtraction and export the final mesh once.

**Tech stack:** Python, NumPy, Shapely, Trimesh, Manifold 3.4+, React, TypeScript, Three.js, Zustand, pytest, Vitest.

- [x] Reproduce the reported failures before implementation changes.
- [x] Keep pocket geometry inside the native engine.
- [x] Give selection and model pose one owner; test restoration and camera release.
- [x] Verify the real source files and fix the material handoff found in the exported result.
- [x] Document coordinate owners, review the final diff, and run focused regression gates.

## 1. Reproduce the failures before editing implementation

- Add an anonymous rectangle with five tiny triangular holes to `tests/test_model_surface_boolean_unit.py`. Call `cut_surface_pocket` on a closed box. Assert a closed positive-volume result, unchanged extents, and removed volume equal to the polygon area times the existing pocket depth plus overlap allowance. This captures the reported failure without committing user artwork.
- Replace the camera-up expectation with local-coordinate behavior: apply face-up rotation to top, bottom, side and tilted frames, then assert +U projects right and +V projects up at multiple model yaw angles.
- Extend selector tests: new bottom/side selection focuses from the front after automatic rotation; starting from a back view is supported; restoring a controlled nonzero pose does not rotate it again or notify a reset; navigation and manual rotation remain independent.
- Extend `Scene3D.test.tsx` to assert store rotation and selection identity reach the selector.
- Run targeted tests and record expected failures.

## 2. Keep pocket geometry inside the native engine

- In `core/model_surface/assembly.py`, replace `_build_polygon_prism_mesh` with a native-solid helper used by `_cut_surface_polygon_pocket`.
- Build `CrossSection(contours, FillRule.EvenOdd).extrude(height_mm)` without exporting its intermediate mesh.
- Keep existing input-model preparation and the existing 0.002–0.02 mm overlap allowance. Convert the prepared base with `Manifold(Mesh64(vertices, faces))`; transform the native cutter using the surface frame's 3x4 matrix; subtract; export once with `to_mesh64()`.
- Preserve native status/nonempty checks, domain error mapping, final metadata, inner cavity winding and physical depth. Remove redundant intermediate volume checks and the unused Trimesh-result coercion helper.
- Update the nearly duplicate boundary regression to exercise the public cut result rather than a private intermediate representation.
- Run boolean and assembly tests against Manifold 3.4.0 and the available newer engine.

## 3. Give selection and model pose one owner

- Add optional `modelRotation` and `selectionId` props to `ModelSurfaceSelector3D`; `Scene3D` supplies the converter store values. Keep the existing uncontrolled fallback for isolated consumers.
- Initialize an existing controlled selection as restored. File loading resets only the uncontrolled fallback. Changes made by the user or by a new selection write through the existing rotation callback; restoration does not write back.
- Identify face-up/focus transitions by selection identity. A new selection gets face-up correction once, then inspection once after the pose is applied. Removing a selection clears this event state. Rebuilding an existing selection preserves the stored pose.
- In `rotationMath.ts`, project the transformed V axis onto the camera plane and normalize it without world-Y sign flips.
- Remove the skip after automatic face-up. Focus uses the existing inspection camera from the surface front. Keep ordinary view controls and manual rotation behavior.
- Restore shared camera up/FOV when leaving the selector, so ordinary and batch preview do not inherit its roll.
- Run selector, Scene3D, converter model-surface and artwork-placement regression tests.

## 4. Make the contract discoverable and verify the real report

- Add `docs/context/model-surface/CONTEXT.md` and a root context-map entry with coordinate owners, lifecycle transitions and the regression matrix. Explain why PR #605's artwork-placement correction differs from this camera/native-solid repair.
- Update the generic pocket failure text in API/frontend to avoid attributing an internal calculation failure to a broken user model. Keep specific invalid-model and insufficient-thickness messages.
- Add today's bilingual announcement items describing orientation, pose restoration and complex-artwork generation fixes.
- Re-run the supplied SVG/STL with the reported four materials and dynamic 5–8 layer settings. Export/reopen the 3MF, verify closed base, material identity, preserved holes, and that the pocket uses the actual printed footprint. Retain private evidence only under `.scratch`.
- Run all model-surface backend tests, relevant frontend tests, announcement tests and TypeScript checking. Scan edited UTF-8 files for corruption and run `git diff --check`.
- Obtain independent review of the final diff, address concrete findings, and stop any task-owned processes before reporting results. Record actual validation and its limits in the domain context.

## 5. Material handoff found during real-file verification

- [x] Add a failing assembly/export regression with the selected material order Red, Yellow, White, Blue and backing indices 0, 3 and default 2. Use only a red artwork mesh so unused selected palette entries must also survive export.
- [x] Before clearing the converter context, use `resolve_material_preview` to preserve the exact base material and source palette. Set `loaded.mesh.metadata["bambu_material_name"]` and pass its RGB to assembly.
- [x] Keep geometry names separate from materials through `OverlaySceneResult.project_slot_names`; the production worker passes that palette to the existing writer and disables native-template slot preservation for material archives, matching S09.
- [x] Export and inspect real-file metadata: five closed geometry objects, four PETG slots, base and white artwork both using extruder 4. Validate the existing registry-template trimming regression.

Final verification details and limits: `docs/context/model-surface/TEST_REPORT.md`.
