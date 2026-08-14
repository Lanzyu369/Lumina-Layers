# 可安装式创意工坊设计

## 状态与范围

本文记录已经确认的创意工坊宿主、GitHub 分发、模块安装和运行隔离方案。它取代旧版
“在 Lumina Studio 源码中注册 React 组件”的宿主方向。

本设计只负责以下子系统：

1. Lumina Studio 中的创意工坊入口和模块管理器；
2. 可独立发布的模块包格式和公开 SDK；
3. 基于 GitHub Registry 与 GitHub Releases 的发现、安装和更新；
4. 模块运行沙箱、权限桥接、故障隔离和回滚；
5. 官方“拼豆工作台”作为预装模块的跨仓库接入方式。

拼豆识别、矩阵编辑、压合渲染和 Lumina 颜色转换属于独立模块的产品设计，不在本文
重新定义。现有
`docs/superpowers/specs/2026-07-30-creative-workshop-bead-mode-design.md`
中的拼豆语义继续作为拆仓参考，但其中的源码内置模块、白名单注册和直接挂载 React
组件方案不再是目标架构。

## 结论

创意工坊第一版不自建商店服务器。GitHub 同时承担源码托管、Release 安装包托管和
Registry 目录托管，Lumina 只实现本地安装器、缓存、校验、权限宿主和运行沙箱。

整体由三个仓库组成：

| 仓库 | 职责 |
| --- | --- |
| `Lumina-studio` | 创意工坊宿主、公开 SDK、包管理器、沙箱、能力桥接和预装包锁定 |
| `Lumina-Fuse-Bead-Studio` | 官方“拼豆工作台”的源码、测试、构建和 Release |
| `Lumina-Workshop-Registry` | 已审核模块目录、精确版本、Release 资产地址、摘要、权限和撤销状态 |

官方模块与第三方模块使用完全相同的包格式、SDK、运行容器和能力检查。`official`
只影响来源标识、默认预装和用户信任展示，不提供私有 API 或更高运行权限。

## 市场方案取舍

本方案组合以下成熟生态的做法：

- Steam Workshop 的订阅式安装、后台更新、本地状态和应用自行解释内容；
- Obsidian、Logseq、思源集市与 HACS 的“独立 GitHub 仓库 + 中央目录 +
  GitHub Release”分发结构；
- RuneLite 的精确版本锁定、依赖可审查、安全模式和故障隔离；
- Figma 的沙箱界面、消息桥接和显式网络范围；
- VS Code 的独立扩展包、禁用、旧版本恢复和恶意扩展撤销；
- Blender 的版本兼容字段、平台字段和带理由的权限声明。

不采用以下做法：

- 不让客户端搜索全站 GitHub 仓库或逐个请求所有仓库的 latest release；
- 不从仓库默认分支、源码 ZIP、任意 CDN 或运行时 URL 直接执行代码；
- 不把权限声明当作提示文字而不做技术强制；
- 不让发布者更新后绕过包校验、兼容性校验和权限变更确认；
- 不让官方拼豆模块导入 Lumina 内部 store、组件或私有工具。

## 目标与非目标

### 目标

- 用户能在创意工坊中浏览、安装、启用、禁用、卸载、更新和回滚模块；
- 已安装模块在 GitHub 或 Registry 暂时不可用时仍可离线运行；
- 开发者只维护自己的 GitHub 仓库即可发布模块；
- 官方模块可以随 Lumina 安装包预装，但仍能被禁用、卸载和重装；
- 模块只能通过版本化宿主能力访问图片、项目、颜色库和 Lumina 交接流程；
- 包下载、解压、切换和回滚均不破坏上一份可运行版本；
- 一个模块崩溃、超时或输出非法数据时不影响主导航、转换器和其他模块；
- Registry 能撤销恶意版本、阻止不兼容版本并保留可审计的版本历史。

### 非目标

- 第一版不建设 Lumina 账号、评分、评论、付费分成或创作者后台；
- 第一版不支持原生动态库、外部程序、Python/Node 子进程或运行时下载代码；
- 第一版不允许模块直接访问任意文件系统、任意网络、系统凭据或 Lumina 数据库；
- 第一版在普通浏览器模式下不执行社区或未审核模块；浏览器平台无法仅靠 iframe CSP
  完整阻止沙箱页面把自身导航到外部地址，不能把不完整隔离伪装成安全能力；
