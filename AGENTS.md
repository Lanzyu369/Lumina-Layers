# Repository Guidelines

## Scope

Lumina Studio is a Python + React/TypeScript multi-material FDM color workflow built around `api/` + `api_server.py` + `frontend/` (FastAPI `:8000` + Vite `:5174`).

## Structure

- `core/`: UI-agnostic domain logic and the staged pipeline in `core/pipeline/`
- `api/`: FastAPI routers, schemas, session/file lifecycle, and worker orchestration
- `frontend/src/`: React 19, TypeScript, Zustand, Axios, Three.js, Tailwind, and Vitest
- `tests/` and `frontend/src/__tests__/`: backend/frontend regression coverage
- `printer_profiles/`, `assets/`, `lut-preset/`: templates, runtime assets, and LUT presets

## Common Commands

- `pip install -r requirements.txt`
- `cd frontend && npm install`
- `python api_server.py` | `python start_dev.py`
- `cd frontend && npm run dev|build|lint`
- `python -m pytest tests/ -v`
- `python -m pytest tests/ --hypothesis-show-statistics`
- `python scripts/run_vitest.py run` (preferred over `cd frontend && npx vitest --run`; see Tests rules)
- `python scripts/run_smoke_tests.py`
- `python scripts/run_full_tests.py`
- `python scripts/run_realtime_tests.py --no-lint`
- `python scripts/profile_stage3.py --also-write-latest`
- `python scripts/check_perf_regression.py`
- `python scripts/check_perf_regression.py --use-cold-start`
- `python scripts/log_quality_check.py --mode fast`
- `python scripts/log_quality_check.py --mode full`
- `docker build -t lumina-layers . && docker run -p 7860:7860 lumina-layers`

## Engineering Rules

- Python: PEP 8, explicit type hints, bilingual Google-style docstrings for new or changed public APIs
- Prefer NumPy/vectorized operations in hot paths
- Code shall favor good OO design: clear abstractions, single responsibility, high cohesion, low coupling, and readable composition
- Code shall remain easy to read: descriptive names, small helpers, shallow nesting, and no overlong functions, god objects, or copy-pasted logic
- Worker entry points must be top-level and picklable; pass only scalars and file paths across processes
- Reuse canonical enums/config from `config.py`, API schemas, and frontend constants
- New utilities, hooks, helpers, or shared modules must land with at least one adoption site (lighthouse user) in the same PR; pure infrastructure-only PRs require explicit justification in the PR body and a follow-up adoption tracking issue. Drop or fold utilities with zero adoption after 30 days to prevent dead code accumulating in shared module trees
- New color modes, modeling modes, printer profiles, or slicer integrations must update validation, UI, translations, persisted settings, and tests together

## Encoding & Text Safety

- All source files that contain Chinese or other non-ASCII text must be read, edited, and saved as UTF-8; do not rely on terminal or shell default code pages
- Treat mojibake as real data corruption until proven otherwise; if text looks like `锟`, `鎷`, `鍙`, `涓`, etc., verify the file with an explicit UTF-8 read before making further edits
- When inspecting non-ASCII content from the shell, use explicit UTF-8 reads such as `Get-Content -Encoding UTF8`; do not trust default `Get-Content`, redirected output, or terminal rendering alone
- For manual code edits, prefer `apply_patch`; avoid PowerShell `Set-Content`, `Out-File`, `>`, `>>`, or ad-hoc scripts for files containing non-ASCII text unless UTF-8 encoding is explicitly forced end-to-end
- After touching Chinese comments, docstrings, translations, or test strings, re-open the edited file with explicit UTF-8 and scan the touched files for common mojibake markers before concluding the work is done
- Keep user-facing Chinese text in `frontend/src/i18n/translations.ts`; avoid duplicating Chinese literals across multiple files when a translation key can be used instead
- If a public API requires bilingual docstrings, verify both languages after the edit; if a private comment/docstring is non-essential and encoding risk is high, prefer concise ASCII-only wording over corrupted Chinese

## Lossless Refactoring

- Keep all existing public API signatures unchanged during refactors
- Write tests to verify current behavior before modifying implementation
- Each refactor should focus on a single responsibility; avoid sweeping changes

## Frontend Rules

