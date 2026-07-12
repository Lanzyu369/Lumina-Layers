# 云耗材与云 LUT 资源中心 v2 设计

状态：二次设计复核修订稿
日期：2026-07-10
目标仓库：Lumina Studio、Lumina Material Registry、Lumina Materials
替代范围：现有“耗材库 / 云端耗材”和“LUT 库 / 云端 LUT”分裂式管理体验

## 1. 背景与问题

Lumina 已具备耗材 Registry、LUT Registry、本地耗材库、本地 LUT 库和包安装能力，但当前实现仍呈现为多条彼此拼接的功能线：

- “云同步”实际是公共目录浏览和选择性安装，不是真正的账号或跨设备同步，命名误导。
- 本地库与云端库分成独立页面，同一资源在两个页面中的身份、版本和状态需要用户自行对应。
- 耗材和 LUT 的安装状态语义不一致。部分路径把“磁盘上存在相同内容”当成“由 Registry 安装并可安全卸载”。
- 耗材安装请求仍可能携带前端返回的 package URL 和 hash；LUT 安装则由后端按 ID/revision 重新解析，安全边界不一致。
- 云端安装内容、用户本地内容和由云端内容派生的可编辑副本没有清晰的所有权边界。
- 更新、回退、卸载、修复和缓存刷新能力在耗材与 LUT 之间不对称。
- 云端条目安装前只能看到有限元数据，用户难以判断是否值得安装。
- `official/community` 既被用作分发 channel，又被 UI 用作质量或来源角标，语义混杂。
- 旧索引、旧本地文件和云端目录之间缺少无损迁移策略。

本设计将两类资源升级为公共资源库产品，但不把耗材和 LUT 合并为同一种业务对象。两者共享生命周期语义、UI 结构和安全原则，各自保留格式、校验器、安装根目录和业务接口。

## 2. 已确认的产品决策

1. 云端能力定位为无需账号的公共资源库，不实现个人云盘或跨设备同步。
2. 耗材与 LUT 是独立资源，不建立依赖图，不自动联动安装，也不组成强制套装。
3. 每个业务区使用“云资源库 / 我的资源”双视图，底层共享同一资源身份和本地状态。
4. 普通用户通过“分享资源”进入提交说明或外部表单；客户端不直接匿名发布。
5. 公开来源只显示“Lumina 官方发布”和“社区分享”。厂商和个人均可属于社区分享。
6. 社区资源先自动校验，再由维护者人工审核；审核通过后才进入公开目录。
7. 客户端自动检查新版本并显示数量角标，但更新必须由用户确认，不在启动时弹窗打断。
8. 提供单项更新和“更新全部”；批量更新允许部分成功，卸载和回退仍逐项确认。
9. 每个受管理资源只保留当前版本和上一个版本，更早版本需要从 Registry 重新下载。
10. 云端安装内容只读。需要修改时创建独立本地副本，原资源继续正常更新。
11. 云端资源支持安装前完整详情预览；不要求先下载完整 package。
12. 资源目录显示下载量，并支持按最近更新和最多下载排序；不做评分、评论和点赞。
13. 旧内容只能通过完整内容 hash 与云端资源关联，禁止按名称、厂商或路径猜测。
14. 正在当前流程中使用的资源不得卸载。历史配方引用缺失资源时提供重新安装入口。

## 3. 目标与非目标

### 3.1 目标

- 让用户明确区分“发现云端内容”和“管理本机内容”。
- 让耗材和 LUT 使用相同的安装、更新、回退、卸载、修复和本地副本语义。
- 正确定义资源身份、版本、内容一致性、本机位置和文件所有权。
- 防止前端篡改下载 URL、hash 或安装路径。
- 在断网、下载失败、包损坏、索引损坏和应用中断后保留上次可用状态。
- 无损迁移既有耗材、LUT 和同步索引，不移动、不覆盖、不误删用户文件。
- 为大量厂商和社区贡献者提供可扩展的发现、筛选和排序体验。
- 维持旧 Studio 客户端的兼容窗口，允许三仓按安全顺序部署。

### 3.2 非目标

- 不实现用户账号、个人私有空间、跨设备同步或云端自动备份。
- 不实现评分、评论、点赞、关注或社区动态流。
- 不建立耗材与 LUT 的依赖、推荐安装或兼容性联动。
- 不让浏览器持有 Registry 维护 token。
- 不把耗材和 LUT 重写为单一通用 package 插件平台。
- 不在 v2 第一阶段废弃所有旧 API、旧 package 或旧索引。
- 不在客户端内实现完整审核后台；审核仍属于 Registry 维护流程。

## 4. 产品信息架构

### 4.1 一级与二级导航

保留两个独立一级业务区：

- `LUT 管理`
- `耗材管理`

原有两组分裂入口合并：

- `LUT 库` + `云端 LUT` -> `LUT 资源`
- `耗材库` + `云端耗材` -> `耗材资源`

校准板、颜色提取、LUT 对比、五色查询、渐变卡生成/提取和配方查询等工具保持独立，不与资源目录混成一个页面。

一级导航可显示可更新数量角标。角标是非阻塞提示，不触发启动弹窗。

### 4.2 云资源库视图

云资源库负责发现和安装，默认包含：

- 快速入口：`Lumina 官方`、`按厂商`、`社区最新`。
- 全局搜索：名称、品牌/厂商、材料类型、颜色模式、发布者和标签。
- 组合筛选：发布者类型、厂商、颜色模式、材料类型和安装状态。
- 排序：最近更新、最多下载。
- 分页或游标加载；禁止一次加载完整大目录。
- 云端资源卡片显示标题、品牌、发布者、资源摘要、最新版本、更新时间、下载量和本地状态。
- “分享资源”打开配置的公开说明或外部表单，不直接调用维护接口。

云端卡片不显示内部 package 路径、完整 hash 或本机路径。技术字段只在详情中的折叠区域展示。

### 4.3 我的资源视图

“我的 LUT”和“我的耗材”负责本机管理：

- 筛选：全部、可更新、云端安装、本地导入、本地副本、安装损坏。
- 操作：单项更新、更新全部、回退、卸载、修复、创建本地副本、详情、导出和删除。
- 云端安装资源只读，不直接编辑。
- 本地导入和本地副本可编辑；它们不随来源资源更新或卸载。
- 卸载只作用于 Lumina 明确拥有的安装路径。
- 删除本地资源必须展示资源名称、精确相对目录和不可撤销警告。

### 4.4 详情体验

云端详情在桌面端使用侧边面板，在窄屏使用全屏页面，以保留目录上下文。详情包含：

- 标题、品牌、发布者类型、发布者名称、说明、标签和更新时间。
- 当前最新 revision 和可见历史版本。
- 下载量、package 大小和兼容性摘要。
- LUT：颜色模式、基础通道、色彩分布/色域摘要、颜色数量、校准说明和预览图表。
- 耗材：色样、材料类型、验证记录摘要、参数概览和适用说明。
- 当前本机状态及允许操作。
- 可折叠技术信息：resource ID、revision ID、content hash 前缀和 package hash 前缀。

预览数据由 Registry 审核流程从已验证内容生成，不信任上传者提交的任意 HTML 或脚本。

## 5. 资源身份与状态模型

### 5.1 身份字段

各字段职责固定：

- 逻辑身份：`material_id` 或 `lut_id`。
- 不可变版本：`revision_id`。
- 核心内容指纹：`content_hash`。
- 压缩包传输完整性：`package_sha256`。
- 本机位置：耗材 `local_directory`，LUT `local_path`。
- 文件所有权：本地 v2 安装索引中的逐文件 `managed_files[]`（role、相对路径、安装时 SHA-256、bytes）以及仅用于清理空目录的 `created_directories[]`；不能从目录路径或名称推断。

名称、品牌、发布者和路径只用于显示、搜索和定位，不能判断两个资源是否相同。

### 5.2 云端资源状态

前端共享以下规范状态，两个领域适配器负责映射各自后端字段：

