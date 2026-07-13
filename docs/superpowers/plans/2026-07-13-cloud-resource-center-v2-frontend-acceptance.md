# Cloud Resource Center V2 Frontend And Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace separate cloud/local material and LUT pages with two independent, production-ready resource centers that support cloud discovery, local management, exact lifecycle actions, offline browsing, and verified desktop/mobile workflows.

**Architecture:** Build one presentation shell and resource view model with two domain adapters. Each domain has `Cloud library` and `My resources` views, but material and LUT retain separate routes, API calls, filters, previews, selection semantics, and capability gates. Backend state/actions remain authoritative; the UI only narrows actions further and keeps the old panels behind a temporary display fallback that still uses v2-backed APIs.

**Tech Stack:** React 19, TypeScript, Zustand, Axios, Tailwind tokens, `lucide-react`, Vitest/Testing Library/fast-check, Playwright, existing i18n and announcement systems.

---

## Confirmed Product Language And Behavior

- Top-level destinations remain separate: `Material resources` and `LUT resources`.
- Each has exactly two primary views: `Cloud library` and `My resources`.
- Public sources are displayed as `Lumina official` or `Community shared` based only on `publisherKind`.
- The contribution action is `Share resource`, not `Submit`, `Contribution`, or wording that implies a competition/review queue.
- Community items may come from manufacturers or individual users and appear together after review.
- Cloud-managed content is read-only. Editing starts by creating a local copy.
- Update availability is a quiet badge/count, not a startup modal.
- Details are shown before install; desktop uses a right details pane, mobile uses a full-screen details view.
- Discovery sorting supports recently updated and downloads; there are no ratings, comments, or popularity claims beyond download count.
- Update/rollback retain current and one previous revision. Older exact history is reinstalled from Registry when available.
- Uninstall applies only to managed cloud content. Delete applies only to local imports/copies. Local equivalent offers adoption but neither uninstall nor create-local-copy; create-local-copy always starts from managed content.
- A resource in use shows which operation is holding it and blocks destructive actions.

## Branch And Dependencies

Use three sequential branches from fresh `dev-refactor` merges:

1. `codex/feat/resource-center-v2-shell`
   - Tasks 1-3: strict domain adapters/store, navigation migration, shared shell and safe Share resource action behind the disabled flag.
2. `codex/feat/resource-center-v2-ui`
   - Tasks 4-8: cloud/my lists, details, lifecycle dialogs, i18n, accessibility, responsive layout and controlled previews.
3. `codex/chore/resource-center-v2-acceptance`
   - Tasks 9-11: legacy display migration, deterministic external-HTTPS browser harness, screenshots, announcements, rollout/rollback and soak evidence.

Start after:

- Registry v2 service is deployed in staging;
- Materials v2 metadata is available in staging;
- Studio resource store/lifecycle/resolver/provenance PRs are merged;
- both domain capabilities can be independently exercised.

The shell and UI PRs keep the feature flag disabled by default and retain the v2-backed legacy display fallback. The acceptance PR may enable rollout only after its cross-repository gates pass. No stage may implement a browser-side fallback that writes v1 state, and later branches may not stack on an unmerged predecessor.

## File Structure

Create feature-owned files:

- `frontend/src/features/resources/types.ts`
  - Shared view types plus separate material/LUT domain payload types.
- `frontend/src/features/resources/api.ts`
  - Capabilities and lifecycle clients; no direct Registry URL.
- `frontend/src/features/resources/adapters.ts`
  - `MaterialResourceAdapter` and `LutResourceAdapter` mapping domain responses to view models.
- `frontend/src/features/resources/resourceCenterStore.ts`
  - Per-domain view/query/filter/cursor/selection/operation state with safe persistence.
- `frontend/src/features/resources/ResourceCenterPage.tsx`
  - Shared page layout only.
- `frontend/src/features/resources/ResourceViewTabs.tsx`
  - Cloud/My segmented view selector.
- `frontend/src/features/resources/ResourceToolbar.tsx`
  - Search, filters, sort, refresh, update-all, share action.
- `frontend/src/features/resources/ResourceList.tsx`
  - Dense desktop rows and compact responsive items; no nested cards.
- `frontend/src/features/resources/ResourceListItem.tsx`
  - Stable repeated item dimensions and state/action summary.
- `frontend/src/features/resources/ResourceDetails.tsx`
  - Desktop side pane/mobile full-screen shell.
- `frontend/src/features/resources/ResourceActions.tsx`
  - Icon/text command mapping from allowed actions.
- `frontend/src/features/resources/ResourceOperationDialog.tsx`
  - Confirmation/progress/partial-result dialogs.
- `frontend/src/features/resources/MaterialResourcePreview.tsx`
  - Material swatch, calibrated color and compatibility facts.
- `frontend/src/features/resources/LutResourcePreview.tsx`
  - Bounded 2D palette/grid summary; deep link to existing full LUT details.
- `frontend/src/features/resources/resourceStatus.ts`
  - Pure labels/tones/action guards.
- `frontend/src/features/resources/resourceShare.ts`
  - Validated public Share resource destination with no credential-bearing URL support.
- `frontend/src/features/resources/__tests__/**`
  - Focused unit/component/property tests.

Modify existing app structure:

- `frontend/package.json`, `frontend/pnpm-lock.yaml`
  - Add `lucide-react`, the Playwright test runner, and the E2E-only basic-SSL Vite plugin through pnpm.
- `frontend/vite.config.ts`
  - Add every new runtime import to the repository's explicit `optimizeDeps.include` contract and keep the cache override testable.
- Create `frontend/playwright.config.ts`
  - External-origin-only browser configuration, fixed projects, artifacts outside the repository.
- Create `frontend/e2e/resource-center-v2.spec.ts`
  - Deterministic material/LUT lifecycle, offline, in-use, responsive, theme, and leak assertions.
- Create `scripts/run_resource_center_e2e.py`
  - Disposable three-repository service/data/browser orchestrator for restart, publish, damage, offline, and cleanup phases.
- Create `tests/test_resource_center_e2e_harness_unit.py`
  - Path refusal, exact-commit checks, process cleanup, secret redaction, phase ordering, and sentinel preservation.
- `frontend/src/types/widget.ts`
  - Add stable `material-resources` and `lut-resources` tab IDs; retain old IDs for persisted migration only.
- `frontend/src/stores/widgetStore.ts`
  - Migrate old local/cloud tab persistence to the matching new resource tab.
- `frontend/src/components/widget/TabNavBar.tsx`
- `frontend/src/components/widget/SubTabBar.tsx`
  - Replace duplicated cloud/library entries with one domain resource entry while keeping material/LUT tools independent.
- `frontend/src/App.tsx`
  - Render new pages and temporary legacy-display fallback.
- `frontend/src/i18n/translations.ts`
  - All regular bilingual strings.
- `frontend/src/data/announcements.ts`
  - End-user release entry after behavior is verified.
- `docs/announcement-maintenance.md`
  - Read only unless announcement semantics themselves change.
- Create `docs/resource-center-v2-user-acceptance.md`
  - Staging test matrix and evidence locations, no secrets/local absolute paths.

Do not put resource orchestration in components. Do not store package URLs/hashes/tokens in Zustand or browser persistence. Do not create a combined material/LUT endpoint or adapter.

## Task 1: API Types And Independent Domain Adapters

