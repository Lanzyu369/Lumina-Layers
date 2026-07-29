# 创意工坊模块开发指南

Creative Workshop module development guide

## 当前边界

创意工坊 v1 提供稳定的模块清单、能力声明、项目存储和图像交接接口。它允许 Lumina
随应用发布官方模块，也为后续第三方模块保留一致的开发契约。

v1 还不是可在线安装任意代码的 Steam 式市场。模块必须作为 Lumina 源码的一部分参与
构建，并且模块 ID 必须进入发布白名单。应用不会下载、安装或执行远程 JavaScript。
未来开放在线分发时，现有清单和宿主服务语义应保持兼容，但还必须补齐签名、权限确认、
沙箱、审核、回滚和网络策略。

Creative Workshop v1 defines stable manifest, capability, project-storage,
and image-handoff contracts. Modules are currently source-integrated,
build-time components whose IDs must be explicitly whitelisted. Lumina does
not download or execute remote module code.

## Manifest v1

模块导出只读、可序列化的 `WorkshopModuleManifest`。下面是官方拼豆模块的等价 JSON：

```json
{
  "manifestSchemaVersion": 1,
  "id": "lumina.bead-pattern",
  "name": {
    "zh": "拼豆模式",
    "en": "Bead Mode"
  },
  "description": {
    "zh": "读取并校正拼豆图纸，预览熨烫压合效果。",
    "en": "Read and correct bead patterns, then preview ironing pressure."
  },
  "author": "Lumina Studio",
  "version": "1.0.0",
  "icon": "bead-grid",
  "minLuminaVersion": "2.0.0",
  "inputKinds": [
    "image/png",
    "image/jpeg",
    "image/webp"
  ],
  "outputKinds": [
    "image/png"
  ],
  "capabilities": [
    "file.pick-image",
    "project.read-write",
    "handoff.image",
    "ui.theme",
    "ui.locale",
    "status.progress",
    "status.error"
  ]
}
```

字段规则：

- `manifestSchemaVersion` 在 v1 必须为 `1`。
- `id` 是永久、全局唯一的模块身份，格式为小写分段名，例如
  `vendor.feature-name`。发布后不可把同一 ID 改作另一种模块。
- `version` 和 `minLuminaVersion` 必须是完整三段语义化版本
  `major.minor.patch`。
- `name`、`description` 是纯文本中文和英文，不接受 HTML。随应用发布的模块应从
  `frontend/src/i18n/translations.ts` 取得文案。
- `inputKinds`、`outputKinds` 必须为非空字符串数组。
- `capabilities` 不可重复，未知能力会使模块停用。

版本建议：

- 修复实现而不改变持久化格式：增加 `patch`。
- 增加向后兼容功能或可选字段：增加 `minor`。
- 无法读取旧项目、改变交接语义或删除公开行为：增加 `major`，并提供显式迁移。
- 项目结构版本独立于模块版本，例如 `bead-project/v1`；不要用模块版本代替项目迁移
  标识。

注册表会按关闭优先原则检查重复 ID、清单结构、清单版本、能力、最低 Lumina 版本和
发布白名单。任何一项失败都会停用模块，不会以降级权限继续运行。

## 七项宿主能力

模块只能调用清单中已经申请的能力。未声明就调用会抛出
`WorkshopHostError`，错误代码为 `capability-denied`。

| 能力 | 可用接口 | 语义 |
| --- | --- | --- |
| `file.pick-image` | `files.pickImage`、`files.decodeImage` | 让用户选择受支持图片，或把已有 Blob 解码为 RGBA |
| `project.read-write` | `projects.save/load/latest/remove` | 仅访问当前模块自己的项目命名空间 |
| `handoff.image` | `files.encodePng`、`handoffImage` | 编码并向 Lumina 交接经过验证的 PNG |
| `ui.theme` | `ui.getTheme` | 读取 `light` 或 `dark` |
| `ui.locale` | `ui.getLocale`、`ui.translate` | 读取语言和宿主翻译 |
| `status.progress` | `status.reportProgress` | 发布可清除的有界进度 |
| `status.error` | `status.reportError`、`status.reportDiagnostics` | 发布可见错误和无内容数据的诊断摘要 |