- `not_installed`：本机没有受管理安装，也没有精确相同的未受管理内容。
- `installed`：索引、当前文件、revision 和 content hash 一致，且安装路径由 Lumina 管理。
- `update_available`：当前安装仍可用，Registry 有更新的已批准 revision。
- `local_equivalent`：本机存在精确相同 content hash，但不是受管理安装。
- `damaged`：索引声明已安装，但文件缺失、hash 不一致或内容无法加载。
- `installing`、`updating`、`rolling_back`、`uninstalling`：瞬时操作状态，不持久化为最终状态。

`local_equivalent` 不得显示“卸载”。“纳入管理”默认把内容复制到受管理目录并写入索引，不移动或删除原文件。只有用户明确确认且原路径已位于受管理根目录时，才允许原地登记所有权。

### 5.3 本地资源状态

- `local_import`：用户导入或既有的本地内容，无云端更新语义。
- `local_copy`：从云端 revision 创建的可编辑副本，保留 `source_resource_id` 和 `source_revision_id` 仅用于追溯。
- `legacy_unresolved`：迁移后尚未完成云端精确 hash 对应的旧内容；仍可正常使用。

本地副本不得在来源资源更新时自动合并，不得在来源资源卸载时删除。

### 5.4 状态判定

判定顺序：

1. 检查 v2 索引中的受管理安装记录。
2. 验证每个 `managed_files[]` path 位于对应 immutable revision 根目录，且文件存在、bytes/hash 与安装记录一致。
3. 重新计算或读取可信缓存中的 content hash。
4. 使用领域加载器验证内容可实际加载。
5. 与 Registry 当前 catalog/detail 的 revision 和 hash 比较。
6. 未命中受管理记录时，才扫描精确 hash 相同的未受管理内容并标记 `local_equivalent`。

不得把 `local_exists=true`、同名文件、同目录名或相同 `material_id` 单独视为 `installed`。

### 5.5 规范状态转换

| 起始状态 | 动作 | 必需 guard | 成功提交 | 失败后可见状态 |
|---|---|---|---|---|
| `not_installed` | install | exact revision 可见；package 绑定通过；path reservation 空闲 | `installed(active=new, previous=null)` | `not_installed` |
| `local_equivalent` | adopt | canonical hash 相等；目标 reservation 空闲 | 复制到 immutable store 后 `installed`；原文件仍在 | `local_equivalent` |
| `installed` / `update_available` | update | 新 revision 不同；合同/事务验证通过 | `installed(active=new, previous=old)` | 原 active/previous 不变 |
| `installed` | rollback local | previous 完整且可加载 | `installed(active=previous, previous=old_active)` | 原 active/previous 不变 |
| `installed` | rollback remote | exact revision 可下载并绑定 | 与 update 相同 | 原 active/previous 不变 |
| `damaged` | repair | exact revision 可重新获得或本地 package 可证明 | 新 immutable revision 成为 active；损坏路径进入受保护 GC | `damaged` |
| `installed` | uninstall | 无 active lease；逐文件 ownership preflight 通过 | active 清空，记录最小 history，revision 进入 GC | `installed` |
| `installed` | detach management | 用户明确确认 | active 清空，现有 payload 作为 `local_import`/`local_equivalent` 保留 | `installed` |
| `local_import` / `local_copy` | delete | 无 lease；path safety 通过；用户确认 | local record 与用户选择的本地文件删除 | 原状态 |
| `local_copy` | edit | 无只读限制；写入本地事务成功 | 同一 `local_id`，hash/updated_at 更新 | 原内容与 hash |

瞬时 `installing/updating/rolling_back/uninstalling` 只存在于操作响应和 journal，不作为重启后的最终事实。重启后由 6.1 启动恢复收敛到表中的稳定状态。

## 6. 本地生命周期行为

### 6.1 安装与更新

安装和更新不覆盖 current 文件，而是发布不可变 revision 并切换索引指针。领域存储布局固定在各自 `_sync/resource-store/` 下，旧目录扫描器必须忽略该目录：

```text
materials/_sync/resource-store/<registry_key>/<material_id>/<revision_id>-<hash12>/...
lut-preset/_sync/resource-store/<registry_key>/<lut_id>/<revision_id>-<hash12>/...
```

所有现有和新工作流在 v2 cutover 后必须通过 Resource Resolver 获取 active immutable path；不能继续根据显示名扫描并直接打开可变化的 legacy path。旧 API 响应可以投影 legacy 名称，但内部读取仍解析为 immutable path。

安装和更新共用以下安全事务：

1. 前端只提交领域 ID 和 revision ID。
2. Studio 后端读取 Registry capability 与 exact-revision detail，在已配置 channel 中解析该 revision。
3. 校验 package URL 与 Registry 同源，禁止重定向；限制响应大小、Content-Length、下载时间和压缩包大小。
4. 校验 `package_sha256`，安全读取 ZIP，并按 8.6 节逐字段绑定 record、manifest 和 payload。
5. 在与最终 revision 目录同一文件系统的 `_sync/transactions/<txid>/staged/` 解压，调用领域加载器验证，并 fsync 每个文件和 staging 目录。staging 不得放在系统临时盘。
6. 写入并 fsync 持久事务日志 `_sync/transactions/<txid>/journal.json`，状态为 `prepared`，内容包括 `base_generation`、目标 immutable path、casefold path reservation、before/after resource record 和逐文件 ownership manifest。
7. 获取“同一资源”跨进程操作锁，再获取短时全局 commit 锁。全局锁保护共享索引、路径 reservation、事务状态和 generation，不在持锁期间下载或解析大文件。
8. 在锁内重新读取索引；只有 `generation == base_generation` 且 canonical/casefold 目标路径仍未被其他资源占用时才提交。否则释放锁、重算 delta 后重试或返回 `resource_commit_conflict`。
9. 把 staged revision 原子重命名到从未存在过的 immutable revision path，fsync 其父目录，并把 journal 更新为 `revision_published`。
10. 将 after record 合并到最新索引，写入 `generation + 1` 的临时索引，fsync 文件，原子替换正式索引，再 fsync 父目录。随后把 journal 更新为 `committed`。
11. 提交后释放锁，统一刷新 LUT 详情/catalog/KD-Tree、耗材列表和相关运行时缓存；上一 rollback slot 或过期 revision 只进入异步 GC，不在主事务内删除。

POSIX 使用文件与父目录 fsync；Windows 使用同卷原子 replace、文件句柄 flush 和持久 journal，不能假设目录 fsync 可用。两种平台都必须有阶段故障注入测试。

#### 启动恢复

Studio 在开放任何 mutating endpoint 前扫描未完成 journal：

- `prepared` 且最终 revision 不存在：删除 staging，标记 `aborted`。
- `revision_published`、最终 revision 完整且索引仍是 `base_generation`：获取全局锁并按 journal 的 after record 确定性前滚。
- `revision_published` 且全局 generation 已被其他资源推进：若 journal 中该 resource 的 before record 与 path-reservation precondition 在最新索引中仍完全成立，则把同一 delta rebase 到最新 generation 后前滚；不能只因无关资源提交就进入 repair。
- `revision_published` 但最终 revision 校验失败：删除未被索引引用的 revision；若存在旧 active record，保持旧 active。
- 索引已经包含 `transaction_id`/after record，但 journal 未完成：标记 `committed` 并进入正常 GC。
- 同一 resource 的 before record 或 path reservation 与 journal 冲突：停止写入，返回 `local_index_recovery_required`，由 repair dry-run 给出方案，禁止猜测覆盖。

因此断电可能留下可识别的 staging 或 orphan immutable revision，但不能留下“无 current”、半个 payload 或无法判断的新文件/旧索引组合。

### 6.2 批量更新

“更新全部”以资源为事务边界：

- 每个资源独立安装、验证和提交。
- 单项失败不回滚其他已成功资源。
- 最终返回成功、跳过和失败列表，以及稳定错误代码。
- 同一资源不得并发执行两个生命周期操作。
- UI 在完成后保留失败项和原因，不能只显示笼统失败提示。

