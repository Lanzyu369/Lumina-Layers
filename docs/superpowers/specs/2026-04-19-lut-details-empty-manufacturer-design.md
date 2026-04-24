# LUT Details Empty Manufacturer Filter Design

## Goal

Allow the LUT details manufacturer dropdown to remain unselected while still auto-selecting the first LUT that matches the active query, and preserve the existing rule that LUT manufacturer data comes directly from LUT metadata whenever metadata provides it.

## Problem

The current LUT details selection flow collapses two different concerns into one value:

- the user's active manufacturer filter
- the manufacturer inferred from the currently selected LUT

`resolveSelection()` currently rewrites an empty manufacturer filter to the first manufacturer in the filtered catalog. That means the UI cannot stay in an "all manufacturers" state. As soon as the catalog or search query changes, the store forces a manufacturer selection and narrows the LUT list.

## Non-Goals

- Do not change the backend LUT details response schema.
- Do not change manufacturer inference precedence on the backend.
- Do not redesign the dropdown component for this task.

## Desired Behavior

### Manufacturer filter

- The manufacturer dropdown may stay empty.
- An empty manufacturer means "do not restrict by manufacturer".
- In that state, the dropdown trigger shows its placeholder instead of a selected manufacturer label.

### LUT auto-selection

- If the active query yields matching LUTs, the store still auto-selects the first matching LUT.
- This auto-selection must not backfill `selectedManufacturer` when the user has not explicitly chosen a manufacturer.
- If the user explicitly picks a manufacturer, LUT options remain limited to that manufacturer.

### Manual LUT selection

- Choosing a LUT should set `selectedLutName`.
- Choosing a LUT must not silently change `selectedManufacturer` from empty to the LUT's manufacturer.

## Backend Confirmation

No backend change is required for the manufacturer source.

`core/lut_details/catalog.py` already resolves manufacturer identity using this precedence:

1. `parsed.metadata.manufacturer`
2. folder-derived manufacturer
3. filename-derived manufacturer
4. fallback `Unlabeled`

This keeps the current "read manufacturer directly from LUT metadata when present" behavior intact. The details API should continue to surface `manufacturer` and `manufacturer_source` from that resolved identity.

## Implementation Scope

### Frontend store

Update `frontend/src/stores/lutDetailsStore.ts` so that:

- empty manufacturer remains a valid persisted selection state
- LUT auto-selection uses the first item from the fully filtered item list
- manufacturer filtering is only applied when the user selected a manufacturer explicitly

### Frontend tests

Extend `frontend/src/__tests__/lut-details-store.test.ts` to cover:

- empty manufacturer preserving all matching LUTs
- catalog fetch defaulting to the first LUT while keeping manufacturer empty
- selecting a LUT while manufacturer is empty keeps the manufacturer filter empty

Optionally extend `frontend/src/__tests__/lut-details-panel.test.tsx` if the placeholder behavior needs direct UI coverage.

### Backend regression confidence

Keep the existing LUT details backend tests as the confidence layer for metadata-first manufacturer resolution. Add backend coverage only if the implementation reveals a missing assertion.

## Risks

- The existing store tests already have local uncommitted edits in this worktree, so the change must be appended carefully without overwriting in-progress work.
- `selectLut()` currently sets `selectedManufacturer` from the selected item, which is correct for explicit manufacturer picks but wrong for the empty-filter flow; changing it must not break the explicit-filter case.

## Review Notes

- This design intentionally keeps the backend catalog grouped by manufacturer; only the frontend selection semantics change.
- The store remains the single source of truth for query/manufacturer/LUT coordination.