**Files:**
- Create: `frontend/src/features/resources/types.ts`
- Create: `frontend/src/features/resources/api.ts`
- Create: `frontend/src/features/resources/adapters.ts`
- Create: `frontend/src/features/resources/__tests__/adapters.test.ts`
- Create: `frontend/src/features/resources/__tests__/api.test.ts`

- [ ] **Step 1: Write failing view-model tests**

Material fixtures use `material_id/local_directory/material_type`; LUT fixtures use `lut_id/local_path/color_mode`. Assert both map common display/state fields, including exact `history_busy -> historyBusy`, while domain facts remain in discriminated payloads. Test complete exact ref versus pure-local null, fixed safe technical prefixes, every local state/action, download counts at `0`, `Number.MAX_SAFE_INTEGER - 1`, and `Number.MAX_SAFE_INTEGER`, compatibility numbers at `-1_000_000_000`, `0`, and `1_000_000_000`, canonical timestamp boundaries `1970-01-01T00:00:00Z`/`9999-12-31T23:59:59Z`, valid `cat_0000000000000000`/`auth_ffffffffffffffff` generations, legacy/local data with a missing publisher kind defaulting to community, `official` channel with community publisher staying community, distinct authorized `team/private` and historical `team/team` records staying restricted without an official badge or persistent browser cache, equal resource IDs under different Registry keys staying separate, and the same logical path/hash under a different ID becoming a local equivalent rather than installed. Test operation-specific action-result identities: managed operations/update-all are cloud-only, delete/local failures are local-only, and only successful adopt/copy/detach transitions may carry both addresses. For adopt, `local_id` is source and the managed address/revision is result; for copy/detach, the managed address/revision is source and `local_id` is result. Material wire results must contain only `material_id`, LUT wire results only `lut_id`; reject generic `resource_id` and dual-domain IDs before mapping either domain into the internal `resourceId` representation. The reducer refreshes/removes exactly those operation-defined rows and never infers direction from which field is non-null. A v2 managed cloud item with a missing Registry key or publisher ID is invalid and must be rejected, never downgraded. Also reject partial refs, wrong kind, malformed hashes, full package hash in a prefix field, unsafe/noninteger/negative download counts, out-of-range/non-finite compatibility numbers, timestamp offsets/fractions/leap seconds/impossible dates/whitespace, swapped/missing/wrong-case/wrong-width generation prefixes, `private` as channel or unknown visibility, illegal empty/partial/mixed action-result addresses, dual-address skipped/failed results, Registry URL/envelope, and absolute local path.

- [ ] **Step 2: Define the shared model**

```typescript
import type { ResourceRevisionRef } from "../../types/resources";

export type ResourceKind = "material" | "lut";
export type ResourceLocalState =
  | "not_installed"
  | "installed"
  | "update_available"
  | "local_equivalent"
  | "damaged"
  | "local_import"
  | "local_copy"
  | "legacy_unresolved";

export type ResourceItemAction =
  | "install"
  | "update"
  | "rollback"
  | "uninstall"
  | "repair"
  | "adopt_local_equivalent"
  | "create_local_copy"
  | "detach_management"
  | "delete";

export type ResourceBatchAction = "update_all";
export type ResourceUsageKind =
  | "preview"
  | "generate"
  | "replace"
  | "extract"
  | "merge"
  | "details"
  | "calibration"
  | "batch"
  | "other";

export interface ResourceViewModel {
  kind: ResourceKind;
  itemKey: string;
  sourceRegistry: string | null;
  resourceId: string | null;
  localId: string | null;
  revisionId: string | null;
  resourceRef: ResourceRevisionRef | null;
  title: string;
  brand: string;
  publisherId: string | null;
  publisherKind: "lumina" | "community";
  publisherName: string;
  displayProvenance: "current_registry" | "installed_snapshot" | "local_content";
  metadataStale: boolean;
  metadataVerifiedAt: string | null;
  distributionAvailable: boolean | null;
  summary: string;
  tags: string[];
  downloadCount: number;
  updatedAt: string;
  localState: ResourceLocalState;
  localDisplayPath: string | null;
  hasPreviousRevision: boolean;
  isInUse: boolean;
  historyBusy: boolean;
  inUseBy: ResourceUsageKind[];
  allowedActions: ResourceItemAction[];
  technical: {
    resourceId: string | null;
    localId: string | null;
    revisionId: string | null;
    contentHashPrefix: string | null;
    packageHashPrefix: string | null;
  };
  domain: MaterialResourceFacts | LutResourceFacts;
}
```

Import the single canonical `ResourceRevisionRef` from `frontend/src/types/resources.ts`, which is already used by recipe/share-card/bug-report provenance. Managed cloud items carry non-null `sourceRegistry`/`resourceId`, null `localId`, a complete matching ref, and a non-null read-only `publisherId`; pure local/unresolved items carry null address-level Registry/resource/publisher IDs, non-null stable `localId`, and a null ref. Local copies/equivalents remain addressed by `localId` even when they have source provenance. `itemKey` is `cloud:{sourceRegistry}:{kind}:{resourceId}` or `local:{kind}:{localId}` and is never derived from title/path/hash; adapters reject both address forms missing, reject mixed cloud/local address fields except explicit action-result/source projection shapes, and keep equal resource IDs from different Registry keys distinct. Current Registry display is accepted only when backend marks it freshly authorized for the same complete ref. Installed fallback remains visibly stale/last-verified, and local content uses `local_content`; frontend never turns envelope drift into `update_available`. `inUseBy` accepts only the fixed usage enum with at most eight unique values and maps those codes through i18n; adapters reject raw session/job/lease/PID/path strings. Publisher filters submit only the opaque read ID and render its accompanying name; equal names remain separate and the ID never enters mutation payloads. Lifecycle requests may echo the stable non-secret Registry key from the item identity, but it can never supply a URL or create a client-selected authority. The technical hash prefixes are null or exactly 12 lowercase hex characters supplied by the server; the adapter rejects a prefix, full digest, or arbitrary string of any other shape. No field contains a full package hash, Registry token, envelope query, Registry origin, or absolute local path.

- [ ] **Step 3: Implement API clients**

Call only Studio relative API routes. Catalog accepts cursor/query/domain filters/sort and returns generations/offline/fetched time. Cloud detail, status, preview, and distribution reads send the backend-returned stable Registry key as the required `source_registry` query value; cloud lifecycle requests send that key plus resource/revision IDs, while local requests send only stable local ID. No client method omits the key or chooses a default Registry from resource ID. Cloud page dedupe/pagination uses complete Registry/kind/resource/revision identity; My Resources uses `itemKey`, so a pure local item never receives a fabricated cloud ID and equal IDs from different registries never overwrite each other. Parse action results with the operation-specific identity rules before refreshing; an invalid result is a contract error and cannot trigger a title/path-based lookup. Use typed error extraction by stable `code`; do not infer behavior from translated message text.

- [ ] **Step 4: Implement separate adapters**

`MaterialResourceAdapter` knows `local_directory`, material compatibility, and material preview. `LutResourceAdapter` knows `local_path`, color mode, LUT preview, and LUT details navigation. Both call pure common mapping for publisher/state/time/count. The shared mapper has two adoption sites in this PR, satisfying the repository's lighthouse rule.

- [ ] **Step 5: Run and commit**

