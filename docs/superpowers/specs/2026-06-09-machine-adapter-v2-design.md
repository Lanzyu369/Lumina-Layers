# 机器适配 V2 设计文档

> **历史设计文档：** 本文中的模板生成和矩阵检查流程已由 FatCat 原生来源目录取代。
> 当前维护流程见 `docs/machine-adapter-v2-maintenance.md`。

## 先说结论

Lumina 需要把现在靠 `config.py` 和 `printer_profiles/*.json` 手工维护的机器适配，升级为一套 **开发期原生读取切片软件 profile，再生成 Lumina 内置设备注册表** 的流程。

这里的“读取切片软件 profile”只发生在开发环境，不发生在用户运行环境。用户安装的 Lumina 仍然只读取仓库内已经生成、已经验证、已经随版本发布的 Lumina 数据。

推荐目标形态是：

```text
开发机上的切片软件安装目录或开源源码仓库
  -> importer 原生解析 profiles/machine/process/filament/printers 等 JSON
  -> resolver 展开 inherits/include
  -> emitter 生成 Lumina registry、3MF metadata template、机器缩略图资产
  -> validator 生成 3MF 样本并比对 manifest
  -> 提交生成结果到 Lumina 仓库
  -> 用户端只读 Lumina 内置 registry
```

核心原则是严格按这个维度隔离：

```text
切片软件 -> 机器型号 -> 喷嘴 -> 具体 profile revision
```

同名机器不能跨切片软件复用。例如 `BambuStudio / Bambu Lab H2D / 0.4` 和 `OrcaSlicer / Bambu Lab H2D / 0.4` 必须是两个独立 profile，因为它们的 JSON、继承树、G-code include、默认 print profile、3MF sidecar 规则和版本戳都可能不同。

## 当前问题

Lumina 目前的 3MF 元数据适配主要散落在这些位置：

- `config.py`
  - `SUPPORTED_SLICERS`
  - `PRINTER_PROFILES`
  - `PrinterProfile.get_template_file()`
  - legacy slicer alias normalize
- `printer_profiles/*.json`
  - 当前 3MF project settings 模板
  - 目前有 29 个基础模板和 29 个 `0.2` 喷嘴变体
- `utils/bambu_3mf_writer.py`
  - `load_printer_template()`
  - `BambuStudio3MFWriter._get_app_version_str()`
  - `BambuStudio3MFWriter._inject_metadata_parts()`
- `api/routers/system.py`
  - `/api/system/printers`
  - `/api/system/slicers`
- `frontend/src/components/SettingsPanel.tsx`
  - 切片软件、机型、喷嘴选择
- `frontend/src/utils/settingsOptionIds.ts`
  - 前端 slicer ID 映射和 Bambu family 判断

这套做法能工作，但维护成本高：

1. 新机器出现时，需要人工补 `config.py`、模板 JSON、前端兼容逻辑、测试。
2. 切片软件更新后，Lumina 不知道哪些 metadata 字段变化了。
3. `Application` / client version stamp 仍然有硬编码。
4. 同一机型在不同切片软件下的 profile 差异没有被显式建模。
5. 机器缩略图、厂商图标、型号分组没有统一资产来源。
6. 当时的 `scripts/verify_3mf_template_matrix.py` 导入 helper 已失效；这一历史计划后来由 FatCat 原生来源目录取代。

## 本机观察到的 profile 来源

本机已经安装了当前 Lumina 支持的 5 个切片软件：

| 切片软件 | 本机版本 | 安装路径 |
| --- | --- | --- |
| Bambu Studio | `02.07.01.57` | `<local slicer install>/Bambu Studio` |
| OrcaSlicer | `2.4.0` | `<local slicer install>/OrcaSlicer` |
| Snapmaker Orca | `2.3.3` | `<local slicer install>/Snapmaker_Orca` |
| ElegooSlicer | `1.5.0.7` | `<local slicer install>/ElegooSlicer` |
| AnycubicSlicerNext | `1.3.9.4` | `<local slicer install>/AnycubicSlicerNext` |

