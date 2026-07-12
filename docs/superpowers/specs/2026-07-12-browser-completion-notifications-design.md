# Browser Completion Notifications Design

## Goal

Add an opt-in browser setting that requests notification permission from a user gesture and sends Windows or macOS system notifications when long-running Lumina work completes successfully.

The initial completion coverage is:

- converter preview, including automatic re-preview
- normal, puzzle, and large-format model generation
- batch generation
- legacy and single-stage calibration generation

## Constraints

- The browser owns notification permission and delivery; the FastAPI backend must not participate.
- Permission must only be requested after the user enables the setting.
- The setting is off by default and persists in the existing `lumina-settings` browser storage.
- Notification permission denial, unsupported browsers, constructor failures, and revoked permissions must never fail or alter a completed Lumina task.
- Existing preview and generation action signatures remain unchanged.
- All new regular UI copy is bilingual and comes from `frontend/src/i18n/translations.ts`.
- The preference is client-only and is intentionally excluded from backend settings sync and share-card recipes because it does not affect generated output or reproducibility.

## Approaches Considered

### 1. Notify from successful store paths (selected)

Call one shared browser-notification adapter immediately after each existing success convergence point. This preserves the store's authoritative knowledge of stale responses, cancellation, alternate output modes, and failure paths. It also covers non-button callers without changing public action signatures.

Trade-off: the converter store gains a small browser-side effect, but that side effect is isolated behind a defensive adapter and matches the existing analytics/logging convergence calls in those paths.

### 2. Subscribe to loading-state transitions in `App`

Watch `isLoading`, `isGenerating`, and related state globally, then infer completion when a flag changes from true to false.

This was rejected because a transition to false can also mean failure, abort, or stale-response suppression. It would duplicate domain-specific success detection and is likely to emit false notifications as workflows evolve.

### 3. Notify only from button handlers

Await each action from `ActionBar` or `CalibrationPanel`, inspect the resulting state, and notify there.

This was rejected because puzzle and large-format generation intentionally return the same value as some failure paths, automatic preview bypasses the button, and slicer auto-generation invokes the store directly. UI wrappers would be incomplete or would require changing action return contracts.

## Architecture

### Notification adapter

Create `frontend/src/utils/browserNotifications.ts` with a narrow interface:

- inspect whether the Notification API is supported and return its permission state
- request permission only when the current state is `default`
- render localized title/body text for a typed completion kind
- construct a browser `Notification` only when permission is `granted`
- catch all permission and delivery errors and return a result instead of throwing

Permission requests use both the standards-based Promise result and the legacy callback result. Modern browsers settle through the Promise, while older macOS Safari releases that return no Promise settle through the callback. The adapter accepts whichever channel resolves first and ignores the duplicate result in browsers that support both.

Each completion kind uses a stable `tag` so repeated work of the same type does not create an unbounded notification stack.

### Settings state and UI

Add `enableCompletionNotifications` and `setEnableCompletionNotifications` to `settingsStore`, defaulting to `false`. Zustand persistence handles older snapshots by merging the missing value from the current defaults. The field is not sent through `syncToBackend()`.

Add a dedicated task-notifications block to the Settings page. Enabling it immediately calls the adapter's permission request from the switch click handler:

- `granted`: persist the setting as enabled and show a success status
- `denied`: keep the setting disabled and explain how to allow notifications in site settings
- `default`: keep the setting disabled and state that permission was not granted
- unsupported or request error: keep the setting disabled and show an actionable status
- disabling: persist `false` without changing browser permission

When the Settings page opens with a persisted enabled value but permission is no longer granted, it reconciles the preference back to `false`.

### Completion delivery

At each success convergence point, read `enableCompletionNotifications` and `language` from `settingsStore`, then call the adapter. Do not emit notifications on validation failures, caught exceptions, aborted requests, or stale responses.

Notifications are informational only. Failure to display one is silently ignored so it cannot change task state, downloads, or generated artifacts.

## User-Facing Copy

The Settings page explains that notifications are sent by the browser and cover previews, model generation, batch generation, and calibration generation. Permission and support states are displayed inline with existing `StatusBanner` styling.

Completion notifications use concise bilingual copy:

- preview: the preview is ready to inspect
- generation: the model is ready to download or send to a slicer
- batch: the batch results are ready
- calibration: the calibration files are ready

## Testing

### Unit and component tests

- notification adapter: unsupported API, existing permission states, permission request success/failure, bilingual payloads, stable tags, and constructor failure isolation
- macOS Safari compatibility: callback-only permission requests and hybrid callback-plus-Promise requests
- settings store: default-off state, setter behavior, and legacy hydration fallback
- Settings page: granted, denied, unsupported, and disable flows
- converter store: preview, normal generation, puzzle generation, large-format generation, and batch success call the adapter only when enabled; failures and stale responses remain silent
- calibration store: both successful workflows notify; failures remain silent

### Verification

- focused Vitest suites through `python scripts/run_vitest.py`
- full frontend TypeScript build and ESLint
- browser run on the local FastAPI/Vite application: enable the option, grant site permission, complete a preview and a generation, and confirm browser notifications are requested and delivered
- macOS verification when a Mac runner is available: exercise Safari's permission prompt and confirm delivery in macOS Notification Center
- process cleanup after browser verification

## Risks and Mitigations

- Browser policies may block or pre-deny notifications. The Settings page reports the state and never represents a denied request as enabled.
- Automatic previews can complete frequently. Stable per-kind notification tags let the browser replace the existing preview notification instead of accumulating unique entries.
- Tests run in jsdom without a native Notification implementation. The adapter boundary is mockable and the browser run provides the real integration check.
- Users can revoke permission outside Lumina. Every delivery rechecks permission, and opening Settings reconciles a stale enabled preference.

## Non-Goals

- Backend, email, mobile push, or service-worker notifications
- notifications for task failures
- notification history inside Lumina
- exporting the preference in recipes or syncing it between browser profiles
- redesigning existing progress indicators or loading messages
