# Packaged sampling and update recovery implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release the recent merged Studio fixes with correct high-layer material sampling, automatic regeneration of obsolete calculation caches, and a usable Launcher update-credential recovery flow.

**Architecture:** The existing material sampler owns validation and its deterministic fallback; the existing cache identity owns rejection and lazy rebuilding of old calculated results. Distribution owns dependency data collection and frozen executable checks. Launcher continues to keep signed offline access separate from the operating-system-held update token and preserves installation identity during recovery. All publication uses existing build, origin and promotion gates.

**Tech Stack:** Python 3.12, NumPy/SciPy, pytest, PyInstaller, Tauri/Rust, React/TypeScript, Vitest, existing Windows SSH and Mac Tart CI.

## Scope and acceptance

- Do not touch customer authorization, seats, payment, stable eligibility, projects, material archives or the user's dirty Studio checkout.
- Keep scheduled automation paused. This is a single explicitly requested manual release.
- Retain old packages, bases, manifests and rollback points. Do not resume old run 1792471618 with different inputs.
- Freeze the merged Studio SHA and clean committed Distribution SHA before building. Do not chase later commits while a build runs.
- Source changes go through a fresh topic PR to `dev-refactor`; local Distribution automation changes stay local and committed.
- Launcher has its own build/update publication. A runtime package alone is not evidence that Launcher is fixed or published.

## Task 1: Material sampling, cache invalidation, and a frozen diagnostic command

**Files:**
- Modify `core/material_candidate_sampling.py` and `core/material_candidate_cache.py`.
- Modify `api_server.py` using its existing JSON diagnostic command path.
- Add focused regression tests beside `tests/test_material_candidate_cache_unit.py` and existing API command tests.
- Update `frontend/src/data/announcements.ts` with a plain-language bilingual item after reading its maintenance guide.

- [x] Write and run failing regression tests before production edits. Cover silent constant Sobol output, nonfinite/out-of-range/incorrectly shaped output, deterministic fallback, and preserved normal sampling and exhaustive small spaces. A representative assertion is:

```python
recipes = _low_discrepancy_recipes(
    material_count=4, layer_count=10, count=4096, seed=7,
)
assert recipes.shape == (4096, 10)
assert np.unique(recipes, axis=0).shape[0] > 4000
assert np.all((recipes >= 0) & (recipes < 4))
```

- [x] Validate samples before integer conversion. Reject collapsed samples even if SciPy returned without raising. Use the existing seeded random fallback; invalid fallback output must fail rather than become a valid cache.
- [x] Version the existing calculation-cache algorithm identity so legacy results are rejected and rebuilt by the normal provider path. Test an old persisted fixture, a fresh rebuilt cache, reuse after reopening, and preservation of unrelated user files. Do not delete user data or introduce another cache system.
- [x] Add `--material-sampling-self-test` to the existing backend command parser. It must run without starting the server, inspect the actual installed SciPy data resource, execute the real Sobol and high-layer recipe paths, and return nonzero on missing resources or invalid samples. Its success JSON contract is:

```json
{"status":"ok","resource_present":true,"dimensions":10,"sample_count":1024,"sobol_unique_points":1024,"candidate_budget":4096,"candidate_count":4096}
```

- [x] Test the diagnostic command's valid and failed exits. Run focused material/cache/provider/API-command tests, affected logging tests if logging changes, and required announcement checks. Record before/after sensitivity, commands, results and cleanup.
- [x] Commit only scoped source/tests/announcement/plan changes. Do not push, merge, build or publish from the implementation subtask.

### Task 1 verification evidence

Interpreter used: `/Users/min/.codex/worktrees/35d1/Lumina-studio/.scratch/svg-fix-20261020/venv/bin/python` (Python 3.12.13, SciPy 1.18.1), invoked without changing that environment.

