# Material Registry Split Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` for inline execution, or `superpowers:subagent-driven-development` only if the user explicitly asks for subagents. Track progress by updating each checkbox as work completes.

**Goal:** Close out the remaining PR #318 review findings so the material-registry split can be re-reviewed and merged safely, while treating PR #242 as superseded by PR #318.

**Architecture:** PR #318 splits material-registry responsibilities across the FastAPI registry routes, local/cloud material sync frontend, and seeded material archives. API routes validate and translate request errors, `core/single_stage` owns archive logic, and frontend panels render user-friendly cloud/local states.

**Tech Stack:** Python/FastAPI, pytest, React 19, TypeScript, Vitest, Electron Builder, GitHub PR workflow.

---

## Current PR Reality

- PR #318: `shmx/feat/material-registry-split-plan` -> `dev-refactor`, head `25c3f89f00215b5376fd50715004240dd59b7aed`, merge state currently dirty.
- PR #242: `Min/feat/material-registry-package-v2` -> `dev-refactor`, review decision is changes requested and the branch is an ancestor/superseded subset of PR #318.
- Previous verification found PR #318 targeted backend tests, targeted Vitest tests, and frontend TypeScript check passing, but four closeout issues remain.

## Task 0: Prepare Isolated Closeout Workspace

**Files:** none.

**Purpose:** Avoid mutating the current main checkout and make it explicit whether fixes land directly on PR #318 or on a follow-up PR.

**Steps:**

- [ ] Run `git status --short` in `/Users/min/CascadeProjects/Lumina-studio`; confirm the main checkout has no unexpected dirty work.
- [ ] Run `git fetch origin dev-refactor pull/318/head:refs/remotes/origin/pr/318 pull/242/head:refs/remotes/origin/pr/242`.
- [ ] Create an isolated worktree for PR #318:

  ```bash
  git worktree add /tmp/lumina-pr318-closeout-20260618 --detach origin/pr/318
  ```

- [ ] In the worktree, verify:

  ```bash
  git rev-parse HEAD
  git merge-base --is-ancestor origin/pr/242 HEAD
  git status --short
  ```

- [ ] If pushing directly to `shmx/feat/material-registry-split-plan` is permitted, switch the worktree to that branch. If not, create `codex/fix/material-registry-split-closeout` from `origin/pr/318` and later open a PR targeting PR #318's branch.

**Expected result:** The closeout work starts from PR #318 head `25c3f89f00215b5376fd50715004240dd59b7aed`; PR #242 is confirmed as included/superseded.

## Task 1: Fix Markdown Whitespace Gate Failure

**Files:**

- `docs/plan/material-registry-split-architecture.md`

**Purpose:** Make `git diff --check origin/dev-refactor...HEAD` pass without changing document meaning.

**Steps:**

- [ ] In the PR #318 worktree, reproduce the failure:

  ```bash
  git diff --check origin/dev-refactor...HEAD
  ```

- [ ] Remove trailing whitespace on `docs/plan/material-registry-split-architecture.md:3` and `docs/plan/material-registry-split-architecture.md:4`.
- [ ] If those spaces were intended as Markdown hard line breaks, replace them with an explicit `<br>`; otherwise leave them as normal wrapped text.
- [ ] Re-run:

  ```bash
  git diff --check origin/dev-refactor...HEAD
  ```

**Expected result:** The command exits cleanly with no trailing-whitespace output.

## Task 2: Enforce Registry Upload Size Limit Before Buffering

**Files:**

- `api/routers/material_registry.py`
- `tests/test_material_registry_api_unit.py`

**Purpose:** Prevent service-mode package uploads from bypassing the configured archive-size cap before validation.

**Behavioral target:** `POST /api/material-registry/v1/packages/upload` should pass `max_bytes=material_package_max_archive_bytes()` into `upload_to_tempfile(...)` and return deterministic `413` for oversized uploads.

**Steps:**