- 第一版不解决 GitHub 在所有网络环境下的可达性；它通过本地缓存和离线预装保证
  已安装功能不被网络阻断；
- 第一版不自动迁移旧的源码内置原型项目；原型尚未作为稳定公开格式发布；
- 第一版不承诺跨模块依赖。模块必须是可独立安装、可独立禁用的自包含包。

## 仓库边界

### Lumina Studio 主仓库

主仓库保留：

- “创意工坊”主导航入口和模块管理界面；
- Registry 客户端、本地缓存和签名验证；
- 模块包下载、摘要校验、解压、版本切换和回滚；
- 只读模块静态资源服务；
- 沙箱 iframe、消息桥接、公开宿主能力和 SDK 类型；
- 模块项目命名空间、配额和交接 Lumina 转换器的适配器；
- 用于宿主回归测试的最小无业务 fixture 模块；
- 官方预装模块的版本与摘要锁文件。

主仓库不保留：

- 拼豆识别、编辑、渲染或拼豆专用界面源码；
- 第三方模块的构建配置；
- 依赖具体模块实现的宿主分支；
- 直接导入外部模块 React 组件的注册表。

### 官方拼豆模块仓库

`Lumina-Fuse-Bead-Studio` 独立拥有：

- 用户可见名称“拼豆工作台”；
- 稳定模块 ID `lumina.bead-pattern`；
- 拼豆项目 schema、识别器、编辑器、渲染器和模块内迁移；
- 对公开 Workshop SDK 的唯一宿主依赖；
- 自己的单元测试、浏览器测试、构建和 Release；
- 自包含的 UI、UI 内部 worker、语言包、图标、README 和许可证。

该仓库可以使用 Lumina 发布的 SDK 开发包，但不能通过源码路径引用
`frontend/src/`、Zustand store、Tailwind 内部组件或主仓库测试 helper。

### Registry 仓库

`Lumina-Workshop-Registry` 保存人工可审查的源条目，并由 GitHub Actions 生成一个
有界的 `registry-v1.json` 和 detached signature。Registry 不保存模块源码或模块
安装包。

模块 ID 一旦收录便绑定到发布者 GitHub 仓库。仓库转移或维护者变更必须单独提交
PR，并由原维护者确认或由 Registry 维护者依据明确的弃权/安全流程接管；不能仅通过
修改模块 manifest 抢占已有 ID。

## 模块包格式

Release 中的标准资产命名为：

```text
<module-id>-<semver>.lumina-workshop
```

`.lumina-workshop` 是 ZIP 容器，但安装器只接受该扩展名和固定目录结构：

```text
manifest.json
ui/index.html            # 唯一运行时入口
assets/icon.png          # 由宿主展示，不由模块运行时读取
assets/gallery/...       # 可选，由宿主展示
README.md
LICENSE
```

`ui/index.html` 必须是单文件、可离线运行的构建产物。运行时脚本、样式、字体、语言包
和图片都内联在该文件中；需要并行计算时，把 worker 构建为字符串并通过 `Blob` URL
启动。第一版不执行 WASM。`assets/` 只供宿主在详情页展示，模块 iframe 不获得读取
包目录的通用接口。

安装器的 v1 硬上限为：

| 项目 | 上限 |
| --- | ---: |
| 下载资产与 ZIP 压缩后大小 | 100 MiB |
| 解压后总大小 | 300 MiB |
| 文件数量 | 2,000 |
| 单个文件 | 100 MiB |
| 单文件压缩比 | 100:1 |

超过任一上限立即中止，不允许 manifest 自行调高。模块不能在启动时下载新的可执行
代码，也不能 `eval`、动态 `import` 或注入脚本。

安装器拒绝：

- 绝对路径、`..`、符号链接、设备文件和大小写冲突路径；
- 解压后文件数、单文件大小或总大小超过上述 v1 硬上限的包；
- manifest 未列出的入口文件；
- 重复模块 ID、非法语义版本或不支持的 manifest schema；
- 不兼容的 Workshop API 或 Lumina 版本；
- 未知权限或空权限理由；
- Registry 摘要与下载字节不一致的包。

### Manifest v1

`manifest.json` 至少包含：

