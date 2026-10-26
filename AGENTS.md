# Repository Guidelines

## Scope

Lumina Studio is a Python + React/TypeScript multi-material FDM color workflow built around `api/` + `api_server.py` + `frontend/` (FastAPI `:8000` + Vite `:4174`).

- `core/`: conversion logic and the S01–S12 pipeline coordinated by `core/pipeline/coordinator.py`.
- `api/`: validation, sessions, file lifecycle, and worker orchestration.
- `frontend/src/`: React, TypeScript, Zustand, and Three.js; `electron/`: desktop host.
- `machine_registry/`, `assets/`, `lut-preset/`: device and runtime data; native 3MF configuration comes from FatCat.

## Working on Changes

- Follow the current user's language and requested format. Comments, documentation, commit bodies, and PR descriptions do not require bilingual text.
- Ordinary work does not require spreadsheet registration, a PRD, an issue, fixed triage labels, or a separate review round. Use `.scratch/` for useful local notes and GitHub Issues when requested.
- Historical plans and reports describe past work; their team procedures, maintainer names, and old workspace paths are not requirements for a new task. Read relevant background through [CONTEXT-MAP.md](CONTEXT-MAP.md).
- Keep changes focused and preserve public API signatures and behavior during refactors. Prefer existing code, canonical enums/config, and small helpers with actual callers; avoid unused infrastructure.
- Use descriptive names and explicit Python type hints. Prefer NumPy/vectorized operations in hot paths.
- Read, edit, and save text as UTF-8; prefer `apply_patch` and re-read changed non-ASCII text to catch encoding damage.

## Pull Requests and AI Assistance

- Use the [PR template](.github/PULL_REQUEST_TEMPLATE.md). Explain the problem, the resulting behavior, and the checks actually run. Keep routine descriptions short; include more detail when needed to assess correctness or risk.
- Every PR must state whether AI was used. This includes help with investigation, implementation, tests, documentation, translation, review, or the PR description itself. If no AI was used, write `None` in the AI assistance section.
- When AI was used, name each actual model and the tool used to access it. A tool or provider name alone (such as Codex, ChatGPT, or Copilot) is not a model identity. Use the identity supplied by the runtime or contributor; if the exact model or variant is unavailable, say `Unknown (via <tool>)` or identify the known model family and state that the exact variant is unknown. Do not guess.
- Describe each model's role concretely: for example, investigating the failure, implementing a named fix, writing regression tests, reviewing the diff, or drafting the description. Distinguish AI assistance from work checked by the contributor.
- Explain how the AI-assisted output was verified. Report actual commands, manual checks, outcomes, and any checks not run; an AI review alone is not evidence that the change works. Refer to the Validation section rather than repeating test logs.
- An agent drafting or updating a PR must fill in this disclosure for its own contribution and other known AI contributions. Keep it accurate as the scope changes. Do not invent another model's identity, a human review, or a passing test. Do not include private prompts or chat transcripts.
- The person submitting the PR remains responsible for understanding and reviewing the full diff, checking the result, and responding to review. Maintainers may request missing disclosure or verification before proceeding with review.

## Architecture and Data

- Keep reusable business logic in `core/`, validation/session handling/error translation in API routes, and CPU-heavy work in workers. Worker entry points must be top-level and picklable; pass scalars and file paths across processes.
- Raise domain errors in `core/`, not `HTTPException`; map them at API boundaries through `api.errors.to_http_exception()`. Keep broad catches at explicit boundaries.
- Validate uploads, LUT/mode compatibility, coordinates, required session/cache keys, and optional dependencies with actionable errors. Use timeouts for external operations and preserve optional-feature fallbacks.
- Register temporary files for cleanup, preserve state before destructive cache mutations, and prevent stale preview/download caching. `user_settings.json` may be missing or partial.
- Final downloads (`.3mf`, `.zip`, recipes, share cards) must survive source-session closure until their TTL expires; preview/cache files may remain session-bound.

## Frontend

- Follow [DESIGN.md](DESIGN.md) and theme tokens for light/dark appearance.
- Keep regular UI strings in `frontend/src/i18n/translations.ts`; supported UI languages remain a product requirement.
- Keep resource URLs relative in state/domain logic. Components handle presentation/local interaction; API clients and Zustand stores handle orchestration.
- Preserve settings persistence and best-effort backend sync.
- New modes, parameters, printers, or slicers must update their relevant validation, UI, translations, and persisted settings together.
- Image-conversion parameters must round-trip through share-card schema/export/import and relevant tests.

## Converter Contracts

