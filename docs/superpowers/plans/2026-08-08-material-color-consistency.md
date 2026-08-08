# Material Color Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make converter previews, custom material recipes, achievable-colour suggestions, and Material Library recipe prediction return the same rounded sRGB colour for an identical material stack.

**Architecture:** Introduce one core forward-prediction boundary that owns canonical white/black substrates and sRGB rounding, then replace the three duplicated converter calculations and the Material Library calculation with that boundary. Resolve the frontend suggestion depth once through the existing printable-layer helper and use the same value for the request and its LRU key.

**Tech Stack:** Python 3.12, NumPy, FastAPI, pytest, React 19, TypeScript, Zustand, Vitest, pnpm, Chrome/Electron.

---

## File Map

- Create `tests/test_material_color_prediction_contract_unit.py`: focused unit contract for canonical substrate selection, rounding, and invalid input.
- Modify `core/material_color_solver.py`: add the shared public `predict_material_recipe_srgb` boundary.
- Modify `api/routers/converter/replace.py`: adopt the boundary for material-archive prediction, recipe application, and padded-pixel recalculation.
- Modify `api/routers/single_stage.py`: adopt the boundary for Material Library recipe prediction and remove the endpoint-local substrate resolver.
- Modify `tests/test_converter_recipe_override_unit.py`: prove converter prediction, application/cache mutation, padding, and dynamic recipe order use the shared contract.
- Modify `tests/test_material_recipe_preview_unit.py`: prove Material Library ignores archive-specific `C0_white` as a physical substrate.
- Modify `frontend/src/stores/converter/store.ts`: use effective printable depth for suggestion requests and cache keys.
- Modify `frontend/src/__tests__/converter-store-material-suggest.test.ts`: prove dynamic and fixed depth behavior and LRU separation.
- Modify `frontend/src/data/announcements.ts`: prepend the required bilingual 2026-08-08 user-facing announcement.
- Modify `docs/superpowers/specs/2026-08-08-material-color-consistency-design.md`: record that the written design is approved.

### Task 1: Establish the isolated baseline

**Files:**
- Verify only; no tracked files change.

- [ ] **Step 1: Confirm linked-worktree isolation and branch**

Run:

```bash
git rev-parse --git-dir
git rev-parse --git-common-dir
git rev-parse --show-superproject-working-tree
git branch --show-current
git status --short
```

Expected: Git dir differs from the common dir, no superproject is printed, the branch is `MOVIBALE/fix/material-color-consistency`, and the worktree is clean.

- [ ] **Step 2: Reuse the matching Python 3.12 environment and install the exact frontend lockfile**

Run:

```bash
ln -s /Users/min/.codex/worktrees/5fe8/Lumina-studio/.venv .venv
pnpm --dir frontend install --frozen-lockfile
pnpm --dir electron install --frozen-lockfile
```

Expected: `.venv/bin/python --version` reports Python 3.12 and pnpm completes without changing either lockfile.

- [ ] **Step 3: Run the pre-change focused baseline**

Run:

```bash
.venv/bin/python -m pytest tests/test_material_recipe_preview_unit.py tests/test_converter_recipe_override_unit.py -v
.venv/bin/python scripts/run_vitest.py run src/__tests__/converter-store-material-suggest.test.ts src/__tests__/material-color-picker.test.tsx
```

Expected: all existing tests pass before regression tests are added.

- [ ] **Step 4: Capture production-equivalent base evidence before code edits**

The current branch differs from base `817a50b16c82804e6bf40106fef5165435cc2a79` only by approved documentation. Start the existing application, use the real `赛纳/赛纳PETG白色 by MingDee` archive at 0.08 mm, and save the observed values plus browser network/console notes under `.scratch/lum-20260805-001/base/`:

```text
Converter/canonical eight-layer white: #FFFFF9
Custom recipe prediction:             #FEFEF9
Material Library prediction:          #FFFFF8
Dynamic 5–8 suggestion request depth: 5
```

