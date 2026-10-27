# Three.js 3D Preview Performance Audit

Date: 2026-04-09
Scope: `frontend/src` Three.js / react-three-fiber 3D preview path

## Summary

This audit focused on WebGL resource lifecycle, model cache behavior, event/timer cleanup, and hot paths that can cause memory growth or frame drops in the 3D preview.

Primary conclusion: the current implementation has multiple high-confidence resource lifecycle issues and several medium-confidence CPU/GPU hot paths. The largest risks come from keeping the 3D scene mounted while hidden, using persistent WebGL drawing-buffer preservation, and rendering cloned Three.js objects through `<primitive>` without a consistent explicit disposal strategy.

## High-Risk Findings

### 1. `Scene3D` remained mounted when the converter tab was hidden

Files:
- `frontend/src/App.tsx`

Evidence:
- The converter tab wrapped `Scene3D` in a container toggled by the `hidden` class instead of conditional rendering.
- This can keep the R3F `Canvas`, render loop, controls, `useFrame` callbacks, and WebGL context alive offscreen.

Impact:
- Wasted CPU/GPU while the user is on another tab
- Longer-lived WebGL resources
- Hard-to-diagnose background memory growth

Status:
- Planned for immediate fix in this remediation batch

### 2. Cloned GLTF scenes/materials/geometries rendered through `<primitive>` lacked a unified disposal strategy

Files:
- `frontend/src/components/ModelViewer.tsx`
- `frontend/src/components/InteractiveModelViewer.tsx`
- `frontend/src/components/BedPlatform.tsx`

Evidence:
- `useGLTF(url)` loads cached assets.
- Components clone scenes and create additional materials/geometries/textures.
- Render path uses `<primitive object={...} />`, where disposal is not reliably handled the same way as declarative mesh/material/geometry nodes.
- No project-wide disposal helper existed.

Impact:
- GPU memory retention after model switches or component unmounts
- Material and geometry leaks, especially during repeated preview/generate cycles

Status:
- Planned for immediate fix in this remediation batch

### 3. `Canvas` used persistent `preserveDrawingBuffer: true`

Files:
- `frontend/src/components/Scene3D.tsx`

Evidence:
- `Canvas` is created with `gl={{ preserveDrawingBuffer: true }}`.
- Screenshot flow reads `gl.domElement.toDataURL(...)` directly.

Impact:
- Increased GPU memory pressure
- Slower rendering on some devices/drivers

Status:
- Confirmed issue; screenshot path should be redesigned before disabling globally
- Deferred from the first code patch to avoid breaking screenshot behavior

## Medium-Risk Findings

### 4. Repeated CPU-heavy geometry generation for outline and cloisonne preview

Files:
- `frontend/src/components/OutlineFrame3D.tsx`
- `frontend/src/components/CloisonneWire3D.tsx`

Evidence:
- Frontend performs rasterization, dilation, masking, rectangle merge, and geometry extrusion in React render memo paths.

Impact:
- Main-thread stalls on complex models or frequent parameter changes

Recommendation:
- Reduce recomputation inputs
- Consider workerization or moving selected preprocessing upstream if this becomes a user-visible bottleneck

### 5. Hover hit-testing remains expensive on complex color mesh sets

Files:
- `frontend/src/components/InteractiveModelViewer.tsx`

Evidence:
- Manual raycasting runs against `colorMeshes` and hover updates are only partially rate-limited.

Impact:
- Pointer-move induced frame drops on complex scenes

Recommendation:
- Continue deduping/throttling
- Consider simplified hit proxies or spatial grouping if scene complexity increases

## Memory Amplification / Cache Duplication

### 6. Layer preview images are cached separately in 2D and 3D views

Files:
- `frontend/src/components/Scene3D.tsx`
- `frontend/src/components/sections/ActionBar.tsx`

Evidence:
- Both components load layer images, decode them into `Image`, draw onto offscreen `canvas`, and retain 2D contexts for sampling.

Impact:
- Duplicate decoded image memory
- Duplicate offscreen canvas memory
- Higher peak memory when layer counts or image resolution are large

Recommendation:
- Introduce a shared layer-buffer cache/service, or centralize ownership in state/store

## Remediation Plan

### Batch 1

- Unmount `Scene3D` when converter tab is inactive
- Add a shared explicit Three.js disposal utility
- Dispose cloned scenes/materials/geometries/textures in `ModelViewer`
- Dispose created bed mesh resources in `BedPlatform`
- Dispose interactive preview clones/mirror meshes/backing fallback resources in `InteractiveModelViewer`

### Batch 2

- Redesign screenshot flow so `preserveDrawingBuffer` can be disabled by default
- Consolidate duplicated 2D/3D layer canvas caches

### Batch 3

- Profile and optimize outline/cloisonne geometry generation
- Review hover raycast scalability on large scenes

## Verification Suggestions

- Repeatedly switch between converter and non-converter tabs and verify GPU/CPU drops when hidden
- Repeatedly generate/replace preview GLBs and watch `renderer.info.memory`
- Use Chrome Performance + Memory panels to confirm that geometry/material/texture counts stabilize after unmount
- Validate screenshot behavior before changing drawing-buffer preservation
