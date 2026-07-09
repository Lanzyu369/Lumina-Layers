# 云耗材与云 LUT 资源中心 v2 设计

状态：待最终文档确认
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
- 文件所有权：本地 v2 安装索引中的 `owned_paths`，不能从路径名称推断。

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
2. 验证 owned path 位于允许根目录，且文件存在。
3. 重新计算或读取可信缓存中的 content hash。
4. 使用领域加载器验证内容可实际加载。
5. 与 Registry 当前 catalog/detail 的 revision 和 hash 比较。
6. 未命中受管理记录时，才扫描精确 hash 相同的未受管理内容并标记 `local_equivalent`。

不得把 `local_exists=true`、同名文件、同目录名或相同 `material_id` 单独视为 `installed`。

## 6. 本地生命周期行为

### 6.1 安装与更新

安装和更新共用安全事务：

1. 前端只提交领域 ID 和 revision ID。
2. Studio 后端重新读取当前 Registry catalog/detail，并在已配置 channel 中解析该 revision。
3. 校验 package URL 与 Registry 同源，禁止重定向。
4. 限制响应大小、Content-Length、下载时间和压缩包大小。
5. 校验 `package_sha256`。
6. 安全读取 ZIP，校验 manifest、每个文件 hash/bytes 和 `content_hash`。
7. 在受管理根目录外的临时目录解压并使用领域加载器验证。
8. 更新时把当前版本移动为唯一上一版本。
9. 通过同文件系统原子重命名切换新版本。
10. 原子写入 v2 索引并刷新 LUT 详情、catalog、KD-Tree、耗材列表和相关运行时缓存。

任一步失败都删除暂存内容并保留当前可用版本。

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
- 当前转换、预览、生成、校准或材料流程正在使用资源时阻止卸载/删除，并指出占用流程。
- 卸载删除 owned paths、上一版本缓存和当前索引记录，但保留最小历史信息用于显示“曾安装”和重新安装。
- 卸载不得删除本地副本或 `local_equivalent` 原文件。
- 历史配方打开时若引用资源缺失，显示资源身份和“重新安装”入口；不得静默改用同名资源。

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

### 8.2 Catalog 公共字段

两个 catalog 条目至少提供：

- 领域 ID：`material_id` 或 `lut_id`
- `revision_id`
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

Catalog 默认每个逻辑资源返回最新已批准 revision。旧 revision 通过详情接口获取，不在主目录重复成多张卡片。

不可变性分成两层：

- 资源 revision 的核心文件和 `content_hash` 永远不可原地改变；核心内容变化必须生成新 `revision_id`。
- 审批、`publisher_kind`、channel 或 visibility 变化可以为同一核心 revision 生成新的分发包 envelope，但必须写入新的不可变 package path，并生成新的 `package_sha256`。旧 package 不得覆盖或复用原路径。

因此 `(resource_id, revision_id, content_hash)` 表示核心内容版本，`package_sha256` 表示某次具体分发 envelope。Catalog 始终指向当前有效 envelope，审计记录保留旧 envelope 的 hash 和路径。

### 8.3 查询与分页

Catalog 支持：

- `q`
- `publisher_kind`
- `brand`
- 领域筛选，例如 `color_mode`、`material_type`
- `sort=updated_desc | downloads_desc`
- `limit`
- `cursor`

过渡期保留 `offset` 和旧响应计数字段。新客户端优先 cursor，避免目录更新或下载量变化导致 offset 重复/漏项。

Cursor 必须包含排序键和资源 ID 稳定次序。按下载量排序时使用请求开始时的分页快照或等价稳定游标，不能因翻页期间计数变化而重复或遗漏同一资源。

### 8.4 详情与历史

新增或扩展领域详情接口：

- `GET /materials/{material_id}`
- `GET /luts/{lut_id}`

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

## 9. Studio API 与前端适配器

### 9.1 安装请求

新增或规范化领域安装接口：

- `POST /api/material-sync/install`，请求仅含 `material_id`、`revision_id`。
- `POST /api/lut-registry/install`，请求仅含 `lut_id`、`revision_id`。

旧 `/api/material-sync/install-from-registry` 在兼容期保留，但后端必须忽略浏览器提供的 URL/hash，按 ID/revision 重新解析，随后标记弃用。

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

### 9.3 共享前端 Resource View Model

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
- owned paths 必须记录规范化相对路径，禁止记录用户绝对路径。

## 12. 本地索引 v2

耗材和 LUT 保留独立索引文件，但使用相同语义：

```json
{
  "schema_version": "2.0",
  "resources": {
    "resource-id": {
      "active_revision_id": "rev_...",
      "active_content_hash": "sha256:...",
      "owned_paths": ["relative/managed/path"],
      "source_registry": "registry-key",
      "publisher_kind": "community",
      "installed_at": "2026-07-10T00:00:00Z",
      "updated_at": "2026-07-10T00:00:00Z",
      "previous": {
        "revision_id": "rev_...",
        "content_hash": "sha256:...",
        "cache_path": "relative/history/path"
      },
      "last_operation": "install"
    }
  },
  "history": {}
}
```

规则：

- 索引使用临时文件、fsync 和同目录原子替换。
- 每次 schema 迁移前保留带时间戳备份。
- 索引不存 token、绝对路径或可由 package 伪造的信任结果。
- `previous` 最多一项。
- 最小卸载历史与受管理安装记录分离，历史不得赋予文件所有权。