```json
{
  "manifestVersion": 1,
  "id": "lumina.bead-pattern",
  "version": "1.0.0",
  "name": {
    "zh-CN": "拼豆工作台",
    "en-US": "Fuse Bead Studio"
  },
  "description": {
    "zh-CN": "分析、编辑并生成可交给 Lumina 的拼豆作品",
    "en-US": "Analyze, edit, and hand fuse-bead artwork to Lumina"
  },
  "publisher": "Lumina",
  "workshopApi": {
    "min": "1.0.0",
    "maxExclusive": "2.0.0"
  },
  "luminaVersion": {
    "min": "1.0.0"
  },
  "entrypoints": {
    "ui": "ui/index.html"
  },
  "permissions": [
    {
      "name": "image.pick",
      "reason": "选择需要分析的拼豆图纸"
    },
    {
      "name": "project.storage",
      "reason": "在本机保存可继续编辑的拼豆项目"
    },
    {
      "name": "color-library.read",
      "reason": "把源颜色映射到用户选择的 LUT 或耗材档案"
    },
    {
      "name": "handoff.image",
      "reason": "把生成图像和物理尺寸交给 Lumina 转换器"
    }
  ]
}
```

`publisher` 是展示字段，不构成身份凭据。可信发布者、官方标识、仓库所有权和实际
下载摘要都以已签名 Registry 为准。

`permissions` 只列出需要用户授权或限定作用域的能力。`ui.locale`、`ui.theme`、
`status.progress` 和 `status.error` 是每个模块都可使用的基础 API，不写入权限清单，
也不能借此读取其他应用状态。

## Registry 与 GitHub Release

客户端每次刷新只读取一个 Registry 索引，不逐模块调用 GitHub API。索引在本地保存
ETag、成功时间和上一份已验证内容；应用安装包还附带一份构建时 Registry 快照。

每个可安装版本在 Registry 中固定：

- 模块 ID、版本和发布者仓库；
- GitHub Release tag 和精确资产名；
- 资产字节数与 SHA-256；
- manifest 摘要、Workshop API 范围和 Lumina 版本范围；
- 权限；
- `active`、`deprecated`、`blocked` 三种状态；
- 若被撤销，面向用户的原因代码和安全等级。

Registry Actions 定期扫描已登记仓库的新 Release，读取资产摘要并创建索引更新 PR：

- 权限、发布者、入口类型和 API 范围未扩大时，完整自动检查通过后可自动合并；
- 新增权限、迁移仓库或改变入口类型时必须人工审核；
- Release 缺少标准资产、版本未递增、摘要不稳定或 manifest 与 Registry 不一致时
  不进入索引；
- Registry 只指向正式 Release，不接受 draft、prerelease 或可移动的默认分支。

官方仓库启用 GitHub Immutable Releases。第三方仓库即使没有启用不可变 Release，
客户端仍以 Registry 中的 SHA-256 为准；资产被替换后会因摘要不符而拒绝安装。

Registry 文件使用 Ed25519 发布密钥生成 detached signature，签名元数据包含
`keyId`。应用内置允许的验证公钥集合；根密钥新增或撤销只能随 Lumina 应用更新，
不能由 Registry 自己声明。没有有效签名的新索引不会覆盖上一份有效缓存。该签名只
证明“此版本已被 Lumina Registry 接受”，不替代模块沙箱和逐项权限检查。

## 安装、更新与卸载

### 安装事务

安装流程固定为：

1. 从已验证 Registry 选择精确版本；
2. 下载到临时文件；连接超时 15 秒、连续 60 秒无新字节则中止、总时长最多
   10 分钟，并在超过 100 MiB 前终止；
3. 校验字节数、SHA-256、包结构、manifest 和兼容性；
4. 解压到模块版本专属的临时目录；
5. 运行不执行模块代码的静态验证；
6. 原子重命名为 `<module-id>/<version>/`；
7. 首次沙箱启动和握手成功后切换 `activeVersion`；
8. 保留上一份成功版本作为回滚点。

任一步失败都删除本次临时内容并继续使用旧版本。安装器不在原目录覆盖文件。

### 更新策略