这些安装目录都存在 Orca/Bambu 系的资源布局：

```text
resources/profiles/<Vendor>/machine/*.json
resources/profiles/<Vendor>/process/*.json
resources/profiles/<Vendor>/filament/*.json
resources/profiles_template/
resources/printers/*.json
```

抽样结果：

- Bambu Studio:
  - `resources/profiles/BBL/machine/Bambu Lab H2D 0.4 nozzle.json`
  - 同目录还包含 H2D 的 `machine_start_gcode`、`machine_end_gcode` 等 include JSON。
- OrcaSlicer:
  - `resources/profiles/BBL/machine/Bambu Lab H2D 0.4 nozzle.json`
  - 同名 H2D profile 与 Bambu Studio 的内容长度和字段存在明显差异。
- ElegooSlicer:
  - `resources/profiles/Elegoo/machine/fdm_elegoo_3dp_001_common.json`
  - 目录结构与 Orca 系一致，应优先复用 Orca/Bambu profile importer。
- AnycubicSlicerNext:
  - `resources/profiles/Anycubic/machine/Anycubic Kobra 3 0.4 nozzle.json`
  - 结构也是 Orca/Bambu 系，但 Anycubic 3MF sidecar 规则和 Bambu/Orca 不完全一样。
- Snapmaker Orca:
  - `resources/profiles/Snapmaker/machine/*.json`
  - 结构与 Orca 系一致。

因此第一版 importer 不需要从零设计 5 套解析器。应先实现一套 Orca/Bambu profile resolver，再用 provider 配置区分 Bambu、Orca、Snapmaker、Elegoo、Anycubic 的 source root、品牌过滤、默认 sidecar 规则和版本戳。

## 目标

### 产品目标

1. 新机器适配从“人工手写模板”变成“开发期读取切片器原生 JSON 后生成 Lumina 数据”。
2. 用户端不需要安装对应切片软件，也不读取用户机器上的切片器目录。
3. 机器选择变成更清晰的三级结构：切片软件、机器型号、喷嘴。
4. 支持机器缩略图和品牌分组，让用户能像在切片软件里一样识别机器。
5. 对同名机器严格区分不同切片软件来源，避免 BambuStudio/Orca/Elegoo/Anycubic profile 混用。

### 工程目标

1. importer 原生读取切片软件 JSON，不手工重写机器字段。
2. registry 记录 source path、source app version、source hash、generated revision。
3. emitter 生成兼容现有 writer 的 3MF metadata template。
4. validator 能自动跑完整 slicer/machine/nozzle matrix。
5. 第一阶段不改变导出行为，先生成与现有模板等价的数据。
6. 后续新增机器时，开发者重新运行 importer，review diff，提交生成结果。
7. Lumina 当前 3MF 工艺要求必须保持不变，切片软件 profile 不能覆盖 `0.08mm` 层高、底板/彩色层策略、壳层、填充、线宽、温度数组等当前导出约束。

## 非目标

- 不在用户运行时读取用户安装的切片软件目录。
- 不把完整切片软件源码作为 Lumina 运行依赖。
- 不在第一版支持用户自定义编辑机器 profile。
- 不在第一版实现云端自动更新机器库。
- 不在第一版完整支持 PrusaSlicer/Cura 的 3MF 元数据。
- 不在第一版改变 Lumina 的建模、材料槽位、层图或 GLB 预览逻辑。
- 不把切片软件默认 print/process profile 直接当成 Lumina 的最终工艺参数。切片软件 profile 可以提供机器默认值和字段来源，但最终导出仍必须叠加 Lumina 自己的工艺 overlay。

## 推荐目录结构

新增开发期输入和生成输出分层：