```bash
python scripts/run_vitest.py run src/features/resources/__tests__/adapters.test.ts src/features/resources/__tests__/api.test.ts
git add frontend/src/features/resources/types.ts frontend/src/features/resources/api.ts frontend/src/features/resources/adapters.ts frontend/src/features/resources/__tests__/adapters.test.ts frontend/src/features/resources/__tests__/api.test.ts
git commit -m "feat(resources): add typed material and LUT adapters"
```

## Task 2: Capability-Gated Store And Cursor State

**Files:**
- Create: `frontend/src/features/resources/resourceCenterStore.ts`
- Create: `frontend/src/features/resources/__tests__/resourceCenterStore.test.ts`
- Create: `frontend/src/features/resources/__tests__/resourceCenterStore.property.test.ts`

- [ ] **Step 1: Write store transition/property tests**

Cover independent domain capability, unknown adapter, migration prepared, read-only repair, query debounce, first/next cursor pages, query change cancel/reset, stale request ordering, duplicate cursor item suppression by complete Registry identity, equal IDs from different Registry keys, catalog generation change, offline cache, selection removal, action progress, update-all partial results, and persistence migration. Fast-check generates response ordering, duplicate IDs/revisions/Registry keys, query changes, and mixed domain states.

- [ ] **Step 2: Define persisted versus ephemeral state**

Persist only per-domain selected view, sort, safe filters, and schema version. Do not persist catalog payloads, details, allowed actions, operation state, cursor, capabilities, error body, URL, hash, or credentials; backend/public cache owns offline data.

- [ ] **Step 3: Gate every action by three conditions**

An item action is visible/enabled only when:

1. target domain reports `resource_store_version="2.0"`;
2. `cutover_state="v2_committed"` and `adapter_generation="resources-v2-1"`;
3. both domain capability actions and item `allowedActions` include it.

One domain's capability never unlocks the other. Parse the design's single wire-level `actions` array into local `Set<ResourceItemAction>` and `Set<ResourceBatchAction>` values using exhaustive literal guards; unknown action values make that domain read-only and produce a contract error. Do not require or emit non-contract `item_actions`/`batch_actions` fields. `update_all` additionally requires the domain's parsed batch-action set to contain it and at least one visible local item whose `allowedActions` contains `update`; it is never inferred from an update count alone. On capability downgrade, cancel pending UI operations, refresh read-only data, and hide mutation commands.

- [ ] **Step 4: Implement request convergence**

Use request IDs/AbortController so old query/page responses cannot overwrite new state. End pagination only when both `has_more=false` and `next_cursor=null`; inconsistent envelopes become a contract error and do not loop. Batch completion applies one refresh and preserves failed items/reasons.

- [ ] **Step 5: Run and commit**

```bash
python scripts/run_vitest.py run src/features/resources/__tests__/resourceCenterStore.test.ts src/features/resources/__tests__/resourceCenterStore.property.test.ts
git add frontend/src/features/resources/resourceCenterStore.ts frontend/src/features/resources/__tests__/resourceCenterStore.test.ts frontend/src/features/resources/__tests__/resourceCenterStore.property.test.ts
git commit -m "feat(resources): manage capability and cursor state"
```

## Task 3: Navigation Migration And Page Shell

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/types/widget.ts`
- Modify: `frontend/src/stores/widgetStore.ts`
- Modify: `frontend/src/components/widget/TabNavBar.tsx`
- Modify: `frontend/src/components/widget/SubTabBar.tsx`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/features/resources/resourceShare.ts`
- Create: `frontend/src/features/resources/ResourceCenterPage.tsx`
- Create: `frontend/src/features/resources/ResourceViewTabs.tsx`
- Create: `frontend/src/features/resources/__tests__/navigation.test.tsx`
- Create: `frontend/src/features/resources/__tests__/resourceShare.test.ts`
- Create: `frontend/src/features/resources/__tests__/ResourceCenterPage.test.tsx`

- [ ] **Step 1: Write persisted-tab migration tests**

Map old `material-library` and `material-cloud-sync` to `material-resources`; old `lut-library` and `lut-cloud-sync` to `lut-resources`. Keep `material-recipe`, `lut-manager`, `lut-details`, `lut-compare`, calibration, extraction, and conversion tools unchanged. Unknown persisted values fall back safely.

- [ ] **Step 2: Add icon dependency through pnpm**

From `frontend/`:

```bash
pnpm add lucide-react
pnpm add -D @playwright/test @vitejs/plugin-basic-ssl
pnpm exec playwright install chromium
```

Expected: `package.json` and `pnpm-lock.yaml` update with one runtime and two development dependencies. Browser binaries stay in Playwright's external cache and are not committed. `@vitejs/plugin-basic-ssl` is used only by the disposable HTTPS E2E server; normal development remains HTTP. Use `Library`, `Cloud`, `HardDrive`, `Search`, `Filter`, `ArrowDownUp`, `RefreshCw`, `Download`, `Upload`, `RotateCcw`, `Trash2`, `Copy`, `Wrench`, `ChevronRight`, `X`, and `MoreHorizontal` where semantically appropriate; do not draw replacement SVGs.

In the same change, add the exact runtime package string `"lucide-react"` to `frontend/vite.config.ts` `optimizeDeps.include` in lexical order. `@playwright/test` is test-only and must not enter the browser prebundle. The cold-cache browser harness in Task 10 deletes/redirects the Vite cache and must fail on dependency-scan 504, stale prebundle imports, or a blank first load.

- [ ] **Step 3: Build the resource page shell**

Use a full-width work surface with constrained inner content, a compact page header, segmented Cloud/My view control, toolbar, list, and unframed detail region. No hero, marketing copy, nested cards, decorative gradients/orbs, or oversized headings. Repeated items may use one border/surface with radius at most 8px.

Set stable toolbar/list/detail dimensions with CSS grid/minmax. Desktop at `>=1024px` uses list plus a `minmax(320px, 420px)` detail column. Mobile uses one column and details as a fixed full-screen layer with safe-area padding.

- [ ] **Step 4: Implement a safe public Share resource destination**

`resourceShare.ts` reads `VITE_RESOURCE_SHARE_URL` at build time and defaults to `https://github.com/lumina-layer-studio/Lumina-materials/blob/master/CONTRIBUTING.md`. Accept only absolute HTTPS URLs with no user info or fragment and reject casefolded/percent-decoded token-like query keys containing credential terms such as `token`, `key`, `secret`, `signature`, `auth`, and `code`; duplicate/empty keys are rejected as well. The command opens a new tab with `noopener,noreferrer`; malformed configuration disables the action and reports one safe configuration error without echoing the URL. Unit tests cover default, approved public form, HTTP, relative, user-info, fragment, duplicate/encoded credential-like query, and window opener isolation.

- [ ] **Step 5: Implement temporary display fallback**

`VITE_RESOURCE_CENTER_V2_UI=1` controls whether App renders new pages or old panels; absent, `0`, or any other value is disabled. Both paths consume v2-backed Studio APIs after backend cutover; disabling the flag never writes v1 or changes marker. Remove the fallback in a later deprecation PR only after telemetry/acceptance.

- [ ] **Step 6: Run and commit**