- 官方预装模块默认自动检查稳定版本，但用户可以关闭自动更新；
- Registry 收录的第三方模块默认提示更新，由用户选择安装；
- 通过 GitHub URL 手工安装的未审核模块默认不自动更新；
- 权限集合扩大时，即使开启自动更新也必须重新确认；
- 更新后第一次启动、项目加载或健康检查失败时自动回滚；
- 用户可从“版本”菜单主动恢复 Registry 仍保留的旧版本。

### 卸载语义

卸载默认只移除模块代码和启用状态，不删除该模块的项目数据。用户可以在二次确认中
选择同时删除项目。

官方预装模块卸载后不会在下次启动时自动复活。包管理器记录卸载状态，并提供：

- 无网络时从安装包内的 seed package 重装；
- 有网络时从 Registry 安装最新兼容版本；
- 禁用但保留代码的轻量选项。

## 官方预装模块

Lumina 的发布流程使用主仓库中的 seed lock 锁定官方模块。lock 必须包含以下字段：

| 字段 | 内容 |
| --- | --- |
| `moduleId` | 稳定 ID，例如 `lumina.bead-pattern` |
| `version` | 完整 SemVer |
| `releaseAsset` | 与版本一致的标准 `.lumina-workshop` 资产名 |
| `sha256` | 发布流水线从实际 Release 写入的 64 位小写十六进制摘要 |

设计阶段不提交虚构摘要；没有真实 Release 和摘要时，seed lock 不能进入正式构建。

打包流水线下载精确 Release 资产、校验摘要并嵌入 Lumina 安装包。首次启动时，包管理器
把 seed package 按正常安装事务注册为已安装模块。运行时不区分“从安装包复制”和
“从 GitHub 下载”的模块。

主仓库 CI 使用最小 fixture 模块验证 SDK 和宿主，不依赖拼豆源码。跨仓库兼容测试再
安装 lock 中的官方拼豆包，验证握手、权限和图片交接。

## 运行隔离

### 沙箱结构

模块 UI 运行在独立 iframe 中，使用：

```text
sandbox="allow-scripts"
```

不授予 `allow-same-origin`、表单提交、弹窗、顶层导航、任意下载或宿主 DOM 访问。
模块响应使用固定 CSP：`default-src 'none'`、`connect-src 'none'`、
`script-src 'unsafe-inline'`、`style-src 'unsafe-inline'`、
`worker-src blob:`、`img-src data: blob:`、`font-src data:`、
`object-src 'none'`、`base-uri 'none'`、`form-action 'none'`。不允许
`unsafe-eval`、外部 URL 或由模块修改 CSP。内联脚本之所以可执行，是因为整个
`ui/index.html` 已通过 Registry 摘要和安装事务固定；iframe 仍处于 opaque origin。

模块包和 SDK 不能依赖 Electron `preload`、Node integration 或桌面专用私有对象。
正式桌面版由 Electron 主进程再加一层请求防火墙：按模块 frame 拦截非 loopback 的
导航、子资源、WebSocket 和其他出站请求，模块无法通过把自身页面导航走来绕过 CSP。
该防火墙属于宿主安全边界，不通过 preload 暴露给模块。

普通浏览器无法提供同等级的 frame 级请求防火墙。因此 v1 浏览器模式只启动签名
Registry 中标记为 `official` 的模块、随应用锁定的官方 seed、主仓库测试 fixture，
以及开发者在显式不安全开发开关下加载的本地包。Registry 社区包、GitHub URL 包和
普通本地包可以浏览、下载和管理，但“打开”按钮说明需要桌面版。开发开关默认关闭，
界面持续显示风险条，并禁止向该模块交付真实项目、图片和色库，只能使用合成 fixture。

“浏览器可运行”只表示宿主允许模块进入原有的受限 iframe，不授予额外权限。iframe
仍使用 `sandbox="allow-scripts"`，不含 `allow-same-origin`；固定 CSP 继续拒绝网络、
弹窗、父页面 DOM 和文件系统访问。模块只能调用 manifest 已声明且由宿主实现的 RPC，
后端以服务端持久化的 `source` 与 `official` 身份作最终授权判断。

### RPC 桥接

宿主与模块通过 `MessageChannel` 通信：