- [ ] Add a failing regression test in `tests/test_material_registry_api_unit.py`:

  ```python
  def test_material_registry_upload_rejects_oversized_upload(
      monkeypatch: pytest.MonkeyPatch,
      tmp_path: Path,
  ) -> None:
      packages_dir = tmp_path / "registry-packages"
      source_package = tmp_path / "upload.zip"
      _write_v2_registry_package(
          source_package,
          material_id="mat_upload_big",
          revision_id="rev_upload_big",
          channel="manual",
      )
      monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_PACKAGES_DIR", str(packages_dir))
      monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD", "approve-secret")
      monkeypatch.setenv("LUMINA_MATERIAL_PACKAGE_MAX_ARCHIVE_BYTES", "32")

      response = _client().post(
          "/api/material-registry/v1/packages/upload",
          headers={"X-Lumina-Material-Registry-Official-Password": "approve-secret"},
          files={"archive": ("upload.zip", source_package.read_bytes(), "application/zip")},
      )

      assert response.status_code == 413
      assert "exceeds maximum size" in response.json()["detail"]
      assert not packages_dir.exists() or not any(packages_dir.rglob("*.zip"))
  ```

- [ ] Run the new test before implementation and confirm it fails for the right reason:

  ```bash
  python -m pytest tests/test_material_registry_api_unit.py -q -k oversized
  ```

- [ ] In `api/routers/material_registry.py`, import `UploadTooLargeError` from `api.file_bridge` and `material_package_max_archive_bytes` from the existing package-limit owner.
- [ ] Change the upload path to:

  ```python
  archive_path = await upload_to_tempfile(
      archive,
      suffix=".zip",
      max_bytes=material_package_max_archive_bytes(),
  )
  ```

- [ ] Add an explicit boundary mapping before broad value/domain handling:

  ```python
  except UploadTooLargeError as exc:
      raise HTTPException(status_code=413, detail=str(exc)) from exc
  ```

- [ ] Re-run:

  ```bash
  python -m pytest tests/test_material_registry_api_unit.py -q -k oversized
  python -m pytest tests/test_material_registry_api_unit.py tests/test_material_sync_api_unit.py -q
  ```

**Expected result:** Oversized registry uploads are rejected before the whole archive is accepted into temp storage, and existing registry/sync tests still pass.

## Task 4: Render a Friendly No-Registry Cloud State

**Files:**

- `frontend/src/components/MaterialCloudSyncPanel.tsx`
- `frontend/src/i18n/translations.ts`
- `frontend/src/__tests__/material-cloud-sync-panel.test.tsx`

**Purpose:** When `LUMINA_MATERIAL_REGISTRY_URL` is absent, the Material Management page should show an intentional offline/cloud-not-configured state, not a raw Axios `422` error.

**Behavioral target:** A backend response with `detail: "Material registry URL is not configured"` should be treated as an expected cloud-disabled state. Local materials remain usable, the cloud list is empty, and the user sees a translated informational notice.

**Steps:**

- [ ] Add a failing Vitest case in `frontend/src/__tests__/material-cloud-sync-panel.test.tsx`:

  ```ts
  it("shows an offline notice when the cloud registry URL is not configured", async () => {
    vi.mocked(fetchMaterialRegistryCatalog).mockRejectedValue({
      response: { data: { detail: "Material registry URL is not configured" } },
    });

    renderPanel();

    expect(await screen.findByTestId("material-cloud-sync-notice")).toHaveTextContent(
      /未配置|not configured/i,
    );
    expect(screen.queryByTestId("material-cloud-sync-error")).not.toBeInTheDocument();
  });
  ```

- [ ] Run the new frontend test before implementation:

  ```bash
  python scripts/run_vitest.py run src/__tests__/material-cloud-sync-panel.test.tsx
  ```

- [ ] In `MaterialCloudSyncPanel.tsx`, add a small helper that extracts `response.data.detail` from Axios-like errors without importing Axios into the component.
- [ ] Add a constant for the backend sentinel detail:

  ```ts
  const MATERIAL_REGISTRY_NOT_CONFIGURED_DETAIL = "Material registry URL is not configured";
  ```

- [ ] In the catalog/status load flow, when catalog loading rejects with that sentinel detail:

  - [ ] Set the cloud catalog response to an empty typed catalog.
  - [ ] Set a translated notice such as `t("mat_sync_catalog_not_configured")`.
  - [ ] Do not populate the error banner with `Request failed with status code 422`.

- [ ] Add `data-testid="material-cloud-sync-notice"` to the informational banner.
- [ ] Add bilingual copy in `frontend/src/i18n/translations.ts`:

  ```ts
  mat_sync_catalog_not_configured: {
    zh: "尚未配置云端耗材库。本地耗材库仍可离线使用；配置 LUMINA_MATERIAL_REGISTRY_URL 后会显示云端耗材。",
    en: "Cloud material registry is not configured. The local material library remains available offline; configure LUMINA_MATERIAL_REGISTRY_URL to show cloud materials.",
  },
  ```

