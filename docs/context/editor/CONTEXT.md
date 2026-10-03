# 编辑提交、预览与生成

本说明覆盖颜色替换、配方、选区、撤销/重做和生成之间的状态契约。
前端保存用户输入并编排请求；已提交作品由服务端现有 session、preview cache、
replacement history 和持久 mask 共同承载。PNG、GLB、图层预览是派生工件。
提交回执与请求队列不另存一套作品或历史。

## 版本与操作各自负责什么

| 标识 | 用途与归属 |
| --- | --- |
| `operation_id` | 标识一次内容操作；丢失响应后查询同一个操作，不能重放 undo/redo/toggle |
| `editor_content_revision` / selection 文档中的 `content_revision` | 服务端确认的作品内容版本；前端不能自行 `+1` |
| `selection_revision` | 共享选区版本；选区改变和作品内容改变是不同事件 |
| preview request revision、session、epoch | 丢弃旧请求对当前页面的写入；取消请求不证明服务端没有提交 |
| GLB token/CAS | 只让匹配当前内容的派生预览发布，不能替代内容提交确认 |

同 session 的内容操作在第一次 `await` 前同步占位并串行执行。
选区变更等待内容提交；依赖选区的编辑和生成等待选区提交。
旧响应无论成功或失败，若可能已在服务端执行，都对账原 operation receipt，
不能直接覆盖新页面，也不能仅靠丢弃响应解除提交屏障。

## 回执与响应丢失

接口是 `GET /api/convert/editor-commit/{session_id}/{operation_id}`，
由 [editor_commit.py](../../../api/editor_commit.py) 管理每个 session 最近
64 条确认记录。重复 operation id 在写缓存、历史和会话前被拒绝为 409，
调用方应查询原回执。

| 状态 | 客户端行为 |
| --- | --- |
| `committed` | 先应用完整业务结果投影，再同步权威内容/选区版本并释放屏障 |
| `failed` | 确认尚未发布；恢复该操作保存的旧状态，允许后续编辑 |
| `pending` / `unknown` / 查询失败 | 保留草稿与错误上下文，暂停依赖编辑、选区和生成，等待显式同步 |

已知内容操作的 committed 回执若缺少业务结果，也不能只改版本号就解除屏障。
业务投影包括预览 URL、替换区域、配方、自由色、计数、基础层参数、动态结果和
undo/redo 标志；不复制 RGB 数组、mask、cache manifest 或 history checkpoint。
回执数量有界不等于业务列表可以截断：129 项列表必须保留第 129 项及对应计数。
响应模型中的可选 `null` 表示未提供，空列表表示明确清空；reset 的明确清空语义单独保留。
选区文档补读失败不能反过来否定已经确认的内容提交。

## 发布与回滚边界

[replace.py](../../../api/routers/converter/replace.py) 复用现有缓存事务，
按 `replacement_history_lock -> selection lock` 顺序协调 session 内的修改。
提交前失败可以恢复工作副本；`cache.commit()` 成功后事务的 `published` 标记
同时保护内存和 artifact-backed 缓存，不能再恢复旧数组或旧会话字段。
发布后历史、回执或派生阶段失败时，保留已发布作品和真实确认状态：未收敛的操作保持
pending/unknown，已发布的 committed 回执不伪报失败。非 200 响应不等于已经回滚。

GLB 调度在内容回执之后执行。GLB 失败只记录派生错误，并由既有 token/CAS
阻止旧结果发布；不能撤销二维内容、材料矩阵、配方或历史，也不要求生成等待无关 GLB。

## 配方的空间目标与基础输入

已应用配方使用应用时保存的 `recipe_override_applied_masks` 位压缩快照，
由 [selection_state.py](../../../api/selection_state.py) 的
`resolve_recipe_override_masks` 统一解析。具备快照键的 session 若 mask 缺失、为空、
损坏或形状不匹配，必须明确失败；不得改用后续临时选区或扩大为全图。
只有没有快照键的旧 session 才使用现有兼容路径。

配方增层属于 `recipe_overrides` 派生状态，不写回基础 `color_layers` /
`layer_height_mm`，避免自动预览重建 session 并清空编辑。
真实来源、几何、基础输入变化仍触发原预览失效；生成通过既有配方层数解析取得实际层数。
Escape 关闭颜色二维子页本身不承担作品回滚，没有证据支持把它改成清空编辑。

## 生成快照与下载

标准、拼图和大画幅生成复用
[generate.py](../../../api/routers/converter/generate.py) 的快照规则：

1. 在 session 的 history/selection 短锁内校验客户端的两种 revision，并捕获完整输入。
2. 独立复制可变输入；缓存工件路径保持引用，数组与嵌套编辑字段不与实时 session 混用。
3. 锁外组装参数，worker 入队前和完成后再次检查内容/选区版本；真实过期请求仍返回 409。
4. 只把匹配输入版本的成功文件注册为当前结果；响应携带实际使用的版本。

最终 `.3mf`、`.zip`、导出配方和分享卡属于 TTL 下载，使用独立注册身份，
关闭或切换源 session 后仍应可下载。PNG、GLB、中间数组可以随 session 清理。
本次生成失败不能发布新成功下载，也不能删除用户此前的成功作品和下载。
S06 中浮雕、掐丝、五色朝上或磁铁孔槽加工失败通过现有阶段错误出口终止；
所选高度图读取失败或缺失也不能被平面模型替代。普通平面入口和兼容分支优先级保持独立。

## 维护与验证入口

- 前端编排：[converter store](../../../frontend/src/stores/converter/store.ts)、
  [editorRevision](../../../frontend/src/stores/converter/editorRevision.ts)、
  [previewCommitGuard](../../../frontend/src/stores/converter/previewCommitGuard.ts)。
- 回执与发布行为：[editor commit tests](../../../tests/test_editor_commit_unit.py)、
  [真实替色 endpoint tests](../../../tests/test_converter_replace_integration_unit.py)、
  [配方 tests](../../../tests/test_converter_recipe_override_unit.py)。
- 生成输入、旧下载与阶段失败：[生成 tests](../../../tests/test_converter_generate_unit.py)、
  [S06 tests](../../../tests/test_s06_failure_unit.py)。
- 前端受控时序：[回执对账](../../../frontend/src/__tests__/converter-store-commit-reconciliation.test.ts)、
  [选区竞态](../../../frontend/src/__tests__/converter-store-selection-race.test.ts)、
  [生成版本](../../../frontend/src/__tests__/converter-store-generate-revision-sync.test.ts)。

验证必须比较 session、RGB/材料矩阵、mask、历史和版本，不能只检查 HTTP 200 或 PNG。
回归场景包括 A 区域配方后改选非重叠 B、响应丢失、提交前失败、发布后失败、连续编辑、
编辑期间生成及源 session 关闭后下载。前端测试通过 `python scripts/run_vitest.py` 运行。
本地确定性证据不能证明所有现场生成错误具有同一根因；现场诊断仍需要 request/session、
operation id、内容/选区版本、提交阶段、HTTP 状态与对应素材，参见
[日志指南](../../logging-guide.md)。