```text
reference/
  slicers/
    BambuStudio/       # 开源源码或导出的源码快照，仅开发分析用
    OrcaSlicer/
    SnapmakerOrca/

tools/
  machine_adapter/
    import_profiles.py
    providers/
      bambu_studio.py
      orca_slicer.py
      snapmaker_orca.py
      elegoo_slicer.py
      anycubic_slicer_next.py
    resolver.py
    emitter.py
    validator.py
    diff_report.py

machine_registry/
  registry.json
  slicers/
    BambuStudio/
      02.07.01.57/
        machines/
        metadata_templates/
        assets/
    OrcaSlicer/
      2.4.0/
        machines/
        metadata_templates/
        assets/

printer_profiles/
  # 第一阶段继续生成现有 writer 可读取的模板文件
```

其中 `reference/slicers` 只服务开发分析和 importer 测试。用户端最终读取的是 `machine_registry` 和兼容生成的 `printer_profiles`。

不开源的 ElegooSlicer、AnycubicSlicerNext 不需要放完整安装包进仓库。开发机上通过本地路径读取它们的 `resources/profiles`，生成后的 Lumina registry 和模板进入仓库。

## 本地路径配置

本地安装目录不应写死到源码。开发机使用一个不提交的配置文件：

```json
{
  "BambuStudio": {
    "source_kind": "local_install",
    "root": "F:/3D Print F/Bambu Studio",
    "version": "02.07.01.57"
  },
  "OrcaSlicer": {
    "source_kind": "local_install",
    "root": "F:/3D Print F/ORCA/OrcaSlicer",
    "version": "2.4.0"
  },
  "ElegooSlicer": {
    "source_kind": "local_install",
    "root": "F:/3D Print F/ElegooSlicer",
    "version": "1.5.0.7"
  },
  "AnycubicSlicerNext": {
    "source_kind": "local_install",
    "root": "F:/3D Print F/AnycubicSlicerNext",
    "version": "1.3.9.4"
  },
  "SnapmakerOrca": {
    "source_kind": "local_install",
    "root": "F:/3D Print F/Snapmaker_Orca",
    "version": "2.3.3"
  }
}
```

这个文件可以放在 `machine_registry.sources.local.json` 或 `dev/machine_registry.sources.local.json`，并加入 `.gitignore`。提交进仓库的是 importer 输出，不是本地路径。

## Provider 分层

### `BambuStudioProvider`

职责：

- 读取 Bambu Studio 的 `resources/profiles` 和 `resources/printers`。
- 支持 BBL 机型、Bambu 版本戳和 Bambu 专属 sidecar 规则。
- 输出 BambuStudio 专属 profile，不与 Orca 同名 profile 合并。

3MF 规则：

- `Application` 使用 registry 中记录的 Bambu Studio 版本。
- 允许生成 `Metadata/filament_sequence.json`。
- 允许生成 `Metadata/cut_information.xml`。
- 保留 `layer_config_ranges.xml` 逻辑。

### `OrcaSlicerProvider`

职责：

- 读取 OrcaSlicer 的 `resources/profiles`。
- 支持 Orca 中的 BBL、Anycubic、Elegoo、Snapmaker 等机器 profile。
- 作为 Elegoo/Snapmaker/Anycubic 换皮解析器的基础类。

3MF 规则：

- `Application` 使用 Orca 的版本戳或 Orca 兼容标识。
- 默认不生成 Bambu-only aux sidecar。
- 保留 project settings、model settings、slice info。

### `SnapmakerOrcaProvider`

职责：

- 复用 Orca resolver。
- 默认只导入 Snapmaker 相关 vendor profile。
- 保留 Snapmaker Orca 的 app version 和显示名称。

3MF 规则：

- 继承 Orca sidecar 策略。
- 不生成 Bambu-only aux sidecar。

### `ElegooSlicerProvider`

职责：

- 复用 Orca resolver。
- 默认只导入 Elegoo vendor profile。
- 优先覆盖当前手工维护的 `elegoo-cc2` 适配。

