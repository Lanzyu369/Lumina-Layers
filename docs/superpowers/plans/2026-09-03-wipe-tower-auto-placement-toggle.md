# 擦料塔自动摆放设置开关实施计划

> **For Codex:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task by task. This worktree is already isolated; do not create commits unless the user asks.

**Goal:** 在设置中提供默认开启、可持久化且覆盖所有支持生成路径的“擦料塔自动摆放”开关。

**Architecture:** 保持 `core/wipe_tower_placement.py` 为唯一布局算法，不改变其求解规则。写入器通过一个显式布尔参数决定是否调用求解器。该设置从前端设置仓库经请求模型、工作进程和流水线上下文传到单件、色卡、拼图、批量合并及大画幅写入器，同时进入配方分享和问题报告复现信息。组合生成必须按最终整体几何重新求解，并且只有布局确实改变时才声明塔位覆盖。

**Tech Stack:** Python 3 / FastAPI / Pydantic / pytest；React 19 / TypeScript / Zustand / Vitest。

---

## Task 1：用回归测试锁定自动摆放开关契约

**Files:**
- Modify: `tests/test_bambu_3mf_wipe_tower_placement_unit.py`
- Test: `tests/test_bambu_3mf_wipe_tower_placement_unit.py`

1. 新增关闭自动摆放的写入器测试。
2. 断言关闭后不调用求解器、不改模板塔位，并输出明确的禁用诊断。
3. 保留开启状态下已有的布局与人工调整告警覆盖。

## Task 2：实现关闭开关后的写入器契约

**Files:**
- Modify: `utils/bambu_3mf_writer.py`
- Modify: `tests/test_bambu_3mf_wipe_tower_placement_unit.py`
- Modify: `tests/test_bambu_3mf_writer_unit.py`

1. 给 `BambuStudio3MFWriter` 与 `export_scene_with_bambu_metadata` 增加默认开启的可选参数，并补双语 API 文档。
2. 关闭时输出可诊断但不报警的 Lumina 元数据；开启时维持当前求解行为。
3. 运行写入器定向测试，确保默认行为不变且关闭值生效。

## Task 3：把开关贯通核心转换和所有导出路径

**Files:**
- Modify: `core/converter.py`
- Modify: `core/pipeline/s09_export_3mf.py`
- Modify: `utils/merged_bambu_3mf_writer.py`
- Modify: `api/workers/converter_workers.py`
- Modify: `api/routers/converter/generate.py`
- Modify: `api/schemas/converter.py`
- Modify: `tests/test_s09_export_3mf_unit.py`
- Modify: `tests/test_converter_batch_worker_unit.py`
- Modify: relevant converter router/merged-writer unit tests

1. 先扩展捕获参数的测试，断言关闭值能到达单件写入器、色卡、拼图、批量子项、批量合并写入器和大画幅写入器。
2. 在 Pydantic 请求模型中增加默认 `True` 的布尔字段。
3. 将字段经普通生成参数、转换上下文和 S09 写入器透传。
4. 拼图与批量合并按最终组合几何重新求解；只在实际调整时声明塔位覆盖。
5. 将字段经批量 multipart 表单、worker 调用与 `MergedBambu3MFWriter` 透传；关闭时合并布局也不运行求解器。
6. 将字段经大画幅 worker 上下文透传并运行各路径定向测试。

## Task 4：在设置页增加默认开启的持久化开关

**Files:**
- Modify: `api/schemas/system.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/stores/settingsStore.ts`
- Modify: `frontend/src/components/SettingsPanel.tsx`
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `frontend/src/stores/converter/store.ts`
- Modify: `tests/test_settings_api_unit.py`
- Modify: relevant frontend settings/converter-store tests

1. 先添加后端设置默认值/保存和前端设置默认值/后端同步/请求透传的失败测试。
2. 在用户设置模型和 Zustand 设置仓库中加入默认开启字段，兼容旧持久化数据。
3. 在设备设置卡片加入符合 `DESIGN.md` 的开关、双语说明和帮助提示；变更时使旧生成结果失效并尽力同步后端。
4. 普通、批量和大画幅请求都从同一设置字段取值。
5. 运行设置与请求构造定向测试。

## Task 5：保持配方分享和问题报告可复现

**Files:**
- Modify: `frontend/src/recipe/types.ts`
- Modify: `frontend/src/recipe/exportRecipe.ts`
- Modify: `frontend/src/recipe/importFlow.ts`
- Modify: `frontend/src/__tests__/recipe-export.test.ts`
- Modify: `frontend/src/__tests__/recipe-import-flow.test.ts`
- Modify: `frontend/src/utils/bugReportContext.ts`
- Modify: `frontend/src/api/feedback.ts`
- Modify: `api/routers/feedback.py`
- Modify: `api/feedback_index.py`
- Modify: matching frontend/backend feedback tests

1. 先扩展配方 round-trip 测试，断言关闭值导出后重新导入仍为关闭。
2. 更新配方类型、导出适配器和导入应用逻辑。
3. 先扩展问题报告测试，断言快照、票据和可读索引都包含该字段。
4. 更新前后端问题报告上下文和索引渲染。
5. 运行配方与问题报告定向测试。

## Task 6：发布说明、编码检查与最终验证

**Files:**
- Modify: `frontend/src/data/announcements.ts`
- Test: `frontend/src/__tests__/useAnnouncement.test.ts`
- Test: `frontend/src/__tests__/announcement-dialog.test.tsx`

1. 按北京时间 `2026-09-03` 新增双语公告，说明设置开关的用户可见效果。
2. 运行写入器、转换链、设置、配方、问题报告和公告的定向后端/前端测试。
3. 运行前端 TypeScript 类型检查。
4. 对所有触及的中文文件做 UTF-8 复读与乱码标记扫描。
5. 检查 `git diff --check`、工作树变更范围和残留进程；只有全部新鲜验证通过后才报告完成。
