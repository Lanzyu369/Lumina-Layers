# Log Governance Roadmap

## 1. Purpose

This roadmap is the v2 closeout reference for Lumina Studio logging governance.
Rounds 7-62 established structured, budgeted success-path canaries across the backend mutation surface, and the program now closes with the `log-governance-v2` tag to be applied on the post-merge `dev-refactor` HEAD.

Use this file to review future logging work quickly:

- `scripts/log_quality_check.py` defines workflow order, default workflow, budget thresholds, and ad-hoc gates.
- `tests/test_logging_exception_governance_unit.py` owns the structured-event inventories and production-path logging guardrails.
- `api/structured_logging.py` and `api/logger.py` own formatting, file-handler setup, external logger normalization, and parent/child process logging protocol.
- `progress/log_audit_fast_reviewer.json` and `progress/log_audit_full_reviewer.json` remain the frozen reviewer baselines for the default canonical gate.

The roadmap does not create new policy.
It records the current contract so future changes can be deliberate: preserve structured events, preserve INFO budget, preserve canaries that prove the user-visible success path completed, and update this document when that contract changes.

## 2. Coverage Map

The v2 program covers backend mutating endpoints with ad-hoc workflow gates unless a row explicitly joined the default canonical workflow.
The default canonical workflow is still:

`startup,lut_list,lut_colors,preview,generate,replace,extract_single_stage,extract,merge_8color,merge_5color_ext`

| Family | PR / rounds | Coverage state | Canary inventory | Gate status |
|---|---|---|---:|---|
| Extractor | #106-#107 / rounds 11-16 | Legacy extractor mutation endpoints covered: extract, manual fix, merge, white-balance preview, rotate, confirm palette | 7 legacy entries in `EXTRACTOR_STRUCTURED_EVENTS` | `extract`, `merge_8color`, and `merge_5color_ext` are canonical; others ad-hoc |
| Converter | #109-#111 / rounds 18-35 | Replace, generate, preview, puzzle, and cleanup mutation endpoints covered | 19 in `CONVERTER_STRUCTURED_EVENTS` | all v2 additions ad-hoc; default `replace` remains canonical |
| Single Stage | #112-#113 / rounds 36-47 | Single-stage extractor and material solver cache mutation endpoints covered | 12 entries stored in `EXTRACTOR_STRUCTURED_EVENTS` | `extract_single_stage` joined canonical in #112; rest ad-hoc |
| Calibration | #118 / rounds 48-49 | Calibration board and single-stage kit generation covered | 2 in `CALIBRATION_STRUCTURED_EVENTS` | ad-hoc |
| Five Color | #118 / rounds 50-52 | Query, swatch generation, and base-colors mutation/read-support path covered | 3 in `FIVE_COLOR_STRUCTURED_EVENTS` | ad-hoc |
| Vectorizer | #118 / round 53 | `POST /api/vectorize` covered | 1 in `VECTORIZER_STRUCTURED_EVENTS` | ad-hoc |
| LUT | #119 / rounds 54-58 | Merge, compare, details, upload, and session info covered | 5 in `LUT_STRUCTURED_EVENTS` | ad-hoc |
| System | #120 expected / rounds 59-60 | Image preview generation and settings persistence covered | 2 in `SYSTEM_STRUCTURED_EVENTS` | ad-hoc |
| Slicer | #120 expected / round 61 | External slicer launch covered with subprocess mocked in runner/tests | 1 in `SLICER_STRUCTURED_EVENTS` | ad-hoc |

Current verified inventory:

- `REQUIRED_STRUCTURED_EVENTS` is a 9-way union: vector, extractor, converter, calibration, five-color, vectorizer, LUT, system, slicer.
- The union currently contains 78 structured event names. Not every name is a new INFO canary; the vector inventory also retains branch and DEBUG-level structured events.
- The v2 closeout canary count remains 51 cumulative by the master-plan accounting.
- `TARGETS` in `tests/test_logging_exception_governance_unit.py` expanded by two entries in this batch (`api/routers/system.py`, `api/routers/slicer.py`) and currently has 38 entries in this repository tree.
- `DEFAULT_MAX_INFO = 30` and `DEFAULT_MAX_INFO_PER_ENDPOINT = 8` are unchanged.

## 3. Cumulative INFO Budget

The default canonical gate is frozen after PR #119 and remains frozen through #120.
Reviewer baseline checks are unchanged: fast `info_lines_within_budget` actual `14/30`, full `info_lines_within_budget` actual `29/30`, per-endpoint max `7/8`.

| PR | Rounds | Default canonical | Reviewer budget state | Notes |
|---:|---|---|---|---|
| #112 | 36-41 | 9 -> 10 steps | fast 14/30, full 29/30, per-EP 7/8 | `extract_single_stage` joined default canonical; reviewer baselines regenerated |
| #113 | 42-47 | unchanged 10 steps | unchanged | single-stage pt2 canaries stayed ad-hoc |
| #114 | interleaved | unchanged | unchanged | non-governance repository PR; no baseline mutation |
| #115 | interleaved | unchanged | unchanged | no default-canonical governance mutation recorded in this tree |
| #116 | interleaved planning row | unchanged | unchanged | original master-plan row for final system/slicer batch; actual expected PR number shifted |
| #117 | verifier fixture precedent | unchanged | unchanged | verifier-level fixture amendments did not change thresholds or baselines |
| #118 | 48-53 | unchanged | unchanged | calibration, five-color, and vectorizer canaries stayed ad-hoc |
| #119 | 54-58 | unchanged | unchanged | LUT canaries stayed ad-hoc; reviewer baselines preserved |
| #120 expected | 59-62 | unchanged | unchanged | system/slicer canaries are ad-hoc; round 62 is docs-only |