Stop only the application processes started for this base capture before Task 2.

### Task 2: Add the canonical core prediction contract

**Files:**
- Create: `tests/test_material_color_prediction_contract_unit.py`
- Modify: `core/material_color_solver.py` after `forward_model`

- [ ] **Step 1: Write the failing core contract tests**

Create `tests/test_material_color_prediction_contract_unit.py` with:

```python
"""Contract tests for user-facing material recipe colour prediction."""

from __future__ import annotations

import numpy as np
import pytest

from core.material_color_solver import (
    MaterialParams,
    forward_model,
    linear_to_srgb_float,
    linear_to_srgb_uint8,
    predict_material_recipe_srgb,
)


def _probe_material() -> MaterialParams:
    return MaterialParams(
        name="Probe",
        directory_name="probe",
        E=np.asarray([0.2, 0.4, 0.6], dtype=np.float64),
        k=np.asarray([1.3, 1.1, 0.9], dtype=np.float64),
        C0_white=np.asarray([0.3, 0.4, 0.5], dtype=np.float64),
        estimated_rgb=np.asarray([80, 120, 160], dtype=np.uint8),
    )


def test_white_substrate_uses_round_to_nearest_srgb() -> None:
    material = _probe_material()
    recipe = np.zeros(5, dtype=np.int32)
    predicted_linear = forward_model(
        recipe,
        [material],
        0.08,
        np.ones(3, dtype=np.float64),
    )
    rounded = linear_to_srgb_uint8(predicted_linear)
    truncated = (linear_to_srgb_float(predicted_linear) * 255.0).astype(np.uint8)

    assert rounded.tolist() == [214, 229, 241]
    assert truncated.tolist() == [214, 229, 240]
    np.testing.assert_array_equal(
        predict_material_recipe_srgb(recipe, [material], 0.08, "white"),
        rounded,
    )


def test_black_substrate_is_pure_zero_not_near_black() -> None:
    material = _probe_material()
    recipe = np.zeros(5, dtype=np.int32)
    pure_black = linear_to_srgb_uint8(
        forward_model(
            recipe,
            [material],
            0.08,
            np.zeros(3, dtype=np.float64),
        )
    )
    near_black = linear_to_srgb_uint8(
        forward_model(
            recipe,
            [material],
            0.08,
            np.full(3, 0.01, dtype=np.float64),
        )
    )

    assert pure_black.tolist() == [80, 105, 118]
    assert near_black.tolist() == [83, 108, 120]
    np.testing.assert_array_equal(
        predict_material_recipe_srgb(recipe, [material], 0.08, "black"),
        pure_black,
    )


def test_invalid_substrate_is_rejected() -> None:
    with pytest.raises(ValueError, match="substrate"):
        predict_material_recipe_srgb(
            np.zeros(1, dtype=np.int32),
            [_probe_material()],
            0.08,
            "transparent",
        )
```

- [ ] **Step 2: Run the new test and prove RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_material_color_prediction_contract_unit.py -v
```

Expected: collection fails because `predict_material_recipe_srgb` does not exist.

- [ ] **Step 3: Implement the minimal shared helper**

Add this public function immediately after `forward_model` in `core/material_color_solver.py`:

```python
def predict_material_recipe_srgb(
    recipe: np.ndarray,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate: str = "white",
) -> np.ndarray:
    """Predict one material recipe as rounded sRGB uint8.
    将一组耗材叠层配方预测为舍入后的 sRGB uint8。

    Args:
        recipe: Bottom-to-top material indices. (从底到顶的耗材索引)
        materials: Available material parameters. (可用耗材参数)
        layer_height_mm: Thickness of each layer in mm. (每层厚度，毫米)
        substrate: ``"white"`` or ``"black"``. (白色或黑色基底)

    Returns:
        A ``(3,) uint8`` sRGB colour. (一个 ``(3,) uint8`` sRGB 颜色)

    Raises:
        ValueError: If ``substrate`` is unsupported. (基底类型不受支持)
    """
    if substrate == "white":
        substrate_linear = np.ones(3, dtype=np.float64)
    elif substrate == "black":
        substrate_linear = np.zeros(3, dtype=np.float64)
    else:
        raise ValueError(
            f"substrate must be 'white' or 'black', got {substrate!r}"
        )

    predicted_linear = forward_model(
        np.asarray(recipe, dtype=np.int32),
        materials,
        layer_height_mm,
        substrate_linear,
    )
    return linear_to_srgb_uint8(predicted_linear).reshape(3)