```bash
python scripts/run_vitest.py run src/features/resources/__tests__/navigation.test.tsx src/features/resources/__tests__/resourceShare.test.ts src/features/resources/__tests__/ResourceCenterPage.test.tsx
git add frontend/package.json frontend/pnpm-lock.yaml frontend/vite.config.ts frontend/src/types/widget.ts frontend/src/stores/widgetStore.ts frontend/src/components/widget/TabNavBar.tsx frontend/src/components/widget/SubTabBar.tsx frontend/src/App.tsx frontend/src/features/resources/resourceShare.ts frontend/src/features/resources/ResourceCenterPage.tsx frontend/src/features/resources/ResourceViewTabs.tsx frontend/src/features/resources/__tests__/navigation.test.tsx frontend/src/features/resources/__tests__/resourceShare.test.ts frontend/src/features/resources/__tests__/ResourceCenterPage.test.tsx
git commit -m "feat(resources): add independent resource center pages"
```

Run `git diff --check`, adapter/property/navigation tests, cold dependency-prebundle smoke, and secret/path scans; open the `resource-center-v2-shell` PR with the flag disabled by default. Exact-head review must prove both domain adapters are adopted by the shell, old persisted tabs migrate deterministically, and no browser mutation can address a Registry URL/path. Merge before Task 4.

## Task 4: Cloud Library Discovery

**Files:**
- Create: `frontend/src/features/resources/ResourceToolbar.tsx`
- Create: `frontend/src/features/resources/ResourceList.tsx`
- Create: `frontend/src/features/resources/ResourceListItem.tsx`
- Create: `frontend/src/features/resources/resourceStatus.ts`
- Create: `frontend/src/features/resources/__tests__/CloudLibrary.test.tsx`

- [ ] **Step 1: Write cloud browsing tests**

Cover initial load, 300 ms debounced search, publisher/brand/domain filters, updated/download sort, load-more cursor, exact duplicate revision handling, empty results, no cache offline, cached offline with fetched timestamp, Registry unreachable, contract unsupported v1 read fallback, update badge, official/community badges, and keyboard item selection.

- [ ] **Step 2: Build dense toolbar controls**

Use search input with `Search`, filter menus with `Filter`, sort menu with `ArrowDownUp`, icon refresh with tooltip, and `Share resource` as a clear external command. Filters are menus/checkboxes, sort is a menu, Cloud/My is segmented, and binary UI preferences use switches/checkboxes. Do not place instructional paragraphs in the UI.

- [ ] **Step 3: Build list items for scanning**

Desktop rows align preview, title/brand, publisher, compatibility, updated/download count, local state, and primary action. Mobile items wrap metadata without horizontal clipping. Official/community, update, damaged, offline, and in-use indicators are short badges; no channel/visibility badge is shown.

Titles use compact panel typography, zero letter spacing, and line clamp only where the complete title remains available in details/accessible label. Action icon buttons have stable `36x36` or `40x40` targets and tooltips.

- [ ] **Step 4: Enforce backend state semantics**

`installed` requires backend managed state; local exact hash is `local_equivalent`. A local equivalent may show only `adopt_local_equivalent` among ownership-changing actions when the backend allows it; it never shows Uninstall or Create local copy. `create_local_copy` is strictly managed -> new local and may appear only on a managed installed/update-available row whose backend `allowed_actions` includes it. Damaged shows Repair. `not_installed` shows Details/Install. Update available keeps the current resource usable and offers Update. Tests reject any local/local-equivalent Create-local-copy control and prove adopt keeps the source local row while adding/refreshing the managed result row.

- [ ] **Step 5: Run and commit**

```bash
python scripts/run_vitest.py run src/features/resources/__tests__/CloudLibrary.test.tsx
git add frontend/src/features/resources/ResourceToolbar.tsx frontend/src/features/resources/ResourceList.tsx frontend/src/features/resources/ResourceListItem.tsx frontend/src/features/resources/resourceStatus.ts frontend/src/features/resources/__tests__/CloudLibrary.test.tsx
git commit -m "feat(resources): build searchable cloud discovery"
```

## Task 5: My Resources Inventory And Local Semantics

**Files:**
- Modify: `frontend/src/features/resources/ResourceToolbar.tsx`
- Modify: `frontend/src/features/resources/ResourceList.tsx`
- Modify: `frontend/src/features/resources/ResourceListItem.tsx`
- Create: `frontend/src/features/resources/__tests__/MyResources.test.tsx`

- [ ] **Step 1: Write local inventory tests**

Cover managed installed/update/damaged, local import, local copy with source trace, unresolved legacy, local equivalent, changed local file/hash, active/previous, pending-GC invisibility, bounded-history busy, same display name/different ID, same resource ID/different Registry key, exact same hash/different ID, and both domain path labels. A history-busy item retains read/use actions, disables update/rollback with a concise in-use reason, and becomes actionable after lease release/GC refresh; a raced `409 resource_history_busy` preserves the row and performs no optimistic revision change. For same-revision envelope/publisher changes, assert current authorized metadata replaces the visible badge without setting update; offline/unreachable falls back to a clearly last-verified installed snapshot; live distribution-unavailable state does not claim the stale official/community badge is current. Test reload stability of local IDs and no network dependency for first render.

- [ ] **Step 2: Render local-first state**

My Resources loads from the backend local index immediately and causes zero Registry requests. Show logical relative display path only, never absolute path. Local copy identifies source title/revision without implying update merge. Legacy unresolved remains usable and offers resolution only when exact candidates are available. Initial managed rows use the installed snapshot with stale/last-verified treatment and unknown distribution availability. On details selection or explicit refresh, call the domain distribution-detail route once for that exact installed revision; render current Registry publisher metadata only when that response says `displayProvenance=current_registry`. Timeout/offline keeps the snapshot treatment, and a live unavailable result marks distribution unavailable without silently presenting a stale `Lumina official` claim as current. Closing/reopening the list does not trigger an N+1 refresh.

- [ ] **Step 3: Add update-all summary without hiding failures**

Toolbar shows update count and Update all only when capability/action allows. Operation dialog groups succeeded/skipped/failed and keeps each failed title/error/action. One item failure does not roll back success or collapse to a generic toast. Refresh once after convergence.

- [ ] **Step 4: Run and commit**

```bash
python scripts/run_vitest.py run src/features/resources/__tests__/MyResources.test.tsx
git add frontend/src/features/resources/ResourceToolbar.tsx frontend/src/features/resources/ResourceList.tsx frontend/src/features/resources/ResourceListItem.tsx frontend/src/features/resources/__tests__/MyResources.test.tsx
git commit -m "feat(resources): manage local resource inventory"
```

## Task 6: Details, Preview, And Lifecycle Actions

**Files:**
- Create: `frontend/src/features/resources/ResourceDetails.tsx`
- Create: `frontend/src/features/resources/ResourceActions.tsx`
- Create: `frontend/src/features/resources/ResourceOperationDialog.tsx`
- Create: `frontend/src/features/resources/MaterialResourcePreview.tsx`
- Create: `frontend/src/features/resources/LutResourcePreview.tsx`
- Create: `frontend/src/features/resources/__tests__/ResourceDetails.test.tsx`
- Create: `frontend/src/features/resources/__tests__/ResourceActions.test.tsx`

- [ ] **Step 1: Write action matrix tests**

For every state/capability combination, assert exact visible action and confirmation copy. Cover install, update, local/remote rollback, unavailable withdrawn history, uninstall, repair, adopt by copy, create local copy, detach management, local delete, managed read-only edit, in-use block, capability loss while dialog open, operation conflict, and retry. Local delete opens only after a fresh detail response supplies a strong ETag, keeps it in dialog-local memory, sends it only as `If-Match`, and clears it on close/success/error. Missing 428 or changed 412 closes/reloads the destructive confirmation and requires the user to confirm current facts again; it never auto-retries deletion.