1. 宿主创建 iframe 和一次性 channel；
2. 模块发送包含 module ID、module version 和 Workshop API version 的握手；
3. 宿主核对当前安装记录后传递受限 `MessagePort`；
4. 后续请求使用版本化 envelope、request ID、方法名和 structured-clone payload；
5. 宿主逐请求检查 manifest 权限和下述固定的参数、速率与超时边界；
6. 二进制图像使用可转移 `ArrayBuffer`，不使用 base64 或共享宿主对象。

未知方法、重复 request ID、过大 payload、超时请求和握手身份不符均被拒绝。模块只能
接收本模块事件和本模块项目，不能枚举其他模块或主应用状态。

RPC v1 使用固定资源边界：

- 握手必须在 iframe `load` 后 10 秒内完成；
- 控制消息的 structured-clone payload 不超过 1 MiB；
- 单次二进制传输不超过 64 MiB；
- 每个模块持续 30 次/秒、突发 60 次的 token bucket；
- 普通宿主调用默认 30 秒超时，二进制交接默认 120 秒；
- 等待用户操作的宿主原生对话框暂停该次调用的超时计时；
- 模块自身的图像分析在沙箱内完成，并通过 `status.progress` 报告，不占用一个
  无限期 RPC。

### 首版能力

公开 Workshop API v1 提供：

| 能力 | 语义 |
| --- | --- |
| `image.pick` | 由宿主打开图片选择器，返回经过类型与像素上限验证的图像 |
| `project.storage` | 读写该模块自己的版本化项目，使用下述 v1 固定配额 |
| `color-library.read` | 读取用户明确选择的 LUT/耗材档案所形成的规范化只读色库 |
| `handoff.image` | 交接 PNG、像素尺寸、物理尺寸和可复现配方信封 |
| `ui.locale` | 读取语言并订阅语言变化 |
| `ui.theme` | 读取主题并订阅主题变化 |
| `status.progress` | 向宿主报告有界进度 |
| `status.error` | 报告标准错误代码与是否可重试 |

`image.pick` 和 `handoff.image` 的单张编码图像不超过 64 MiB，最长边不超过
16,384 像素，总像素不超过 64 MP。宿主按声明 MIME 和实际文件头双重验证。

`color-library.read` 不暴露 LUT 文件路径、内部 Zustand store 或耗材档案的任意字段。
宿主返回稳定的色库 ID、显示名称、颜色、可公开材料标识和映射结果。模块保留源图颜色
与打印映射颜色两套数据，不能用打印色覆盖源矩阵。

第一版不提供一般网络权限。需要云服务的模块必须等待后续 `network.fetch` 能力；该
能力上线时按域名 allowlist、请求方法、响应大小和用户确认限制，模块仍不能直接使用
浏览器 `fetch` 绕过宿主。

## 项目与数据边界

模块项目由宿主按 module ID 隔离存储。v1 每个模块总配额为 256 MiB，单个项目记录
不超过 64 MiB，可写入分享卡的配方信封不超过 1 MiB。宿主负责配额、原子写入、备份
和删除；模块负责自己的项目 schema 和显式迁移函数。未来提高上限属于宿主版本变更，
模块不能通过 manifest 自行申请无限空间。

更新模块前，宿主保留项目快照。若新版本迁移失败，宿主回滚代码和项目指针，原数据
不被覆盖。卸载模块不默认删除项目。

模块交给 Lumina 的内容必须是可验证的值对象：

- 标准 PNG 或后续明确支持的输出格式；
- 有界像素宽高；
- 有界且相互一致的物理尺寸；
- 模块 ID、模块版本、项目 schema 和渲染 schema；
- 可放入分享卡的有界配方信封。

宿主重新校验交接数据，不能因为模块已经安装便信任其尺寸、MIME、透明度或配方结构。

## 用户界面

主导航继续保持：

```text
… → 图像转矢量 → 创意工坊 → 设置
```

创意工坊包含三个视图：

1. **已安装**：预装和用户安装的模块，可打开、更新、禁用、卸载和查看版本；
2. **发现**：来自已验证 Registry 的模块，支持搜索、分类和安装；
3. **开发者**：安装本地 `.lumina-workshop` 或输入 GitHub 仓库地址。

模块详情页展示：

- 名称、作者、来源仓库、版本、兼容性和官方/社区/未审核标识；
- README、更新说明和所需权限；
- 安装、打开、更新、回滚、禁用和卸载操作；
- 若权限变化，显示新旧权限差异而不是重复整份清单。

