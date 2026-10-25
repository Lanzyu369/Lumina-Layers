# Cloudflare Credits Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Open the approved interactive credits garden from PR #668's header menu, read the real Cloudflare catalog and avatars, and start the application for local review.

**Architecture:** Keep the existing header/navigation from PR #668. A lazy credits dialog owns loading and close/focus behavior; a catalog client owns remote JSON verification and the last successful IndexedDB snapshot; the canvas garden owns presentation and physical interaction. Reuse the approved prototype physics and avatar caching without shipping its roster or images in the app.

**Tech Stack:** React 19, TypeScript, existing canvas JavaScript renderer, IndexedDB, Web Crypto, Vite, Vitest.

---

## Scope and source

- Base: PR #668 head `a9deb313989e14f83af9edabafe432961f257d16`, local branch `MIn/feat/cloudflare-credits`.
- Data: `https://lumina-studio-credits.pages.dev/manifest.json`; resolve hosted avatars against `assets_base` relative to this manifest.
- Approved interactions: `.scratch/credits-bubble/lumina-credits.html` and `avatar-cache.js`.
- No bundled names, avatars, financial data, credentials, or generated data scripts.
- Preserve real full names inside avatar bubbles, sources in results/cards, full-screen density, native device-pixel resolution, search flight with displacement, pop/recovery pressure, eight sponsor styles plus developer identity. Sponsor effects start off.
- No total-count headline, grade legend/labels, enlarged initials, instructional copy or thank-you hero. Use the real logo and PR #668 MiSans typography, theme tokens, ghost controls and shared close button.

## Task 1: Verified catalog reader

**Files:** `frontend/src/credits/types.ts`, `catalog.ts`, `catalog.test.ts`, `useCreditsCatalog.ts`.

- [x] Define the shared display-only `CreditsRecord` and `CreditsCatalog` contract. Keep record avatar fields relative when hosted; resolve them only at image loading.
- [x] Write failing tests for successful manifest/roster loading, SHA-256 mismatch, wrong schema/URL, offline cache fallback and caller cancellation.
- [x] Implement `loadCreditsCatalog(signal?: AbortSignal): Promise<CreditsCatalog>` using anonymous timed fetches, manifest checks and SHA-256 verification. Write a single last-good IndexedDB snapshot only after validation; a failed refresh preserves it. Cancellation must not resurrect a closed view.
- [x] Add `useCreditsCatalog()` returning `{catalog, loading, error, reload}`. Abort when unmounted and ignore superseded responses.
- [x] Run `python3 scripts/run_vitest.py run src/credits/catalog.test.ts` and inspect the result.

## Task 2: Preserve the approved bubble garden

**Files:** `frontend/src/credits/CreditsGarden.tsx`, scoped garden styles, renderer/cache modules and their tests/declarations.

- [x] Add behavioral tests before porting: default sponsor effects off, full exact-name search/duplicate platforms, cleanup of event handlers/frame callbacks, native DPR and local-container coordinates.
- [x] Adopt the prototype as a mountable capability receiving `CreditsCatalog`; use a scoped root instead of document-wide selectors. Keep the existing physics and visual behavior rather than substitute a simplified demo.
- [x] Use the shared app font/theme tokens for chrome. Keep optical bubble colors as visual content. Put motion/effect controls together in one translucent floating toolbar using the existing switch semantics.
- [x] Translate all visible/accessible copy through `translations.ts` labels supplied by the React layer. Do not draw tier/developer labels inside bubbles.
- [x] Dispose resize/input listeners, animation callbacks, pending image callbacks and decoded image resources on unmount; pause when hidden. The full dataset stays searchable while only visible bubbles acquire rendering resources.
- [x] Run focused renderer/component tests through `scripts/run_vitest.py`.

## Task 3: Application entry and dialog

**Files:** `frontend/src/components/HeaderMenu.tsx`, its test, `frontend/src/App.tsx`, `frontend/src/credits/CreditsDialog.tsx`, its test, `frontend/src/i18n/translations.ts`.

- [x] Add a failing menu test proving the labelled credits action calls the callback and closes the menu.
- [x] Add the optional `onOpenCredits` menu callback using `HeaderMenuItem`. App supplies it and lazily opens the credits dialog.
- [x] Reuse `useDialogFocusTrap` and the shared close control. Show translated loading/error/retry states; show the cached catalog if the network fails after a previous successful visit.
- [x] Suspend the background workspace rendering while credits is open, preserving the existing Zustand/session state. On close restore the previous workspace and focus to the menu trigger.
- [x] Add Chinese and English keys for menu, title, load/error/retry, search/status, source and motion/effect controls.
- [x] Test entry, error retry, focus/Escape close and successful catalog handoff; keep normal menu navigation tests passing.

## Task 4: Validation and preview

- [x] Run the focused menu/catalog/garden/dialog suites, `pnpm build`, lint changed frontend files, and `git diff --check`.
- [x] Review scope compliance first, then code quality. Repair actionable issues before the final browser run.
- [x] Start Vite and the backend if the app health gate requires it. Open the actual app, enter credits through the menu and exercise the real Cloudflare path; search a real complete name, toggle effects, pop/recover, close and reopen, inspect both themes.
- [x] Save screenshot and runtime evidence. Verify the rendered roster has 12,770 records and avatar requests use Cloudflare/social origins without local fixture data.
- [x] Keep only the preview processes needed for the user's explicit request, record stop commands, and stop other owned helpers.

**Completion evidence:** the real app on the PR #668 base opens the approved bubble garden using the live Cloudflare dataset, tests/build pass, and the running preview is available to the user. Do not claim packaged Electron or long-term network reliability was verified.
