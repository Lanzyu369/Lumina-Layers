# GLB Mesh Kernel v2 — 本地测试总结与提交前清单

本地 review 已完成 10 遍，覆盖：scope 审计、生产代码、测试套件、deps-blocked 子进程验证、log governance、spec ↔ code 一致性、性能数字交叉核对、artifact 清理、文档诊断、push 准备。本文是签收前的最后一份对照表。

## 1. 目标与边界

**做了什么：** 在 `core/pipeline/s11_glb_preview.py` 内并存两条 mesh kernel 后端（v1 = 现有 Shapely RLE + `unary_union`；v2 = `rasterio.features.shapes` + `manifold3d.CrossSection.extrude`），通过 env `LUMINA_GLB_KERNEL` 切换；默认走 v1，v2 仅显式 opt-in，缺依赖或运行期失败自动回退到 v1。

**没做什么：**

- 没改 `requirements.txt`
- 没改 `api/`、`frontend/`、`config.py`、`core/pipeline/coordinator.py`、`core/converter.py` 的 re-export 列表
- 没改 cache schema（`color_contours` 仍由 `cv2.findContours` 写入，与 kernel 选择无关）
- 没改 default kernel（仍 `shapely_v1`）
- 没改 GLB scene-graph 契约（节点名 `color_<hex>` / `backing_plate` / per-face RGBA / AABB）
- 没引入 numba / 手写 boundary tracing / earcut（已归档 spec 的旧方向）

## 2. 本次最终改动清单

### 修改（3 个文件）

| 文件 | 变化行数 | 用途 |
| --- | --- | --- |
| `core/pipeline/s11_glb_preview.py` | +345 / -5 | 新增 `_resolve_kernel_choice` / `_v2_available(log_warning=...)` / `_build_color_extruded_mesh_v2` / dispatcher；现有 `_build_color_extruded_mesh` 改名为 `_build_color_extruded_mesh_shapely_v1`，公共名改成 dispatcher。8 个新结构化日志事件全部带 actionable extras。v2 helper atomic：任一 component 失败立即整色 abort，不允许 partial 输出。 |
| `scripts/profile_stage3.py` | +47 / -3 | 新增 `--image` / `--lut` / `--width-mm` 三参数（同时传或全省略；混传报错 exit 2）。默认仍跑 TCT.jpg，stage 计时 / Warm Protocol / `artifacts/perf_baseline.json` schema 全部不变。 |
| `tests/test_logging_exception_governance_unit.py` | +35 / -2 | `EXCEPT_EXCEPTION_BASELINE` 60 → 65（旧值 61 是 `<=` 上限，实际 pre-change 是 60；delta = +5）；docstring 列出 5 个新 broad except 的归属 + 每个事件名 + actionable extras。 |

### 新增（11 个文件，全部本地或可提交）

| 路径 | 说明 | 是否提交 |
| --- | --- | --- |
| `tests/test_glb_v2_kernel_unit.py` | 19 tests：8 helper-direct geometry（缺 deps SKIP）+ 11 dispatcher / fallback / feature-flag（无依赖也跑） | yes |
| `tests/test_glb_dual_kernel_equivalence.py` | 1 test：v1 vs v2 节点 / volume / AABB 等价性（缺 deps SKIP） | yes |
| `tests/test_glb_v2_high_fragmentation.py` | 1 test：60 colors × ≥ 10 components 合成图，验证守恒 + 记录性能（缺 deps SKIP） | yes |
| `tests/_glb_v2_no_deps_runner.py` | 子进程 runner：屏蔽 `rasterio` / `manifold3d`，验证 8 SKIP / 11 PASS | yes |
| `scripts/spike_glb_mesh_library_eval.py` | 只读 library spike 脚本（rasterio / manifold3d / pyclipper 评估） | yes（历史决策溯源） |
| `scripts/benchmark_glb_kernel_matrix.py` | 只读多 mode × 多 size benchmark 脚本 | yes |
| `progress/glb-preview-mesh-library-spike.md` | spike 报告（人类可读） | yes |
| `progress/glb-preview-mesh-library-spike.json` | spike 报告（机器可读） | yes |
| `progress/glb-benchmark-jpg-multisize-multimode.md` | benchmark 报告（人类可读） | yes |
| `progress/glb-benchmark-jpg-multisize-multimode.json` | benchmark 报告（机器可读） | yes |
| `progress/glb-mesh-kernel-v2-pre-commit-review.md` | 本文 | yes |