```

Add `predict_material_recipe_srgb` to the module's Public API list.

- [ ] **Step 4: Run the core contract and prove GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_material_color_prediction_contract_unit.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit the core boundary**

Run:

```bash
git add core/material_color_solver.py tests/test_material_color_prediction_contract_unit.py
git commit -m "fix(materials): centralize recipe color prediction"
```

### Task 3: Align Material Library recipe prediction

**Files:**
- Modify: `tests/test_material_recipe_preview_unit.py`
- Modify: `api/routers/single_stage.py`

- [ ] **Step 1: Add a regression that distinguishes canonical white from archive `C0_white`**

In `tests/test_material_recipe_preview_unit.py`, import `predict_material_recipe_srgb` and add:

```python
def test_white_substrate_ignores_first_archive_c0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = [
        MaterialParams(
            name="Capture-biased red",
            directory_name="capture-red",
            E=np.asarray([0.6, 0.05, 0.05], dtype=np.float64),
            k=np.asarray([4.0, 4.0, 4.0], dtype=np.float64),
            C0_white=np.asarray([0.35, 0.45, 0.55], dtype=np.float64),
            estimated_rgb=np.asarray([220, 30, 30], dtype=np.uint8),
        ),
        _SYNTHETIC_PALETTE[1],
    ]
    monkeypatch.setattr(
        "api.routers.single_stage.load_multiple_materials",
        lambda _directory_names: materials,
    )
    expected_rgb = predict_material_recipe_srgb(
        np.arange(len(materials), dtype=np.int32),
        materials,
        0.08,
        "white",
    )
    archive_c0_rgb = linear_to_srgb_uint8(
        forward_model(
            np.arange(len(materials), dtype=np.int32),
            materials,
            0.08,
            materials[0].C0_white,
        )
    )
    assert expected_rgb.tolist() != archive_c0_rgb.tolist()

    response = _client().post(
        "/api/extractor/material-recipe-preview",
        json={
            "directory_names": ["capture-red", "blue"],
            "layer_height_mm": 0.08,
            "substrate": "white",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["predicted_rgb"] == expected_rgb.tolist()
```

- [ ] **Step 2: Run the endpoint regression and prove RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_material_recipe_preview_unit.py::test_white_substrate_ignores_first_archive_c0 -v
```

Expected: the response matches the first material's capture-specific `C0_white`, not the canonical result.

- [ ] **Step 3: Replace the endpoint-local substrate calculation**

In `api/routers/single_stage.py`, replace imports of `forward_model` and `linear_to_srgb_uint8` with `predict_material_recipe_srgb`, delete `_resolve_substrate_linear`, and replace the prediction block with:

```python
    recipe = np.arange(len(materials), dtype=np.int32)
    predicted_srgb = predict_material_recipe_srgb(
        recipe=recipe,
        materials=materials,
        layer_height_mm=float(payload.layer_height_mm),
        substrate=payload.substrate,
    )
    predicted_rgb = [int(c) for c in predicted_srgb.tolist()]
```

- [ ] **Step 4: Run the complete Material Library endpoint suite**

Run:

```bash
.venv/bin/python -m pytest tests/test_material_recipe_preview_unit.py -v
```

Expected: all tests pass, including pure black and invalid-substrate cases.

- [ ] **Step 5: Commit the Material Library adoption**

Run:

```bash
git add api/routers/single_stage.py tests/test_material_recipe_preview_unit.py
git commit -m "fix(materials): align library recipe substrate"
```

### Task 4: Align converter prediction, application, and padding

**Files:**
- Modify: `tests/test_converter_recipe_override_unit.py`
- Modify: `api/routers/converter/replace.py`

- [ ] **Step 1: Add converter rounding and cache regressions**

Import `MaterialParams` and `predict_material_recipe_srgb` in `tests/test_converter_recipe_override_unit.py`, add a `_rounding_probe_material` fixture helper using the exact values from Task 2, then add two tests after `_seed_material_archive_session`:

```python
def test_predict_material_archive_uses_canonical_rounded_rgb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store, _registry = _client_with_state()
    session_id, _mask = _seed_material_archive_session(
        store,
        preview_colors={0: [80, 120, 160, 255]},
        slot_names=["Probe"],
    )
    material = _rounding_probe_material()
    monkeypatch.setattr(
        "api.routers.converter.replace.load_multiple_materials",
        lambda _paths: [material],
    )

    response = client.post(
        "/api/convert/predict-recipe",
        json={
            "session_id": session_id,
            "recipe": [0, 0, 0, 0, 0],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["rgb"] == [214, 229, 241]
    assert response.json()["source"] == "material_archive_forward_model"


def test_apply_material_archive_rounds_override_and_padded_pixels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store, _registry = _client_with_state()
    session_id, region_mask = _seed_material_archive_session(
        store,
        preview_colors={0: [80, 120, 160, 255]},
        slot_names=["Probe"],
        layer_count=3,
    )
    store.put(session_id, "material_layer_count", 5)
    material = _rounding_probe_material()
    monkeypatch.setattr(
        "api.routers.converter.replace.load_multiple_materials",
        lambda _paths: [material],
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [0, 0, 0, 0, 0],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["rgb"] == [214, 229, 241]
    updated_rgb = store.get(session_id)["preview_cache"]["matched_rgb"]
    expected = np.asarray([214, 229, 241], dtype=np.uint8)
    assert np.all(updated_rgb[region_mask] == expected)
    assert np.all(updated_rgb[~region_mask] == expected)
```

Define the shared test helper as:

```python
def _rounding_probe_material() -> MaterialParams:
    return MaterialParams(
        name="Probe",
        directory_name="probe",
        E=np.asarray([0.2, 0.4, 0.6], dtype=np.float64),
        k=np.asarray([1.3, 1.1, 0.9], dtype=np.float64),
        C0_white=np.asarray([0.3, 0.4, 0.5], dtype=np.float64),
        estimated_rgb=np.asarray([80, 120, 160], dtype=np.uint8),
    )
```

- [ ] **Step 2: Run both regressions and prove RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_converter_recipe_override_unit.py::test_predict_material_archive_uses_canonical_rounded_rgb \
  tests/test_converter_recipe_override_unit.py::test_apply_material_archive_rounds_override_and_padded_pixels -v
```

Expected: current responses truncate the blue channel to 240.

- [ ] **Step 3: Adopt the shared helper in all three converter calculations**

Change the module import in `api/routers/converter/replace.py` to:

```python
from core.material_color_solver import predict_material_recipe_srgb
```

At every material-archive call site, resolve the canonical substrate from the
preview cache/session and pass it to the shared helper. Normalize the declared
recipe order explicitly instead of unconditionally reversing it:

```python
recipe_bottom_to_top = convert_recipe_between_orders(
    recipe,
    source_order,
    "Bottom2Top",
)
predicted_rgb = predict_material_recipe_srgb(
    np.asarray(recipe_bottom_to_top, dtype=np.int32),
    materials,
    layer_height_mm=layer_height_mm,
    substrate=substrate,
)
```

For fixed recipe application, independently convert the submitted recipe to
`Top2Bottom` before writing `material_matrix`. Dynamic prepared recipes are
already explicitly `Top2Bottom`.

Add a two-material `Bottom2Top` + black-substrate regression that asserts the
predict/apply calls receive the submitted bottom-to-top order unchanged, the
padded-pixel recalculation also receives black, and the cache stores the
equivalent top-to-bottom recipe.

- [ ] **Step 4: Update dynamic tests to patch the new boundary**

Replace monkeypatches of `api.routers.converter.replace.forward_model` and `linear_to_srgb_float` with `api.routers.converter.replace.predict_material_recipe_srgb`. The order-checking fake must retain this signature and assertion behavior:

```python
    def fake_predict_material_recipe_srgb(
        recipe,
        materials,
        layer_height_mm,
        substrate="white",
    ):
        seen_bottom_to_top.append([int(value) for value in recipe])
        assert layer_height_mm == 0.08
        assert substrate == "white"
        return np.asarray([137, 188, 225], dtype=np.uint8)
```

For the benefit-curve test, patch the shared helper to return `np.asarray(target_b, dtype=np.uint8)`.

- [ ] **Step 5: Run converter regression coverage**

Run:

```bash
.venv/bin/python -m pytest tests/test_converter_recipe_override_unit.py -v
```

Expected: all converter recipe tests pass, including fallback, virtual-material, dynamic-order, padding, and cache assertions.

- [ ] **Step 6: Commit the converter adoption**

Run:

```bash
git add api/routers/converter/replace.py tests/test_converter_recipe_override_unit.py
git commit -m "fix(converter): unify material recipe rgb"
```

### Task 5: Query and cache the printable dynamic depth

**Files:**
- Modify: `frontend/src/__tests__/converter-store-material-suggest.test.ts`
- Modify: `frontend/src/stores/converter/store.ts`

- [ ] **Step 1: Add the dynamic-depth and LRU regression**

Add this test to `frontend/src/__tests__/converter-store-material-suggest.test.ts`:

```typescript
  it("uses printable dynamic depth in both the request and LRU key", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);
    useConverterStore.setState({
      materialDynamicLayerCountEnabled: true,
      materialMaxLayerCount: 8,
    });
    fetchMaterialColorSuggestionsMock
      .mockResolvedValueOnce(stubResponse({ layer_count: 8 }))
      .mockResolvedValueOnce(stubResponse({ layer_count: 7 }));

    await useConverterStore.getState().fetchMaterialSuggestions("#C86432");
    expect(fetchMaterialColorSuggestionsMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ layerCount: 8 }),
      "#C86432",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );

    useConverterStore.setState({ materialMaxLayerCount: 7 });
    await useConverterStore.getState().fetchMaterialSuggestions("#C86432");

    expect(fetchMaterialColorSuggestionsMock).toHaveBeenCalledTimes(2);
    expect(fetchMaterialColorSuggestionsMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ layerCount: 7 }),
      "#C86432",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