- [ ] **Step 2: Build details before install**

Details show actual resource title/preview, publisher, summary, brand/tags, compatibility, current/previous/history revisions, update time, downloads, local state/path, source trace, and allowed actions. A collapsed technical section may show resource ID, revision ID, and server-projected content/package hash prefixes. Do not expose a full package hash, package/Registry URL, envelope, token, filesystem absolute path, channel, or visibility as primary user metadata.

Desktop details is an unframed side pane separated by a divider. Mobile details is full-screen with sticky compact action bar and an icon Close button. Focus moves into details and returns to the selected item on close.

- [ ] **Step 3: Use domain previews that reveal content**

Material preview uses calibrated estimated color/swatches and material compatibility facts. LUT preview uses a bounded sampled palette/color grid from controlled backend summary; it does not download or parse the package in the browser. A Details tool link may open the existing full LUT inspector. Do not add a new Three.js scene here.

- [ ] **Step 4: Implement precise confirmations**

Install/update state exact revision and expected effect. Rollback identifies target revision. Uninstall states only managed source is removed and local copies remain. Delete identifies a local import/copy and the server-projected exact relative directory; unknown sidecars disable delete with safe guidance. Detach states files remain but cloud management/update is removed. In-use displays operation labels and no destructive confirm button. No confirmation text, Zustand action, or browser storage contains the ETag, absolute path, or file hash.

- [ ] **Step 5: Run and commit**

```bash
python scripts/run_vitest.py run src/features/resources/__tests__/ResourceDetails.test.tsx src/features/resources/__tests__/ResourceActions.test.tsx
git add frontend/src/features/resources/ResourceDetails.tsx frontend/src/features/resources/ResourceActions.tsx frontend/src/features/resources/ResourceOperationDialog.tsx frontend/src/features/resources/MaterialResourcePreview.tsx frontend/src/features/resources/LutResourcePreview.tsx frontend/src/features/resources/__tests__/ResourceDetails.test.tsx frontend/src/features/resources/__tests__/ResourceActions.test.tsx
git commit -m "feat(resources): add previews and lifecycle actions"
```

## Task 7: Bilingual Copy, Theme, Responsive, And Accessibility

**Files:**
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `frontend/src/features/resources/ResourceCenterPage.tsx`
- Modify: `frontend/src/features/resources/ResourceViewTabs.tsx`
- Modify: `frontend/src/features/resources/ResourceToolbar.tsx`
- Modify: `frontend/src/features/resources/ResourceList.tsx`
- Modify: `frontend/src/features/resources/ResourceListItem.tsx`
- Modify: `frontend/src/features/resources/ResourceDetails.tsx`
- Modify: `frontend/src/features/resources/ResourceActions.tsx`
- Modify: `frontend/src/features/resources/ResourceOperationDialog.tsx`
- Modify: `frontend/src/features/resources/MaterialResourcePreview.tsx`
- Modify: `frontend/src/features/resources/LutResourcePreview.tsx`
- Create: `frontend/src/features/resources/__tests__/accessibility.test.tsx`
- Create: `frontend/src/features/resources/__tests__/responsive-contract.test.tsx`

- [ ] **Step 1: Add complete bilingual keys**

Add Chinese/English keys for navigation, Cloud/My, search/filter/sort, source badges, all states/actions, details/history, offline/empty/error, update-all results, confirmations, in-use, and stable backend error guidance. Test key parity. Use `分享资源 / Share resource`; avoid `投稿 / Submit`.

- [ ] **Step 2: Use design tokens and restrained palette**

No raw `#fff`, `bg-white`, `text-black`, one-hue page, gradient, glow, or nested cards. Use existing surface/text/border/action/semantic tokens in light and dark themes. Keep cards/rows at radius 8px or less and page bands unframed.

- [ ] **Step 3: Implement keyboard and screen-reader behavior**

Search/filter/sort labels are explicit. Segmented view has tab semantics. List supports normal tab order and Enter/Space details activation without trapping arrows unexpectedly. Icon buttons have accessible names and hover/focus tooltips. Dialog/full-screen details trap focus, close on Escape when safe, announce operation status, and restore focus.

- [ ] **Step 4: Lock responsive dimensions**

Test 320, 375, 390, 768, 1024, 1440, and 1920 CSS widths. Long Chinese/English brand/title/error/paths wrap or clamp inside parents, no fixed viewport font scaling, no negative letter spacing, no control shift on badges/loading, no overlap, and no horizontal page scroll.

- [ ] **Step 5: Run and commit**

```bash
python scripts/run_vitest.py run src/features/resources/__tests__/accessibility.test.tsx src/features/resources/__tests__/responsive-contract.test.tsx
git add frontend/src/i18n/translations.ts frontend/src/features/resources/ResourceCenterPage.tsx frontend/src/features/resources/ResourceViewTabs.tsx frontend/src/features/resources/ResourceToolbar.tsx frontend/src/features/resources/ResourceList.tsx frontend/src/features/resources/ResourceListItem.tsx frontend/src/features/resources/ResourceDetails.tsx frontend/src/features/resources/ResourceActions.tsx frontend/src/features/resources/ResourceOperationDialog.tsx frontend/src/features/resources/MaterialResourcePreview.tsx frontend/src/features/resources/LutResourcePreview.tsx frontend/src/features/resources/__tests__/accessibility.test.tsx frontend/src/features/resources/__tests__/responsive-contract.test.tsx
git commit -m "feat(resources): polish responsive bilingual resource UI"
```

## Task 8: Replace Old Panel Assumptions And Preserve Tool Workflows

**Files:**
- Modify: `frontend/src/components/MaterialCloudSyncPanel.tsx`
- Modify: `frontend/src/components/MaterialLibraryPanel.tsx`
- Modify: `frontend/src/components/LutCloudSyncPanel.tsx`
- Modify: `frontend/src/components/LutLibraryPanel.tsx`
- Modify: `frontend/src/stores/converter/store.ts`
- Modify: `frontend/src/components/sections/LegacyLutSelector.tsx`
- Modify: `frontend/src/components/ui/MaterialPickerDialog.tsx`
- Modify: `frontend/src/components/sections/MaterialColorPicker.tsx`
- Modify: `frontend/src/__tests__/material-cloud-sync-panel.test.tsx`
- Modify: `frontend/src/__tests__/material-library-panel.test.tsx`
- Modify: `frontend/src/__tests__/lut-cloud-sync-panel.test.tsx`
- Modify: `frontend/src/__tests__/lut-library-panel.test.tsx`
- Modify: `frontend/src/__tests__/material-picker.test.tsx`
- Modify: `frontend/src/__tests__/material-color-picker.test.tsx`
- Do not delete old panels in this PR

- [ ] **Step 1: Replace wrong installed-state assertions**

Current material cloud tests treat same directory/hash across IDs as installed. Change them to expect `local_equivalent`; only backend managed identity is installed. Add equivalent LUT tests and ensure official badges read publisher kind rather than channel/path.

- [ ] **Step 2: Preserve converter/tool selection by exact refs**

When users choose a managed resource from new lists/pickers, converter state stores display name/path plus exact ref in the same order. Local resources store null exact ref. Material backing remains an index into selected materials. Existing LUT manager/details/compare and material recipe tools remain separate destinations and receive stable aliases/refs.

- [ ] **Step 3: Test old display fallback against v2 store**