判断：

ElegooSlicer 是 Orca/Bambu 系换皮，安装目录中已经存在 `resources/profiles/Elegoo/machine`、`resources/profiles_template` 和 `resources/printers`。因此适配不应重写一套 parser，而应直接复用 Orca provider，只在 provider metadata 和 sidecar policy 上区分。

3MF 规则：

- 使用 ElegooSlicer 的 app version。
- 不生成 Bambu-only aux sidecar。
- 保留 Elegoo 当前能识别的 project settings 字段。

### `AnycubicSlicerNextProvider`

职责：

- 复用 Orca resolver。
- 默认只导入 Anycubic vendor profile。
- 优先覆盖当前手工维护的 Kobra 系适配。

判断：

AnycubicSlicerNext 的 profile 结构也是 Orca/Bambu 系，但当前 Lumina writer 对 Anycubic 有专门规则：使用 `Metadata/custom_gcode_per_layer.xml`。因此 parser 可以复用，3MF sidecar policy 必须单独保留。

3MF 规则：

- 使用 AnycubicSlicerNext 的 app version。
- 生成 `Metadata/custom_gcode_per_layer.xml`。
- 不生成 Bambu-only aux sidecar。

## 原生 JSON 解析规则

切片软件 profile JSON 通常有这些字段：

- `type`
- `name`
- `inherits`
- `include`
- `from`
- `setting_id`
- `instantiation`
- `printer_model`
- `printer_variant`
- `nozzle_diameter`
- `printable_area`
- `printable_height`
- `default_print_profile`
- `default_filament_profile`
- `printer_settings_id`
- 各类 machine limit、G-code、thumbnail、filament、process 字段

解析器需要按切片软件语义处理：

1. 扫描 `resources/profiles/<vendor>/<kind>/*.json`。
2. 按 `type` 分类为 `machine`、`process`、`filament` 等。
3. 用 `name`、文件名和 `setting_id` 建索引。
4. 对每个 `instantiation == true` 的 machine profile 生成候选机器。
5. 展开 `inherits` 链。
6. 展开 `include` 链，例如 Bambu H2D 的 machine start/end G-code 模板。
7. 合并字段时保留切片软件原生语义，不自行猜测数组长度。
8. 记录参与合并的所有 source file path 和 hash。

第一版不要试图理解所有字段含义。第一版只需要确保 Lumina 3MF writer 依赖的字段被稳定提取，并把完整 resolved project settings 存下来。

## Lumina registry 数据模型

`machine_registry/registry.json` 是前端和后端查询入口，提供小而稳定的索引：

```json
{
  "schema_version": 1,
  "generated_at": "2026-06-09T00:00:00+08:00",
  "slicers": [
    {
      "slicer_id": "BambuStudio",
      "display_name": "Bambu Studio",
      "source_kind": "local_install",
      "source_version": "02.07.01.57",
      "profile_format": "bambu_orca",
      "machines": [
        {
          "machine_profile_id": "BambuStudio:bbl:bambu-lab-h2d",
          "display_name": "Bambu Lab H2D",
          "brand": "Bambu Lab",
          "vendor_key": "BBL",
          "bed_width": 350,
          "bed_depth": 320,
          "bed_height": 325,
          "thumbnail": "slicers/BambuStudio/02.07.01.57/assets/bambu-lab-h2d.png",
          "nozzles": [
            {
              "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
              "nozzle_size": "0.4",
              "source_profile_name": "Bambu Lab H2D 0.4 nozzle",
              "template": "slicers/BambuStudio/02.07.01.57/metadata_templates/bambu-lab-h2d_0_4.json",
              "revision": "sha256:...",
              "supported": true
            }
          ]
        }
      ]
    }
  ]
}
```

字段职责：

- `slicer_id`
  - Lumina 标准切片软件 ID。
  - 必须参与设备身份。
