# Browser Completion Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in browser permission flow and reliable Windows/macOS completion notifications for converter preview/generation, batch generation, and calibration generation.

**Architecture:** Keep permission and Notification API handling in one defensive browser adapter. Persist only a client-side boolean in `settingsStore`, expose it through the existing Settings page, and invoke the adapter from authoritative success convergence points so failure, cancellation, and stale-response paths stay silent.

**Tech Stack:** React 19, TypeScript 5.8, Zustand 5, Browser Notification API, Vitest 4, Testing Library, Vite 6

## Global Constraints

- Work only in `C:\Users\shmx\.codex\worktrees\win-notify\Lumina-Layers` on `shmx/feat/browser-completion-notifications`.
- Keep the backend and existing store action signatures unchanged.
- The preference remains browser-local and is not included in backend settings sync or share-card recipes.
- Use `frontend/src/i18n/translations.ts` for all regular UI strings.
- Do not use TDD for this task, per the repository instruction; implement a cohesive slice, then add focused regression coverage before moving to the next slice.
- Run all non-watch Vitest commands through `conda run -n Lumina-Layers python scripts/run_vitest.py`.

---

### Task 1: Browser notification adapter

**Files:**
- Create: `frontend/src/utils/browserNotifications.ts`
- Create: `frontend/src/utils/__tests__/browserNotifications.test.ts`

**Interfaces:**
- Produces: `CompletionNotificationKind = "preview" | "generation" | "batch" | "calibration"`
- Produces: `BrowserNotificationPermission = NotificationPermission | "unsupported" | "error"`
- Produces: `getBrowserNotificationPermission(): BrowserNotificationPermission`
- Produces: `requestBrowserNotificationPermission(): Promise<BrowserNotificationPermission>`
- Produces: `showBrowserCompletionNotification(kind, language): boolean`

- [ ] **Step 1: Implement the adapter**

Use a single bilingual message table and stable tags. The exported delivery function must check support and `permission === "granted"` on every call and catch constructor failures:

```ts
export type CompletionNotificationKind =
  | "preview"
  | "generation"
  | "batch"
  | "calibration";

export type BrowserNotificationPermission =
  | NotificationPermission
  | "unsupported"
  | "error";

export function getBrowserNotificationPermission(): BrowserNotificationPermission;
export function requestBrowserNotificationPermission(): Promise<BrowserNotificationPermission>;
export function showBrowserCompletionNotification(
  kind: CompletionNotificationKind,
  language: "zh" | "en",
): boolean;
```

`requestBrowserNotificationPermission()` returns an existing `granted` or `denied` state without calling `requestPermission()`, calls it only for `default`, and returns `error` on an exception. It must accept both the Promise result used by modern browsers and the callback-only result used by older macOS Safari releases, settling exactly once if a browser supplies both. `showBrowserCompletionNotification()` creates `new Notification(title, { body, tag })` and never throws.

- [ ] **Step 2: Add adapter regression tests**

Use `vi.stubGlobal("Notification", MockNotification)` and restore globals after each test. Cover unsupported, granted without a request, denied without a request, Promise request success, callback-only macOS Safari success, hybrid callback-plus-Promise settlement, request exception, Chinese and English payloads, stable tags, and a throwing constructor.

- [ ] **Step 3: Run the adapter tests**

Run:

```powershell
conda run -n Lumina-Layers python scripts/run_vitest.py run src/utils/__tests__/browserNotifications.test.ts
```

Expected: the new test file passes with zero unhandled exceptions.

### Task 2: Persisted Settings permission flow

**Files:**
- Modify: `frontend/src/stores/settingsStore.ts`
- Modify: `frontend/src/components/SettingsPanel.tsx`
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `frontend/src/__tests__/settings-store-hydration.test.ts`
- Create: `frontend/src/components/__tests__/SettingsPanel.notifications.test.tsx`

**Interfaces:**
- Consumes: adapter functions from Task 1
- Produces: `SettingsState.enableCompletionNotifications: boolean`
- Produces: `SettingsActions.setEnableCompletionNotifications(enabled: boolean): void`

- [ ] **Step 4: Add the browser-local setting**

Add the state and action without changing `syncToBackend()`:

```ts
export interface SettingsState {
  enableCompletionNotifications: boolean;
}

export interface SettingsActions {
  setEnableCompletionNotifications: (enabled: boolean) => void;
}

export const DEFAULT_SETTINGS: SettingsState = {
  enableCompletionNotifications: false,
};
```

The persisted-state merge already overlays older snapshots on current defaults, so no persist version bump is required.

- [ ] **Step 5: Add bilingual permission and status copy**

Add translation keys for the section heading, description, enable label, granted, denied, dismissed/default, unsupported, and request-failed states. The Chinese description must explicitly say that browser notifications cover preview, model generation, batch generation, and calibration generation.

- [ ] **Step 6: Add the Settings page interaction**

Import the adapter, track the current permission and request-in-progress state, and reconcile a stale persisted `true` value when permission is not granted. The switch handler follows this exact state machine:

```ts
const handleCompletionNotificationsChange = async (enabled: boolean) => {
  if (!enabled) {
    setEnableCompletionNotifications(false);
    return;
  }

  setNotificationPermissionLoading(true);
  const permission = await requestBrowserNotificationPermission();
  setNotificationPermission(permission);
  setEnableCompletionNotifications(permission === "granted");
  setNotificationPermissionLoading(false);
};
```