```

- [ ] **Step 2: Run the test and prove RED**

Run:

```bash
.venv/bin/python scripts/run_vitest.py run src/__tests__/converter-store-material-suggest.test.ts
```

Expected: the first request uses layer count 5 and the second call reuses the wrong five-layer cache entry.

- [ ] **Step 3: Resolve suggestion depth once and reuse it**

In `fetchMaterialSuggestions`, add:

```typescript
      const suggestionLayerCount = resolveMaterialPrintLayerCount(state);
```

Use `suggestionLayerCount` as `layerCount` in `_materialSuggestCacheKey` and `fetchMaterialColorSuggestions`.

Because the dynamic maximum is now a request/cache dependency, changes to any
suggestion input must also cancel the current request and clear the visible
suggestion state. Advance a latest-request token when cancelling and verify it
after the request resolves; this prevents a mocked or non-cooperative
transport from restoring a stale result after `AbortController.abort()`.

Add a regression that starts an eight-layer request, changes the maximum to
seven, resolves the old request despite its aborted signal, and asserts that
the store remains cleared.

- [ ] **Step 4: Run frontend behavior tests and build**

Run:

```bash
.venv/bin/python scripts/run_vitest.py run \
  src/__tests__/converter-store-material-suggest.test.ts \
  src/__tests__/material-color-picker.test.tsx \
  src/__tests__/converter-store-dynamic-material-layer-count.test.ts