- `source_version`
  - 导入时的切片软件版本。
  - 不建议放入用户持久选择 ID，否则用户升级 Lumina 后设置容易失效。
- `machine_profile_id`
  - 同一切片软件下同一机器的稳定 ID。
- `device_profile_id`
  - `slicer + vendor + machine + nozzle` 的稳定 ID。
  - 这是生成请求里未来最推荐传递的设备 ID。
- `revision`
  - 当前 generated profile 的内容哈希。
  - 用于 diff、缓存失效、回滚和测试。
- `template`
  - 3MF writer 实际读取的 resolved metadata template。

## 兼容现有 `printer_profiles`

第一阶段不能直接删掉 `printer_profiles`。推荐 emitter 同时生成两类输出：

1. 新 registry 输出：
   - `machine_registry/registry.json`
   - `machine_registry/slicers/.../metadata_templates/*.json`
   - `machine_registry/slicers/.../assets/*`
2. 旧 writer 兼容输出：
   - `printer_profiles/*.json`
   - 文件名继续兼容 `PrinterProfile.get_template_file()`。

这样可以先把 importer 和 registry 建起来，再逐步让后端读取 registry。迁移顺序应该是：

1. importer 生成现有 18 个 profile 的等价模板。
2. 修复并恢复 metadata matrix 校验。
3. `utils/bambu_3mf_writer.load_printer_template()` 支持从 registry 读取，失败时回退旧 `printer_profiles`。
4. `/api/system/printers` 和 `/api/system/slicers` 改为 registry 驱动。
5. 前端改为按 `slicer -> machine -> nozzle` 展示。
6. 旧 `PRINTER_PROFILES` 保留一段时间作为 fallback。
7. 等所有生成路径稳定后，再减少 `config.py` 中硬编码。

## Lumina 工艺参数保护线

机器适配 V2 不能把切片软件的默认 print/process profile 直接变成 Lumina 的最终导出工艺。Lumina 现在生成 3MF 有自己的硬性工艺要求，这些要求是产品行为的一部分，必须在 V2 中继续保留。

当前必须保护的典型参数包括：

- `layer_height = 0.08`
- `initial_layer_height = 0.08`
- `wall_loops = 1`
- `top_shell_layers = 0`
- `bottom_shell_layers = 1`
- `bottom_surface_pattern = monotonicline`
- `sparse_infill_density = 100%`
- `sparse_infill_pattern = zig-zag`
- `elefant_foot_compensation = 0`
- `enable_support = 0`
- `brim_width = 5`
- `brim_type = auto_brim`
- 当前按颜色槽位生成的 `nozzle_temperature`、`bed_temperature`、`filament_type` 数组形状
- `layer_config_ranges.xml` 中用于底板粗层高的规则
- 单面、双面、5 色扩展、拼图、大画幅、校准卡等流程对 3MF 参数的既有约束

因此 V2 的合并顺序必须是：

```text
切片软件原生 machine profile
  -> 展开 inherits/include，得到 resolved machine metadata
  -> 提取机器尺寸、喷嘴、G-code、默认字段、切片器识别字段
  -> 应用 Lumina 工艺 overlay
  -> 输出最终 3MF project_settings / slice_info / model_settings
```

优先级规则：

1. 机器能力字段由切片软件原生 profile 提供，例如热床尺寸、可打印区域、喷嘴直径、机器型号、打印机变体、机型识别 ID。
2. 切片器识别字段由 provider 提供，例如 `Application` 版本戳和 sidecar policy。
3. Lumina 工艺字段由 Lumina overlay 提供，优先级高于切片软件默认 process profile。
4. 如果某个切片器必须依赖自己的 process profile 字段才能识别机器，可以把字段复制到 metadata template，但不能覆盖 Lumina 的受保护工艺字段。
5. 如果新机器的原生 profile 与 Lumina overlay 冲突，importer 必须在 diff report 中标红，而不是静默选择一边。

