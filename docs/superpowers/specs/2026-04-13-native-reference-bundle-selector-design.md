# Native Reference Bundle Selector Design

## Goal

Align Lumina's native reference source selection with the reference project by replacing the current single-LUT UX for `ReferenceDB`, `ReferencePack`, and `ReferenceModel` with a bundle-driven flow:

- `版本` (`旧版` / `新版`)
- `品牌` (native brand scope = `material_type + vendor`)
- native DB multi-select within that brand

Legacy/custom LUT behavior remains unchanged.

## Problem

Lumina currently exposes native reference assets as flat single-select LUT entries. That breaks parity with the reference workflow in three ways:

1. The reference runtime selects from a vendor/material bundle of multiple ColorDBs, while Lumina currently lets the user choose only one DB.
2. `ReferencePack` and `ReferenceModel` are exposed as independent user-facing options even though they are runtime assets tied to the same vendor/material scope as the DB bundle.
3. Because the frontend request shape is still `lut_name`-centric, preview, layer preview, recipe matching, and 3MF metadata can drift away from the bundle semantics used by the reference implementation.

## Non-Goals

- Do not convert legacy/custom LUTs to multi-select in this phase.
- Do not redesign the existing predictive/custom-recipe workflow outside the source selection surface.
- Do not invent a Lumina-only native asset packaging format in this phase.

## User Experience

### Version switch

Add a top-level selector in the converter basic settings:

- `旧版`
- `新版`

Behavior:

- `旧版` preserves the current single-LUT flow.
- `新版` enables the native reference bundle flow.

### Old version flow

Under `旧版`:

- Keep the current LUT single-select control.
- Group legacy/custom sources under brand labels for display only.
- `Custom` is shown as its own personal brand.
- Request payloads continue to use the existing `lut_name` field only.

### New version flow

Under `新版`:

- Replace the flat LUT selector with a native brand selector.
- A native brand is defined by `(material_type, vendor)`, for example `PLA / BambuLab`.
- After a brand is selected, render a multi-select list of `ReferenceDB` entries in that brand.
- Default selection is all DBs in the brand.

`ReferencePack` and `ReferenceModel` are not directly user-selectable in this mode. They are discovered and bound automatically by the backend based on the selected native brand.

### Source summary

When a native brand is selected, the UI must show:

- the selected brand label
- selected DB count
- package/model availability
- supported modes
- source kind summary for the assembled runtime

## Data Model

### Frontend state

Extend converter state with:

- `source_selection_mode: "legacy_single" | "native_bundle"`
- `selected_native_brand_key: string`
- `selected_native_db_names: string[]`
- `nativeSourceCatalog: NativeSourceCatalog | null`

Existing fields retained:

- `lut_name`
- `lutList`
- `lutListFull`
- `selectedLutInfo`

Rules:

- `lut_name` remains authoritative for `legacy_single`.
- `selected_native_brand_key` and `selected_native_db_names` become authoritative for `native_bundle`.
- Existing local persistence for `lut_name` is preserved.
- New persistence keys are added for the native bundle selection state.

### Request model

Keep existing `lut_name` for backward compatibility and add:

- `source_selection_mode`
- `native_material_type`
- `native_vendor`
- `native_db_names`

Validation:

- `legacy_single` requires `lut_name`
- `native_bundle` requires all of `native_material_type`, `native_vendor`, and at least one `native_db_name`

## API Changes

### New catalog endpoint

Add a LUT/source catalog endpoint that returns both old and new selection surfaces.

Response shape:

- `legacy_groups`
- `native_brands`

Each native brand entry contains:

- `brand_key`
- `material_type`
- `vendor`
- `display_name`
- `db_options`
- `default_db_names`
- `package_name` (optional)
- `model_name` (optional)
- `supported_modes`

The frontend uses this endpoint to render:

- the old-version brand and LUT choices
- the new-version native brand and DB bundle choices

### Preview/generate requests

`/api/convert/preview` and `/api/convert/generate` accept either:

- old single-LUT mode
- new native bundle mode

The backend must normalize both into the same runtime context used by the pipeline.

## Backend Runtime Behavior

### Legacy single source

No behavior change:

- `lut_name` resolves through `LUTManager`
- existing exact lookup / predictive behavior remains intact

### Native bundle source

For `native_bundle` requests:

1. Resolve the native brand using `(material_type, vendor)`.
2. Validate every requested `native_db_name` belongs to that brand.
3. Discover same-scope `ReferencePack` and `ReferenceModel` assets, if present.
4. Build runtime metadata and exact lookup from the selected DB subset.
5. Preserve full bundle metadata for preview and export, even when only a subset of DBs is selected.

This keeps runtime semantics aligned with the reference project:

- multiple DBs participate in candidate lookup
- pack/model are implicit runtime assets
- metadata still reflects the native bundle scope

## 3MF and Metadata Expectations

For native bundle runs:

- exported 3MF metadata must preserve the full selected bundle palette/material order
- the selected DB subset must still map into the correct bundle slot order
- preview colors, layer previews, and slicer consumable metadata must stay aligned with the assembled native runtime

## Error Handling

New native-bundle errors must be deterministic and actionable:

- unknown native brand
- no DBs selected
- selected DB not in brand
- selected brand has no usable runtime assets
- selected mode unsupported by the assembled native runtime

Legacy request failures remain unchanged.

## Testing

### Backend

- catalog response contains expected native brands and DB lists
- native bundle request validation accepts valid inputs and rejects mixed-brand DBs
- preview/generate for `native_bundle` produces the same runtime kind and supported modes as the discovered bundle
- existing legacy `lut_name` requests remain unchanged

### Frontend

- `旧版` shows single-select legacy/custom flow only
- `新版` shows brand selector + DB multi-select
- native brand switch resets selected DBs to that brand defaults
- deselecting some DBs persists correctly
- old persisted `lut_name` state still restores under `旧版`

### Regression

- existing custom/legacy LUT workflows do not regress
- native package/model preview and export stay compatible with the previously fixed metadata and layer-preview paths

## Implementation Breakdown

1. Add backend catalog and native-bundle request parsing.
2. Extend converter request schemas and pipeline LUT loading to accept normalized native bundle selections.
3. Add frontend catalog types and store state for version/brand/DB selection.
4. Replace the basic-settings LUT selector UI with a split old/new source picker while preserving legacy behavior.
5. Add focused backend/frontend regression coverage.

## Review Notes

- Scope is intentionally limited to native reference source selection.
- Legacy/custom LUT multi-select is postponed until the user's future upgraded LUT format exists.
- `ReferencePack` and `ReferenceModel` remain discoverable runtime assets, not user-facing primary choices.