pnpm --dir frontend build
```

Expected: all focused Vitest tests pass and Vite completes a production build.

- [ ] **Step 5: Commit the frontend depth fix**

Run:

```bash
git add frontend/src/stores/converter/store.ts frontend/src/__tests__/converter-store-material-suggest.test.ts
git commit -m "fix(converter): suggest printable dynamic recipes"
```

### Task 6: Publish the user-facing change record

**Files:**
- Modify: `frontend/src/data/announcements.ts`
- Modify: `docs/superpowers/specs/2026-08-08-material-color-consistency-design.md`

- [ ] **Step 1: Mark the approved design**

Change the design status line to:

```markdown
**Status:** Approved for implementation
```

- [ ] **Step 2: Prepend today's bilingual announcement**

Prepend this entry to `ANNOUNCEMENTS`:

```typescript
  {
    version: "2026-08-08",
    title: {
      zh: "Lumina Layers — 材料配方颜色一致性",
      en: "Lumina Layers — Consistent material recipe colours",
    },
    sections: [
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "相同的耗材叠层现在会在转换预览、自定义配方、可实现颜色推荐和材料库配方查询里显示一致的模拟颜色；动态 5–8 层模式也会按实际八层范围寻找配方。",
            en: "The same filament stack now shows one consistent simulated colour in conversion previews, custom recipes, achievable-colour suggestions, and Material Library recipe lookup. Dynamic 5–8 layer mode also searches the full printable eight-layer depth.",
          },
        ],
      },
    ],
  },
