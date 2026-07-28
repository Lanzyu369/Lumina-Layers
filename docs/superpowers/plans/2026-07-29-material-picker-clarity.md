# Material Picker Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved larger material picker with type and brand navigation, independent profile favorites, same-product author grouping, and objective mixed-material confirmation.

**Architecture:** Extend the saved-material list contract with optional structured metadata while preserving every legacy archive. Put filtering, grouping, legacy type classification, and mixed-selection calculations in a pure frontend model module; keep local favorite persistence in a separate utility; keep the React dialog focused on accessible interaction and responsive presentation. Existing downstream selection continues to receive only `directory_name` values.

**Tech Stack:** Python 3, FastAPI/Pydantic, React 19, TypeScript, Tailwind CSS, localStorage, Heroicons, Vitest/Testing Library, pytest.

---

## File map

- `core/single_stage/materials.py`: read, preserve, and expose structured archive metadata; provide a conservative display-only type bridge for legacy archives.
- `api/schemas/responses.py`: publish the optional metadata in the saved-material response schema.
- `frontend/src/api/types.ts`: mirror the response fields for the frontend.
- `frontend/src/components/ui/materialPickerModel.ts`: pure type, brand, search, product-grouping, sorting, and mixed-selection logic.
- `frontend/src/utils/materialPickerPreferences.ts`: versioned favorite persistence with legacy directory-name fallback.
- `frontend/src/components/ui/MaterialPickerDialog.tsx`: accessible responsive dialog, navigation, cards, author profiles, warnings, and second confirmation.
- `frontend/src/components/sections/BasicSettings.tsx`: load-error/retry integration and unchanged directory-name handoff.
- `frontend/src/i18n/translations.ts`: all new Chinese and English UI copy.
- `tests/test_single_stage_unit.py`: backend metadata and preservation regressions.
- `frontend/src/__tests__/material-picker-model.test.ts`: pure frontend behavior regressions.
- `frontend/src/__tests__/material-picker-preferences.test.ts`: arbitrary multi-favorite persistence regressions.
- `frontend/src/__tests__/material-picker.test.tsx`: dialog behavior, keyboard semantics, grouping, favorites, and mixed confirmation.
- `frontend/src/__tests__/BasicSettings.test.tsx`: library failure and retry integration.
- `frontend/package.json` and `pnpm-lock.yaml`: use `@heroicons/react` for standard UI icons.
- `design-qa.md`: final source-to-implementation visual comparison record.

### Task 1: Saved-material metadata contract

**Files:**
- Modify: `tests/test_single_stage_unit.py`
- Modify: `core/single_stage/materials.py`
- Modify: `api/schemas/responses.py`
- Modify: `frontend/src/api/types.ts`

- [ ] **Step 1: Write failing backend metadata tests**

Add a focused archive-list test with explicit metadata:

```python
def test_list_saved_stage_a_material_archives_exposes_picker_metadata(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "BrandA" / "PLA Red"
    material_dir.mkdir(parents=True)
    (material_dir / "stage_A_parameters.json").write_text(
        json.dumps({"parameters": {}}),
        encoding="utf-8",
    )
    (material_dir / "material.json").write_text(
        json.dumps(
            {
                "material_name": "PLA Red",
                "brand": "BrandA",
                "material_type": "PLA",
                "material_product_id": "product-brand-a-pla-red",
                "material_profile_id": "profile-alice",
                "contributor_name": "Alice",
                "stage_a_params_file": "stage_A_parameters.json",
                "material_summary": {"estimated_rgb": [220, 35, 45]},
            }
        ),
        encoding="utf-8",
    )

    [item] = list_saved_stage_a_material_archives(
        materials_dir=str(materials_root)
    )

    assert item["material_type"] == "PLA"
    assert item["material_type_source"] == "archive"
    assert item["material_product_id"] == "product-brand-a-pla-red"
    assert item["material_profile_id"] == "profile-alice"
    assert item["contributor_name"] == "Alice"
```

Add one legacy classification test proving exact PLA/PETG tokens are display-only and ambiguous names stay unknown:

```python
@pytest.mark.parametrize(
    ("material_name", "expected_type"),
    [
        ("拓竹PLA Basic 红色", "PLA"),
        ("魔创PETG蓝色", "PETG"),
        ("Plant Fiber Red", None),
    ],
)
def test_saved_material_picker_metadata_classifies_only_exact_legacy_tokens(
    tmp_path: Path,
    material_name: str,
    expected_type: str | None,
) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "sample"
    material_dir.mkdir(parents=True)
    (material_dir / "stage_A_parameters.json").write_text(
        json.dumps({"parameters": {}}),
        encoding="utf-8",
    )
    (material_dir / "material.json").write_text(
        json.dumps(
            {
                "material_name": material_name,
                "stage_a_params_file": "stage_A_parameters.json",
                "material_summary": {"estimated_rgb": [10, 20, 30]},
            }
        ),
        encoding="utf-8",
    )

    [item] = list_saved_stage_a_material_archives(
        materials_dir=str(materials_root)
    )

    assert item["material_type"] == expected_type
    assert item["material_type_source"] == (
        "legacy_name" if expected_type else None
    )
```

Add a save regression proving a new archive gets a stable profile ID and an existing archive keeps all explicit metadata across verification merge:

```python
def test_save_stage_a_material_archive_preserves_picker_metadata(
    tmp_path: Path,
) -> None:
    params_payload = {
        "meta": {},
        "parameters": {
            "channels": [
                {
                    "color_name": "PLA Red",
                    "E": [0.2, 0.3, 0.4],
                    "k": [1.0, 1.1, 1.2],
                }
            ],
            "substrates": [
                {"substrate_id": "white", "C0": [0.9, 0.9, 0.9]},
                {"substrate_id": "black", "C0": [0.1, 0.1, 0.1]},
            ],
        },
        "fitted_substrates": {},
        "validation": {"overall": {"mean_delta_e": 1.0}},
    }
    fit_summary = {
        "overall_validation": {
            "mean_delta_e": 1.0,
            "rmse_linear": 0.1,
            "channel_rmse": [0.1, 0.1, 0.1],
        },
        "warnings": [],
    }
    material_summary = {
        "estimated_rgb": [220, 35, 45],
        "estimated_k": [1.0, 1.1, 1.2],
        "white_zero_rgb": [240, 240, 240],
        "black_zero_rgb": [30, 30, 30],
        "layer_height_mm": 0.04,
        "sample_boxes": [],
    }
    first = save_stage_a_material_archive(
        material_name="PLA Red",
        params_payload=params_payload,
        fit_summary=fit_summary,
        source_summary={"capture": 1},
        material_summary=material_summary,
        materials_dir=str(tmp_path / "materials"),
    )
    first_payload = json.loads(Path(first.archive_path).read_text(encoding="utf-8"))
    first_payload.update(
        {
            "material_type": "PLA",
            "material_product_id": "product-red",
            "contributor_name": "Alice",
        }
    )
    Path(first.archive_path).write_text(
        json.dumps(first_payload),
        encoding="utf-8",
    )

    second = save_stage_a_material_archive(
        material_name="Ignored replacement name",
        params_payload=params_payload,
        fit_summary=fit_summary,
        source_summary={"capture": 2},
        material_summary=material_summary,
        materials_dir=str(tmp_path / "materials"),
        existing_directory_name=first.material_summary["directory_name"],
    )
    second_payload = json.loads(Path(second.archive_path).read_text(encoding="utf-8"))

    assert second_payload["material_profile_id"] == first_payload["material_profile_id"]
    assert second_payload["material_type"] == "PLA"
    assert second_payload["material_product_id"] == "product-red"
    assert second_payload["contributor_name"] == "Alice"
```

- [ ] **Step 2: Run the backend tests and verify RED**

Run:

```bash
python -m pytest tests/test_single_stage_unit.py \
  -k "picker_metadata or preserves_picker_metadata" -v
```

Expected: failures show missing metadata keys and missing generated `material_profile_id`.

- [ ] **Step 3: Implement the minimal backend contract**

In `core/single_stage/materials.py`, add helpers with these signatures:

```python
_MATERIAL_PICKER_METADATA_KEYS = (
    "material_type",
    "material_product_id",
    "material_profile_id",
    "contributor_name",
)


def _clean_optional_archive_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _resolve_picker_material_type(
    archive_payload: dict[str, Any],
    *,
    material_name: str,
    relative_directory_name: str,
) -> tuple[str | None, str | None]:
    explicit = _clean_optional_archive_text(archive_payload.get("material_type"))
    if explicit:
        return explicit.upper(), "archive"
    haystack = f"{material_name} {relative_directory_name}"
    for candidate in ("PETG", "PLA"):
        if re.search(
            rf"(?<![A-Za-z0-9]){candidate}(?![A-Za-z0-9])",
            haystack,
            flags=re.IGNORECASE,
        ):
            return candidate, "legacy_name"
    return None, None
```

Have `_saved_material_library_item_from_archive()` return the resolved type, source, product ID, profile ID, and contributor. Do not create product IDs or contributors from names.

When `save_stage_a_material_archive()` creates a new archive, write:

```python
"material_profile_id": f"profile_{uuid.uuid4().hex}",
```

When updating an existing archive, copy all keys in `_MATERIAL_PICKER_METADATA_KEYS` from the existing payload before writing the reconstructed payload. Never persist a `legacy_name` type inference.

Add nullable fields to `SavedMaterialLibraryItemResponse`:

```python
material_type: str | None = None
material_type_source: Literal["archive", "legacy_name"] | None = None
material_product_id: str | None = None
material_profile_id: str | None = None
contributor_name: str | None = None
```

Mirror them in `SavedMaterialLibraryItem`:

```typescript
material_type?: string | null;
material_type_source?: "archive" | "legacy_name" | null;
material_product_id?: string | null;
material_profile_id?: string | null;
contributor_name?: string | null;
```

- [ ] **Step 4: Run the backend tests and verify GREEN**

Run the command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Commit the metadata contract**

```bash
git add tests/test_single_stage_unit.py core/single_stage/materials.py \
  api/schemas/responses.py frontend/src/api/types.ts
git commit -m "feat(materials): expose picker profile metadata"
```

### Task 2: Pure picker model and favorite persistence

**Files:**
- Create: `frontend/src/components/ui/materialPickerModel.ts`
- Create: `frontend/src/utils/materialPickerPreferences.ts`
- Create: `frontend/src/__tests__/material-picker-model.test.ts`
- Create: `frontend/src/__tests__/material-picker-preferences.test.ts`

- [ ] **Step 1: Write failing pure-model tests**

Cover the following public API:

```typescript
import {
  buildBrandOptions,
  buildMaterialProductGroups,
  filterMaterialGroups,
  getMaterialTypeCategory,
  summarizeSelectedMaterialTypes,
} from "../components/ui/materialPickerModel";
```

Required assertions:

```typescript
const pla = makeMaterial({
  material_name: "Red PLA",
  directory_name: "JAYO/red-pla",
  brand: "JAYO",
  material_type: "PLA",
});
const petg = makeMaterial({
  material_name: "Black PETG",
  directory_name: "jayo/black-petg",
  brand: "jayo",
  material_type: "PETG",
});
const unknown = makeMaterial({
  material_name: "Legacy Red",
  directory_name: "legacy-red",
  brand: null,
  material_type: null,
});
const materials = [pla, petg, unknown];

expect(getMaterialTypeCategory(pla)).toBe("pla");
expect(getMaterialTypeCategory(petg)).toBe("petg");
expect(getMaterialTypeCategory(unknown)).toBe("other");

expect(
  buildBrandOptions(materials, {
    all: "全部品牌",
    unassigned: "未分组",
  }).map((item) => item.label),
).toEqual(["全部品牌", "JAYO", "未分组"]);

expect(buildMaterialProductGroups(materials)).toHaveLength(2);
expect(buildMaterialProductGroups(materials)[0].profiles).toHaveLength(2);

expect(
  filterMaterialGroups(groups, {
    query: "Alice",
    type: "all",
    brandKey: "all",
    favoriteKeys: new Set(),
  }),
).toHaveLength(1);

expect(summarizeSelectedMaterialTypes(materials, ["pla-a", "petg-a"])).toEqual({
  counts: [{ label: "PLA", count: 1 }, { label: "PETG", count: 1 }],
  requiresConfirmation: true,
  hasUnknown: false,
});
```

Prove grouping is conservative: same brand/name without the same
`material_product_id` remains two product cards.

- [ ] **Step 2: Write failing favorite-persistence tests**