With feature flag off and both domains committed, old panels list/install/rollback through legacy projections but cannot write v1. Managed edits/deletes return read-only guidance. With one domain v1, only that old domain panel remains available for mutation.

- [ ] **Step 4: Run old and new target suites**

```bash
python scripts/run_vitest.py run \
  src/__tests__/material-cloud-sync-panel.test.tsx \
  src/__tests__/material-library-panel.test.tsx \
  src/__tests__/lut-cloud-sync-panel.test.tsx \
  src/__tests__/lut-library-panel.test.tsx \
  src/__tests__/material-sync-api.test.ts \
  src/__tests__/lut-api.test.ts \
  src/features/resources/__tests__
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MaterialCloudSyncPanel.tsx frontend/src/components/MaterialLibraryPanel.tsx frontend/src/components/LutCloudSyncPanel.tsx frontend/src/components/LutLibraryPanel.tsx frontend/src/stores/converter/store.ts frontend/src/components/sections/LegacyLutSelector.tsx frontend/src/components/ui/MaterialPickerDialog.tsx frontend/src/components/sections/MaterialColorPicker.tsx frontend/src/__tests__/material-cloud-sync-panel.test.tsx frontend/src/__tests__/material-library-panel.test.tsx frontend/src/__tests__/lut-cloud-sync-panel.test.tsx frontend/src/__tests__/lut-library-panel.test.tsx frontend/src/__tests__/material-picker.test.tsx frontend/src/__tests__/material-color-picker.test.tsx
git commit -m "test(resources): align legacy panels with v2 semantics"
```

Run all Task 4-8 component tests, production build, lint, and desktop/mobile light/dark screenshot inspection against deterministic mocks; open the `resource-center-v2-ui` PR while the production flag remains disabled. Exact-head review must cover action direction, text fit/overlap, a11y, independent material/LUT behavior, and the v2-backed legacy fallback. Merge before Task 9.

## Task 9: Build, Lint, And Full Automated Gate

**Files:**
- Modify only defects discovered by these gates

- [ ] **Step 1: Run resource frontend suite**

```bash
python scripts/run_vitest.py run src/features/resources/__tests__ src/__tests__/recipe-roundtrip.property.test.ts src/utils/__tests__/bugReportContext.test.ts
```

Expected: all pass through the project wrapper.

- [ ] **Step 2: Run TypeScript build and lint**

From `frontend/`:

```bash
pnpm build
pnpm lint
```

Expected: both exit `0`; no untranslated literal, unsafe `any`, hook dependency, or raw-color error is introduced.

- [ ] **Step 3: Run backend contract and smoke gates**

```bash
python -m pytest tests/test_resource_center_api_unit.py tests/test_resource_legacy_adapters_unit.py tests/test_resource_workflow_resolution_unit.py tests/test_resource_session_leases_unit.py -q
python scripts/run_smoke_tests.py
python scripts/log_quality_check.py --mode fast
```

Expected: all exit `0`.

- [ ] **Step 4: Scan UI source for design regressions**

```bash
rg -n '(#[0-9a-fA-F]{3,8}|bg-white|text-black|rounded-(2xl|3xl|full)|tracking-tight|tracking-\[-|gradient|blur-[23]xl)' frontend/src/features/resources
```

Review every match. Semantic `rounded-full` is allowed only for circular icon controls/badges, never text command pills where a standard button/icon works. Raw colors/negative tracking/decorative gradients are removed.

## Task 10: Real Staging Browser Acceptance

**Files:**
- Modify: `frontend/devServerConfig.ts`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/__tests__/dev-server-config.test.ts`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/resource-center-v2.spec.ts`
- Create: `scripts/run_resource_center_e2e.py`
- Create: `tests/test_resource_center_e2e_harness_unit.py`
- Create: `docs/resource-center-v2-user-acceptance.md`
- Store screenshots/video/network logs outside repositories

- [ ] **Step 1: Prepare isolated staging data**

Use a dedicated Registry data directory and copied Studio material/LUT roots. Publish:

- community material revision A and B;
- community LUT revision A and B;
- one explicit Lumina publisher resource approved by authorized test configuration;
- same-name/different-ID resources;
- local exact equivalent;
- withdrawn historical revision;
- package binding/hash failure fixture.

Record test IDs/commits in an external evidence manifest. Never use production/user data for destructive actions.

- [ ] **Step 2: Implement a disposable cross-repository orchestrator**

Write unit tests first for exact clean commit verification, refusal of the primary Studio/material/LUT roots, symlink/reparse destinations, evidence inside any checkout, loopback bind host, occupied/fixed port reuse, child startup failure, timeout, SIGINT, crash between every phase, secret redaction, and an outside sentinel that must remain byte-identical.

`scripts/run_resource_center_e2e.py` requires explicit `--registry-checkout`, `--materials-checkout`, `--evidence-dir`, and non-loopback `--bind-host`. It verifies exact clean commits, creates a UUID temporary run root outside all checkouts, and uses `git archive` plus a path-safe tar extractor to materialize exact Studio/Registry/Materials HEADs there; it never runs a service against a source checkout. After checking free space and `frontend/pnpm-lock.yaml`/package-manager identity, copy the prepared frontend `node_modules` tree into the archived frontend without following links outside that dependency tree. `LUMINA_VITE_CACHE_DIR`, build output, test results, browser profile, logs, output, feedback, Registry data, and Studio material/LUT roots all point inside the run/evidence roots. Set `PYTHONDONTWRITEBYTECODE=1` for Python children. Add `resolveViteCacheDir()`, `resolveResourceE2EHttpsEnabled()`, and `resolveExternalResourceCenterUrl()` to `frontend/devServerConfig.ts`; consume the first two in `vite.config.ts` and the last in `frontend/playwright.config.ts`. Test cache defaults/absolute paths, exact-`1` HTTPS override, and every external-host boundary in `frontend/src/__tests__/dev-server-config.test.ts`. The config imports `@vitejs/plugin-basic-ssl` as a development plugin but never adds it to `optimizeDeps.include`; only browser runtime package `lucide-react` enters that list.

Copy only fixture/source packages into disposable service data and write a safe fixture manifest with per-Playwright-project unique resource IDs/logical paths. Generate one non-secret run-scoped Registry key matching the production contract and pass it as both material/LUT key because both domains use this same disposable authority. Generate maintainer/approver/read/cursor secrets in memory with `secrets.token_urlsafe`, pass them only through child environments, and redact environment/headers/argv/output; no token enters evidence or disk. One phase restarts Studio with a different safe Registry key against the same URL and proves the old namespace is not reused, then restores the original key and revalidates online.

For each Playwright project, start Registry and the Studio backend on loopback, then start Vite on the supplied LAN/staging interface with OS-assigned free ports. Under `LUMINA_RESOURCE_E2E_HTTPS=1`, conditionally enable `@vitejs/plugin-basic-ssl`; Playwright uses an isolated context with `ignoreHTTPSErrors=true` and host-resolver rules that map UUID-named `lumina-resource.test` and `attacker.test` hosts to the disposable Vite server. Normal Vite startup never enables the plugin. Configure `LUMINA_RESOURCE_MUTATION_REMOTE_ENABLED=1`, the exact generated HTTPS Studio Origin, and the exact loopback backend Host seen through Vite's proxy; never use `LUMINA_ALLOW_PUBLIC_GRAY_API` as the write bypass. Bind the backend only to loopback so it is not directly reachable from the LAN. This disposable proxy verifies the application's Origin/Host policy; Task 11 separately rehearses real reverse-proxy authentication and direct-backend isolation.