现有 `material_sync_scheduler` 会调用会安装 package 的 `refresh_material_sync_from_registry`。v2 必须拆开“检查目录”和“安装更新”：

- 新增只读 check/catalog refresh 路径，后台 scheduler 只能调用该路径并计算 `update_available`。
- scheduler 不得安装、覆盖或回退任何资源。
- 旧 `LUMINA_MATERIAL_SYNC_STARTUP_REFRESH` 和 `LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S` 在过渡期映射为“检查更新”配置并记录弃用提示，不能继续保持静默安装语义。
- 旧 `/api/material-sync/refresh` 在兼容期保留为显式人工调用的旧批量安装接口，但新 UI 和新 scheduler 不再使用它；删除时另开弃用 PR。
- 新“更新全部”使用 v2 独立资源事务和部分成功响应，不复用旧全目录 refresh 的隐式安装语义。

### 6.3 回退

- 每个资源最多保留当前版本和一个上一版本。
- 本地上一版本可用时，回退不访问网络。
- 更早 revision 只能从 Registry 重新下载，并执行完整安装校验。
- 回退后，原当前版本成为新的上一版本，允许用户撤销误回退。
- Registry 已撤下且本地未保留的版本不可回退，UI 应明确说明。

### 6.4 卸载、删除与使用中保护

- `uninstall` 只用于受管理云端安装。
- `delete` 只用于本地导入和本地副本。
- 当前转换、预览、生成、校准或材料流程持有资源租约时阻止卸载/删除，并指出占用流程。
- 卸载按 6.1 节事务提交“无 active revision”的新 generation；逐文件删除和目录清理由异步 GC 按 11.4 节所有权规则执行。
- 卸载不得删除本地副本或 `local_equivalent` 原文件。
- 历史配方打开时若引用资源缺失，显示资源身份和“重新安装”入口；不得静默改用同名资源。

### 6.5 Revision 租约与回收

所有会读取耗材或 LUT 的工作流必须先通过 Resource Resolver 固定：

```json
{
  "source_registry": "public-default",
  "resource_kind": "lut",
  "resource_id": "lut_...",
  "revision_id": "rev_...",
  "content_hash": "sha256:...",
  "immutable_path": "lut-preset/_sync/resource-store/..."
}
```

Resolver 创建持久 lease 文件 `_sync/leases/<lease_id>.json`，记录 session/job ID、主进程 PID 与启动标识、exact revision、创建时间、heartbeat/expiry。主进程持有租约并把 immutable path 作为标量传给 worker；worker 不重新解析“当前版本”。正常完成、会话关闭或取消时释放租约；启动恢复只清理 PID/start marker 已失效或超过 TTL 且无活动 session 的 stale lease。

生命周期规则：

| 操作 | revision 有活动租约时的行为 |
|---|---|
| update | 允许发布新 immutable revision，并只为新工作流切换 active；旧 revision 不回收 |
| rollback | 允许切换未来 active；已租用 revision 保持原路径与内容 |
| repair | 发布或重新验证新 immutable revision；不得原地修改租用中的 payload |
| uninstall/delete | 按产品决策阻止并返回 `resource_in_use` |
| previous/GC 清理 | 标记 `pending_gc`，最后一个 lease 释放后才执行 |

“只保留 current + previous”是可回退 slot 的逻辑上限。有活动租约的更老 revision 可以临时超出该上限，但不再作为可回退选项；租约释放后再由 GC 回收。这样一次工作流不会混用更新前后两个版本。

## 7. 三仓职责

### 7.1 Lumina Studio

Studio 负责：

- 合并 Registry 目录与本机状态。
- 规范化耗材/LUT 状态为共享前端视图模型。
- 受管理安装、更新、回退、卸载、修复和本地副本。
- 使用领域加载器做最终可用性验证。
- 使用中资源保护、缓存失效、离线目录缓存和迁移。
- 隐藏 Registry token、package URL 和本机绝对路径。

Studio 不负责公开上传、批准、频道切换或下载量计数。

### 7.2 Lumina Material Registry

Registry 负责：

- 耗材和 LUT 的公开 catalog、详情、预览摘要和版本历史。
- 上传到 pending、自动验证、人工批准、拒绝、下架和频道管理。
- 不可变 revision 和 package 下载。
- `publisher_kind`、`publisher_name`、发布时间和下载量。
- 包审批或频道变更后重写 manifest，并重算 package path/hash/bytes。
- 对旧 catalog 响应保持兼容。

Registry 不负责判断某台 Studio 是否安装，也不接收浏览器指定的本机路径。

### 7.3 Lumina Materials

Materials 内容仓负责：

- 保存耗材/LUT 源内容及可复现的 package 产物。
- 保存构建和校验所需的公开 manifest 元数据。
- 通过 CI 验证包结构、hash 和预览生成输入。

内容仓禁止保存：

- Registry token 或其他密钥。
- 生产服务器地址以外的私有部署配置。
- 服务器绝对路径、对象存储内部路径和本机用户路径。
- 本机同步索引、运行时缓存、下载量或安装状态。

## 8. Registry 公共契约

### 8.1 兼容策略

本设计采用“领域 API + 公共字段集合”，不新增一个把耗材和 LUT 混成同类型的通用 API。

- 耗材继续使用 `material_id`、`local_directory` 和耗材兼容字段。
- LUT 继续使用 `lut_id`、`local_path` 和 LUT 兼容字段。
- 两类 catalog/detail 返回相同语义的发布者、时间、统计、hash 和预览字段。
- Studio 前端共享适配器把领域响应映射为统一 Resource View Model。

Registry 必须保留两套明确版本的读契约，不能原地改变 v1：

- 现有 `/api/material-registry/v1/materials/catalog` 和 `/api/material-registry/v1/luts/catalog` 保持当前响应形状、所有已批准 revision 的列表语义，以及“未传 `limit` 时返回全部匹配条目”的默认行为。
- 新增 `/api/material-registry/v2/materials/catalog` 和 `/api/material-registry/v2/luts/catalog`，只在 v2 中启用“每个逻辑资源返回最新 approved revision”、默认分页、cursor、publisher、统计和预览摘要。
- 新增 `GET /api/material-registry/v1/capabilities`。Studio 只有在响应明确声明 `resource_catalog_v2=true` 后才使用 v2；404、超时或不支持时继续使用完整 v1 adapter，不猜测能力。
- v1 与 v2 可以读取同一 Registry record，但必须由独立投影器生成响应，禁止为了 v2 简化而改变 v1 snapshot。

Capability 响应固定为：

```json
{
  "schema_version": "1.0",
  "resource_catalog_v2": true,
  "catalog_versions": {"material": ["1", "2"], "lut": ["1", "2"]},
  "package_schema_versions": {"material": ["2.0", "2.1"], "lut": ["1.0", "2.0"]},
  "features": ["cursor", "exact_revision", "publisher", "preview", "download_count"]
}
```

### 8.2 Catalog 公共字段

两个 v2 catalog 条目至少提供：

- `contract_version`: `2.0`
- `package_kind`: `lumina_material_bundle | lumina_lut_bundle`
- `package_schema_version`
- 领域 ID：`material_id` 或 `lut_id`
- `revision_id`
- `content_hash_algorithm`
- `content_hash`
- `package_url`
- `package_sha256`
- `package_bytes`
- `publisher_kind`: `lumina | community`
- `publisher_name`
- `title`
- `summary`
- `brand`
- `tags`
- `published_at`
- `updated_at`
- `download_count`
- `channel`
- `visibility`
- `compatibility`
- 领域安装位置：`local_directory` 或 `local_path`

`channel/visibility` 是服务端分发策略；UI 官方角标只能根据 `publisher_kind=lumina` 显示。

v2 LUT 条目形状示例：