通过 GitHub URL 安装时，宿主只接受该仓库正式 Release 中的标准包资产。界面明确标为
“未经过 Lumina Registry 审核”，但运行权限和沙箱不能降低。宿主计算并保存首次安装
字节的 SHA-256；因为该摘要没有 Registry 签名，后续版本永不静默自动更新，每次都
按新的未审核安装重新展示来源、摘要和权限差异。普通浏览器模式只能管理这类安装，
不能运行。

模块打开后占用创意工坊内容区，宿主始终保留模块名称、返回工坊、运行状态和关闭入口。
模块不能覆盖主导航、设置、系统对话框或其他模块界面。

## 故障、撤销与安全模式

模块实例出现以下任一情况时被终止：

- 握手失败；
- 主线程长时间无响应；
- RPC 连续超时或超出速率；
- 未捕获错误循环；
- 输出持续违反 schema 或尺寸限制；
- iframe 尝试被 CSP 阻止的外部访问并触发安全策略。

单次失败显示重试和返回工坊。相同版本连续三次启动失败后自动禁用，并提供回滚。
Lumina 启动参数和恢复界面提供“创意工坊安全模式”，一次性禁用所有非核心模块；用户
设置和项目不被删除。

Registry 撤销分两级：

- `deprecated`：继续运行已安装版本，但停止推荐并提示迁移；
- `blocked`：禁止新安装和新启动；保留项目与包文件供诊断或回滚，不静默删除用户
  数据。

应用无法获取新 Registry 时继续使用最后一份有效索引和已安装模块。只有带有效签名的
新索引可以触发 blocked 状态。

## 兼容性与版本规则

- 包版本使用完整 SemVer，不接受 `latest`、分支名或短提交哈希作为安装身份；
- Workshop API 主版本变化视为不兼容；
- 模块声明 `[min, maxExclusive)` API 范围；
- Lumina 只安装同时满足 API 与应用版本范围的版本；
- Registry 保留仍受支持的历史版本，供旧版 Lumina 和用户回滚；
- 模块项目 schema 与包版本分开演进；
- 权限集合是版本内容的一部分，更新不能在运行时临时扩权。

公开 SDK 从 `Lumina-studio` 构建，并作为 GitHub Release 资产发布。模块开发仓库可以
把精确 SDK tarball URL 锁进依赖，不需要访问主仓库内部源码。SDK 只包含类型、
manifest validator、RPC client 和测试 fixture，不包含宿主实现。

## 从当前原型迁移

当前分支中的 `frontend/src/workshop/modules/bead/` 是产品探索原型，不作为新的插件
运行时继续扩写。迁移顺序固定为：

1. 先在主仓库建立包格式、SDK、安装器、沙箱和最小 fixture；
2. 为现有创意工坊界面接入已安装模块列表；
3. 在独立拼豆仓库迁移纯领域代码和 UI，移除所有主仓库内部 import；
4. 发布首个标准 `.lumina-workshop` Release；
5. 主仓库以 seed lock 预装该 Release，并通过跨仓库契约测试；
6. 删除主仓库中的拼豆专用源码和测试；
7. Registry 收录官方模块后再开放“发现”页。

在第 5 步完成前，现有源码内置原型可以作为迁移对照，但不能与新包同时显示为两个
“拼豆工作台”，也不能成为新 SDK 的隐式私有实现。

旧实施计划
`docs/superpowers/plans/2026-07-30-creative-workshop-bead-mode.md`
记录的是原型构建历史，不再用于后续执行。新的实施计划必须按上述迁移顺序拆分，并
把主仓库宿主、独立拼豆模块和 Registry 分成可独立验证的阶段。

## 测试与验收

### 包与 Registry

- 合法包、摘要错误、损坏 ZIP、路径穿越、符号链接、ZIP bomb 和重复路径；
- 非法 manifest、未知权限、版本不兼容和发布者仓库变更；
- Registry 签名成功、签名失败、缓存回退、离线快照和 blocked 条目；
- GitHub Release 资产被替换后摘要不一致；
- 未审核 GitHub URL 安装不会获得额外权限。

### 安装生命周期