```

- [ ] **Step 3: Run announcement type and rendering gates**

Run:

```bash
pnpm --dir frontend exec tsc --noEmit
.venv/bin/python scripts/run_vitest.py run src/__tests__/useAnnouncement.test.ts src/__tests__/announcement-dialog.test.tsx
```

Expected: TypeScript and both announcement suites pass.

- [ ] **Step 4: Verify UTF-8 and commit release communication**

Run:

```bash
iconv -f UTF-8 -t UTF-8 frontend/src/data/announcements.ts >/dev/null
iconv -f UTF-8 -t UTF-8 docs/superpowers/specs/2026-08-08-material-color-consistency-design.md >/dev/null
rg -n "锟|鎷|鍙|涓" frontend/src/data/announcements.ts docs/superpowers/specs/2026-08-08-material-color-consistency-design.md
git diff --check
git add frontend/src/data/announcements.ts docs/superpowers/specs/2026-08-08-material-color-consistency-design.md
git commit -m "docs(announcement): note material color consistency"
```

Expected: both `iconv` commands succeed, the mojibake scan prints nothing, `git diff --check` is clean, and the commit succeeds.

### Task 7: Verify the complete fix like a real user

**Files:**
- Read/execute only; save screenshots and logs under `.scratch/lum-20260805-001/` without committing them.

- [ ] **Step 1: Run the complete focused automated gate from a clean status**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_material_color_prediction_contract_unit.py \
  tests/test_material_recipe_preview_unit.py \
  tests/test_converter_recipe_override_unit.py -v
.venv/bin/python scripts/run_vitest.py run \
  src/__tests__/converter-store-material-suggest.test.ts \
  src/__tests__/material-color-picker.test.tsx \
  src/__tests__/converter-store-dynamic-material-layer-count.test.ts \
  src/__tests__/useAnnouncement.test.ts \
  src/__tests__/announcement-dialog.test.tsx
pnpm --dir frontend build
git diff --check
git status --short
```