```json
{
  "contract_version": "2.0",
  "package_kind": "lumina_lut_bundle",
  "package_schema_version": "2.0",
  "lut_id": "lut_example",
  "revision_id": "rev_example",
  "content_hash_algorithm": "lumina-lut-file-bytes-v1",
  "content_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  "package_url": "/api/material-registry/v2/luts/lut_example/revisions/rev_example/package",
  "package_sha256": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
  "package_bytes": 12345,
  "publisher_kind": "community",
  "publisher_name": "Example Contributor",
  "title": "Example PETG RYBW",
  "summary": "Four-channel PETG calibration LUT",
  "brand": "Example Brand",
  "tags": ["PETG", "RYBW"],
  "published_at": "2026-07-10T00:00:00Z",
  "updated_at": "2026-07-10T00:00:00Z",
  "download_count": 42,
  "channel": "community",
  "visibility": "community",
  "compatibility": {"color_mode": "4-Color RYBW"},
  "local_path": "Example/PETG/example-rybw.npy"
}
```

v2 Catalog 默认每个逻辑资源返回最新已批准 revision。旧 revision 通过详情接口获取，不在 v2 主目录重复成多张卡片。v1 Catalog 继续返回当前所有匹配 revision。

不可变性分成两层：

- 资源 revision 的核心文件和 `content_hash` 永远不可原地改变；核心内容变化必须生成新 `revision_id`。
- 审批、`publisher_kind`、channel 或 visibility 变化可以为同一核心 revision 生成新的分发包 envelope，但必须写入新的不可变 package path，并生成新的 `package_sha256`。旧 package 不得覆盖或复用原路径。

因此 `(resource_id, revision_id, content_hash)` 表示核心内容版本，`package_sha256` 表示某次具体分发 envelope。Catalog 始终指向当前有效 envelope，审计记录保留旧 envelope 的 hash 和路径。

### 8.3 查询与分页

v2 Catalog 支持：

- `q`
- `publisher_kind`
- `brand`
- 领域筛选，例如 `color_mode`、`material_type`
- `sort=updated_desc | downloads_desc`
- `limit`
- `cursor`

v1 保留 `offset`、可选 `limit` 和旧响应计数字段，且未传 `limit` 时必须返回全部匹配项。v2 默认 `limit=50`、最大 `100`，新客户端使用 cursor，避免目录更新或下载量变化导致 offset 重复/漏项。

Cursor 必须包含排序键和资源 ID 稳定次序。按下载量排序时使用请求开始时的分页快照或等价稳定游标，不能因翻页期间计数变化而重复或遗漏同一资源。

### 8.4 详情与历史

新增 v2 领域详情接口：

- `GET /api/material-registry/v2/materials/{material_id}`
- `GET /api/material-registry/v2/luts/{lut_id}`

响应包含：

- 完整展示信息。
- 安装前预览摘要和安全的预览资源 URL。
- 最新 revision。
- 当前可见历史 revision 列表。
- 各 revision 的发布时间、content hash、package hash/bytes 和兼容字段。

预览 URL 必须指向受控静态内容，不允许上传者提供任意外链脚本或 HTML。

### 8.5 下载统计

- `download_count` 由 Registry 下载路由记录，不接受客户端上报任意计数。
- HEAD、范围探测和失败响应不计入下载量。
- 下载量用于粗略发现排序，不宣传为唯一用户数或安装成功数。
- 统计更新不得改变已批准 package、revision ID 或 package hash。

### 8.6 Canonical 内容身份合同

v2 响应和新 package manifest 必须同时携带 `content_hash_algorithm` 与带 `sha256:` 前缀的小写 `content_hash`。算法名、输入字节和编码固定如下，任何仓库不得自行解释。Legacy package 先由其明确 schema adapter 规范化，再参与逐字段绑定：

#### Material：`lumina-material-required-files-v1`

1. 必需 role 固定为 `material_archive` 和 `stage_a_parameters`，各恰好一个。
2. 对实际文件字节分别计算小写 64 位 SHA-256 hex。
3. 不使用 ZIP 内提交者可控路径作为逻辑名；逻辑名固定为 `material.json` 和 `stage_A_parameters.json`。
4. 按下列 UTF-8/ASCII 字节精确拼接，不带结尾换行：

```text
material.json:<material_file_sha256>\nstage_A_parameters.json:<stage_a_file_sha256>
```

5. 对上述字节计算 SHA-256，并编码为 `sha256:<hex>`。

#### LUT：`lumina-lut-file-bytes-v1`

1. manifest 中必须且只能有一个 `lut_file` role。
2. `content_hash` 是该 LUT 文件原始字节的 SHA-256，编码为 `sha256:<hex>`；文件名和 `local_path` 不进入 hash。
3. `files[].sha256` 必须等于同一原始字节 hash 的无前缀 64 位 hex。

现有 LUT package v1 的顶层 hash 使用“逻辑文件名 + 文件 SHA”的历史算法。该字段不得原地重定义：

- v1 endpoint、v1 package 和既有 revision 继续保留 legacy 值。
- v2 Registry 投影从已验证的 `lut_file` 字节派生 `content_hash_algorithm=lumina-lut-file-bytes-v1` 与新的 v2 `content_hash`，并可额外返回 `legacy_content_hash` 供审计。
- 新建 LUT package schema v2 直接使用 `lumina-lut-file-bytes-v1`；Studio 同时支持 legacy v1 package 和 v2 package，但只用 v2 canonical hash 建立 `local_equivalent`。
- Material schema 2.0 既有 `lumina-material-required-files-v1` 语义保持不变；v2 Registry adapter 对缺失算法名的 schema 2.0 固定补该值。新建 material schema 2.1 显式携带算法名。不得把 schema 2.0 原地判为无效或改变既有内容身份。

`revision_id` 是 Registry 分配或接受后冻结的 opaque ID，客户端不得从 hash 自行重建。安装时 Studio 必须把服务端 exact-revision record 与“按已声明 package schema 规范化后的 manifest”逐字段绑定：

- `kind`
- `schema_version`
- `material_id | lut_id`
- `revision_id`
- `content_hash_algorithm`
- canonical `content_hash`
- `local_directory | local_path`
- `channel`
- `visibility`
- 每个必需 file 的 role、path、bytes 和 sha256
- 下载响应的 `package_sha256` 和 `package_bytes`

任一字段不一致都以 `registry_package_binding_mismatch` 失败；不得只验证 ZIP 自洽后继续安装。

### 8.7 跨仓黄金夹具

Registry 仓是合同 schema 与黄金 package 的规范源，至少保存：

- 单耗材 material package v2。
- legacy LUT package v1 及其 v2 catalog 投影。
- LUT package v2。
- channel/visibility 重写后的 envelope。
- path traversal、大小写碰撞、symlink、hash 不符和字段绑定不符的拒绝夹具。

Materials 与 Studio vendoring 完全相同的 fixture bytes，并保存 `UPSTREAM.json`，记录 Registry commit、相对路径和每个文件 SHA-256。三仓集成 CI 克隆 exact commits，逐字节比较夹具，再分别运行 builder、Registry validator 和 Studio installer；只复制结构相似的测试数据不算合同测试。

## 9. Studio API 与前端适配器

### 9.1 安装请求

保留并规范化领域安装接口：

- `POST /api/material-sync/install` 保持现有 multipart ZIP 本地导入合同，不改变 Content-Type、字段名或响应形状。
- `POST /api/material-sync/install-from-registry` 继续承担云端耗材安装。v2 请求只需 `material_id`、`revision_id`；旧请求中的 `package_url`、`package_sha256` 继续允许出现但被服务端忽略，后端按 ID/revision 重新解析。
- `POST /api/lut-registry/install`，请求仅含 `lut_id`、`revision_id`。

必须为三种请求形状建立合同测试：multipart 本地耗材导入、含 URL/hash 的 legacy Registry JSON、只含 ID/revision 的 v2 Registry JSON。两个 material handler 不复用同一路由或依赖 Content-Type 猜测分派。

### 9.2 生命周期接口

两个领域提供同语义操作：

- `GET status`
- `POST install/update`
- `POST rollback`
- `POST uninstall`
- `POST repair`
- `POST adopt-local-equivalent`
- `POST create-local-copy`
- `POST update-all`

路由可保留领域前缀，不要求合并成一个通用 endpoint。响应映射为公共状态、操作结果和稳定错误代码。