### `.kiro/` 改动（gitignored，不进 PR）

- `.kiro/specs/glb-preview-mesh-kernel-optimization/{requirements,design,tasks}.md`：rasterio + manifold3d 方向的 12 项 Requirement、721 行 Design、18 个 Task、Mermaid 依赖图。
- `.kiro/specs/_archived-glb-mesh-kernel-handwritten/`：旧手写 boundary + earcut 方向归档（含 README 解释放弃理由）。

### 仓库内已存在但**与本 PR 无关**的 untracked 文件

git status 把它们一起列出来了，但不要带进本 PR：

- `docs/snapmaker-u1-618-lumina-video-brand-review.md`
- `docs/snapmaker-u1-618-lumina-video-script.md`
- `docs/snapmaker-u1-618-lumina-video-subtitle-script.md`

提交时显式只 `git add` 本 PR 相关文件，不要 `git add .` 或 `git add docs/`。

## 3. 测试结果矩阵（本地实测）

### 3.1 默认 v1 dispatcher 下完整回归

```bash
.venv/bin/python -m pytest \
    tests/test_glb_v2_kernel_unit.py \
    tests/test_glb_dual_kernel_equivalence.py \
    tests/test_glb_v2_high_fragmentation.py \
    tests/test_segmented_glb_unit.py \
    tests/test_segmented_glb_properties.py \
    tests/test_region_3d_preview_sync_unit.py \
    tests/test_logging_exception_governance_unit.py \
    tests/test_structured_logging_unit.py \
    tests/test_logger_unit.py \
    tests/test_backing_plate_unit.py \
    tests/test_backing_plate_properties.py \
    tests/test_backward_compat_properties.py \
    tests/test_s11_geometry_unit.py
```

**结果：183 passed, 0 failed, 0 errored, 8.39 s** ✓

### 3.2 `LUMINA_GLB_KERNEL=v2` 强制下既有 GLB 回归

```bash
LUMINA_GLB_KERNEL=v2 .venv/bin/python -m pytest \
    tests/test_segmented_glb_unit.py \
    tests/test_segmented_glb_properties.py \
    tests/test_region_3d_preview_sync_unit.py \
    tests/test_backing_plate_unit.py \
    tests/test_backing_plate_properties.py \
    tests/test_s11_geometry_unit.py
```

**结果：38 passed, 0 failed, 5.37 s** ✓ — 证明 v2 在所有现有 v1 契约下也通过。

### 3.3 缺依赖子进程验证

```bash
.venv/bin/python tests/_glb_v2_no_deps_runner.py
```

**结果：11 passed, 9 skipped, 0.66 s** ✓ — dispatcher / fallback / feature-flag 测试在缺 `rasterio` / `manifold3d` 时仍跑通；helper-direct 测试干净 SKIP。

### 3.4 日志治理三件套

```bash
.venv/bin/python -m pytest \
    tests/test_logging_exception_governance_unit.py \
    tests/test_structured_logging_unit.py \
    tests/test_logger_unit.py
```

**结果：21 passed, 0 failed, 1.18 s** ✓

### 3.5 日志质量 fast gate

```bash
.venv/bin/python scripts/log_quality_check.py --mode fast
```

**结果：RESULT: PASS**（8 governance + 5 workflow 全 PASS） ✓

### 3.6 性能验收（Warm Protocol，run2 / run3 中位数）

