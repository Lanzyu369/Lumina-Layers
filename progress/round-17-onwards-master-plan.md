# Round 17+ Master Plan — Full LOG Governance Coverage

> Authoritative plan to drive the LOG governance program from round-16 (~27% coverage) to **100% backend coverage**, then to a tagged release `log-governance-v2`.
>
> **Pre-state** (post-PR-#107):
> - `dev-refactor` HEAD = `7b80515`
> - pytest = 2132 passed, 8 skipped
> - Default canonical 9-step gate `startup,lut_list,lut_colors,preview,generate,replace,extract,merge_8color,merge_5color_ext` = INFO 28/30, per-EP 7/8, **5 canaries fire**
> - `EXTRACTOR_STRUCTURED_EVENTS` = 7
> - `INFO budget headroom`: **2 lines** in default canonical, **1 endpoint** in per-EP cap
>
> **Gap to 100%**:
> - The original `progress/governance-roadmap.md` §5 listed ~16 uncovered workflows but **missed** the `api/routers/converter/` subdirectory (7 sub-router files, ~22 endpoints) and undercounted `single_stage` (14 endpoints, only 1 listed).
> - **Real uncovered count: ~45 mutating endpoints across 8 router families.**

## 1. Inventory of remaining work

### 1.1 Already covered (rounds 7-16)

| Family | Endpoints | Canaries |
|---|---|---|
| `extractor.py` (7 endpoints) | extract / manual-fix / merge-8color / merge-5color-extended / preview-wb / rotate / confirm-palette | 7 (full coverage) |
| `converter/replace.py` (1 of 12) | region-replace | `converter_region_replace_timing` |
| `converter/preview.py` (1 of 6) | preview (vector branch) | `vector_branch_done`, `vector_matched_rgb_overrides_applied` |
| `converter/generate.py` (1 of 3) | generate (vector branch) | `vector_branch_done`, `vector_3mf_exported` |

### 1.2 Uncovered (rounds 17+ targets)

| Family | File | New canary count | Default-canonical candidate? |
|---|---|---|---|
| Converter Replace | `converter/replace.py` (11 of 12) | **11** | None (all ad-hoc) |
| Converter Generate | `converter/generate.py` (2 of 3) | **2** (large-format, batch) | None |
| Converter Preview | `converter/preview.py` (3 of 6) | **3** (auto-detect-colors, crop, upload-heightmap) | None |
| Converter Puzzle | `converter/puzzle.py` (2 of 2) | **2** (puzzle-layout-preview, generate-puzzle) | None |
| Converter Cleanup | `converter/cleanup.py` (1 of 1) | **1** (cleanup-session-files) | None |
| Single Stage | `single_stage.py` (12 of 14) | **12** | `extract-single-stage` (1 candidate, joins canonical) |
| Calibration | `calibration.py` (2 of 2) | **2** | None |
| Five Color | `five_color.py` (3 of 4) | **3** (clear-cache, query, generate-swatch) | None |
| Vectorizer | `vectorizer.py` (1 of 2) | **1** (POST root /api/vectorize) | None |
| Slicer | `slicer.py` (1 of 2) | **1** (launch) | None |
| LUT | `lut.py` (5 of 12) | **5** (upload, merge, compare, predict-recipe-color, search-recipes) | None |
| System | `system.py` (2-3 of 7) | **2-3** (image-preview, save-settings, optionally clear-cache) | None |

**Totals**:
- 11+2+3+2+1+12+2+3+1+1+5+3 = **~46 new canaries**
- Default canonical: stays 9-step → 10-step (only `extract-single-stage` joins). INFO 28 → 29.
- Per-EP: stays at 7/8 ceiling (no new emission to existing endpoints).

### 1.3 Skipped (out of scope for v2)

- Pure GET reads: `/api/lut/list`, `/api/lut/catalog`, `/api/lut/{n}/colors`, `/api/lut/{n}/info`, `/api/lut/{n}/details`, `/api/system/printers|slicers|settings|stats`, `/api/slicer/detect`, `/api/vectorize/defaults`, `/api/five-color/base-colors`, `/api/extractor/gradient-card-materials` (GET), `/api/extractor/material-solver-caches` (GET), `/api/convert/bed-sizes|bed-preview|layer-images|glb-status` (GET), `/api/convert/gradient-groups/{id}` (GET).
- Trivial lifecycle: `/api/session/heartbeat`, `/api/session/close`.
- Frontend-driven flows (dialog-confirm, palette-edit, settings-invalidation): require Playwright/browser automation extension to `scripts/log_quality_check.py`. Defer to round-63+ as a separate "log-governance-v3" program.

## 2. PR / Round structure

8 PRs, ~62 rounds, ~25-35h cumulative GPT execution time. Each PR follows the round-12-to-16 batch pattern (one branch, multiple commits, single PR, Cascade autonomous merge per PR).

| PR | Rounds | Branch | Endpoints | Commits | Estimated GPT time |
|---|---|---|---|---|---|
| **#108** | 17 (D-class) | `docs/refresh-governance-roadmap-v2` | 0 (doc only) | 1 | ~1h |
| **#109** | 18-23 | `feat/log-converter-replace-pt1-canaries` | 6 | 6 | ~5h |
| **#110** | 24-29 | `feat/log-converter-replace-pt2-canaries` | 6 | 6 | ~5h |
| **#111** | 30-35 | `feat/log-converter-misc-canaries` | 6 (gen-large-format, batch, puzzle ×2, auto-detect, cleanup) | 6 | ~5h |
| **#112** | 36-41 | `feat/log-single-stage-pt1-canaries` | 6 (extract-single-stage **joins canonical**, fit-stage-a, gradient-card ×4) | 6 | ~5h |
| **#113** | 42-47 | `feat/log-single-stage-pt2-canaries` | 6 (export, import, solver-cache ×4) | 6 | ~5h |
| **#114** | 48-53 | `feat/log-misc-routers-canaries` | 6 (calibration ×2, five_color ×3, vectorizer) | 6 | ~5h |
| **#115** | 54-58 | `feat/log-lut-family-canaries` | 5 (upload, merge, compare, predict-recipe, search-recipes) | 5 | ~4h |
| **#120 expected** | 59-62 | `feat/log-system-canaries-and-v2-retro` | 3 + retro (image-preview, save-settings, slicer/launch + retro docs; tag is post-merge) | 4 | ~4h |

**Total**: 9 PRs, ~47 endpoints + 1 doc + 1 retro+tag = 49 commits, **rounds 17-62**.

## 3. INFO budget evolution

| After PR | Default canonical INFO | Headroom | Per-EP max | New canaries cumulative |
|---|---|---|---|---|
| Round 16 (now) | 28/30 | 2 | 7/8 | 5 (extractor) + 2 (vector/replace) = 7 |
| #108 (doc refresh) | 28/30 | 2 | 7/8 | 7 |
| #109-#111 (converter ×18 ad-hoc) | 28/30 | 2 | 7/8 | 25 |
| #112 (single_stage pt1, +1 to canonical) | **29/30** | **1** | 7/8 | 31 |
| #113 (single_stage pt2 ad-hoc) | 29/30 | 1 | 7/8 | 37 |
| #114 (misc ad-hoc) | 29/30 | 1 | 7/8 | 43 |
| #115 (LUT ad-hoc) | 29/30 | 1 | 7/8 | 48 |
| #120 expected (system/slicer ad-hoc, +retro) | 29/30 | 1 | 7/8 | 51 |

The final batch did not need a DEBUG demotion.
If future default-canonical headroom is exhausted, use the round-7 pattern in a dedicated governance PR. **Do not raise thresholds.**

## 4. Authority chain (unchanged from rounds 7-16)

```
GPT-5.5 (executes per-PR mega-prompt)
    -> opens ONE PR per batch (commits = endpoint count + optional doc/test commits)
    -> Cascade (runs §9 verification matrix across the branch)
    -> Cascade (autonomous squash-merge if PASS, autonomous rejection if FAIL)
    -> Cascade (writes next PR's mega-prompt and hands to user)
```

User retains override authority but does not need to be in the loop for individual PRs. Cascade may autonomously merge the entire 9-PR sequence given the standing authorization granted at round 11.

If a batch hits a real blocker, GPT writes `progress/round-NN-blocker.md` and stops. Cascade reads, decides whether to escalate to user or to revise the prompt and retry.

If a batch exhausts GPT context, GPT writes `progress/round-NN-resume-state.md`. Subsequent GPT session resumes from there.

## 5. Per-PR prompt template (Cascade writes one before each batch)

Each PR's mega-prompt is its own self-contained file at `progress/round-NN-prompt.md` and follows the round-12-to-16 prompt structure:
- §0 authority + merge protocol
- §1 mission summary
- §2 per-round specs (Investigator data + emission spec + workflow runner step + tests)
- §3 cross-round shared concerns (helpers, INFO budget bookkeeping)
- §4 subagent decomposition (6 roles, repeated per round)
- §5 verification handoff template (paste into PR body)
- §6 constraints (do not violate)
- §7 failure modes
- §8 中文摘要

Cascade writes the next PR's prompt only after the previous PR has been merged, so the prompt can reference real merged-state facts (commit SHAs, test counts, etc.).

## 6. Reviewer baselines

Baselines are regenerated only when the **default canonical** workflow legitimately changes:
- PR #112 (single_stage pt1) is the **only batch** in this program that mutates the default canonical (adds `extract-single-stage` step). It regenerates `progress/log_audit_full_reviewer.json` and `progress/log_audit_fast_reviewer.json` to a 10-step shape.
- PR #108 also regenerates them but only the documented INFO numbers — the workflow shape stays at 9-step.
- PRs #109-#111, #113, #118, #119, and the expected #120 do **not** regenerate baselines (their canaries are ad-hoc gates only).

## 7. Tag and release point

After the final system/slicer retrospective PR lands and §9 verifies green:
- Cascade tags `log-governance-v2` on `dev-refactor` HEAD.
- Tag message documents: rounds 7-62, ~51 canaries, 100% backend mutation coverage, frontend-driven flows deferred to v3.
- `progress/governance-roadmap.md` is reset to v2 baseline reflecting full coverage. The §5 "Uncovered" list shrinks to the 3 frontend-driven flows.

## 8. Risk register

| Risk | Mitigation |
|---|---|
| Default canonical exceeds 30 INFO | DEBUG-demote in a dedicated governance PR; never raise threshold |
| Per-EP cap exceeded on existing endpoint | Refactor canary to be the only INFO emission on that endpoint |
| Workflow runner can't synthesize fixture for some endpoint | Document blocker; consider real on-disk fixture (last resort with Reviewer approval per roadmap §5) |
| Worker pool / subprocess endpoint emits log line outside main process | Verify `LUMINA_LOG_INIT_BY_PARENT=1` propagation; guard with structured_logging unit test |
| GPT batch hits context limit mid-PR | Resume-state protocol; subsequent GPT session resumes from `progress/round-NN-resume-state.md` |
| Two consecutive PRs touch same module and merge-conflict | Cascade rebases the second branch onto the first's merge commit before §9 verification |
| Some endpoints turn out trivial / not worth canary | Reviewer may downgrade to "skip with rationale" in PR's investigator report; final canary count may shrink from 46 to ~42 |

## 9. Out of scope (explicit)

- Frontend tests / Vitest / Playwright additions
- New product features
- Refactoring `core/*` or worker pool
- Changing `DEFAULT_MAX_INFO` or `DEFAULT_MAX_INFO_PER_ENDPOINT`
- Adding new external loggers to the normalization set
- Touching `audit_logs.py` or `structured_logging.py` beyond pass-through whitelist updates
- Performance optimization (separate program)

## 10. Cascade's running checklist (kept here, not in user-facing notes)

- [x] PR #108 merged → write PR #109 prompt
- [x] PR #109 merged → write PR #110 prompt
- [x] PR #110 merged → write PR #111 prompt
- [x] PR #111 merged → write PR #112 prompt
- [x] PR #112 merged (canonical 9→10 step) → write PR #113 prompt
- [x] PR #113 merged → write next misc-router prompt
- [x] Misc-router governance PR merged → write LUT prompt
- [x] LUT governance PR #119 merged → write final system/slicer prompt
- [x] Final PR #120 expected → Cascade verifies, squash-merges, tags `log-governance-v2`, archives plan, sends final acceptance to user

## 11. Final state

Actual governance execution used the planned round sequence but repository PR numbers shifted because non-governance work landed between batches.
The v2 closeout should be read as PRs #108-#120 with interleaved repository history, ending in the expected final PR #120 for rounds 59-62.

Actual canary batches:

| PR | Rounds | Result |
|---:|---|---|
| #108 | 17 | Roadmap refresh opened the v2 program |
| #109 | 18-23 | Converter replace pt1 canaries |
| #110 | 24-29 | Converter replace pt2 canaries |
| #111 | 30-35 | Converter generate/preview/puzzle/cleanup canaries |
| #112 | 36-41 | Single-stage pt1 canaries; default canonical changed 9 -> 10 |
| #113 | 42-47 | Single-stage pt2 canaries |
| #118 | 48-53 | Calibration, five-color, and vectorizer canaries |
| #119 | 54-58 | LUT family canaries |
| #120 expected | 59-62 | System image-preview, system save-settings, slicer launch, and v2 retrospective docs |

Final verified source facts:

- Cumulative v2 canary count remains 51 by the master-plan accounting.
- `REQUIRED_STRUCTURED_EVENTS` is now a 9-way union: vector, extractor, converter, calibration, five-color, vectorizer, LUT, system, slicer.
- The current union contains 78 structured event names because it includes branch/debug inventory as well as INFO success canaries.
- `TARGETS` gained `api/routers/system.py` and `api/routers/slicer.py`; the current list has 38 entries in this repository tree.
- Default canonical stays 10-step after #112: `startup,lut_list,lut_colors,preview,generate,replace,extract_single_stage,extract,merge_8color,merge_5color_ext`.
- Reviewer baseline checks stay frozen at fast actual `14/30`, full actual `29/30`, and per-endpoint actual `7/8`.
- Rounds 59-62 do not change `DEFAULT_WORKFLOW`, threshold constants, reviewer baseline files, `core/*`, or `utils/*`.

Verifier-level fixture amendments that future programs should remember:

- #112 established the canonical 9 -> 10 baseline regeneration pattern.
- #113 preserved single-stage pt2 as ad-hoc-only and kept baseline files unchanged.
- #117 is the standing precedent for verifier-level fixture repair when the implementation is correct but runner infrastructure is too narrow.
- #119 established the async/multipart and session-bound LUT fixture precedent reused by the final batch.

Standing handoff for v3:

- Session lifecycle flows: `/api/session/heartbeat`, `/api/session/close`.
- Browser-confirmed cache flows, including `/api/system/clear-cache` as exercised by the frontend.
- Dialog-confirm, palette-edit, and settings-invalidation flows that require Playwright/browser orchestration.
- No PR #121 prompt is planned for v2; the next program should be explicitly scoped as log-governance-v3.

---

## 中文摘要

这份是从 round 17 推进到 LOG 治理 v2 (100% 后端覆盖) 的总规划。原 `governance-roadmap.md` §5 严重低估工作量——它把 `api/routers/converter/` 7 个子路由当成不存在，把 `single_stage` 14 个端点只算成 1 个。真实情况是 8 个 router 家族里还有 **~46 个未治理的 mutating endpoint**。

按 round 12-16 的批量模式拆成 **9 个 PR、~62 个 round**，每个 PR 6 个 commit 左右：

- PR #108 (round 17): roadmap 文档刷新（D 类，1 commit）
- PR #109-#111: Converter 家族 18 个端点
- PR #112-#113: single_stage 12 个端点（其中 `extract-single-stage` 入默认 canonical 9→10 步）
- PR #114: calibration + five_color + vectorizer + slicer 6 个端点
- PR #119: LUT 5 个 POST/会话端点
- PR #120 预期: system 2 个端点 + slicer launch + 终结 retrospective；tag `log-governance-v2` 由 Cascade 合并后执行

**协议**：与 round 11、round 12-16 完全一致——GPT 执行单个 PR、Cascade 自主验收 squash-merge、Cascade 写下一个 PR 的 mega-prompt。用户在 round 11 时给的"自主合并、跑完整个程序"授权延续到本程序结束。

**INFO 预算**：默认 canonical 从 28/30 升到 29/30（仅 PR #112 那一次 +1），剩 1 槽留给未来。其他 canary 全在 ad-hoc gate，不影响默认门禁。最终批次没有做 DEBUG-demote，也绝不调阈值。

**前端驱动流程**（session lifecycle / clear-cache UI / dialog-confirm / palette-edit / settings-invalidation）需要扩 `scripts/log_quality_check.py` 加入 Playwright，工程量大，**留给后续 v3 程序**，不在 v2 范围。

**终态**：约 51 个累计 canary，9 路 structured-event union，默认 canonical 固定在 10 步，结束于 `log-governance-v2` tag。