- Frontend design specification: follow `DESIGN.md` (referenced, not duplicated here) as the authoritative source for visual language, layout, components, and interaction patterns; when in doubt, defer to `DESIGN.md` over ad-hoc styling
- All user-facing strings must come from `frontend/src/i18n/translations.ts`
- Support both light and dark themes via tokens/Tailwind vars; no raw UI colors like `#fff`, `bg-white`, or `text-black`
- Keep frontend resource/file URLs as relative paths in state/domain logic; only normalization-focused tests may use absolute localhost inputs
- Keep components focused on presentation/local interaction; use API clients and Zustand stores for orchestration
- Preserve `settingsStore` persistence and best-effort backend sync
- New image-conversion features or parameters must update the share-card recipe schema, export/import adapters, and round-trip tests in the same PR.

## Architecture & Robustness

- Preserve layering: `core/` -> API/workers -> UI
- Put reusable business logic in `core/`; routes do validation, session/file handling, and error translation; CPU-heavy work belongs in workers or `core/`
- The staged pipeline lives in `core/pipeline/` (S01–S12 step modules coordinated by `coordinator.py`)
- Keep preview/generation flows compatible with `SessionStore` and `FileRegistry`
- Validate file types, LUT/mode compatibility, coordinates, required cache/session keys, and optional dependencies early with actionable errors
- Never assume session/cache state exists or is fresh; return deterministic `4xx`/`5xx`, not raw tracebacks
- Register every temp file for cleanup; preserve original state before destructive cache mutations; prevent stale preview/download caching
- Use explicit timeouts, distinguish fatal vs non-fatal failures, and degrade optional features such as HEIC/HEIF gracefully
- Use structured logging fields (`request_id`, `session_id`, `event`, `error_type`) on API/worker paths; do not add business `print(...)` in governed paths
- Keep broad `except Exception` only at explicit boundary guards; prefer typed/domain exceptions and centralized mapping via `api.errors.to_http_exception()`
- In `core/*`, do not raise `HTTPException`; raise domain/core errors and map at API boundaries
- Current supported workflows include calibration, extraction/manual correction, LUT merge/inspection, preview/generation, batch conversion, large-format tiled generation, printer/slicer integration, and BW/4-color/6-color/8-color/5-color-extended modes

## Converter Regression Checklist

- LUT changes must validate all supported storage paths: `.npy`, keyed `.json`, `.npz`, and `.msgpack`; verify RGB entries, `metadata`, `palette`, `color_mode`, `base_channel_idx`, `layer_order`, and `stacks` together rather than treating any one field as authoritative
- Placeholder or all-Air recipe stacks are missing data, not valid custom recipes; standard-size LUTs (`32`, `1024`, `1296`, `2468`, `2738`) must rebuild recipes when stacks are absent or placeholder-only, while preserving any real keyed JSON recipes
- Color-mode aliases must be canonicalized consistently across `ColorSystem`, API schemas, LUT metadata inference, extractor save paths, public LUT APIs, preview validation, and generation validation
- Final user downloads such as `.3mf`, `.zip`, exported recipes, and share cards must be TTL/ephemeral artifacts that survive source session close; preview/cache artifacts such as GLB, PNG, and intermediate arrays may remain session-bound
- Any change touching session cleanup, `FileRegistry`, download URLs, or generate responses must include a regression test where the source session is closed or switched before the download URL is fetched
- Converter features must cover raster/high-fidelity, vector/native SVG, LUT-backed, and material-archive flows, or explicitly reject unsupported combinations with a deterministic API error and test
- 3MF export changes must preserve material identity through source selection, mesh metadata, auxiliary meshes, single-stage kits, and slicer template mapping; do not infer every slot from template row 0
- Material-archive flows must not assume `base_channel_idx === 0` or canonical English palette labels; resolve base channels from selected materials, metadata, Chinese/English names, and hex values where available
- 3D outline or footprint logic must declare its geometry source; derive irregular/transparent image silhouettes from alpha or color geometry rather than backing meshes modified by fridge-magnet cavities or auxiliary parts
- User-visible converter changes must update share-card schema/import/export tests, bug-report context, and announcements when the new state affects reproduction, persistence, or release notes

## Logging Governance

