# Lightweight Browser Preview Authority Design

## Context

Lumina Studio currently has two distinct geometry products:

1. A browser preview that must remain responsive and visually communicate the
   current converter settings.
2. Exact printable geometry that is written into the final 3MF.

PR #586 fixed a real native Vector/SVG timing race, but its later commits also
made generated print-scene GLBs authoritative for relief, coating, outlines,
cloisonne, keychains, fridge magnets, and model-surface overlays. That ownership
rule conflicts with the product decision confirmed on 2026-08-28: the browser
must always use a lightweight preview representation, while exact geometry is a
3MF-only concern.

The existing UI already renders most advanced preview semantics in real time on
top of a lightweight segmented GLB. Model-surface selection and artwork
placement are also already interactive before generation. The fix should
preserve those paths instead of replacing them with a generated print-scene
GLB.

## Product Contract

- The converter's browser model is always a preview-owned, lightweight asset or
  an existing lightweight/procedural representation.
- The Generate action creates the exact 3MF download but never changes the
  browser model to a print-exact GLB.
- Generate may reuse a validated, session-owned preview GLB internally to avoid
  redundant export work, but the generate response does not become the source
  of truth for the viewer.
- Parameter changes continue to update the visible preview in real time when
  the existing Three.js preview layer can represent them.
- An asynchronous preview result is accepted only when it still belongs to the
  active session, source, and preview request revision.
- A missing, expired, or foreign preview never causes an old or print-exact GLB
  to be displayed. The current preview path rebuilds or continues through its
  existing loading state.
- Final 3MF downloads remain TTL-bound artifacts that survive source-session
  closure. Preview GLBs remain session-bound and are removed with the session.

## Chosen Architecture

### 1. Preview and generation have separate ownership

Preview endpoints and preview polling exclusively own the browser model URL.
The single-item generate endpoint retains its response schema for compatibility,
but it must not publish a newly exported print-scene GLB as `preview_3d_url`.
The frontend must ignore any legacy generated model URL for the converter's
single-item viewer and keep `previewGlbUrl` as the authoritative GLB source.

The backend generation pipeline still computes exact meshes wherever the 3MF
writer needs them. It skips optional browser-GLB export after the 3MF is
complete. Native Vector may consume a validated existing segmented preview path
where an internal pipeline contract still expects a preview artifact, without
registering, copying, or transferring it again.

### 2. Preserve real-time lightweight rendering

The current quick-preview renderer remains responsible for live visual changes:

- dimensions and XY scaling;
- backing thickness and single/double-sided display;
- material and replacement colours;
- colour-based relief heights;
- outline and cloisonne proxy geometry;
- keychain and fridge-magnet helpers;
- puzzle cut-line overlays;
- the existing lightweight base presentation while coating is enabled.

These changes must not wait for Generate and must not rebuild a print mesh.
Where the existing preview request already refreshes the segmented asset, the
300 ms auto-preview debounce and stale-request rejection remain intact.

Heightmap upload already derives a per-colour average `color_height_map` that
the lightweight viewer applies in real time. Keep that bounded approximation in
the browser; per-pixel heightmap geometry remains exact only inside the 3MF.
This PR does not add a second heightmap mesh builder.

### 3. Keep model-surface preview unchanged

Model-surface upload, face selection, rotation, placement, and artwork updates
continue through the existing `ModelSurfaceSelector3D` interaction. Generate
must not hide that selector or replace it with a final overlay-scene GLB.

This PR does not introduce model decimation for uploaded STL/OBJ files. If a
future measured case shows that a user's source model itself is too expensive to
display, that is a separate input-model performance problem and should be
handled independently.

### 4. Revision and lifecycle safeguards

The preview flow keeps two logically separate kinds of state:

- **Asset identity:** session, source file/version, modeling mode, segmentation
  inputs, and any parameter that requires a different server-built lightweight
  asset.
- **Live display state:** colours, materials, transforms, dimensions, relief
  heights, outlines, attachments, and other values applied immediately by the
  viewer.

Async responses are guarded by the asset identity/request sequence. Live state
is always read from the latest store state, so a valid lightweight base asset can
continue to render current real-time settings without accepting stale network
responses.

Preview registration must remain session-owned. If a session closes while an
async preview is running, the completed artifact is discarded and cleaned up.
The final 3MF remains registered under its independent TTL lifecycle.

## Alternatives Rejected

### Rebuild a lightweight GLB for every setting change

This centralizes geometry on the backend but loses the existing real-time
interaction, creates unnecessary CPU work, and adds visible latency for colour,
material, dimension, and helper changes that the viewer already handles.

### Rebuild all preview geometry in the browser

This could feel immediate, but it duplicates increasingly complex geometry
rules from the Python pipeline and increases the chance that the preview's
business semantics diverge from the 3MF. The browser should compose bounded
preview representations, not become a second print-geometry engine.

## Error Handling

- Missing/expired preview: keep or rebuild the preview-owned representation;
  never use a generated print GLB as fallback.
- Session mismatch: reject the artifact and schedule/currently await the active
  session's preview.
- Stale async response: discard it without mutating `previewGlbUrl`.
- Optional lightweight-surface failure: retain the last valid lightweight
  preview/loading presentation and surface a normal preview error; completed
  3MF generation remains valid.
- Session close during preview work: remove partial/completed preview artifacts
  and do not re-register them.
- Session close after generation: preview URLs become unavailable while the TTL
  3MF download remains available.

## Verification and Acceptance Criteria

Automated coverage must prove:

1. Generate never makes a print-exact GLB authoritative in the frontend,
   including when Generate completes before the segmented preview.
2. The asynchronous lightweight preview becomes visible when ready and stale
   responses cannot replace a newer session/revision.
3. Relief, outline, coating, cloisonne, keychain, fridge-magnet, puzzle, colour,
   material, replacement, dimension, and structure changes keep their existing
   real-time preview behavior.
4. Model-surface interaction remains visible and live before and after Generate;
   no final overlay-scene GLB is exported for browser ownership.
5. Invalid, expired, or cross-session preview paths are not reused.
6. Native Vector generation can reuse a current registered segmented asset
   without duplicate registration or export, while the exact 3MF remains
   unchanged.
7. Ordinary raster and heightmap paths do not fall back to a print-exact browser
   GLB. Heightmap continues to use its existing per-colour lightweight height
   approximation in the viewer.
8. Preview cleanup and final-download TTL behavior remain correct when the
   source session is closed or switched during work.

The focused backend pytest suite, frontend Vitest suite through
`python scripts/run_vitest.py`, smoke suite, frontend build, and fast log-quality
gate must pass. R4C1 must be replayed in both timing orders. Browser network
evidence must show that only the lightweight segmented GLB is downloaded, and
the generated 3MF must remain structurally equivalent to the baseline.

## Non-Goals

- Changing 3MF construction, print geometry, topology, shell separation,
  material identity, slicer coverage, or print quality.
- Fixing PR #585 puzzle topology or mixing any mesh/3MF work from that PR.
- Optimizing arbitrary uploaded model-surface STL/OBJ files without a separate
  measured performance case.
- Automatically merging PR #586.