Render the new block with `Switch`, an inline `HelpDot` beside the visible label, and `StatusBanner`; disable the switch only while requesting or when unsupported. Denied and error states must tell users the feature remains off.

- [ ] **Step 7: Add store and component tests**

Extend hydration coverage to assert older snapshots receive `false`. In the focused SettingsPanel test, mock printer/slicer APIs and the Notification constructor, then verify:

- granting permission sets the store to `true`
- denying permission leaves it `false` and shows the denied message
- unsupported API disables the switch and shows the unsupported message
- disabling an enabled setting does not call `requestPermission()`
- English locale renders the English label

- [ ] **Step 8: Run Settings regression tests**

Run:

```powershell
conda run -n Lumina-Layers python scripts/run_vitest.py run src/utils/__tests__/browserNotifications.test.ts src/__tests__/settings-store-hydration.test.ts src/components/__tests__/SettingsPanel.notifications.test.tsx src/components/__tests__/SettingsPanel.machineAdapter.test.tsx src/components/__tests__/SettingsPanel.baseLayerHeightModifier.test.tsx
```

Expected: all listed files pass and existing machine/slicer settings behavior remains unchanged.

### Task 3: Authoritative completion integration

**Files:**
- Modify: `frontend/src/stores/converter/store.ts`
- Modify: `frontend/src/stores/calibrationStore.ts`
- Modify: `frontend/src/stores/__tests__/converter-native-source.test.ts`
- Modify: `frontend/src/stores/__tests__/batchStore.test.ts`
- Modify: `frontend/src/__tests__/calibration-store.property.test.ts`

**Interfaces:**
- Consumes: `showBrowserCompletionNotification(kind, language)` from Task 1
- Consumes: `enableCompletionNotifications` and `language` from `settingsStore`

- [ ] **Step 9: Add one defensive completion helper per store module**

The helper reads live settings at completion time and returns immediately when the preference is off:

```ts
function notifyCompletion(kind: CompletionNotificationKind): void {
  const settings = useSettingsStore.getState();
  if (!settings.enableCompletionNotifications) return;
  showBrowserCompletionNotification(kind, settings.language);
}
```

- [ ] **Step 10: Wire converter success convergence points**

Call `notifyCompletion("preview")` after the successful preview state and analytics event. Call `notifyCompletion("generation")` after each normal, puzzle, and large-format generation success event. Call `notifyCompletion("batch")` after successful batch state and analytics. Do not add calls to validation, catch, stale-response, abort, or `finally` paths.

- [ ] **Step 11: Wire calibration success convergence points**

Call `notifyCompletion("calibration")` after the successful legacy calibration state update and after the successful single-stage kit state update. Both catch paths remain unchanged.

- [ ] **Step 12: Add integration assertions**

Mock `showBrowserCompletionNotification`, enable the setting, and assert the correct completion kind and current language after each covered success. Add negative assertions for disabled settings and representative failure/stale paths. Reuse existing API fixtures for normal, puzzle, large-format, batch, legacy calibration, and single-stage calibration responses.

- [ ] **Step 13: Run focused completion regression tests**

Run:

```powershell
conda run -n Lumina-Layers python scripts/run_vitest.py run src/utils/__tests__/browserNotifications.test.ts src/stores/__tests__/converter-native-source.test.ts src/stores/__tests__/batchStore.test.ts src/__tests__/calibration-store.property.test.ts
```

Expected: all covered completion modes pass and notification mocks stay untouched on failure/stale paths.

### Task 4: Full verification, browser proof, and publication

**Files:**
- Verify: all files changed by Tasks 1-3
- Verify: `docs/superpowers/specs/2026-07-12-browser-completion-notifications-design.md`
- Verify: `docs/superpowers/plans/2026-07-12-browser-completion-notifications.md`

- [ ] **Step 14: Run frontend quality gates**

Run serially:

```powershell
conda run -n Lumina-Layers python scripts/run_vitest.py run src/utils/__tests__/browserNotifications.test.ts src/__tests__/settings-store-hydration.test.ts src/components/__tests__/SettingsPanel.notifications.test.tsx src/stores/__tests__/converter-native-source.test.ts src/stores/__tests__/batchStore.test.ts src/__tests__/calibration-store.property.test.ts
corepack pnpm --dir frontend build
corepack pnpm --dir frontend lint
```

Expected: all commands exit 0. Do not weaken lint, TypeScript, or test configuration to obtain a pass.

- [ ] **Step 15: Run browser verification**

Start the application with the project launcher, open `http://localhost:5174`, navigate to Settings, enable completion notifications, grant the browser prompt, and verify the enabled status. Complete one real preview and one real generation using a repository sample asset. Confirm the browser constructs the corresponding notification payloads and, where the controlled browser exposes it, the Windows or macOS notification toast appears. On macOS, verify Safari's callback-compatible permission path and Notification Center delivery when a Mac runner is available.

- [ ] **Step 16: Clean up and independently review**

Stop the launcher with:

```powershell
conda run -n Lumina-Layers python start_all.py --kill
```

Check for leftover `api_server.py`, `start_all.py`, Vite, Vitest, and project-scoped Node processes. Review the complete diff against `origin/dev-refactor`, check UTF-8 text for mojibake markers, and address all actionable findings.

- [ ] **Step 17: Commit, push, and open the PR**

Stage only intended files. When publishing, use a Conventional Commit title and a PR targeting `dev-refactor`, describing purpose, implementation, tests, browser proof, and residual limitations.