- RED, before production edits: `python -m pytest tests/test_material_candidate_sampling_unit.py tests/test_material_sampling_cache_recovery_unit.py tests/test_material_sampling_self_test_unit.py -q --tb=short` — 25 failed, 7 passed. Collapsed sampling had one unique recipe and only 64 final candidates; invalid fallback output was accepted; persisted `hybrid-v2` data was reused; the diagnostic argument was missing.
- RED: `python -m pytest tests/test_material_dynamic_catalog_cache_unit.py::test_old_sampling_source_catalog_is_rebuilt_without_deleting_old_payload -q --tb=short` — 1 failed because the old sampling-source catalog was still accepted.
- Additional RED: `python -m pytest tests/test_material_sampling_self_test_unit.py -k sanitizes -q --tb=short` — 1 failed, 1 passed; an unexpected dependency's unsafe reason-code attribute needed sanitizing.
- GREEN: `python -m pytest tests/test_material_candidate_sampling_unit.py tests/test_material_sampling_cache_recovery_unit.py tests/test_material_sampling_self_test_unit.py tests/test_material_candidate_cache_unit.py tests/test_material_lut_provider_unit.py tests/test_material_lut_provider_candidate_runtime_unit.py tests/test_material_dynamic_catalog_cache_unit.py tests/test_material_color_prediction_contract_unit.py tests/test_api_server_bind_unit.py tests/test_native_svg_packaging_contract_unit.py tests/test_native_svg_self_test_control_flow_unit.py tests/test_svg_compensation_packaging_unit.py -q --tb=short` — 138 passed, including both provider paths and fresh-process reuse of healthy rebuilt files.
- GREEN: `python -m pytest tests/test_api_errors_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v` — 21 passed. `python scripts/log_quality_check.py --mode fast` — PASS; evidence in ignored `progress/log_audit_fast_20261021_155248.{log,json}`. No logger implementation or event inventory changed.
- Final combined re-run of the 138-test command plus the three error/logging suites above — 159 passed in 4.24s.
- GREEN: `pnpm exec tsc --noEmit` from `frontend/`; `python scripts/run_vitest.py run src/__tests__/useAnnouncement.test.ts src/__tests__/announcement-dialog.test.tsx` — 2 files, 34 tests passed. Dependencies were restored to this isolated worktree from the existing pnpm store with `pnpm install --offline --frozen-lockfile`; no lockfile changes or global toolchain installation.
- GREEN: `python api_server.py --material-sampling-self-test` — exit 0 and the exact success contract above. This is source-level evidence only; the parent release workflow still owns native frozen package checks.
- Safety: legacy cache pairs and unrelated project/material/user-file sentinels remain byte-identical. Existing provider runtimes have no process-local memo; dynamic catalog identity already includes the sampling algorithm version, so `hybrid-v3` invalidates both derived paths without deletion or a new cache system.
- Cleanup: all task-owned subprocesses exited; a filtered process inventory found no remaining backend, launcher, Vite, Vitest or esbuild process. `git diff --check` passed and every touched text file decoded as UTF-8 with no common mojibake markers.

## Task 2: Distribution dependency collection and real packaged sampling gate

**Files:**
- Modify Distribution `studio-overlay/lumina_studio.spec`.
- Modify its existing packaged smoke/check path and corresponding tests.
- Keep packaging changes in the current dedicated Distribution branch, committed but not pushed.

- [ ] Add failing tests that demonstrate the missing SciPy resource and absence of a frozen diagnostic invocation. Use the existing spec execution/test seams rather than checking for a magic source string alone.
- [ ] Explicitly collect required `scipy.stats` runtime data, including `_sobol_direction_numbers.npz`, in the existing spec.
- [ ] Invoke the new frozen backend diagnostic during both existing Windows and Mac package checks. Validate the JSON contract and fail on a missing file, a nonzero exit, collapsed samples or an underfilled candidate budget. Keep timeouts and report evidence in the existing check results.
- [ ] Verify the pre-fix artifact fails this gate and the corrected artifact passes on each native platform. Add only the new focused check; do not repeat already passing unrelated suites or require manual desktop handoffs.
- [ ] Run affected Distribution regressions and commit the clean build inputs before native execution.

## Task 3: Launcher update-credential recovery

**Files:**
- Launcher native credential/release-query/error-diagnostic code.
- Launcher activation/recovery UI and `frontend/src/i18n/translations.ts`.
- Focused Rust/frontend/native QA tests and the existing release metadata.

- [ ] Write failing behavior tests for a missing credential, a temporarily inaccessible credential, an activated user reaching the recovery form, failed recovery preserving offline access, and successful same-installation recovery refreshing updates.
- [ ] Preserve safe operating-system error categories in diagnostic logs without token values or user paths. Only transient store/read failures may use a small bounded retry; do not retry missing, malformed, permission-denied or server-denied credentials as generic network errors.
- [ ] Make recovery available while offline activation remains valid. Reuse the existing activation backend with the same installation identity. Never delete the signed receipt, regenerate installation identity, consume a new device seat, or bypass server authorization.
- [ ] Test persistence across process reopening and update/restart on the native platforms using isolated test identities, not real customers. Retain the existing offline-use behavior.
- [ ] Run focused and affected Launcher tests, then independent spec and quality review before the normal signed native release procedure. Do not dispatch Actions or deploy a new server/authentication contract.

## Task 4: Integrate and publish the exact verified releases

- [ ] Review actual changes since Studio source `62b5ed9e73984ee7fbbf393f431eb13a3d0d36a4`; write concise complete zh/en release notes outside the repositories. Include only completed merged behavior.
- [ ] Complete independent spec then quality review, push only fresh topic branches, and integrate via normal PRs. Do not push protected branches or the local Distribution automation branch.
- [ ] Record exact merged Studio and Distribution identities, release notes and active Launcher version. Run only `/Users/min/.codex/local/lumina-distribution-release/release --expect-source SHA --notes NOTES --publish` for the runtime.
- [ ] Follow original tasks across transient disconnections with existing bounded resume mechanisms; do not change input identity or fabricate stage outcomes.
- [ ] Require native Windows and Mac sampling/cache checks, existing package checks, reversible deltas, private R2 and Aliyun validation and existing restricted promotion. Publish Launcher through its separate established signed updater path.
- [ ] Verify the actual online manifests, versions and unchanged beta audience through the existing read-only interfaces. Update the recorded published baseline only after actual promotion evidence.
- [ ] Report versions/source, user-visible changes, full/delta sizes, measured phase times, any unexecuted checks and evidence paths; stop all task-owned local processes. Leave automation paused and stop when both requested updates are actually published.