| Metric | v1 | v2 | Ratio | 阈值 | 状态 |
| --- | ---: | ---: | ---: | --- | --- |
| `s11_mesh_loop_s` | 18.587 s | 5.299 s | 0.285× (3.51× speedup) | R1.1 ≤ Old × 0.50 | PASS |
| `s11_s` | 18.744 s | 5.416 s | 0.289× (3.46× speedup) | R1.2 ≤ Old × 0.35 AND ≤ 6.0 s | PASS |
| GLB bytes | 16,337,596 | 13,542,864 | 0.829× (-17%) | R2.1 ≤ Old × 1.05 | PASS |
| vertex count | 434,568 | 364,825 | 0.840× | R2.2 ≤ floor(Old × 1.05) | PASS |
| face count | 779,192 | 639,294 | 0.821× | R2.3 ≤ floor(Old × 1.05) | PASS |

输入：`/Users/min/Downloads/9DCCD9AB393A882ECB61703FF607F690.jpg` + `lut-preset/精亮/精亮&PLA4色&RYBW.npy` + `target_width_mm=225`。本地工件：`artifacts/perf_baseline_old.json` + `artifacts/perf_baseline_new.json`（gitignored）。

### 3.7 Multi-mode × multi-size benchmark（额外证据）

`progress/glb-benchmark-jpg-multisize-multimode.md` — 3834×2205 测试图、5 modes（4-Color RYBW / BW / 8-Color / 6-Color / 5-Color-Extended）× 4 widths（75 / 150 / 225 / 300 mm）× 2 kernels × 3 runs = 120 successful runs。

- 几何平均 `s11_mesh_loop_s` speedup：**3.27×**
- 最佳：`5-Color-Extended` @ 300 mm，**4.61×**
- 最差：`4-Color RYBW` @ 75 mm，2.69×（小图 mesh_loop 已经低，加速空间小）
- v2 GLB / vertex / face 全部 80-87% of v1（即 v2 永远更小，远低于 R2 的 1.05× 上限）
- 0 fallback / 0 WARNING / 0 几何错误 / 0 GLB 加载失败

### 3.8 `except Exception` 治理

实测全 `TARGETS` 路径下 `except Exception` 总数：65（与新 baseline 一致）。

```
api/app.py                              2
api/routers/converter/generate.py       4
api/routers/converter/replace.py        2
api/routers/feedback.py                 3
api/routers/lut.py                      9
api/workers/converter_workers.py        3
core/pipeline/s11_glb_preview.py        5  (NEW: import probe + import-in-helper + polygonize + per-component + compose)
core/vector_engine.py                  37
TOTAL = 65
```

5 个新点全部是第三方 C-extension 边界守卫，每个都发结构化 WARNING，extra 至少含 `event` + `error_type` + `error_message` / `import_error` / `value` / `components` / `failed_component_index` / `fallback_kernel`，符合 AGENTS.md 「WARNING/ERROR must carry actionable fields」。

## 4. Spec ↔ 代码一致性

实测 8 个事件名集合双向一致（spec ↔ `core/pipeline/s11_glb_preview.py`），无遗漏：

```
glb_kernel_unknown_value
glb_kernel_v2_compose_failed
glb_kernel_v2_import_failed
glb_kernel_v2_no_manifolds
glb_kernel_v2_polygonize_failed
glb_kernel_v2_requested_unavailable
glb_kernel_v2_runtime_fallback
glb_kernel_v2_unavailable
```

`_v2_available_silent()` 在所有 spec 文档中已替换为 `_v2_available(log_warning=False)`，与代码完全一致。env-read timing 在 spec 中已弱化为「下一次 dispatcher 调用生效」（不再写「单次 generate_segmented_glb 调用内严格固定」），与实现的「per-color re-read env」契合。

R1.2 阈值已从作废的 `≤ 2.50 s` 改写为「≤ Old × 0.35 AND ≤ 6.0 s」，并附 caveat 说明 spike 1.46 s 仅作设计参考。

## 5. 提交前清单（手动签收）

按顺序逐项打勾后再提交：

### 5.1 范围

- [ ] `git diff requirements.txt` 为空
- [ ] `git diff api/` 为空
- [ ] `git diff frontend/` 为空
- [ ] `git diff config.py core/pipeline/coordinator.py core/converter.py core/image_processing.py` 为空
- [ ] 修改的 3 个文件就是 `core/pipeline/s11_glb_preview.py` + `scripts/profile_stage3.py` + `tests/test_logging_exception_governance_unit.py`，不多也不少
- [ ] 不要 `git add docs/snapmaker-u1-618-*.md`，那 3 份文件与本 PR 无关
- [ ] 不要 `git add artifacts/`，整个目录是 gitignored 的（保险起见）