### 9.3 Studio capability 与 legacy 投影

新增 `GET /api/resources/capabilities`，响应 schema 固定为：

```json
{
  "schema_version": "1.0",
  "resource_store_version": "2.0",
  "cutover_state": "v2_committed",
  "domains": {
    "material": {"catalog_version": "2", "actions": ["install", "update", "rollback", "uninstall", "repair", "update_all"]},
    "lut": {"catalog_version": "2", "actions": ["install", "update", "rollback", "uninstall", "repair", "update_all"]}
  },
  "legacy_response_versions": {"material_sync": "1.0", "lut_registry": "1.0"}
}
```

新前端只有看到受支持的 `resource_store_version` 和 domain action 后才显示对应按钮。旧 status/catalog endpoint 从 v2 store 生成 legacy response projection，保持旧字段、空值、计数和 HTTP 状态合同；不得读取或写入独立 v1 索引作为第二事实源。

### 9.4 Legacy mutating endpoint 规则

cutover 前，v1 是唯一写入者；cutover 提交后，v2 store 是唯一写入者：

- multipart `/api/material-sync/install` 通过 v2 importer 登记 `local_import`，但保持旧响应。
- `/install-from-registry` 和 LUT `/install` 通过 v2 transaction manager 安装受管理资源。
- 旧 `/api/material-sync/refresh` 显式调用时适配到 v2 `update_all`；scheduler 不再调用它。
- 旧按路径编辑接口遇到 managed resource 返回 `409 managed_resource_read_only`；用户必须创建本地副本。
- 旧按路径删除接口遇到 managed resource 返回 `409 managed_resource_read_only`，不能把 path delete 暗中解释为卸载。
- 旧按路径编辑/删除本地资源仍必须进入 v2 local-resource service，并执行 path safety、lease 和用户确认语义。
- 所有旧接口都必须对 active lease 返回 `409 resource_in_use`，并使用同一稳定错误映射。

保留旧页面仅表示保留旧展示和请求形状，不表示允许 v1 直接写磁盘。新 UI 回滚也只能关闭入口并继续使用 v2 store；cutover 后不得自动降级回 v1 writer。

### 9.5 共享前端 Resource View Model

前端共享模型至少包含：

- `kind: material | lut`
- `resourceId`
- `revisionId`
- `title`
- `brand`
- `publisherKind`
- `publisherName`
- `summary`
- `tags`
- `downloadCount`
- `updatedAt`
- `localState`
- `localDisplayPath`
- `hasPreviousRevision`
- `isInUse`
- `allowedActions`

`allowedActions` 由后端状态与前端能力共同收窄，前端不得根据按钮文案自行推测是否可以卸载或删除。

共享 UI 只负责布局、筛选、卡片、详情和状态展示。耗材/LUT 适配器负责 API 调用、领域预览和本地动作。

## 10. 发布者、频道与审核语义

### 10.1 发布者类型

- `lumina`：由 Lumina 团队发布并维护。
- `community`：由厂商、作者或普通用户分享，经审核后公开，但不代表 Lumina 对打印结果背书。

只有 approver 角色可以把 `publisher_kind` 设置为 `lumina`。普通上传默认固定为 `community`。

现有 Materials 仓的目录不能作为发布者证据。当前 `materials-src/official`、`packages/community` 和实际 package channel 存在历史不对称，LUT 源与 package 则主要位于 community。迁移时必须建立显式发布者清单或 sidecar 元数据：

- 缺少显式元数据的既有资源一律迁移为 `community`。
- 只有维护者逐项确认的资源才能设为 `lumina`。
- 不得根据 `official/` 目录名、品牌名、文件名、旧 channel 或旧 UI 角标批量推断 `publisher_kind=lumina`。
- 源目录 channel、package 分发 channel 和 publisher kind 分别校验，不能再互相替代。

### 10.2 Channel 与 Visibility

`channel` 和 `visibility` 保留为服务端分发与访问策略，不直接展示为来源角标。公开 v2 第一阶段至少支持当前公开频道并兼容旧客户端。

批准或切换 channel/visibility 时：

1. 更新 Registry record。
2. 重写 ZIP 内 manifest。
3. 重新计算 package SHA-256 和 bytes。
4. 使用新的不可变 package path。
5. 原 catalog 不得短暂返回 record 与 ZIP manifest 不一致的组合。

### 10.3 分享与审核流程

1. 用户从 Studio 点击“分享资源”。
2. 打开公开说明或外部表单。
3. 维护工具把 package 上传到 pending。
4. Registry 执行自动格式、hash、路径、大小和领域可加载性校验。
5. 维护者人工审核标题、归属、说明、预览和基本合理性。
6. 批准后生成受控预览并进入公开 catalog。

Studio 普通用户界面不显示 pending、rejected 或维护 token。

## 11. Package 与路径安全

### 11.1 信任边界

- 浏览器不能指定最终 package URL、package hash 或安装路径。
- Studio 只信任自身配置的 Registry origin，并按 ID/revision 重新解析。
- package URL 必须与 Registry 同源；禁止重定向。
- 生产 Registry 要求 HTTPS。开发环境可通过显式配置允许 localhost/测试 HTTP，禁止静默降级。
- token 只存在于 Registry 维护端或 Studio 服务端环境，不进入前端 bundle、catalog、日志、Materials 仓和错误消息。

HTTPS 强制必须按部署能力分阶段启用：先为生产 Registry 配置 HTTPS 和健康检查，再让 Studio 默认拒绝远程 HTTP。过渡版本对既有远程 HTTP 配置显示明确警告，但不得在 HTTPS 请求失败后自动回退到 HTTP。

### 11.2 ZIP 安全

Registry 审核和 Studio 安装都必须拒绝：

- 绝对路径、`..`、`.`、空 path segment 和 Windows drive。
- 大小写折叠后的重复路径。
- 符号链接、设备文件、FIFO 和其他非普通文件。
- 超过 entry 数量、单文件大小、总解压大小和压缩率限制的包。
- manifest 未声明的 payload。
- 声明 bytes/hash 与实际不符的文件。
- LUT 非允许扩展名或一包多 LUT。
- 耗材缺少必需 role 或包含本地缓存/统计文件。

### 11.3 路径规范

- 所有 manifest path 使用 POSIX 相对路径。
- LUT `local_path` 不含 `lut-preset/` 和重复 `Cloud/` 前缀。
- 耗材 `local_directory` 是 `materials/` 下相对目录。
- Studio 把规范化目标解析到固定受管理根目录，并再次验证 `resolved_path` 未逃逸。
- `managed_files[]` 和 `created_directories[]` 只记录受管理 revision 根目录下的规范化相对路径，禁止记录用户绝对路径。
- 逻辑 `local_path/local_directory` 还必须生成 Unicode-normalized、分隔符规范化并大小写折叠的 reservation key；两个资源不得占用同一 reservation，即使当前平台大小写敏感。

### 11.4 删除与覆盖的所有权证明

卸载、previous GC、repair 清理和任何会移除文件的操作都先执行完整 preflight：

1. 重新解析每个 `managed_files[]` path，确认仍在对应 immutable revision 根目录。
2. 确认文件仍是普通文件，不是 symlink/reparse point 或其他特殊对象。
3. 重新核对 bytes 和 SHA-256。
4. 扫描 revision 目录，确认不存在 manifest 未声明的本地 sidecar。
5. 检查 revision 没有活动 lease。

任一已管理文件不匹配或出现未知 sidecar 时，整个删除事务 fail closed 为 `local_path_conflict`，默认不删除任何文件。用户可以选择“解除管理”，它只移除 active/ownership 关系并把现有内容登记为本地资源，绝不删除磁盘内容；不提供跳过冲突文件后继续部分卸载的隐式行为。

preflight 全部通过后，只删除 `managed_files[]` 中仍匹配的文件，再按 deepest-first 对 `created_directories[]` 执行 rmdir；非空目录保留。索引、journal 与文件删除仍使用 6.1 节 generation/事务恢复协议。

## 12. 本地索引 v2