- Always log via `from api.structured_logging import get_logger` and pass `extra={"event": "<snake_case>", ...}`; never use bare `print(...)` for business output, and never start a `message` with a `[TAG]` prefix
- Event names must be specific (`image_processor_done`, `lut_colors_loaded`); avoid catch-all patterns matching `*_log` / `status_*` / `request_*`. The only allowlisted bucket events are `client_log` (frontend log relay) and `log_file_configured` (logger bootstrap)
- WARNING/ERROR records must carry actionable fields (`error_type`, `error_message`, `path`, `dependency`, etc.); a level alone is not enough
- External loggers (`uvicorn`, `fastapi`, `starlette`, `asyncio`, `httpx`, `watchfiles`) are normalized by `_resolve_event_label` in `api/structured_logging.py`; `uvicorn.error` is held at WARNING so server lifecycle banners do not spend INFO budget; ANSI noise keys (`color_message`, `color_msg`) are filtered by `_EXTERNAL_NOISE_KEYS`. Update both sets together when onboarding a new external logger
- Spawned workers and subprocess servers must inherit `LUMINA_LOG_PATH` and `LUMINA_LOG_INIT_BY_PARENT=1`; `setup_file_logging()` then attaches silently without re-emitting `log_file_configured`. Preserve this protocol when changing worker pool startup or any code that spawns child processes
- File handler always writes JSON Lines; the console handler picks `human` (TTY) or `json` (pipe) automatically and respects `LUMINA_LOG_FORMAT=json|human|auto`
- Per-workflow INFO budget: a single request-scoped endpoint (preview, generate, etc.) emits at most 8 INFO lines; a full preview + generate run stays at most 30. `request_completed` and other catch-all buckets must stay at 0
- Pipeline events follow the `*_init` -> `*_done` (or `*_failed`) two-stage convention; demote intermediate progress traces to DEBUG instead of inflating INFO
- When adding a mutating endpoint to any file in `tests/test_logging_exception_governance_unit.py::TARGETS` (currently 14 governed source files spanning all 9 backend router families), emit a single success-path `<family>_<action>_done` INFO at convergence, register the event in the matching whitelist (e.g. `LUT_STRUCTURED_EVENTS`, `SYSTEM_STRUCTURED_EVENTS`) inside `REQUIRED_STRUCTURED_EVENTS`, and add an ad-hoc workflow step in `scripts/log_quality_check.py::WORKFLOW_ORDER` plus the matching runner branch; do not extend the default canonical workflow without an explicit governance round
- Bug-triage entry point for AI agents and humans: default log file is `<repo>/logs/lumina_<timestamp>.log` (JSON Lines); start at `docs/logging-guide.md` §6, which covers four canonical recipes — filter by `session_id` for stuck-flow reproduction, aggregate `*_timing` events for slow-path triage, filter `level=ERROR` with `error_type` / `error_message` / `path` for failure analysis, and read `log_quality_check.py --mode fast` stderr for gate-failure localization. Copy-pasteable PowerShell, bash, and `jq` commands are in §2-§5 of the guide
- After any logger-touching change, run `python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v` (currently 21 passed; this number grows as new whitelists are introduced — the requirement is PASS, not a fixed count) before opening a PR
- Run `python scripts/log_quality_check.py --mode fast` as the smoke gate and `--mode full` before release; both default to the canonical 10-step workflow (`startup,lut_list,lut_colors,preview,generate,replace,extract_single_stage,extract,merge_8color,merge_5color_ext`) which is FROZEN at INFO `14/30 fast`, `29/30 full`, per-endpoint `7/8`. Exit codes are `0` = PASS, `1` = governance violation, `2` = script error. Do not weaken thresholds (`--max-info`, `--max-info-per-endpoint`) to "fix" failures — address the offending event instead
- `vector` remains in `WORKFLOW_ORDER` for narrow vector debugging; `replace` is its strict superset and the canonical gate.
- Alternate color-mode replace gates (`replace_bw`, `replace_8color`, `replace_5color_ext`) are available for ad-hoc per-mode regression testing. The default PR-time gate stays at `replace` (4-Color RYBW). The replace family is mutually exclusive within a single workflow run.
- Reusable infrastructure: `api/structured_logging.py` (formatters + fallback), `api/logger.py` (file handler + parent marker protocol), `scripts/audit_logs.py` (read-only auditor), `scripts/log_quality_check.py` (workflow runner + governance scanner), `progress/log_audit_*_reviewer.json` (frozen baselines), `progress/governance-roadmap.md` (v2 final coverage map and entry point), `docs/logging-guide.md` (bilingual operator and contributor guide); v2 program closure is captured by tag `log-governance-v2`