## 13. 迁移设计

### 13.1 首次启动

1. 读取旧索引并创建外部可恢复备份。
2. 只读扫描当前耗材和 LUT。
3. 旧同步索引记录只有在路径位于受管理根目录、hash 一致且内容可加载时，才迁移为 `installed`。
4. 无受管理记录但 content hash 与云端精确匹配的内容标记为 `local_equivalent`，不取得删除所有权。
5. 无法匹配的内容标记为 `local_import` 或 `legacy_unresolved`，继续可用。
6. 原子写入 v2 索引；失败时保留旧索引和全部文件。

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
- unsafe_archive
- content_unloadable
- local_path_conflict
- local_index_invalid
- local_install_damaged

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

- Catalog 查询、筛选、排序、cursor 分页和旧 offset 兼容。
- 每个逻辑资源只返回最新 approved revision。
- 详情、历史和预览响应。
- `publisher_kind` 权限：普通上传不能设置 lumina。
- 下载量只在有效下载计数，不改变 package hash。
- 上传、批准、拒绝、下架和 channel/visibility 重写。
- ZIP 路径穿越、大小写碰撞、symlink、设备文件、压缩炸弹、未声明 payload、hash/bytes 不符。
- revision 不可变性和并发批准。
- token 与私有配置泄露扫描。

### 17.2 Materials

- 所有 package 通过 Registry 同版本 validator。
- 源文件到 package 的确定性构建。
- manifest channel/visibility/publisher/hash 一致。
- LUT 一包一 LUT；耗材必需 role 完整。
- 禁止本地缓存、绝对路径、token、私有配置和 IDE 产物。
- 预览生成输入完整且可由 Registry 重建。

### 17.3 Studio 后端

- 前端篡改 URL/hash/path 不影响后端解析结果。
- 安装、更新、回退、卸载、修复和采用本地等价内容的状态机。
- managed installed 与 local equivalent 不混淆。
- 使用中资源保护。
- 当前 + 上一版本保留策略。
- 下载中断、hash 不符、无效 manifest、内容不可加载和原子切换失败。
- v1 -> v2 索引迁移、无网络迁移、损坏索引恢复和 dry-run repair。
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

## 18. 性能与容量目标

- “我的资源”首屏不等待网络。
- Catalog 默认每页 50 条，最大 100 条。
- 搜索使用防抖并由 Registry 执行，不先下载全部目录。
- Catalog 缓存命中后应在 200 ms 级别返回本地结果；网络目标由部署监控单独定义。
- 更新全部限制并发下载数，避免耗尽磁盘、网络或文件句柄。
- hash 扫描缓存以文件大小、mtime 和 inode/file identity 为提示，但最终建立云端等价关系时必须有完整 hash。
- 预览摘要大小受限，列表页不加载完整 LUT 点云或大型验证历史。

## 19. 分阶段交付与合并顺序

### 阶段 0：契约与测试夹具

- 固定公共字段、错误代码、状态枚举和示例响应。
- Registry、Materials 和 Studio 各自加入合同测试。
- 不改变用户界面。

### 阶段 1：Registry 向后兼容扩展

- 增加 publisher、详情、预览摘要、版本历史、下载量、查询和 cursor。
- 保留旧字段和 offset。
- 完成安全与不可变 revision 测试。

### 阶段 2：Materials 元数据与内容校验

- 补齐公开来源、说明、标签和预览输入。
- 重建或修复不满足新合同的 package。
- 不提交密钥、私有部署资料或本机路径。

### 阶段 3：Studio 后端生命周期 v2

- 新索引、迁移器、状态机、安装/更新/回退/卸载/修复和离线缓存。
- 旧 UI 仍可使用旧 endpoint。
- 新行为通过临时能力开关或 capability response 暂不默认启用。

### 阶段 4：Studio 前端资源中心

- 合并本地库和云端页面。
- 上线双视图、详情、更新角标和批量更新。
- 保留一版旧页面回退能力，但不双写两套索引。

### 阶段 5：联调、灰度与清理

- 三仓测试环境联调和真人浏览器验收。
- 小范围开启 v2，观察安装失败率、迁移结果和错误日志。
- 稳定后默认启用，并在后续独立 PR 删除旧 UI 和弃用 endpoint。

合并顺序固定为 Registry -> Materials -> Studio 后端 -> Studio 前端/启用。任何阶段都不能要求尚未部署的下游字段才能维持旧功能。

## 20. 发布与回滚

- Registry 先部署，新增字段必须对旧客户端无害。
- Materials 内容更新只发布满足旧客户端仍可下载的 package。
- Studio 首次发布 v2 时保留旧索引备份和旧 UI 回退入口。
- 若 v2 UI 出现问题，可关闭 v2 入口并继续使用同一后端索引；不得回滚文件系统到未验证快照。
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

## 22. 设计取舍总结

本设计刻意不追求“一套通用资源平台”。共享的是用户能理解的生命周期、安全原则、状态模型和 UI 结构；耗材与 LUT 的文件、校验、缓存和业务 API 保持领域独立。这样可以消除当前最明显的半成品感和状态错误，又不会用一次大重写把已经工作的转换、校准和材料流程置于高风险中。