耗材和 LUT 保留独立索引文件，但使用相同 schema。`source_registry` 是 Studio 配置中的稳定 registry key，不是可变化或可能含凭据的 URL：

```json
{
  "schema_version": "2.0",
  "store_id": "b9ad6823-7cf0-4aac-95cf-34d2f39b6957",
  "generation": 42,
  "cutover": {
    "state": "v2_committed",
    "committed_at": "2026-07-10T00:00:00Z",
    "legacy_index_sha256": "sha256:..."
  },
  "managed_resources": {
    "public-default|lut|lut_example": {
      "entry_kind": "managed",
      "resource_kind": "lut",
      "source_registry": "public-default",
      "resource_id": "lut_example",
      "publisher_kind": "community",
      "active": {
        "revision_id": "rev_current",
        "content_hash_algorithm": "lumina-lut-file-bytes-v1",
        "content_hash": "sha256:...",
        "package_sha256": "sha256:...",
        "package_bytes": 12345,
        "logical_path": "Brand/example.npy",
        "immutable_path": "_sync/resource-store/public-default/lut_example/rev_current-0123456789ab",
        "managed_files": [
          {
            "role": "lut_file",
            "path": "example.npy",
            "sha256": "0123456789abcdef...",
            "bytes": 12000
          }
        ],
        "created_directories": ["."],
        "installed_at": "2026-07-10T00:00:00Z",
        "transaction_id": "tx_..."
      },
      "previous": {
        "revision_id": "rev_previous",
        "content_hash_algorithm": "lumina-lut-file-bytes-v1",
        "content_hash": "sha256:...",
        "immutable_path": "_sync/resource-store/public-default/lut_example/rev_previous-fedcba987654",
        "managed_files": [
          {
            "role": "lut_file",
            "path": "example.npy",
            "sha256": "fedcba9876543210...",
            "bytes": 11900
          }
        ]
      },
      "pending_gc": [],
      "updated_at": "2026-07-10T00:00:00Z"
    }
  },
  "local_resources": {
    "local_50fd03c5-7726-4bf1-b589-734b7e52125c": {
      "local_id": "local_50fd03c5-7726-4bf1-b589-734b7e52125c",
      "entry_kind": "local_copy",
      "resource_kind": "lut",
      "domain_path": {"local_path": "Custom/example-copy.npy"},
      "content_hash_algorithm": "lumina-lut-file-bytes-v1",
      "content_hash": "sha256:...",
      "observed_files": [
        {"path": "Custom/example-copy.npy", "sha256": "...", "bytes": 12000}
      ],
      "source_ref": {
        "source_registry": "public-default",
        "resource_id": "lut_example",
        "revision_id": "rev_current",
        "content_hash": "sha256:..."
      },
      "migration_state": "resolved",
      "created_at": "2026-07-10T00:00:00Z",
      "updated_at": "2026-07-10T00:00:00Z"
    }
  },
  "path_reservations": {
    "brand/example.npy": "public-default|lut|lut_example"
  },
  "legacy_aliases": {
    "Cloud/Brand/example.npy": "public-default|lut|lut_example"
  },
  "uninstall_history": {}
}
```

规则：

- 索引使用 6.1 节的 generation、临时文件、fsync、同目录原子替换和事务 journal。
- 每次 schema 迁移前保留带时间戳备份。
- 索引不存 token、绝对路径或可由 package 伪造的信任结果。
- `previous` 最多一项。
- `pending_gc` 可以临时保存因 lease 无法删除的旧 revision，但不作为可回退版本。
- `local_resources` 必须为 `local_import`、`local_copy`、`legacy_unresolved` 和 `local_equivalent` 分配稳定 UUID 型 `local_id`；重启和重新扫描不得因显示名变化创建新身份。
- `local_copy.source_ref`、`local_equivalent.source_ref` 和 deferred migration state 必须持久化。它们不授予删除所有权。
- `observed_files` 只记录扫描时事实，用于变化检测；它不是 `managed_files`，删除本地资源仍要求用户显式确认。
- `path_reservations` 的 key 使用 Unicode normalization、POSIX 分隔符和 casefold 后的领域逻辑路径。
- `legacy_aliases` 只用于在旧 catalog/扫描器中抑制迁移前物理副本的重复展示；它不授予删除所有权。
- 最小卸载历史与受管理安装记录分离，历史不得赋予文件所有权。

### 12.1 Exact revision 重装合同

Registry v2 为两个领域提供受 channel/token 授权的 exact revision 路由：

- `GET /api/material-registry/v2/materials/{material_id}/revisions/{revision_id}`
- `GET /api/material-registry/v2/materials/{material_id}/revisions/{revision_id}/package`
- `GET /api/material-registry/v2/luts/{lut_id}/revisions/{revision_id}`
- `GET /api/material-registry/v2/luts/{lut_id}/revisions/{revision_id}/package`

详情响应包含 8.6 节全部绑定字段和当前有效 package envelope。下架、无权限或已物理清除的 revision 返回可区分错误，不能退回 latest revision。

### 12.2 配方与可复现性 provenance

新保存的配方、分享卡和 bug-report reproduction 在原有名称字段之外增加可选引用：

```json
{
  "source_registry": "public-default",
  "resource_kind": "lut",
  "resource_id": "lut_example",
  "revision_id": "rev_current",
  "content_hash_algorithm": "lumina-lut-file-bytes-v1",
  "content_hash": "sha256:..."
}
```

导入旧数据时该对象可缺失，并继续现有名称/附件兼容；对象存在时必须优先按 exact revision 解析，hash 不匹配不得静默改用 latest 或同名资源。该字段要同步更新 share-card schema、导入/导出 adapter、round-trip 测试、feedback assembler 和 bug reproduction loader。

## 13. 迁移设计

### 13.1 首次启动

1. 读取旧索引并创建外部可恢复备份，记录备份 SHA-256。
2. 在 v1 仍是唯一写入者时只读扫描当前耗材和 LUT，构建带 `base_fingerprints` 的 v2 shadow index。
3. 旧同步索引记录只有在路径位于允许根目录、hash 一致且内容可加载时，才成为 managed migration candidate。迁移器把 candidate 复制到同文件系统 immutable revision staging 并再次验证；不移动或删除原文件。
4. 无受管理记录但 canonical content hash 与云端精确匹配的内容标记为 `local_equivalent`，不取得删除所有权。
5. 无法匹配的内容分配稳定 `local_id`，标记为 `local_import` 或 `legacy_unresolved`，继续可用。
6. Shadow index 为原物理路径记录 `legacy_aliases`，使 cutover 后旧 catalog/扫描器不会把原副本重复展示；alias 不授予删除所有权。
7. 校验 shadow index、path reservation、immutable candidate、黄金夹具合同和旧响应投影；失败时删除 shadow/staging，不改变 writer 或原文件。
8. 按 13.4 节提交 cutover marker。只有 marker 原子提交后，shadow index 才成为正式 v2 generation 0。

迁移不移动、不改名、不覆盖、不删除资源。

### 13.2 无网络迁移

- 本地分类不依赖网络。
- 云端精确 hash 对应延后到下次 catalog 成功刷新。
- 未完成对应不影响转换、详情、导出或本地编辑。

### 13.3 修复工具

提供离线审计/修复命令，默认 dry-run：

- 检查索引 schema、owned path、hash、历史版本和孤立暂存目录。
- 输出拟执行动作和风险。
- `--apply` 才允许重建索引、清理已确认的暂存目录或修复可证明的记录。
- 绝不根据名称或路径猜测云端 ID。

### 13.4 单写者 cutover 协议

每个领域在 `_sync/resource-store-marker.json` 保存独立 marker：

```json
{
  "schema_version": "1.0",
  "state": "v2_committed",
  "store_id": "uuid",
  "committed_generation": 0,
  "legacy_index_sha256": "sha256:...",
  "committed_at": "2026-07-10T00:00:00Z"
}
```

允许状态只有 `v1_active`、`migration_prepared` 和 `v2_committed`：