- [ ] Re-run:

  ```bash
  python scripts/run_vitest.py run src/__tests__/material-cloud-sync-panel.test.tsx
  ```

**Expected result:** The no-registry case is no longer displayed as a raw failure, and the local/offline material workflow remains available.

## Task 5: Run Focused Regression Matrix

**Files:** none unless a failure requires a targeted fix.

**Purpose:** Verify the closeout changes without over-expanding the test surface.

**Commands:**

- [ ] Whitespace gate:

  ```bash
  git diff --check origin/dev-refactor...HEAD
  ```

- [ ] Backend closeout suite:

  ```bash
  python -m pytest \
    tests/test_api_app_unit.py \
    tests/test_material_registry_api_unit.py \
    tests/test_material_sync_api_unit.py \
    tests/test_material_sync_scheduler_unit.py \
    tests/test_material_seed_unit.py \
    -q
  ```

- [ ] Existing single-stage/material package regression tests referenced by PR #318:

  ```bash
  python -m pytest \
    tests/test_single_stage_package_api_unit.py \
    tests/test_single_stage_package_properties.py \
    tests/test_single_stage_package_zip_security_unit.py \
    tests/test_single_stage_materials_unit.py \
    tests/test_material_library_api_unit.py \
    tests/test_material_package_migration_unit.py \
    tests/test_api_app_unit.py \
    -q
  ```

- [ ] Frontend closeout suite:

  ```bash
  python scripts/run_vitest.py run \
    src/__tests__/material-sync-api.test.ts \
    src/__tests__/material-cloud-sync-panel.test.tsx \
    src/__tests__/material-library-panel.test.tsx
  ```

- [ ] TypeScript:

  ```bash
  corepack pnpm --dir frontend exec tsc -b
  ```

**Expected result:** All focused backend, frontend, TypeScript, and whitespace gates pass.

## Task 6: Manual Browser Reality Check

**Files:** none unless a failure requires a targeted fix.

**Purpose:** Confirm the user-visible Material Management behavior matches the fix, not just unit tests.

**Steps:**

- [ ] Start the backend and frontend from the PR #318 worktree without `LUMINA_MATERIAL_REGISTRY_URL` configured.
- [ ] Open the Material Management page.
- [ ] Confirm local library still loads seeded/local materials.
- [ ] Confirm cloud panel shows the translated not-configured notice.
- [ ] Confirm the page does not show `Request failed with status code 422`.
- [ ] If a local registry fixture is available, run one configured-registry smoke check and confirm cloud catalog data still renders.
- [ ] Stop all processes started for verification.
- [ ] Check for leftovers matching `api_server.py`, `start_all.py`, `vite`, `vitest`, `esbuild`, `node_modules`, or the PR worktree path, and clean them up.

**Expected result:** The default desktop/local development state is understandable and no long-running processes are left behind.

## Task 7: Commit, Report, and Merge-Readiness Handoff

**Files:** Git metadata and GitHub PR comments only.

**Purpose:** Leave PR #318 in a state maintainers can review and merge, and make PR #242's superseded status explicit.

**Steps:**

- [ ] Review final diff:

  ```bash
  git diff --stat
  git diff
  ```

- [ ] Commit with focused Conventional Commit messages. Suggested grouping:

  ```text
  chore(materials): fix registry split plan whitespace
  fix(materials): cap registry service package uploads
  fix(materials): show no-registry cloud library notice
  ```

  Combining into fewer commits is acceptable if the final diff remains easy to review.

- [ ] Push to the PR #318 branch if permitted. Otherwise push `codex/fix/material-registry-split-closeout` and open a PR into `shmx/feat/material-registry-split-plan`.
- [ ] Update PR #318 with a concise final status comment listing:

  - User-visible changes.
  - The exact commits pushed.
  - The exact verification commands and pass/fail results.
  - Browser reality-check result.
  - Remaining risk, if any.

- [ ] Comment on PR #242 that it is superseded by PR #318 and should not be merged standalone after PR #318 is green.
- [ ] Do not push directly to `dev-refactor` or `main`.
- [ ] Merge PR #318 only after required checks and reviewer approval are green. Close PR #242 as superseded after PR #318 lands.

**Expected result:** PR #318 has no known closeout blockers, reviewers have concrete evidence, and PR #242 is handled as superseded rather than merged independently.