这意味着 importer 可以读取 `process/*.json` 和 `filament/*.json`，但第一版只能把它们作为机器识别和缺省字段来源，不能让切片器默认的 `0.20mm Standard` 等 process profile 改掉 Lumina 当前 `0.08mm` 输出。

## 3MF 元数据生成规则

writer 不应该继续散落硬编码版本戳。V2 后版本戳来自 registry：

```json
{
  "slicer_id": "ElegooSlicer",
  "source_version": "1.5.0.7",
  "application_metadata": "ElegooSlicer-1.5.0.7",
  "sidecar_policy": "orca_like_without_bambu_aux"
}
```

sidecar policy 第一版定义为：

| policy | 适用 | 行为 |
| --- | --- | --- |
| `bambu_studio` | BambuStudio | 生成 Bambu aux sidecar，例如 `filament_sequence.json` 和 `cut_information.xml` |
| `orca_like` | OrcaSlicer、SnapmakerOrca、ElegooSlicer | 不生成 Bambu-only aux sidecar，保留主要 metadata config |
| `anycubic_next` | AnycubicSlicerNext | 生成 `custom_gcode_per_layer.xml`，不生成 Bambu-only aux sidecar |

如果后续实际样本显示 Elegoo 或 Snapmaker 需要额外 sidecar，就新增 policy，不要把判断写成零散 `if slicer == ...`。

## 机器缩略图导入

目标是让 Lumina 机器选择界面有类似切片软件的机器识别体验。

导入策略：

1. 先从 `resources/printers/*.json` 读取机器 code、缩略图字段和资产引用。
2. 如果 JSON 中没有直接图片路径，扫描 `resources/printers`、`resources/profiles`、`resources/web` 等资产目录找同名或 code 关联图片。
3. 找到后复制到 `machine_registry/slicers/<slicer>/<version>/assets/`。
4. 生成统一尺寸的 web 友好图，例如 PNG/WebP。
5. registry 中只保存相对路径。

如果某个机器没有缩略图，UI 使用品牌占位图，不阻断 profile 导入。

## 新机器选择 UI

UI 不应该继续只显示一个扁平机型列表。推荐结构：

```text
切片软件
  Bambu Studio
  OrcaSlicer
  ElegooSlicer
  Anycubic Slicer Next
  Snapmaker Orca

机器型号
  按品牌分组
  卡片显示缩略图、型号、热床尺寸、喷嘴数量

喷嘴
  0.2 / 0.4 / 0.6 / 0.8
  只显示当前 profile 已导入并通过校验的喷嘴
```

前端展示原则：

- 同名机器在不同切片软件下分别展示，不合并。
- 用户切换切片软件后，只显示该切片软件下有 profile 的机器。
- 如果旧设置中的 `printerModel + slicerSoftware + nozzleSize` 能映射到新 `device_profile_id`，自动迁移。
- 如果映射失败，回退到默认 `BambuStudio:bbl:bambu-lab-h2d:0.4`，并提示用户重新选择。

## Importer 命令设计

推荐命令：

```powershell
python tools/machine_adapter/import_profiles.py `
  --sources dev/machine_registry.sources.local.json `
  --slicers BambuStudio OrcaSlicer ElegooSlicer AnycubicSlicerNext SnapmakerOrca `
  --output machine_registry `
  --emit-legacy-printer-profiles `
  --report logs/machine_adapter_import_report.json