## Tests

- Backend: `pytest` + Hypothesis; Frontend: Vitest + fast-check
- File naming: `test_*_unit.py` / `test_*_properties.py` (Python); `*.test.ts(x)` / `*.property.test.ts` (Frontend)
- Add focused regression tests for new algorithms, bug fixes, cache/session/temp-file cleanup, timeout/fallback paths, invalid uploads/LUTs, and out-of-bounds/background clicks
- Keep gate layering: `smoke` for fast pre-push checks, `full` for release-level regression, `watch` for local feedback loops
- Keep performance checks reproducible via `profile_stage3` + `check_perf_regression`; default regression decisions should use warm runs (run2/run3)
- Maintain governance tests (`tests/test_logging_exception_governance_unit.py`, URL/resource contract guards) when changing logging, exception boundaries, or URL semantics
- Always invoke non-watch frontend tests through `python scripts/run_vitest.py <args>` (transparent to `vitest run ...`); the wrapper binds the run to a Windows Job Object so the worker tree dies with the wrapper, and sweeps orphan fork workers before each run. This prevents the multi-GB fork-worker pile-up seen when agents repeatedly spawn `npx vitest run` and abort it. Watch mode (`run_realtime_tests.py`, `npm run test:watch:core`) is unaffected. The fork pool is also capped via `LUMINA_VITEST_MAX_FORKS` in `frontend/vite.config.ts` (default `2`)

## Destructive Git Operations & Data Safety

- Treat any of the following as destructive and protect data **before** running them: `git reset --hard`, `git checkout -- .`, `git clean`, `git stash drop`/`pop` (after rebases), `git rebase`, `git cherry-pick` paired with branch resets, `git switch -f`, force-pushes, and `git restore --worktree` over dirty paths
- Before any destructive op on a dirty working tree, snapshot the worktree to a path **outside** the repo (e.g. `Copy-Item -Recurse <repo> <repo>.bak-YYYYMMDD-HHMM`) or at least `tar`/`zip` it; do not rely on `git stash` alone as a backup
- Never trust `git stash -u` to preserve untracked files on Windows: stash creation can silently emit an empty untracked tree (sentinel `4b825dc6`), losing those files when the working tree is later overwritten by `reset --hard`. Untracked content is never in the object store, so reflog/fsck cannot recover it
- For any file you care about that is currently untracked, run `git add -N <path>` or `git add <path>` (even without committing) to admit it into the object store **before** any destructive op; for ad-hoc scripts that must stay untracked, copy them outside the repo first
- Never compose multi-step destructive git workflows into a single shell pipeline. Run **one git command at a time**, capture and verify output (file count, branch hash, working tree state) before the next step. PowerShell pipelines and complex one-liners truncate, swallow, or reorder stdout and make failed steps invisible
- For all git stdout that needs inspection, use `cmd /c "git ... > logs\out.txt 2>&1"` byte-level redirection then read the file; do not rely on PowerShell pipes (`|`), `Out-File`, `Set-Content`, or terminal rendering for git output (these double-encode UTF-8 and may discard lines)
- Before `reset --hard`, always print the current `git status --short` count and the target ref hash; refuse to proceed if either is unexpected
- After any destructive op, immediately verify: tracked files via `git diff --stat`, untracked recovery via `git ls-files --others --exclude-standard`, and disk presence of any file you expected to keep; if anything is missing, stop and check `git fsck --unreachable` and IDE Local History (`%APPDATA%\Windsurf\User\History`) before further mutations
- When a destructive op affects another agent's or the user's dirty work, ask first; do not assume `stash`/`pop` is round-trip safe across branch switches and cherry-picks

## Branch Naming & Lifecycle