Use the desired API:

```typescript
import {
  favoriteKeyForMaterial,
  loadMaterialProfileFavorites,
  saveMaterialProfileFavorites,
} from "../utils/materialPickerPreferences";

const favorites = new Set(["profile-a", "profile-b", "profile-c"]);
saveMaterialProfileFavorites(favorites);
expect(loadMaterialProfileFavorites()).toEqual(favorites);
expect(favoriteKeyForMaterial(legacyMaterial)).toBe("dir:Brand/Legacy");
```

Include malformed localStorage JSON and storage-write exception cases; both must degrade to an empty set/no thrown error.

- [ ] **Step 3: Run the tests and verify RED**

```bash
python scripts/run_vitest.py run \
  src/__tests__/material-picker-model.test.ts \
  src/__tests__/material-picker-preferences.test.ts
```

Expected: module-resolution failures because the two production modules do not exist.

- [ ] **Step 4: Implement the pure modules**

`materialPickerModel.ts` must export:

```typescript
export type MaterialTypeFilter = "favorites" | "all" | "pla" | "petg" | "other";
export type MaterialProductGroup = {
  key: string;
  productId: string | null;
  brand: string | null;
  materialType: string | null;
  profiles: SavedMaterialLibraryItem[];
};

export function getMaterialTypeCategory(
  item: SavedMaterialLibraryItem,
): Exclude<MaterialTypeFilter, "favorites" | "all">;

export function buildBrandOptions(
  materials: SavedMaterialLibraryItem[],
  labels: { all: string; unassigned: string },
): Array<{ key: string; label: string; count: number }>;

export function buildMaterialProductGroups(
  materials: SavedMaterialLibraryItem[],
): MaterialProductGroup[];

export function filterMaterialGroups(
  groups: MaterialProductGroup[],
  filters: {
    query: string;
    type: MaterialTypeFilter;
    brandKey: string;
    favoriteKeys: Set<string>;
  },
): MaterialProductGroup[];

export function summarizeSelectedMaterialTypes(
  materials: SavedMaterialLibraryItem[],
  selectedDirectoryNames: string[],
): {
  counts: Array<{ label: string; count: number }>;
  requiresConfirmation: boolean;
  hasUnknown: boolean;
};
```

Brand keys use `normalize("NFKC").trim().toLocaleLowerCase()`. Product groups use only a non-empty `material_product_id`; otherwise each profile gets its own group. Search includes name, directory, brand, resolved type, and contributor. Sort by localized material name by default and by `usage_last_used_at` when requested.

`materialPickerPreferences.ts` uses:

```typescript
const MATERIAL_PROFILE_FAVORITES_KEY =
  "lumina_material_profile_favorites_v1";
```

Store a JSON array of any number of profile keys. Stable profile keys use
`profile:${material_profile_id}` and legacy fallbacks use
`dir:${directory_name}`.

- [ ] **Step 5: Run the tests and verify GREEN**

Run the Step 3 command. Expected: both test files pass.

- [ ] **Step 6: Commit the pure behavior**

```bash
git add frontend/src/components/ui/materialPickerModel.ts \
  frontend/src/utils/materialPickerPreferences.ts \
  frontend/src/__tests__/material-picker-model.test.ts \
  frontend/src/__tests__/material-picker-preferences.test.ts
git commit -m "feat(frontend): model material picker navigation"
```

### Task 3: Responsive dialog, favorites, profiles, and mixed confirmation

**Files:**
- Modify: `frontend/src/__tests__/material-picker.test.tsx`
- Modify: `frontend/src/components/ui/MaterialPickerDialog.tsx`
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `frontend/package.json`
- Modify: `pnpm-lock.yaml`

- [ ] **Step 1: Replace accordion expectations with failing approved-flow tests**

Keep existing closed/cancel/staged-selection coverage, then add tests for:

```typescript
expect(screen.getByRole("dialog", { name: "选择耗材" })).toHaveAttribute(
  "aria-modal",
  "true",
);
expect(screen.getByRole("tab", { name: "PLA" })).toBeInTheDocument();
expect(screen.getByTestId("material-picker-brand-sidebar")).toBeInTheDocument();
expect(screen.getByTestId("material-picker-card-grid")).toHaveClass(
  "md:grid-cols-2",
);
```