- 首次安装、更新、禁用、启用、卸载、保留项目、完全删除和离线重装；
- 更新中断时旧版本仍可启动；
- 新版本握手失败、项目迁移失败和手动回滚；
- 官方 seed package 与社区下载包走相同验证代码；
- 用户卸载官方模块后重启不会自动恢复。

### 沙箱与能力

- iframe 无法读取父 DOM、cookie、localStorage、任意 Lumina API 或其他模块数据；
- CSP 阻止外部脚本、直接 fetch、弹窗、导航和任意下载；
- RPC 身份、权限、payload 上限、超时、取消、速率和二进制 transfer；
- `color-library.read` 只返回规范化字段；
- 非法图片交接、尺寸矛盾、空图和超大配方被宿主拒绝；
- 模块异常不会卸载主应用状态或影响其他模块。

### 用户流程

在浅色/深色、中文/英文下验证。桌面窗口完成：

1. 从发现页安装社区 fixture；
2. 打开、保存项目并交接图片；
3. 查看权限变化并拒绝更新；
4. 安装更新后回滚；
5. 禁用和卸载；
6. 离线打开已安装模块；
7. 触发连续崩溃后进入安全模式；
8. 从预装 seed 恢复官方拼豆模块。

本地浏览器模式完成签名 Registry 官方模块、官方 seed 与宿主 fixture 的打开、保存和
交接，并单独验证 Registry 社区包、GitHub URL 包和普通本地包不能启动，开发开关只
能收到合成 fixture。

自动化测试、构建成功和 HTTP 200 不能替代真实浏览器验收。模块分析类流程必须等待
异步状态收敛，再验证完整编辑、保存、刷新和交接链路。

## 研究资料

本文在 2026-07-30 核对了以下一手资料：

- [Steam Workshop Implementation Guide](https://partner.steamgames.com/doc/features/workshop/implementation)
  ——订阅、后台安装、更新状态和由宿主解释内容；
- [Obsidian Community Plugin Registry](https://github.com/obsidianmd/obsidian-releases)
  ——中央目录、独立 GitHub 仓库、版本兼容和 Release 资产；
- [Logseq Marketplace](https://github.com/logseq/marketplace)
  ——中央包清单、仓库 PR 收录、Release ZIP 和高风险能力审查；
- [思源社区集市](https://github.com/siyuan-note/bazaar/blob/main/README_zh_CN.md)
  ——中文生态中的独立包仓库和中央集市提交流程；
- [HACS 发布要求](https://hacs.xyz/docs/publish/start/)
  ——GitHub 仓库、manifest、Release 版本和自定义仓库；
- [RuneLite Plugin Hub](https://runelite.dev/plugin-hub/)
  ——社区模块的收录审核与宿主故障边界；
- [Figma: How Plugins Run](https://developers.figma.com/docs/plugins/how-plugins-run/)
  ——沙箱、iframe UI、消息通信和网络限制；
- [MDN: CSP sandbox](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/sandbox)
  ——iframe 沙箱能够限制脚本、弹窗和顶层导航，但不能替代桌面宿主的出站请求防火墙；
- [VS Code Extension Runtime Security](https://code.visualstudio.com/docs/configure/extensions/extension-runtime-security)
  ——发布者信任、签名、扫描和撤销；
- [GitHub Immutable Releases](https://docs.github.com/en/enterprise-cloud@latest/code-security/concepts/supply-chain-security/immutable-releases)
  ——锁定 tag 与 Release 资产；
- [Blender Extension Manifest](https://docs.blender.org/manual/en/latest/advanced/extensions/getting_started.html)
  ——包 manifest、兼容性和带理由的权限声明。

## 完成标准

只有同时满足以下条件，才可以把“可安装式创意工坊”标记为完成：

- 主仓库不再通过 React import 注册官方拼豆模块；
- 官方拼豆包在独立仓库构建并通过公开 SDK 运行；
- 官方预装与社区安装共享同一校验、沙箱和能力桥接；
- GitHub Registry 可以安装精确 Release 资产并在离线时回退；
- 摘要失败、权限扩张、崩溃、更新失败和撤销都有可验证的恢复路径；
- 用户能看到来源、权限、版本和审核状态；
- 真实浏览器完成安装、打开、交接、更新、回滚、卸载和安全模式流程；
- 现有 Lumina 图像转换、LUT/耗材档案和分享卡往返没有回归。