Expected: every test and build passes; only deliberate `.scratch` evidence is untracked/ignored.

- [ ] **Step 2: Compare the head behavior with the captured base evidence**

Use commit `817a50b16c82804e6bf40106fef5165435cc2a79` as the recorded base and the real `赛纳/赛纳PETG白色 by MingDee` archive at 0.08 mm. Require the head evidence to replace every mismatch below with the canonical result and eight-layer request depth:

```text
Converter/canonical eight-layer white: #FFFFF9
Custom recipe prediction:             #FEFEF9
Material Library prediction:          #FFFFF8
Dynamic 5–8 suggestion request depth: 5
```

- [ ] **Step 3: Start the PR branch backend and frontend**

Run in separate terminals:

```bash
.venv/bin/python api_server.py
pnpm --dir frontend dev --host 127.0.0.1
```

Expected: FastAPI listens on 8000 and Vite reports its local URL without startup errors.

- [ ] **Step 4: Exercise the complete human path in real Chrome**

Open the Vite URL in real Chrome and perform these visible actions:

1. Load a real local SVG into the converter.
2. Select real Saiana material archives and enable dynamic 5–8 layers at 0.08 mm.
3. Generate preview and confirm the preview remains usable after gradient-group selection and flattening.
4. Search achievable colours for `#FFFFF9`; inspect the network form payload and require `layer_count=8`.
5. Open custom recipe editing, choose Saiana PETG white for all eight layers, predict, apply, and require `#FFFFF9` in the dialog and updated preview.
6. Open Material Library recipe lookup, add the same Saiana white archive eight times in visible order, predict, and require `#FFFFF9`.
7. Confirm no failed application requests, uncaught console errors, permanent loading states, or stale five-layer suggestion reuse.
8. Save screenshots plus console/network observations under `.scratch/lum-20260805-001/`.

- [ ] **Step 5: Repeat the primary prediction path in Electron**

Stop the standalone FastAPI/Vite processes, then run:

```bash
pnpm dev:electron
```

In the Electron window, repeat custom-recipe prediction/application and Material Library prediction with the same stack, and require the same `#FFFFF9`. Record any platform-only gap explicitly rather than inferring success.

- [ ] **Step 6: Stop only processes started by this verification**

Run:

```bash
.venv/bin/python start_all.py --kill
```

Then inspect command lines for this worktree path and confirm no `api_server.py`, `start_all.py`, Vite, Vitest, Electron, or esbuild process started by this task remains. Do not stop processes belonging to another worktree.

### Task 8: Review, publish, and verify the pull request

**Files:**
- Review all tracked changes and commit history.

- [ ] **Step 1: Use verification-before-completion and request a code review**

Review the diff for scope, substrate/order correctness, fallback preservation, test quality, UTF-8, and zero unrelated changes. Run the focused gates again if the review changes code.

- [ ] **Step 2: Push the topic branch**

Run:

```bash
git status --short
git log --oneline origin/dev-refactor..HEAD
git push -u origin MOVIBALE/fix/material-color-consistency
```

Expected: only the topic branch is pushed; protected branches are untouched.

- [ ] **Step 3: Create a ready PR against `dev-refactor`**

Create the PR with English first and Chinese second. Include:

- bug/root-cause summary;
- explicit non-goals, including the PR #549 SVG/GLB race;
- exact base/head commits;
- automated command results;
- real Chrome and Electron observations;
- the Saiana `#FFFFF9` acceptance comparison;
- any unresolved human-verification gap.

- [ ] **Step 4: Verify the real remote state**

Run:

```bash
gh pr view --json number,url,state,isDraft,baseRefName,headRefName,headRefOid,statusCheckRollup
git ls-remote --heads origin MOVIBALE/fix/material-color-consistency
```

Expected: the PR is open, ready rather than draft, targets `dev-refactor`, points to the pushed head commit, and the remote branch hash matches local `HEAD`.