这些能力不提供 Zustand store、转换器组件、任意文件系统、用户设置、网络请求或
HTML 注入。官方模块同样遵守这一限制。

## 宿主服务签名

公开接口以 `frontend/src/workshop/types.ts` 为准。v1 的核心形状如下：

```ts
interface WorkshopHostServices {
  files: {
    pickImage(): Promise<WorkshopPickedImage | null>;
    decodeImage(file: Blob): Promise<WorkshopRaster>;
    encodePng(raster: WorkshopRaster, filename: string): Promise<File>;
  };
  projects: {
    save<TProject>(
      record: Omit<WorkshopProjectRecord<TProject>, "moduleId">,
    ): Promise<void>;
    load<TProject>(
      projectId: string,
    ): Promise<WorkshopProjectRecord<TProject> | null>;
    latest<TProject>(): Promise<WorkshopProjectRecord<TProject> | null>;
    remove(projectId: string): Promise<void>;
  };
  ui: {
    getLocale(): "zh" | "en";
    getTheme(): "light" | "dark";
    translate(key: string): string;
  };
  status: {
    reportProgress(update: WorkshopProgressUpdate | null): void;
    reportError(error: WorkshopVisibleError | null): void;
    reportDiagnostics(summary: WorkshopDiagnosticSummary | null): void;
  };
  handoffImage(
    handoff: WorkshopImageHandoff,
    options?: { replaceExisting?: boolean },
  ): Promise<
    { status: "needs-confirmation" } |
    { status: "completed" }
  >;
}

interface WorkshopModuleProps {
  manifest: WorkshopModuleManifest;
  host: WorkshopHostServices;
  pendingRecipeSource: WorkshopRecipeSource | null;
  clearPendingRecipe(): void;
}
```

模块定义还可以实现 `validateRecipeSource(source)`。只有它能够完整、安全地恢复分享卡
中的模块数据时才返回 `true`；异常和 `false` 都会使该来源按“不可继续编辑”处理，但
主转换器配方仍可正常导入。

## 生命周期

1. Lumina 在启动时验证所有模块清单，并保留注册顺序。
2. 用户从创意工坊首页打开已启用模块。
3. 宿主按清单创建有能力限制的 `WorkshopHostServices`。
4. 模块优先消费 `pendingRecipeSource`，否则加载本模块最近项目或创建新项目。
5. 模块通过宿主保存项目、报告状态，并在准备好时交接 PNG。
6. 返回工坊首页时，临时配方和诊断摘要会清除；项目按模块命名空间保留。
7. 模块卸载或渲染失败由独立错误边界隔离，不影响主导航和转换器。

## 项目命名空间与迁移

每条记录都包含：

```ts
interface WorkshopProjectRecord<TProject> {
  moduleId: string;
  projectId: string;
  schemaVersion: string;
  createdAt: string;
  updatedAt: string;
  project: TProject;
}
```

宿主强制把记录写入当前清单 ID 的命名空间；模块不能把 `moduleId` 伪装成其他模块。
项目保存在浏览器 IndexedDB，无法使用时会回退到本次会话内存。临时的工坊 shell 状态
只持久化活动模块 ID 和各模块最近项目 ID，不持久化分享卡 payload 或诊断数据。

模块必须在读取后、修改前验证 `schemaVersion`：

- 当前版本：完整验证，再进入编辑器。
- 已知旧版本：逐版迁移，校验迁移结果后另存为当前版本。
- 未知新版本或迁移失败：报告稳定错误代码，保留原记录，不做部分写回。
- 迁移函数应保持确定性，不读取网络或宿主外部状态。

包含 `Blob` 的项目使用 structured clone 保存；分享卡来源则必须是纯 JSON。分享卡应
只保存重新编辑所需的最小数据，不保存原图字节、对象 URL 或本地路径。

## 图像交接与替换确认

`handoffImage` 是模块进入 Lumina 转换器的唯一入口。v1 宿主会验证：