Seed revision A, run install phase, restart Studio and run persistence phase, publish/approve B, run update/in-use/rollback/copy/uninstall/delete phases, damage only the disposable managed payload, run repair/sidecar/detach phases, stop Registry for cached/no-cache offline phases, restart it, and run final convergence. Invoke the Playwright spec separately with `E2E_SCENARIO` for each phase; do not add a product test-control endpoint. Verify the run-root sentinel and source checkouts after every destructive phase.

Before the accepted lifecycle run, issue real browser requests from a second non-allowlisted Origin and from the allowlisted Origin with wrong Host, HTTP scheme, missing Origin, `Origin: null`, and `Sec-Fetch-Site: cross-site`. Every classified persistent resource POST/PATCH/PUT/DELETE mutation must return the typed 403 before its ASGI receive callable, Registry request, or file/index change, while GET and explicitly inventoried read-only POST routes remain subject only to their read policy. Capture network evidence without recording the private staging hostname or proxy credential.

Own child process groups and close them in `finally`; timeout escalates TERM then KILL only to owned PIDs. At the end inspect process command lines and ports for this exact run ID. Retain failed run data for diagnosis only under the external evidence root, but always stop processes and redact logs.

- [ ] **Step 3: Configure a repeatable external-origin browser suite**

`frontend/playwright.config.ts` requires absolute `STUDIO_EXTERNAL_URL` and `EVIDENCE_DIR` and obtains the URL only through `resolveExternalResourceCenterUrl()`. That helper uses the platform URL parser and hostname facts rather than substring-matching the complete URL. Reject `localhost` (including a trailing dot and `.localhost` names), every address in `127.0.0.0/8`, IPv6 `::1`, IPv4-mapped loopback, URL user info, non-HTTP(S), and any evidence path inside the Studio checkout. `frontend/src/__tests__/dev-server-config.test.ts` covers `127.0.0.0`, `127.0.0.1`, `127.0.0.2`, `127.1.2.3`, `127.255.255.255`, the adjacent accepted `126.255.255.255`/`128.0.0.0`, bracketed `::1`, mapped loopback, `localhost.`, and a `.localhost` name so no one-literal shell guard can replace the parser. Define Chromium projects `desktop-light`/`desktop-dark` at `1440x900` and `mobile-light`/`mobile-dark` at `390x844`, one worker, no retries locally, trace/video on first failure, and screenshot output under `$EVIDENCE_DIR/{projectName}`. It does not start a local web server.

`resource-center-v2.spec.ts` uses accessible roles/names first and stable `data-testid` only for repeated resource identities. It records console errors, failed requests, response bodies/headers for Studio API calls, and browser storage keys. Fail the test if any browser-visible value contains `Authorization`, bearer text, token-like query keys, Registry package URL/envelope, a POSIX/macOS or Windows user-home absolute path, or an absolute managed payload path.

- [ ] **Step 4: Start services and use a non-localhost origin**

The harness first performs a production build from a cold redirected Vite cache with its copied `node_modules/.bin/vite build --outDir "$RUN_FRONTEND_DIST"`, `VITE_RESOURCE_CENTER_V2_UI=1`, and a public Share resource URL. It then launches archived Registry and Studio backend on loopback, and launches the archived Vite dev server as the disposable external HTTPS frontend/proxy with `LUMINA_RESOURCE_E2E_HTTPS=1`, the supplied non-loopback bind host, and a clean cache directory. `vite.config.ts` conditionally adds `basicSsl()` only for that exact env value and proxies `/api` to the loopback Studio port. Reserve dynamic ports with bounded launch/retry and health-check exact process IDs; never kill an unrelated listener. Fail if the cold first page returns a dependency 504, imports a stale optimize-deps hash, serves a blank root, or contacts the backend outside the Vite proxy.

For a predeployed staging run, require staging HTTPS behind its authenticated proxy. Set `STUDIO_EXTERNAL_URL` to the resulting complete origin and assert it is not loopback before opening it:

```bash
: "${STUDIO_EXTERNAL_URL:?set the staging or LAN Studio URL}"
python - "$STUDIO_EXTERNAL_URL" <<'PY'
import ipaddress
import sys
from urllib.parse import urlsplit

parsed = urlsplit(sys.argv[1])
host = (parsed.hostname or "").rstrip(".").casefold()
if (
    parsed.scheme != "https"
    or not host
    or parsed.username is not None
    or parsed.password is not None
    or parsed.path not in ("", "/")
    or parsed.query
    or parsed.fragment
):
    raise SystemExit("STUDIO_EXTERNAL_URL must be one complete HTTPS origin")

try:
    address = ipaddress.ip_address(host)
except ValueError:
    address = None

mapped = getattr(address, "ipv4_mapped", None)
if (
    host == "localhost"
    or host.endswith(".localhost")
    or host.startswith("127.")
    or (address is not None and address.is_loopback)
    or (mapped is not None and mapped.is_loopback)
):
    raise SystemExit("STUDIO_EXTERNAL_URL must not use a loopback host")
PY
```

Open `$STUDIO_EXTERNAL_URL`. Confirm browser network requests call Studio-relative APIs and Studio alone calls Registry.

- [ ] **Step 5: Run material journey as a user**

Cloud browse/search/filter -> open details -> install A -> restart Studio -> verify installed -> publish/see B update -> update -> start workflow using B -> attempt uninstall and observe in-use block -> close workflow -> rollback to A -> create local copy -> uninstall managed source -> confirm local copy remains -> delete local copy with confirmation.

- [ ] **Step 6: Run LUT journey as a user**

Browse actual palette preview -> install A -> select in converter -> install/select second LUT -> preserve chosen multi-LUT order -> preview/generate -> update first to B while session holds A -> confirm session result remains A -> close -> rollback -> exact historical reopen -> uninstall after release.

- [ ] **Step 7: Run damage/offline/failure journey**

In the disposable root only, remove/modify one managed file -> status damaged -> repair. Add unknown sidecar -> uninstall fails closed and files remain -> detach management preserves bytes. Disconnect Registry -> My Resources works, Cloud shows cached timestamp/offline, install/update disabled; remove cache -> show unavailable rather than zero results. Trigger partial update-all and verify failed item/reason remains.

- [ ] **Step 8: Execute the automated journeys and capture evidence**

From the Studio root, run the harness unit gate and all fixed Playwright projects against disposable three-repository services:

```bash
: "${REGISTRY_CHECKOUT:?set the exact Registry checkout}"
: "${MATERIALS_CHECKOUT:?set the exact Materials checkout}"
: "${BIND_HOST:?set a non-loopback LAN interface address}"
: "${EVIDENCE_DIR:?set an evidence directory outside the repository}"
python -m pytest tests/test_resource_center_e2e_harness_unit.py -q
python scripts/run_vitest.py run src/__tests__/dev-server-config.test.ts
python scripts/run_resource_center_e2e.py \
  --registry-checkout "$REGISTRY_CHECKOUT" \
  --materials-checkout "$MATERIALS_CHECKOUT" \
  --bind-host "$BIND_HOST" \
  --evidence-dir "$EVIDENCE_DIR" \
  --projects desktop-light,desktop-dark,mobile-light,mobile-dark
```