```

常用模式：

- `--slicers ElegooSlicer`
  - 只更新 Elegoo。
- `--machine "Bambu Lab H2D"`
  - 只更新某个机器。
- `--nozzles 0.2 0.4`
  - 只生成 Lumina 当前支持喷嘴。
- `--include-unsupported-nozzles`
  - 额外导入 0.6/0.8，但 UI 默认隐藏，后续确认后开放。
- `--dry-run`
  - 只输出 diff report，不写文件。

## Diff report

每次重新导入都必须生成差异报告。报告至少包含：

- 新增机器
- 删除机器
- 新增喷嘴
- 删除喷嘴
- `printable_area` 变化
- `printable_height` 变化
- `default_print_profile` 变化
- `default_filament_profile` 变化
- `printer_model` / `printer_variant` 变化
- sidecar policy 变化
- application metadata 变化
- 受保护 Lumina 工艺字段变化，例如 `layer_height`、`initial_layer_height`、壳层、填充、支撑、底板层高规则
- 参与 resolved profile 的 source hash 变化

差异报告用于 review，不应该只看生成文件 diff。

## 校验策略

### 单元测试

新增 importer fixture：

- Bambu H2D 0.4，覆盖 `inherits` 和 `include`。
- Orca H2D 0.4，验证同名 profile 不与 Bambu 混用。
- Elegoo common profile，验证 Orca provider 可复用。
- Anycubic Kobra 3 0.4，验证 `anycubic_next` sidecar policy。
- Snapmaker profile，验证 provider 过滤和显示名称。

测试内容：

- JSON 扫描能找到候选 profile。
- `inherits` 展开顺序稳定。
- `include` 文件被合并或保留引用，结果可复现。
- `device_profile_id` 由 `slicer + vendor + machine + nozzle` 组成。
- 同名机器在不同 slicer 下 revision 不互相覆盖。
- Lumina 工艺 overlay 优先级高于切片软件默认 process profile。
- 受保护工艺字段在导入前后保持当前行为，例如 `0.08mm` 层高不会被原生 `0.20mm Standard` 覆盖。

### 矩阵测试

> **已废弃（2026-09-28）：** 本节假设模板文件仍由 Lumina 管理。其矩阵脚本和模板来源已随原生来源目录切换删除；当前维护说明见 `docs/machine-adapter-v2-maintenance.md`。以下内容仅保留为历史设计记录。

修复 `scripts/verify_3mf_template_matrix.py`，让它从 registry 获取所有 supported device profile：

```text
for each supported slicer
  for each supported machine
    for each supported nozzle
      export sparse palette 3MF
      export full palette 3MF
      inspect manifest
      compare project settings subset
      compare protected Lumina process fields
      compare Application metadata
      compare expected sidecar presence