Test brand and type filtering without clearing staged selections. Test case-only brand normalization. Test that two explicit profiles under one product render one card and two profile rows after expansion. Test that each profile can be favorited independently and that the Favorites tab keeps both.

Test mixed confirmation:

```typescript
fireEvent.click(screen.getByText("Red PLA"));
fireEvent.click(screen.getByText("Black PETG"));
expect(screen.getByRole("status")).toHaveTextContent("PLA 1 项");
expect(screen.getByRole("status")).toHaveTextContent("PETG 1 项");

fireEvent.click(screen.getByRole("button", { name: "完成" }));
expect(
  screen.getByRole("alertdialog", { name: "确认混合耗材类型？" }),
).toBeInTheDocument();
expect(screen.getByText(/请确认喷嘴温度、热床温度和层间粘结/)).toBeInTheDocument();
expect(screen.queryByText(/新手建议/)).not.toBeInTheDocument();
```

Verify “返回调整” keeps selection and “仍然使用” calls `onConfirm` with the exact directory names.

Add keyboard tests for initial search focus, Escape order, focus restoration, and star/profile accessible labels.

- [ ] **Step 2: Run the dialog test and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/material-picker.test.tsx
```

Expected: failures reference missing tabs, sidebar, product cards, favorite controls, dialog semantics, and mixed confirmation.

- [ ] **Step 3: Add the icon dependency**

```bash
cd frontend
pnpm add @heroicons/react
```

Use Heroicons for search, close, star, chevron, warning, and sort controls. Do not add handcrafted SVGs or text glyph icons.

- [ ] **Step 4: Implement translations**

Add Chinese and English keys for:

- favorites/all/PLA/PETG/other tabs
- all brands/unassigned/brand mobile selector
- name/recent sort
- unknown type/unknown author
- profile count, contributor, validation count, updated time
- favorite/unfavorite accessible labels
- empty favorites/no filtered results
- immediate mixed-type status
- mixed confirmation title/body/actions
- expand/collapse profiles
- retry loading

The mixed body must remain exactly objective in Chinese:

```text
当前选择包含 {types}。请确认喷嘴温度、热床温度和层间粘结符合你的打印方案。
```

- [ ] **Step 5: Implement the dialog**

Use this structural contract:

```tsx
<div role="presentation" data-testid="material-picker-dialog-overlay">
  <div
    ref={dialogRef}
    role="dialog"
    aria-modal="true"
    aria-labelledby={titleId}
    aria-describedby={descriptionId}
    className="grid h-[min(51.25rem,calc(100vh-3rem))] w-[min(68rem,calc(100vw-3rem))] grid-rows-[auto_auto_minmax(0,1fr)_auto] overflow-hidden rounded-2xl border shadow-2xl"
  >
    <header />
    <section>{/* search, type tabs, mobile brand select, sort */}</section>
    <div className="grid min-h-0 md:grid-cols-[13rem_minmax(0,1fr)]">
      <aside data-testid="material-picker-brand-sidebar" />
      <main>
        <div
          data-testid="material-picker-card-grid"
          className="grid gap-3 md:grid-cols-2"
        />
      </main>
    </div>
    <footer />
  </div>
</div>
```

Behavior requirements:

- Search opens focused.
- Tab focus stays inside the active dialog and returns to the trigger on close.
- Escape closes the alert dialog first, then the main dialog.
- Favorites save immediately and never alter staged selection.
- A one-profile card toggles directly.
- A multi-profile card expands; selecting a profile replaces any other selected profile in that product group.
- Type and brand filters never clear hidden staged items.
- Mixed type status appears immediately.
- Done submits directly for one type, otherwise opens the alert dialog.
- Mobile hides the brand sidebar, shows a brand select, and uses one card column.
- Footer stays visible while the brand list and result list scroll independently.

- [ ] **Step 6: Run the dialog test and verify GREEN**

Run the Step 2 command. Expected: all dialog and persistence tests pass.

- [ ] **Step 7: Commit the dialog**

```bash
git add frontend/src/__tests__/material-picker.test.tsx \
  frontend/src/components/ui/MaterialPickerDialog.tsx \
  frontend/src/i18n/translations.ts frontend/package.json pnpm-lock.yaml