The harness invokes `pnpm exec playwright test e2e/resource-center-v2.spec.ts` from `frontend/` for each phase/project. The spec executes the material, LUT, damage/offline, in-use, restart-persistence, and partial-failure journeys above through visible controls and asserts backend convergence after every mutation. It captures these states in each applicable project:

```text
1440x900 desktop light
1440x900 desktop dark
390x844 mobile light
390x844 mobile dark
```

Capture Cloud, My Resources, desktop details, mobile full-screen details, update-all partial failure, in-use block, and offline state directly under `EVIDENCE_DIR`; do not create or update in-repository snapshot baselines during acceptance. Use explicit bounding-box and computed-layout checks to reject overlap, clipping, horizontal page scroll, zero-size controls, and details outside the viewport. LUT preview tests sample captured pixels and reject an all-background result. Retain the human-inspected PNGs, trace/video on failure, and sanitized network/console manifest outside repositories.

- [ ] **Step 9: Run interaction and accessibility checks**

Use keyboard only for navigation, view switch, search/filter/sort, details, install confirmation, dialog close, and focus restoration. Check visible focus and accessible names. For LUT preview, assert sampled cells contain non-background pixels; no canvas should be blank if an existing canvas-based inspector is opened.

- [ ] **Step 10: Stop every process**

Run `python start_all.py --kill` for Studio leftovers, stop Registry and any staging HTTP proxy, close Playwright contexts, and inspect process command lines for `api_server.py`, `start_all.py`, `vite`, `vitest`, `esbuild`, Registry uvicorn, and checkout paths. Leave no server/watch process running.

Document exact commands, commits, outcomes, screenshot filenames, console/network result, and cleanup in `docs/resource-center-v2-user-acceptance.md` using relative evidence labels rather than local absolute paths.

After process cleanup and evidence redaction succeed, commit the reusable harness/config plus the sanitized acceptance record; screenshots, traces, browser profiles, runtime roots, and private host facts stay outside the repository:

```bash
git add frontend/devServerConfig.ts frontend/vite.config.ts frontend/src/__tests__/dev-server-config.test.ts frontend/playwright.config.ts frontend/e2e/resource-center-v2.spec.ts scripts/run_resource_center_e2e.py tests/test_resource_center_e2e_harness_unit.py docs/resource-center-v2-user-acceptance.md
git commit -m "test(resources): add isolated browser acceptance"
```

## Task 11: Announcement, Rollout Flag, And Final PR Evidence

**Files:**
- Modify: `frontend/src/data/announcements.ts`
- Modify: `docs/resource-center-v2-user-acceptance.md`
- Create: `docs/resource-center-v2-rollout.md`

- [ ] **Step 1: Add a Beijing-date bilingual announcement**

Follow `docs/announcement-maintenance.md`. Add to today's entry or prepend today's date. Use plain user language under suitable categories. Cover cloud browsing, separate material/LUT management, update/rollback, and editable local copies; do not mention store/schema/endpoint/PR/commit/adapter.

- [ ] **Step 2: Verify announcement history semantics**

```bash
python scripts/run_vitest.py run src/__tests__/useAnnouncement.test.ts src/__tests__/announcement-dialog.test.tsx
```

From `frontend/`:

```bash
pnpm exec tsc --noEmit
```

Expected: all pass.

- [ ] **Step 3: Define rollout and rollback**

Enable new UI first in staging, then small production cohort, then default. Observe catalog errors, install/update failures by stable code, migration/cutover state, damaged rate, repair use, lease fences, and frontend exceptions. UI rollback disables only the display flag; committed backend domains remain v2 writers and old panels consume v2 projections.

The staging checklist requires an authenticated HTTPS reverse proxy, explicit stable non-secret material/LUT Registry keys for every v2-enabled endpoint, exact resource-mutation Origin/Host allowlists, stripped client-supplied forwarding/auth-assertion headers, and a firewall probe proving the backend port cannot be reached directly. Run one accepted resource write through the proxy and one rejected cross-site write; `LUMINA_ALLOW_PUBLIC_GRAY_API` alone must not enable resource writes. Checked-in evidence contains no proxy credential, private hostname, certificate key, or full private Origin.

Write `docs/resource-center-v2-rollout.md` with the exact flag values, capability prerequisites, Registry/Materials/Studio commit manifest, preflight queries, cohort progression criteria, stop thresholds, UI-only rollback, per-domain mutation closure, Registry v2 projection rollback, backup/repair ownership, and post-rollback verification. Never instruct operators to reopen a committed v1 writer or delete a live SQLite/index store.

- [ ] **Step 4: Final diff and secret/local-path scan**

```bash
git diff --check origin/dev-refactor...HEAD
git status --short
POSIX_HOME_PATTERN="$(printf '/%s/' Users)"
WINDOWS_HOME_PATTERN="$(printf '[A-Za-z]:\\\\%s\\\\' Users)"
SENSITIVE_PATTERN='Bearer[[:space:]]+[A-Za-z0-9._~+/-]+|BEGIN[[:space:]]+(RSA[[:space:]]+|EC[[:space:]]+|OPENSSH[[:space:]]+)?PRIVATE[[:space:]]+KEY|LUMINA_[A-Z0-9_]*(TOKEN|SECRET|KEY)[A-Z0-9_]*[[:space:]]*=[[:space:]]*[^$[:space:]]'
rg -n --hidden --glob '!\.git/**' --glob '!tests/fixtures/**' "(${SENSITIVE_PATTERN}|${POSIX_HOME_PATTERN}|${WINDOWS_HOME_PATTERN})"
```

Expected: only intended files, no private data, no runtime screenshots/browser profiles inside the repo.

- [ ] **Step 5: Commit and open exact-head review**

```bash
git add frontend/src/data/announcements.ts docs/resource-center-v2-user-acceptance.md docs/resource-center-v2-rollout.md
git commit -m "feat(resources): ship material and LUT resource centers"
```

Open this final delta as `resource-center-v2-acceptance`. Its PR body includes exact three-repository/deployed commits, capability combinations tested, automated commands/counts, real-browser URL class (LAN/staging without private hostname credentials), lifecycle journeys, screenshots, console/network result, accessibility result, process cleanup, soak evidence, rollback evidence, and residual rollout risk. Request exact-head review after all artifacts refer to that same head; do not merge based on evidence captured from the prior UI PR.

## Frontend And Release Merge Gate

Do not merge unless:

- material/LUT remain independent destinations/adapters/filters/previews/capabilities;
- Cloud/My views and all state/action semantics match backend facts;
- official/community badge uses only publisher kind;
- local equivalent is never called installed and never offers uninstall;
- install details appear before action; desktop/mobile details are usable;
- managed read-only/local copy/uninstall/delete wording is unambiguous;
- update-all preserves partial failures and one convergence refresh;
- ordered multi-LUT/material/backing exact refs survive selection and workflows;
- offline cache is clearly stale/browse-only and no-cache is not rendered as zero;
- mixed-domain capability combinations hide unsafe actions;
- Chinese/English, light/dark, keyboard, focus, and all target widths pass;
- no text/icon overlap, clipping, horizontal page scroll, blank preview, raw color, decorative gradient, or nested card remains;
- old display fallback writes only v2 after cutover;
- full Vitest/build/lint/backend/logging checks pass;
- non-localhost real install/update/rollback/copy/uninstall/delete/damage/offline/in-use tests pass on isolated data;
- screenshots and console/network evidence are reviewed;
- no server/test process remains;
- exact-head independent review has no blocking finding.