Budget rules remain:

- Do not raise `DEFAULT_MAX_INFO` or `DEFAULT_MAX_INFO_PER_ENDPOINT` to fix a failure.
- Do not weaken reviewer baselines when a new canary is ad-hoc.
- Do not add new exclusions to `_INFO_BUDGET_EXCLUDED_EVENTS` without a separate governance round.
- Keep `request_completed` and other catch-all buckets at zero.
- New default-canonical rows require an explicit governance PR, fresh baselines, and roadmap updates.

## 4. Yellow Flags

- **Default canonical headroom is narrow.** Full mode sits at reviewer actual `29/30`; any future default-canonical addition needs a real budget decision.
- **Fast and full are intentionally different.** Fast mode uses mocks and does not prove worker-level vector canaries; full mode remains the source of truth for subprocess, worker, and vector branch behavior.
- **Subprocess and persistent-state workflows need isolation.** Round 60 backs up and restores `user_settings.json`; round 61 mocks `api.routers.slicer.detect_installed_slicers` and `api.routers.slicer.launch_slicer` to avoid launching a real GUI process.
- **Timestamped audit files are scratch output.** Do not commit `progress/log_audit_<mode>_<timestamp>.json` unless a verifier explicitly asks for an artifact.
- **Mojibake remains a release blocker.** Files containing Chinese text must be read and written as UTF-8, and touched files should be scanned for common mojibake markers before completion.

## 5. Uncovered / Deferred To V3

The v2 backend mutation program is closed.
Remaining logging-governance work requires browser-driven or frontend-aware coverage rather than more backend-only TestClient workflows.

Deferred v3 seeds:

- `/api/session/heartbeat` and `/api/session/close` lifecycle flows.
- `/api/system/clear-cache` and related GET/read flows as exercised through the UI, including confirmation and cache invalidation behavior.
- Dialog-confirm flows that require browser state and user interaction.
- Palette-edit and settings-invalidation flows that need Playwright-level orchestration.
- Any future frontend-driven workflow whose success cannot be proven by a direct backend request alone.

Do not stretch `scripts/log_quality_check.py` with brittle backend-only substitutes for these flows.
The next program should add a Playwright/browser layer deliberately.

## 6. V2 Closeout State

`log-governance-v2` closes on these facts after PR #120 is merged:

- Rounds covered: 7-62.
- Governance PR range: #108-#120, with non-governance PRs interleaved in the repository history.
- Canary accounting: 51 cumulative success-path canaries by the v2 master-plan count.
- Structured-event inventory: 9-way `REQUIRED_STRUCTURED_EVENTS` union, currently 78 names.
- Target inventory: `TARGETS` expanded by `system.py` and `slicer.py`; current source list length is 38 entries.
- Default canonical gate: 10 steps, unchanged by rounds 59-62.
- Reviewer baselines: fast check actual `14/30`, full check actual `29/30`, per-endpoint actual `7/8`.
- Baseline files: unchanged in the final system/slicer/retro batch.
- Tag: Cascade applies `log-governance-v2` on the post-merge `dev-refactor` HEAD; this PR must not create the tag.

## 7. Glossary

**Canary event**: a structured INFO log line whose presence proves a success path completed.

**Structured event**: a log record carrying `extra={"event": "<snake_case_name>", ...}` and actionable fields beyond the message string.

**Default canonical gate**: the default `scripts/log_quality_check.py` workflow used for reviewer baselines.

**Ad-hoc gate**: a first-class workflow step that can be run by name but does not alter the default canonical baseline.

**Replace family**: `{replace, replace_bw, replace_8color, replace_5color_ext}`. Exactly one member may appear in a workflow run.

**Runtime-only alternate**: an ad-hoc workflow that must pass when relevant but does not have a committed reviewer baseline file.

## Chinese 摘要

这份路线图记录 LOG 治理 v2 的终局状态。Rounds 7-62 已经把后端 mutating endpoint 的成功路径 canary 补齐，最终由 Cascade 在 PR #120 合并后的 `dev-refactor` HEAD 上打 `log-governance-v2` tag。

默认 canonical 仍是 10 步：`startup,lut_list,lut_colors,preview,generate,replace,extract_single_stage,extract,merge_8color,merge_5color_ext`。Rounds 59-62 只新增 system / slicer 的 ad-hoc gate，不改默认门禁、不重生 baseline。

当前 reviewer 基线保持：fast 检查实际 `14/30`，full 检查实际 `29/30`，单端点 `7/8`。`DEFAULT_MAX_INFO = 30` 和 `DEFAULT_MAX_INFO_PER_ENDPOINT = 8` 不能作为修复失败的手段上调。

v3 的种子是前端驱动流程：session lifecycle、system clear-cache 的 UI 行为、dialog-confirm、palette-edit、settings-invalidation。这些需要 Playwright/browser 层扩展，不应继续用后端-only 请求硬凑。