```

第一阶段要求当前 18 个机器、5 个切片器相关组合全部通过。

### 实机软件 smoke

对每个 provider 至少保留一个人工或半自动 smoke：

- BambuStudio 打开 Bambu H2D 0.4 3MF。
- OrcaSlicer 打开 Orca H2D 0.4 3MF。
- ElegooSlicer 打开 Elegoo CC2 0.4 3MF。
- AnycubicSlicerNext 打开 Kobra 系 0.4 3MF。
- SnapmakerOrca 打开 Snapmaker U1 或当前支持机器 0.4 3MF。

smoke 观察项：

- 切片器不崩溃。
- 机器型号识别正确。
- 喷嘴尺寸识别正确。
- 默认层高/线宽没有被锁成明显错误值。
- 材料槽数量和颜色正常。
- 缩略图不导致 Anycubic 等切片器卡死。

## 迁移计划

### 阶段 1：只生成，不切换

目标：建立 importer、registry、diff、validator，但现有运行链路仍使用旧 `config.py + printer_profiles`。

验收：

- registry 能生成。
- legacy `printer_profiles` 能同步生成。
- 生成结果和当前手工模板的关键 metadata subset 等价。
- 矩阵校验脚本恢复可用。

### 阶段 2：后端双读

目标：后端优先读 registry，失败回退旧配置。

涉及：

- `load_printer_template()`
- `/api/system/printers`
- `/api/system/slicers`
- `PrinterProfile` 兼容层

验收：

- 当前 UI 不需要一次性大改。
- 现有生成、拼图、校准、批量、大画幅、单阶段套件继续传旧字段也能工作。

### 阶段 3：前端机器选择升级

目标：设置页和生成请求改为以 `device_profile_id` 为主，旧三字段兼容。

涉及：

- `SettingsPanel`
- `settingsStore`
- request schema
- recipe export/import
- share card
- artifact invalidation

验收：

- 用户能按切片软件、机器、喷嘴选择。
- 机器卡片显示缩略图。
- 旧用户设置可迁移。

### 阶段 4：扩大导入范围

目标：从只覆盖当前 18 个机器，扩大到每个 provider 的官方支持机器。

规则：

- 默认只展示通过 validator 的机器。
- 未经过 Lumina 真实 3MF smoke 的机器可以进入 registry，但标记为 `experimental` 或默认隐藏。
- 0.6/0.8 喷嘴可以先导入但 UI 不默认开放，等 Lumina 模型层高/线宽策略确认后再开启。

## 风险与处理

### 风险 1：切片软件 JSON 继承语义理解不完整

处理：

- 第一版只支持 Orca/Bambu 系。
- 保留 raw source hash 和 resolved output。
- 用真实切片软件打开 3MF 做 smoke。

### 风险 2：生成文件 diff 很大，review 困难

处理：

- 生成机器级 diff report。
- 每次 PR 按 provider 或机器批次拆分。
- 大规模新增机器先标记 experimental，不直接默认开放。

### 风险 3：版本戳变化导致旧切片器兼容性回退

处理：

- registry 记录 source version。
- sidecar policy 与 app version 分离。
- 保留旧版本 profile 一段时间，必要时允许选择 profile revision。

### 风险 4：机器缩略图版权和来源不清

处理：

- registry 记录 asset source。
- 开源切片器资源按其许可证处理。
- 闭源安装包资源在正式分发前需要确认授权；如果授权不清，使用 Lumina 自绘占位图或厂商公开素材。

### 风险 5：Anycubic/Elegoo 虽是 Orca 换皮，但 3MF 行为仍有差异

处理：

- parser 复用 Orca。
- sidecar policy 单独配置。
- 每个 provider 至少保留一个真实软件 smoke。
- 发现差异时新增 policy，而不是在 writer 中继续堆散乱条件。

## 成功标准

第一版完成后，应满足：

1. 开发机重新运行 importer 可以从 Bambu/Orca/Snapmaker/Elegoo/Anycubic 当前安装目录生成 Lumina registry。
2. 当前 Lumina 已支持的 18 个机器和 0.2/0.4 喷嘴仍可生成有效 3MF。
3. Bambu H2D 在 BambuStudio 和 OrcaSlicer 下是两个独立 profile。
4. Elegoo 和 Anycubic 通过 Orca/Bambu provider 体系导入，不需要手写新 parser。
5. `Application` 版本戳从 registry 来，不再只靠 writer 硬编码。
6. 机器选择 UI 有足够数据展示缩略图、品牌、热床尺寸、喷嘴列表。
7. 重新导入切片软件新版本时，能用 diff report 看清机器和 metadata 变化。
8. 受保护 Lumina 工艺参数在 V2 前后保持一致，尤其是 `0.08mm` 层高、底板/彩色层策略和当前 3MF 导出参数不会被切片软件默认 profile 改写。

## 建议下一步

下一步不是直接改 UI，而是先做 implementation plan，顺序应为：

1. 修复 metadata matrix 校验入口。
2. 添加最小 registry schema 和读取器。
3. 实现 Orca/Bambu profile resolver。
4. 用 Bambu H2D、Orca H2D、Elegoo CC2、Anycubic Kobra、Snapmaker U1 做第一组 fixtures。
5. emitter 先生成现有 `printer_profiles` 兼容输出。
6. 后端双读 registry。
7. 最后再升级前端机器选择 UI。

这个顺序能避免一上来改 UI 却发现底层 profile 解析不稳定。