1. `v1_active`：旧 writer 可写；v2 只能扫描和构建 shadow。
2. `migration_prepared`：进程获取全局 commit 锁，所有 mutating endpoint 暂停；重新核对旧 index hash 和所有 `base_fingerprints`。
3. 若任一 fingerprint 变化，回到 `v1_active` 并重建 shadow；不合并不确定变化。
4. 若一致，写入并 fsync v2 index generation 0，再原子写 marker 为 `v2_committed`，fsync 父目录。
5. marker 提交后恢复 endpoint；所有 legacy/new endpoint 只能调用 v2 store。

启动时 marker 为 `migration_prepared` 则默认保持写入关闭，按备份 hash、shadow generation 和 journal 判定回到 `v1_active` 或完成 `v2_committed`；无法证明时进入只读 repair 模式。

`v2_committed` 是不可自动逆转的 writer 边界。关闭 feature flag 或回退前端只影响 UI；若 v2 本身故障，只能在停机维护中使用已验证备份和 repair 命令恢复，不能让 v1 与 v2 再次并发写入。

### 13.5 精确重装与 deferred migration

- `legacy_unresolved` 保存本地 canonical hash、扫描 generation、候选 registry key 和 `migration_state=deferred`，离线重启后不得丢失。
- Catalog 恢复后只按 8.6 canonical hash 建立候选；一个 hash 对应多个云端身份时保持 unresolved，并要求用户选择，不能任取第一个。
- exact provenance 引用缺失时，Studio 调用 12.1 exact revision detail/package；404、无权限或 hash 不符直接报告，不能安装 latest 代替。
- 成功重装产生新的 managed immutable revision；历史配方继续固定原 revision，不因 active pointer 变化而改写。

## 14. 离线与错误体验

### 14.1 离线

- “我的资源”从本机索引立即加载，全部本地工作流继续可用。
- 云资源库显示最近一次成功 catalog 缓存及更新时间。
- 离线缓存允许搜索和查看已缓存详情，但禁用安装、更新和远程历史下载。
- 无缓存时显示“当前无法连接资源库”，不能显示为“0 个资源”。

### 14.2 错误分类

后端返回稳定错误代码，至少区分：

- registry_not_configured
- registry_unreachable
- registry_contract_unsupported
- resource_not_found
- revision_not_found
- resource_in_use
- package_origin_invalid
- package_download_failed
- package_size_invalid
- package_hash_mismatch
- manifest_invalid
- content_hash_mismatch
- registry_package_binding_mismatch
- unsafe_archive
- content_unloadable
- resource_commit_conflict
- local_path_conflict
- local_index_invalid
- local_index_recovery_required
- local_install_damaged
- managed_resource_read_only

用户文案说明可采取的下一步，技术详情进入日志。错误中不回显 token、私有 URL 查询参数或绝对路径。

## 15. 缓存与一致性

- Catalog 缓存按 Registry 配置、channel 和查询条件隔离。
- 详情缓存按领域 ID + revision ID 隔离。
- 安装、更新、回退、修复和卸载成功后，统一触发领域缓存失效。
- LUT 必须刷新 LUT catalog、详情、颜色网格、KD-Tree 和转换器选择数据。
- 耗材必须刷新耗材列表、详情、求解器输入和使用状态，不删除可重建缓存以外的用户数据。
- 批量操作完成后只执行一次收敛刷新，避免每项操作导致 UI 抖动。
- 后端状态是本地安装语义的事实源；前端缓存不能覆盖后端新状态。

## 16. 可观测性

每个生命周期操作记录结构化事件，至少包含：

- request_id
- resource_kind
- resource_id
- revision_id
- operation
- previous_state
- final_state
- package_bytes
- duration_ms
- error_type / error_message（失败时）

禁止记录 token、完整授权头、私有下载签名和用户绝对路径。批量更新输出一个批次汇总事件，每个失败资源保留可定位子事件。

## 17. 测试策略

### 17.1 Registry

- v1 Catalog 在 181+ 条数据、未传 limit 时仍返回全部；保留多 revision、旧 hash 与旧字段。
- v2 Catalog 查询、筛选、排序、稳定 cursor 分页和每个逻辑资源只返回最新 approved revision。
- capability 缺失/旧版本/支持 v2 三种协商结果。
- 详情、历史和预览响应。
- exact revision detail/package 的 channel/token 授权、404 与下架语义。
- `publisher_kind` 权限：普通上传不能设置 lumina。
- 下载量只在有效下载计数，不改变 package hash。
- 上传、批准、拒绝、下架和 channel/visibility 重写。
- ZIP 路径穿越、大小写碰撞、symlink、设备文件、压缩炸弹、未声明 payload、hash/bytes 不符。
- material/LUT canonical hash 算法的逐字节黄金向量，以及 legacy LUT v1 -> v2 投影。
- record/manifest 的 kind/schema/ID/revision/hash/path/channel/files 任一字段不一致都拒绝。
- revision 不可变性和并发批准。
- token 与私有配置泄露扫描。

### 17.2 Materials

- 所有 package 通过 Registry 同版本 validator，并与 Registry 黄金 fixture byte-for-byte 对齐。
- 源文件到 package 的确定性构建。
- manifest channel/visibility/publisher/hash 一致。
- LUT 一包一 LUT；耗材必需 role 完整。
- legacy LUT v1 package 保持旧 hash，LUT v2 package 使用 `lumina-lut-file-bytes-v1`，禁止原地重定义。
- 禁止本地缓存、绝对路径、token、私有配置和 IDE 产物。
- 预览生成输入完整且可由 Registry 重建。

### 17.3 Studio 后端

- multipart `/material-sync/install`、legacy 四字段 `/install-from-registry` 和 v2 两字段 `/install-from-registry` 合同。
- 前端篡改 URL/hash/path 不影响后端解析结果；exact record/manifest 绑定任一字段不符都拒绝。
- 安装、更新、回退、卸载、修复和采用本地等价内容的状态机。
- managed installed 与 local equivalent 不混淆。
- update/rollback/repair 时 existing workflow 固定旧 immutable revision；卸载/delete 和 GC 在 lease 下被阻止。
- 当前 + 上一版本保留策略。
- 下载中断、hash 不符、无效 manifest、内容不可加载和原子切换失败。
- 对 `prepared`、`revision_published`、index replaced、journal committed 各阶段做进程崩溃/断电注入并验证启动恢复。
- 两个不同资源并发提交无 lost update；同资源并发互斥；Unicode/casefold 相同路径 reservation 冲突。
- v1 -> v2 shadow/cutover、marker 各阶段、无网络迁移、损坏索引恢复和 dry-run repair。
- cutover 后所有 legacy mutating endpoint 只写 v2；legacy path edit/delete 不能绕过 managed read-only 和 lease。
- `local_import/local_copy/legacy_unresolved/local_equivalent` 重启后 local_id、source_ref 和 deferred state 保持。
- 配方、分享卡、bug report provenance round-trip 与 exact revision 重装。
- managed file 被修改、增加 sidecar 或替换为 symlink/reparse point 时卸载 fail closed 且不删任何文件；detach 只解除管理。
- 安装后 catalog/详情/转换器缓存刷新。
- 源会话切换或关闭后的资源可用性。
- Windows/macOS/Linux 路径与大小写行为。
- 结构化日志质量门禁。

### 17.4 Studio 前端

- 云资源库 / 我的资源双视图。
- 快速入口、搜索、筛选、排序、cursor 加载和空/离线/错误状态。
- 官方/社区角标只读取 publisher kind。
- 所有本地状态与允许动作映射。
- 更新角标、更新全部部分成功、单项失败保留。
- 安装前详情、移动端全屏详情和桌面侧边详情。
- 云端只读、本地副本创建、删除/卸载文案与使用中阻止。
- 中英文、明暗主题、键盘导航和窄屏布局。

### 17.5 跨仓联调与真人验收