git commit -m "feat(frontend): redesign material picker"
```

### Task 4: Basic Settings loading failure and retry

**Files:**
- Modify: `frontend/src/__tests__/BasicSettings.test.tsx`
- Modify: `frontend/src/components/sections/BasicSettings.tsx`

- [ ] **Step 1: Write the failing integration test**

Mock the first `listGradientCardMaterials()` call as rejected and the second as resolved. Open the material picker and assert:

```typescript
expect(screen.getByTestId("material-picker-load-error")).toBeInTheDocument();
fireEvent.click(screen.getByRole("button", { name: "重试" }));
await screen.findByText("Recovered PLA");
```

Also retain the existing assertion that confirmation updates
`selectedMaterialDirNames` with directory names, not product/profile IDs.

- [ ] **Step 2: Run the integration test and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/BasicSettings.test.tsx \
  -t "retries the material library"
```

Expected: failure because the component currently collapses errors into an empty material list and has no retry callback.

- [ ] **Step 3: Implement retryable loading**

Extract the existing request into a `loadMaterialLibrary()` callback. Track:

```typescript
const [materialLibraryError, setMaterialLibraryError] = useState(false);
```

Pass `loadError={materialLibraryError}` and
`onRetry={() => void loadMaterialLibrary()}` to `MaterialPickerDialog`.
Clear the error only when a new request starts or succeeds.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the Step 2 command without `-t`, then run:

```bash
python scripts/run_vitest.py run \
  src/__tests__/material-picker.test.tsx \
  src/__tests__/BasicSettings.test.tsx
```

Expected: both files pass.

- [ ] **Step 5: Commit the integration**

```bash
git add frontend/src/__tests__/BasicSettings.test.tsx \
  frontend/src/components/sections/BasicSettings.tsx
git commit -m "fix(frontend): make material picker loading retryable"
```

### Task 5: Automated verification

**Files:**
- Review: all modified files

- [ ] **Step 1: Run focused backend coverage**

```bash
python -m pytest \
  tests/test_single_stage_unit.py \
  tests/test_material_brand_unit.py \
  tests/test_material_sync_api_unit.py -v
```

Expected: zero failures.

- [ ] **Step 2: Run focused frontend coverage**

```bash
python scripts/run_vitest.py run \
  src/__tests__/material-picker-model.test.ts \
  src/__tests__/material-picker-preferences.test.ts \
  src/__tests__/material-picker.test.tsx \
  src/__tests__/BasicSettings.test.tsx \
  src/__tests__/material-library-panel.test.tsx
```

Expected: zero failures.

- [ ] **Step 3: Run lint and production build**

```bash
cd frontend
pnpm lint
pnpm build
```

Expected: both commands exit 0.

- [ ] **Step 4: Inspect text safety and diff hygiene**

```bash
git diff --check
rg -n "锟|鎷|鍙|涓" \
  core/single_stage/materials.py \
  api/schemas/responses.py \
  frontend/src/api/types.ts \
  frontend/src/components/ui/materialPickerModel.ts \
  frontend/src/utils/materialPickerPreferences.ts \
  frontend/src/components/ui/MaterialPickerDialog.tsx \
  frontend/src/components/sections/BasicSettings.tsx \
  frontend/src/i18n/translations.ts \
  tests/test_single_stage_unit.py \
  frontend/src/__tests__/material-picker-model.test.ts \
  frontend/src/__tests__/material-picker-preferences.test.ts \
  frontend/src/__tests__/material-picker.test.tsx \
  frontend/src/__tests__/BasicSettings.test.tsx
```

Expected: `git diff --check` exits 0 and the mojibake scan returns no matches.

### Task 6: Chrome reality test and design QA

**Files:**
- Create: `design-qa.md`
- Evidence: `.scratch/design-audit/material-picker-2026-07-29/09-favorites-and-author-profiles.png`
- Evidence: new implementation screenshots under `.scratch/design-audit/material-picker-implementation-2026-07-29/`

- [ ] **Step 1: Start the local application**

Use the repository launcher and record the actual frontend URL:

```bash
python start_all.py
```

Do not leave duplicate backend, Vite, Vitest, or esbuild processes.

- [ ] **Step 2: Test the primary desktop flow in the user's Chrome**