- 模块、模块版本和 `recipeSource` 身份必须与当前清单一致。
- 文件必须是可解码、至少含一个非透明像素的 PNG。
- 网格为 `1..128` 行和 `1..128` 列。
- PNG 必须严格为每格 `32 × 32` 像素，即
  `pixelWidth = columns × 32`、`pixelHeight = rows × 32`。
- `beadPitchMm` 为 `0.5..10`；推荐宽高为 `0.5..400 mm`，并严格等于
  `columns/rows × beadPitchMm`。
- `preserveCanvasBounds` 必须为 `true`，透明格仍保留物理画布边界。

如果转换器已有用户工作，第一次调用返回 `{ status: "needs-confirmation" }`，不会替换
任何内容。模块应显示明确确认界面；用户确认后以
`{ replaceExisting: true }` 再次交接。成功返回 `{ status: "completed" }`，Lumina
原子加载 PNG、推荐尺寸和模块来源，并切换回主转换流程。

模块生成的 PNG 只能包含预期颜色与透明度。辅助网格、编号、水印、编辑高亮和诊断覆盖
层不可写入交接文件。

## 错误、进度和诊断

可见错误结构：

```ts
interface WorkshopVisibleError {
  code: string;
  message: string;
  retryable: boolean;
}
```

错误代码应使用稳定的 kebab-case；`message` 是面向当前用户的安全说明，不放堆栈、
文件路径或原图内容。可重试错误允许用户保留项目并重试；致命结构或迁移错误应提供返回
工坊入口。

宿主自身会使用 `capability-denied`、`invalid-handoff-identity`、
`invalid-handoff-image`、`invalid-handoff-grid`、`invalid-handoff-pixels`、
`invalid-handoff-size` 和 `empty-handoff-image` 等代码拒绝非法调用。模块不可捕获后
伪装成成功。

`reportProgress` 使用 `{ phase, completed, total }`；完成或取消时传 `null`。
`reportDiagnostics` 只用于有界诊断：

```ts
interface WorkshopDiagnosticSummary {
  projectSchemaVersion: string;
  inputMode: string | null;
  rows: number | null;
  columns: number | null;
  compression: number | null;
  errorCode: string | null;
}
```

Bug 报告只在创意工坊标签处于活动状态时采集此摘要，再加上宿主绑定的模块 ID 和版本。
它不会读取项目、矩阵、色板或转换器里的分享卡来源。

## v1 白名单与未来在线分发

v1 的 `OFFICIAL_WORKSHOP_MODULES` 和 `WORKSHOP_MODULE_WHITELIST` 都在源码中维护。
新增模块需要在同一版本中提交模块定义、清单、白名单项、翻译、测试和一个实际采用点。
仅创建“公共工具”而不带可运行模块不符合仓库的 lighthouse adoption 规则。

不要把远程 URL、动态 `import()`、`eval`、下载脚本或第三方 CDN 作为绕过白名单的
方式。在线工坊开放之前至少需要：

- 可验证的包签名和发布者身份；
- 安装前权限说明与用户确认；
- iframe、worker 或等价的代码沙箱；
- 文件、网络、剪贴板和持久化配额策略；
- 内容审核、恶意包撤销和版本回滚；
- 兼容性、依赖锁定和自动更新策略。

这些机制尚未实现，因此 v1 白名单不是安全沙箱的替代品。

## 官方拼豆模块：lighthouse 实现

`frontend/src/workshop/modules/bead/` 是公开契约的第一套完整采用点。它通过宿主选图，
识别并校正三类清晰图纸，保存带原图 `Blob` 的版本化项目，以可逆矩阵编辑颜色和透明
支撑，预览 0–100 的熨烫压合效果，然后输出每格 32 像素的 PNG 交接给 Lumina。

它不直接导入转换器 store、不调用网络 API，也不自行访问 IndexedDB。分享卡恢复由
模块的 `validateRecipeSource` 和单一恢复函数验证；交接后仍走 Lumina 原有的预览、
叠色和 3MF 生成路径。开发新模块时，应把这一目录当作能力隔离、项目迁移、错误报告和
交接确认的基准实现，而不是复制其拼豆专用算法。