- 三仓 checkout 与 `UPSTREAM.json` 指定 exact commit/fixture SHA 一致。
- 使用固定 Registry 测试实例和临时 Studio worktree。
- 从非 localhost 地址打开 Studio，浏览真实 catalog。
- 分别安装一个耗材和一个 LUT，重启后确认状态和文件。
- 发布测试 revision，确认角标和更新全部。
- 执行回退并验证当前/上一版本交换。
- 创建本地副本并卸载来源，确认副本保留。
- 制造文件缺失和 hash 变化，确认 damaged/repair。
- 断开 Registry，确认本地可用和云端缓存提示。
- 使用当前流程占用资源，确认卸载被阻止。
- 截图桌面与移动端，并检查控制台、API 失败和残留进程。

所有破坏性验收只操作临时 worktree 和测试 Registry，不删除生产或用户主工作区数据。

### 17.6 设计基线证据

本设计复核使用以下 exact baseline：

- Studio base：`6f8589fb17c77e09468879709f17a3b768d4dff3`
- Registry：`ba6e642b4a9565f66363951bcceef095eb8081da`
- Materials：`163103130c531260bc58ba5c913cc856f1808dea`

已执行命令：

```text
python -m pytest tests -q
python scripts/validate_packages.py --packages packages
python scripts/validate_lut_packages.py --packages lut-packages
python -m pytest tests/test_material_sync_api_unit.py tests/test_lut_registry_sync_unit.py tests/test_material_sync_scheduler_unit.py -q
python scripts/run_vitest.py run src/__tests__/material-cloud-sync-panel.test.tsx src/__tests__/material-library-panel.test.tsx src/__tests__/lut-cloud-sync-panel.test.tsx src/__tests__/lut-library-panel.test.tsx src/__tests__/material-sync-api.test.ts src/__tests__/lut-api.test.ts
```

对应结果为 Registry 55 passed、Materials 174 个耗材包与 67 个 LUT 包校验通过、Studio 后端 144 passed、Studio 前端 46 passed。这些只证明实施前基线，不证明 v2 已实现；每个实现 PR 必须记录自己的 exact base/head、命令和行为证据。

## 18. 性能与容量目标

- “我的资源”首屏不等待网络。
- Registry v1 Catalog 保持未传 limit 时全量返回；只有 v2 Catalog 默认每页 50 条、最大 100 条。
- 搜索使用防抖并由 Registry 执行，不先下载全部目录。
- Catalog 缓存命中后应在 200 ms 级别返回本地结果；网络目标由部署监控单独定义。
- 更新全部限制并发下载数，避免耗尽磁盘、网络或文件句柄。
- hash 扫描缓存以文件大小、mtime 和 inode/file identity 为提示，但最终建立云端等价关系时必须有完整 hash。
- 预览摘要大小受限，列表页不加载完整 LUT 点云或大型验证历史。

## 19. 分阶段交付与合并顺序

### 阶段 0：契约与测试夹具

- 固定 v1 不变合同、v2 公共字段、canonical hash 算法、错误代码、状态枚举和 exact-revision 示例响应。
- Registry 提交黄金 package；Materials 和 Studio vendor exact bytes 与 `UPSTREAM.json`，加入跨仓 checksum/合同测试。
- 不改变用户界面。

### 阶段 1：Registry 向后兼容扩展

- 新增独立 v2 catalog/detail/exact revision/package 与 capability；增加 publisher、预览摘要、版本历史、下载量、查询和 cursor。
- v1 endpoint 保持未传 limit 全量、多 revision、旧 hash 和旧响应形状，不原地改变默认值。
- 完成安全与不可变 revision 测试。

### 阶段 2：Materials 元数据与内容校验

- 补齐公开来源、说明、标签和预览输入。
- 重建或修复不满足新合同的 package。
- 不提交密钥、私有部署资料或本机路径。

### 阶段 3：Studio 后端生命周期 v2

- 新索引、durable transaction/recovery、revision lease、单写者 cutover、状态机、安装/更新/回退/卸载/修复和离线缓存。
- 旧 UI/endpoint 保留请求与响应合同，但所有 mutation 经过 v2 adapter；不存在 v1/v2 双写。
- 在 capability 未启用前只构建/校验 shadow index，不提交 cutover marker。

### 阶段 4：Studio 前端资源中心

- 合并本地库和云端页面。
- 上线双视图、详情、更新角标和批量更新。
- 保留一版旧页面展示回退能力；回退 UI 仍读取/写入同一 v2 store，绝不恢复 v1 writer。

### 阶段 5：联调、灰度与清理

- 三仓测试环境联调和真人浏览器验收。
- 小范围开启 v2，观察安装失败率、迁移结果和错误日志。
- 稳定后默认启用，并在后续独立 PR 删除旧 UI 和弃用 endpoint。

合并顺序固定为 Registry v2 additive contract -> Materials v2 metadata/packages -> Studio 后端（先 shadow、后 cutover）-> Studio 前端/启用。任何阶段都不能要求尚未部署的下游字段才能维持旧功能。

## 20. 发布与回滚

- Registry 先部署，新增字段必须对旧客户端无害。
- Materials 内容更新只发布满足旧客户端仍可下载的 package。
- Studio 首次发布 v2 时保留旧索引备份和旧 UI 回退入口；cutover 前可以关闭 shadow，cutover 后 v2 是唯一 writer。
- 若 v2 UI 出现问题，可关闭 v2 入口并让旧 UI 使用 v2 legacy projection；不得恢复 v1 writer，也不得回滚文件系统到未验证快照。
- 若 Registry 新字段故障，Studio 使用最近 catalog 缓存并保持本地功能。
- 若迁移失败，记录失败并回到旧索引，不继续执行安装或清理。
- 旧 API 的删除必须在遥测确认旧客户端使用率可接受后单独进行。

## 21. 验收标准

设计完成的最低标准：

1. 用户不再看到“云同步”作为资源目录名称。
2. 耗材和 LUT 都具有云资源库/我的资源双视图和一致操作语言。
3. 同一逻辑资源在 UI 中只有一张云端卡片，并正确叠加本地状态。
4. `installed` 只表示受管理且 hash 一致的可用安装。
5. 本地等价内容、本地副本和安装损坏有独立状态和安全动作。
6. 云端安装资源不可直接编辑；创建副本后可编辑且不受来源更新/卸载影响。
7. 浏览器不能控制 package URL/hash/path。
8. 安装、更新和回退失败不会破坏当前可用版本。
9. 正在使用的资源不能卸载，历史引用缺失时可重新安装。
10. 断网时本地资源完全可用，云资源库不显示假空目录。
11. 旧内容迁移不移动、不覆盖、不删除文件，只用完整 hash 建立等价关系。
12. Lumina 官方与社区分享由显式 publisher 字段决定，不由路径、名称或 channel 猜测。
13. 三仓合同、安全、迁移、前端和跨仓真人验收全部通过。
14. 所有测试服务、浏览器 profile 和长运行进程在验收结束后清理。
15. Registry v1 在无 limit、181+ 条目和多 revision 下保持现有完整响应；v2 分页不会影响旧 Studio。
16. Material/LUT canonical hash 算法有显式版本、固定输入字节和三仓 byte-identical 黄金夹具。
17. 每个事务阶段崩溃后能确定性恢复；两个资源并发提交不会 lost update，casefold 路径不会双重占用。
18. 预览/生成固定 exact immutable revision；更新、回退、修复和 GC 不会改变租约中的 payload。
19. cutover 后 v2 是唯一 writer，旧 endpoint 和旧 UI 不能绕过只读、所有权或使用中保护。
20. local copy、deferred migration 和 exact provenance 重启后不丢失，历史配方可按 exact revision 重装。
21. 卸载/GC 删除前逐文件核对安装时 hash；文件被修改或含未知 sidecar 时 fail closed 且不删除用户内容。

## 22. 设计取舍总结

本设计刻意不追求“一套通用资源平台”。共享的是用户能理解的生命周期、安全原则、状态模型和 UI 结构；耗材与 LUT 的文件、校验、缓存和业务 API 保持领域独立。这样可以消除当前最明显的半成品感和状态错误，又不会用一次大重写把已经工作的转换、校准和材料流程置于高风险中。