At the same desktop viewport as the source mock:

1. Open material-archive mode and the picker.
2. Verify type tabs, complete neutral brand list, and two-column cards.
3. Search by author and material type.
4. Favorite multiple profiles from the same product and verify the Favorites tab.
5. Select PLA and PETG, verify immediate warning.
6. Click Done, verify the objective second confirmation.
7. Return to adjust, then choose “仍然使用”.
8. Reopen and verify favorites persisted.
9. Check browser console for errors.

- [ ] **Step 3: Test compact layout and keyboard flow**

At a viewport narrower than 760px:

1. Verify brand dropdown replaces the sidebar.
2. Verify cards use one column and the footer remains reachable.
3. Use only keyboard controls to search, filter, expand profiles, favorite, select, confirm, and close.
4. Verify focus returns to the “选择耗材” trigger.

- [ ] **Step 4: Capture and compare source and implementation**

Capture the same desktop state as:

```text
.scratch/design-audit/material-picker-2026-07-29/09-favorites-and-author-profiles.png
```

Create a single side-by-side comparison image containing the source and implementation at normalized dimensions. Evaluate typography, spacing, tokens, icon consistency, copy, responsive structure, and the visible favorite/profile state.

- [ ] **Step 5: Write and iterate `design-qa.md`**

The report must include source and implementation paths, viewport, pixel sizes, state, full-view evidence, any focused comparison, findings, iteration history, tested interactions, console result, and:

```text
final result: passed
```

If any P0/P1/P2 remains, keep `final result: blocked`, fix it, recapture, and compare again.

- [ ] **Step 6: Stop local processes and run final verification**

```bash
python start_all.py --kill
git status --short --branch
git log --oneline --decorate -6
```

Confirm no launcher, backend, Vite, Vitest, esbuild, or project Node processes remain. Keep only a verified preview if the user explicitly asks it to remain running.

- [ ] **Step 7: Commit the QA record**

```bash
git add design-qa.md
git commit -m "test(frontend): verify material picker experience"
```

### Task 7: Selected material whole-card feedback

**Files:**
- Modify: `frontend/src/__tests__/material-picker.test.tsx`
- Modify: `frontend/src/components/ui/MaterialPickerDialog.tsx`

- [ ] **Step 1: Write failing selected-card regressions**

Replace the generic border-only assertion with tests proving that a selected
single-profile card receives the picker-specific pale surface, inset outline,
and light shadow while its unselected neighbor does not. Add the same assertion
for a grouped product after one author profile is selected.

- [ ] **Step 2: Run the focused tests and verify RED**

```bash
python scripts/run_vitest.py run \
  src/__tests__/material-picker.test.tsx \
  -t "whole-card treatment"
```

Expected: both tests fail because the picker still uses the shared active-row
class and has no picker-specific inset selected state.

- [ ] **Step 3: Implement the approved subtle selected state**

Define one local card-state class in `MaterialPickerDialog.tsx` and use it for
both single-profile and multi-profile outer cards:

```typescript
const materialPickerSelectedCardClass =
  "border-blue-300/80 bg-blue-50/50 ring-1 ring-inset ring-blue-200/60 " +
  "shadow-[var(--shadow-control-hover)] dark:border-blue-400/60 " +
  "dark:bg-blue-500/10 dark:ring-blue-400/20";
```

Keep the existing blue check and keyboard-only focus ring. Do not add scale,
translation, pulse, or looping animation.

- [ ] **Step 4: Run tests and production build**

```bash
python scripts/run_vitest.py run src/__tests__/material-picker.test.tsx
cd frontend
pnpm build
```

Expected: all material-picker tests pass and the production build exits 0.

- [ ] **Step 5: Compare selected and unselected cards in Chrome**

Open a brand containing side-by-side selected and unselected cards. Verify the
whole-card state is visible but subtle, the inset outline does not overlap a
hovered neighbor, pointer clicks do not leave an inner focus ring, and the card
does not move. Restore the original staged selection before handing the page
back to the user.

- [ ] **Step 6: Commit the refinement**

```bash
git add frontend/src/__tests__/material-picker.test.tsx \
  frontend/src/components/ui/MaterialPickerDialog.tsx
git commit -m "feat(frontend): emphasize selected material cards"
```