- LUT changes must preserve all supported formats (`.npy`, keyed `.json`, `.npz`, `.msgpack`) and their RGB, metadata, palette, color mode, base channel, layer order, and recipe stacks.
- Placeholder/all-Air stacks are missing recipes. Standard-size LUTs (`32`, `1024`, `1296`, `2468`, `2738`) must rebuild absent/placeholder recipes while preserving real keyed JSON recipes.
- Canonicalize color-mode aliases consistently across loading, extraction, API validation, preview, and generation.
- Preserve material identity through source selection, mesh metadata, auxiliary meshes, and slicer templates. Do not infer all slots from template row 0 or assume base channel 0/English palette names.
- Cover the raster, vector/native SVG, LUT-backed, and material-archive paths affected by a change; unsupported combinations need a deterministic API error.
- Derive irregular/transparent image outlines from alpha or color geometry, not backing meshes altered by magnet cavities or auxiliary parts.
- Before changing bug-report assembly, attachments, cleanup, or captured conversion parameters, read [bug-report-reproducibility.md](docs/bug-report-reproducibility.md) and preserve ticket-based reproduction.
- Before editing announcements or their history semantics, read [announcement-maintenance.md](docs/announcement-maintenance.md); announcement text keeps the product's supported languages.

## Logging

- Use `from api.structured_logging import get_logger` with specific `extra={"event": "<snake_case>", ...}` fields on API/worker paths, rather than business `print(...)` or tagged message prefixes.
- WARNING/ERROR records need actionable context; routine progress belongs at DEBUG. Keep pipeline `*_init` → `*_done` / `*_failed` events.
- Child processes inherit `LUMINA_LOG_PATH` and `LUMINA_LOG_INIT_BY_PARENT=1`; file logs remain JSON Lines.
- Logging usage and checks are described in [logging-guide.md](docs/logging-guide.md). Update relevant checks for actual logging changes; do not add event inventories, frozen count baselines, or governance procedures.

## Setup and Checks

- Use Python 3.12 for the current native SVG dependency. Install backend dependencies with `python -m pip install -r requirements.txt`; native 3MF setup is in [desktop-electron.md](docs/desktop-electron.md).
- Tests additionally need `python -m pip install -r requirements-dev.txt`. PostgreSQL is optional and uses `requirements-postgres.txt`; ordinary local runs do not need a database.
- Use pnpm, pinned by `packageManager`, for `frontend/` and `electron/`; enable it with `corepack enable`. Do not use npm/yarn.
- Start with `python api_server.py` or `python start_all.py`; frontend development uses `pnpm dev`.
- Backend tests use pytest/Hypothesis; all backend files named `test_*.py` are collected, including integration tests. Frontend tests use Vitest/fast-check.
- Test real behavior and known failure paths, not copies of implementation, helper existence, or arbitrary test-count targets. Use existing regression coverage and add focused tests for meaningful gaps; documentation-only changes need no new runtime tests.
- Run relevant tests for the change. Use `python scripts/run_smoke_tests.py` for a smoke gate and `python scripts/run_full_tests.py` when full regression is requested or needed by the affected behavior.
- Run non-watch frontend tests through `python scripts/run_vitest.py <args>`; frontend build/lint use `pnpm build` / `pnpm lint` from `frontend/`.
- Session cleanup, download URLs, or generate-response changes need regression coverage that fetches the final download after closing/switching its source session.
- Logging/exception changes need `python -m pytest tests/test_api_errors_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v` and the relevant `log_quality_check.py` workflow; use `--mode full` for full logging validation.
- For performance changes, use `scripts/profile_stage3.py` + `scripts/check_perf_regression.py` with reproducible warm runs. Do not manufacture a new historical baseline from current outputs.

## Git and Local Processes

- Keep secrets, machine-local settings, generated caches, logs, and transient artifacts out of commits. Use Conventional Commits for titles; no fixed language order is required.
- Preserve unrelated dirty work. Before destructive Git operations, save an external backup including untracked files; do not rely on stash alone. Execute and verify such operations separately; get agreement before overwriting someone else's work.
- When publishing changes, use a fresh topic branch. Target `main` for public `Lumina-Layers` PRs and `dev-refactor` for private `Lumina-studio` PRs, unless a maintainer explicitly specifies another target. Never push or force-push directly to `dev-refactor` or `main`; use `--force-with-lease` for any necessary topic-branch force-push.
- Stop long-running processes started by the task unless the user wants them kept running. Use the project wrappers (`start_all.py --kill`, `scripts/run_vitest.py`) where appropriate, check for leftovers, and leave unrelated processes alone.