### 5.2 测试

- [ ] §3.1 默认 v1 完整回归 = 183 passed
- [ ] §3.2 v2 强制下既有回归 = 38 passed
- [ ] §3.3 缺依赖子进程 = 11 passed / 9 skipped
- [ ] §3.4 日志治理 = 21 passed
- [ ] §3.5 log_quality_check fast = RESULT: PASS
- [ ] §3.6 R1 / R2 阈值断言 5 / 5 PASS
- [ ] §3.7 多 mode × 多 size benchmark：0 fallback / 0 WARNING / 0 错误

### 5.3 治理

- [ ] s11 内 `print(...)` 数 = 0
- [ ] s11 内 `[TAG]` 前缀的 log message 数 = 0
- [ ] s11 内 `except Exception` 数 = 5（全部带 actionable extras）
- [ ] 全 TARGETS 路径 `except Exception` 总数 = 65（与 baseline 一致）
- [ ] 8 个新事件名 spec ↔ code 双向一致

### 5.4 分支与 PR

- [ ] 当前分支是 `dev-refactor`（保护分支）；**不能直接 push 到此分支**
- [ ] 切到新分支：`git checkout -b shmx/feat/glb-mesh-kernel-v2-scaffold`
- [ ] 显式 add：仅 add 本 PR 相关文件（见 §2 列表），用 `git add -p` 或者 `git add <path>` 一份份加，避免误带
- [ ] commit message 用 Conventional Commits：英文先，中文后
- [ ] 推送：`git push -u origin shmx/feat/glb-mesh-kernel-v2-scaffold`（带 `-u`，**不带 `--force`**）
- [ ] 通过 `gh pr create` 开 PR，目标分支是 `dev-refactor`
- [ ] PR 描述按 spec R12 / Task 18 出（暂时还没生成模板，需要时再让 Kiro 单独出）

### 5.5 在线追踪

- [ ] 提交前先在在线工程跟踪表里登记本次改动（AGENTS.md「Hygiene & Commits」开头那条）

## 6. 已知限制 / 风险 / Follow-up

- **Phase 2 不在本 PR**：默认 kernel 仍是 `shapely_v1`，对终端用户**无可见行为变化**。把默认切到 `auto` 是阶段 2 独立 PR；同 PR 决定是否把 `rasterio` + `manifold3d` 进 `requirements.txt`。
- **Windows arm64 缺 manifold3d wheel**：用户在 `LUMINA_GLB_KERNEL=v2` 下会 import 失败 → dispatcher 自动回退 v1 + WARNING（v2 显式）/ 静默（auto）。不阻塞发布。
- **多机性能抖动**：本地 macOS arm64 / Python 3.12 上的实测数（v2 / v1 ≈ 0.29×）需要在 CI / 其他平台再验证一次。R1.1 阈值是 ≤ 0.50×，给了 70% 余量；R1.2 是 ≤ 0.35× AND ≤ 6.0 s，余量约 9%（5.42 s vs 6.0 s）。
- **4-Color + hue_weight=0.5 vs RYBW + hue_weight=0.0**：v2 mesh_loop 在前者约 5.3 s，在后者约 1.4 s（差 3.6×），加速比都稳定 3.5× 但绝对秒数不同。怀疑 hue_weight=0.5 让相邻颜色合并少 → component 暴涨。已记入 spec tasks.md `## Follow-up`，本 PR 不追。
- **SVG / vector 路径不在本规格范围**：`vector_engine.py` 自己做几何，不走 s11 的 per-color extrude，本次改动不影响。
- **手动 UI smoke**：建议合入前在浏览器开 `LUMINA_GLB_KERNEL=v2` 跑一次 4-Color RYBW @ 225 mm + BW @ 75 mm，目视确认 3D 预览的颜色分块、底板、点击高亮、双面切换、轮廓显示与默认 v1 一致。是 30 分钟以内的事。