- Default to `<owner>/<topic>` for in-flight work (e.g., `Lanz/frontend-and-agents-tweaks`, `Min/fix-relief-height-map-init`); this matches the dominant style on upstream and best supports composite multi-topic branches that stay open until PR
- Conventional `<type>/<topic>` (e.g., `fix/material-archive-vector-preview`, `feat/gradient-card-ux-upstream-merge`) is acceptable **only** when the branch will stay single-topic until merge; if the work will accumulate mixed topics, prefer the `<owner>/<topic>` form so the name does not lie about its contents
- Topic segment: kebab-case, name the intent rather than the touched files; avoid file extensions in branch names (no `-md`, `-tsx`, `-py`, etc.)
- Long-lived branches (`dev-refactor`, `main`) are protected: never push directly, never force-push, always merge through PR
- Once a topic branch has been merged into a long-lived branch (e.g., its tip becomes a `Merge pull request #N from .../<branch>` commit on `dev-refactor`), treat it as **retired**: do not stack new commits on it. Cut a fresh `<owner>/<topic>` branch from the current `origin/dev-refactor` for follow-up work, even if it would feel like "the same line of work"
- For local safety snapshots and rollback pointers, use `backup/<YYYY-MM-DD>-<short-context>` (e.g., `backup/2026-04-26-pre-reorg`); these stay local-only and should be cleaned up once the snapshotted work is verified safe
- When in doubt about an existing branch, run `git log --decorate -1 <branch>` and check whether its tip is already a merge commit on a protected branch before adding more commits to it

## Hygiene & Commits

- Before implementing a feature request or bug fix, remind the user to register the planned change in the online tracking spreadsheet first — this ensures traceability and avoids duplicate or conflicting work
- Do not commit secrets, machine-local config, IDE junk, generated caches, or transient artifacts
- `user_settings.json` is optional runtime data; code must tolerate missing or partial values safely
- Use Conventional Commits: `<type>(<scope>): <subject>`
- When commit bodies or PR descriptions are needed, write English first and Chinese second
- Summaries should explain why, not just touched files

## Git Push Safety

- **Never push directly to `dev-refactor` or `main`** — these are protected long-lived branches; all changes must land via pull request
- Always create a new feature/fix branch (e.g. `feat/xxx`, `fix/xxx`), push that branch, and open a PR against `dev-refactor`
- **Never force-push (`push -f` / `--force`) to `dev-refactor` or `main`** — force-pushing a shared branch can silently overwrite others' work and break CI
- If a force-push to a non-protected branch is absolutely necessary (e.g. rebasing a personal PR branch), always use `--force-with-lease` so the push is rejected if the remote has moved on
- Before pushing, verify the target branch name; a mistaken `git push origin dev-refactor` instead of a feature branch is a hard-to-undo error

## In-App Announcement Maintenance

- Source of truth: `frontend/src/data/announcements.ts`; rendered by `AnnouncementDialog` via `useAnnouncement` on first launch
- Any PR merged to the default branch that introduces a user-visible change (new feature, behavior change, UX fix, notable stability fix) must be reflected in the announcement file in a follow-up commit or PR
- Versioning is by **publish date in Beijing time (UTC+8)**, formatted `YYYY-MM-DD`; never use semver here, never backdate, never use a future date
- If the latest entry's `version` equals today's Beijing date, append new `items` to the appropriate existing `sections[].category`; otherwise prepend a new `AnnouncementEntry` whose `version` is today's Beijing date
- **Every user-facing string in `announcements.ts` is bilingual**: `title`, each `sections[].category`, and every item must be a `{ zh, en }` `LocalizedText`; both locales are mandatory and must describe the same change
- Use the canonical category vocabulary (keep order stable): zh `新功能` / en `New`, zh `颜色工作站` / en `Color Workstation`, zh `提取器（校色卡）` / en `Extractor (Calibration Card)`, zh `校准 & 材料` / en `Calibration & Materials`, zh `预览 & 交互` / en `Preview & Interaction`, zh `矢量化` / en `Vectorisation`, zh `稳定性` / en `Stability`; add a new category only when no existing one fits, and when adding, introduce both zh and en at once
- Writing style: plain language on both sides — Chinese is the product voice first, English mirrors it naturally (not a literal gloss); one sentence per item, explain the user-visible outcome rather than the code path; no emoji, no PR/issue numbers, no internal module names
- Keep `title` stable within a release cycle; only bump it when the marketing framing actually changes (bump both zh and en together)
- After editing, run `cd frontend && npx tsc --noEmit` plus `python scripts/run_vitest.py run src/__tests__/useAnnouncement.test.ts src/__tests__/announcement-dialog.test.tsx`; both must stay green
- Suggested AI workflow when merging PRs: (1) read the merged PR titles/bodies since the last announcement commit, (2) distill each into one bilingual bullet under the right category (write zh first, then mirror in en), (3) update `announcements.ts` following the rules above, (4) open a small follow-up PR titled `docs(announcement): refresh YYYY-MM-DD updates`

你的思考和回复，都用中文！！！
