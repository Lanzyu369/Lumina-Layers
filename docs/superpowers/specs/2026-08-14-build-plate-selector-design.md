# 切片软件原生打印板选择器设计

## 目标

在“设置 -> 打印与切片”的当前设备卡片下方增加横向打印板选择器。列表严格跟随当前切片软件、版本与打印机，使用该切片软件的原生名称和原生元数据值，并展示 Lumina 自有的中性打印板图片。用户选择会应用于所有 Lumina 生成的 3MF，并在真实切片软件中打开后自动选中对应打印板。

## 数据模型

机器注册表继续作为唯一设备数据源。每个切片软件版本新增 `build_plates`，每项包含：

- `id`：Lumina 内部稳定 ID，仅在该切片软件版本内使用；
- `display_name`：版本作用域适配器中经原生项目/profile 核验的显示名称；
- `project_value`：写入 `Metadata/project_settings.config` 的 `curr_bed_type`；
- `plate_value`：写入盘面元数据 `bed_type` 的值；
- `image`：跨切片软件共享的 Lumina 中性打印板图片路径；
- `source_path`、`source_version` 与 `revision`：仅描述 Lumina 中性图片的来源标识、生成版本与校验值。

每个机器条目增加 `supported_build_plate_ids` 与 `default_build_plate_id`。喷嘴条目不重复这些字段，因选择按“切片软件 + 机器型号”记忆。旧版注册表没有打印板数据时保持现有模板默认行为。

打印板 ID、名称以及项目/盘面/sidecar 元数据值是 `tools/machine_adapter/build_plates.py` 中版本作用域的显式适配契约，并用原生项目和 profile 核验；它们不是从 profile 动态提取的通用目录。导入工具仅从固定版本的机器与喷嘴 profile 派生每台机器的支持范围、默认项和多喷嘴交集。Anycubic Kobra S1 的 Engineering Plate 另有精确到切片软件版本与机型的真人切片排除，因为验收 G-code 的热床温度为零。展示图片不从上游应用复制：六张无品牌中性 PNG 由同一工具确定性生成并由各切片软件共享，`source_path`、`source_version` 与 `revision` 只记录 `lumina-neutral-v1` 图片生成物；仓库不包含或再分发厂商打印板图片。

## API 与设置状态

打印机接口为每个设备配置返回解析后的打印板列表与默认 ID。前端保存 `buildPlateSelections` 映射，键为已经包含切片软件作用域的 `machine_profile_id`，值为打印板 ID；同时把当前解析值保存到后端用户设置，供所有生成入口复用。

选择解析顺序：

1. 当前组合已记忆且仍受支持的值；
2. 当前机器由固定 profile 派生的默认值；
3. 注册表第一项；
4. 无注册表数据时不传覆盖值，沿用模板。

原选择在升级后消失时回退至默认项，并向用户显示一次明确提示。

## 界面

打印板区域位于当前设备卡片与底板层高修改器之间。宽屏单行横向排列，空间不足时横向滚动，不改成竖排列表。

每张卡片使用固定内容框，但图片保持中性资源的原始比例：`width/height: auto`、`max-width/max-height: 100%`、`object-fit: contain`，禁止拉伸和裁切。选中项显示主题色边框、单选标记和当前状态。卡片提供完整键盘和读屏语义，并兼容明暗主题。

## 3MF 写入

所有生成请求接受可选 `build_plate_id`。后端根据 `device_profile_id` 在机器注册表中解析并校验，前端传来的字符串不能直接进入压缩包。

写出器在同一收敛点同步设置：

- `Metadata/project_settings.config` 的 `curr_bed_type`；
- `Metadata/model_settings.config` 的盘面 `bed_type`；
- 定制切片器要求的盘面 sidecar，例如 `Metadata/plate_1.json`。

字段值来自注册表适配数据，不假设项目值与盘面值相同。不支持打印板元数据的切片器继续保持现有输出，不伪造字段。

所有 3MF 工作流必须传递该值：普通图片转换、原生 SVG/矢量、材料档案、批量与拼图、校准、配方色卡、五色流程、单阶段工具包和创意工坊交接。

## 兼容与警告

非法或跨设备 ID 在 API 边界拒绝。注册表升级导致旧选择失效时使用该机器由 profile 派生的默认值并返回警告。PLA/PETG 与打印板温度不匹配只提示、不阻止导出，切片软件保留最终校验权。

## 测试与验收

自动化测试覆盖：

- 注册表解析、重复 ID、缺失图片和校验值；
- 原生 profile 能力导入与中性图片确定性生成；
- API 返回范围与资源路径安全；
- 设置按切片软件和机器记忆、默认值与失效回退；
- 横屏布局、中性图片比例、键盘与明暗主题；
- 各 3MF 请求和工作流的参数传递；
- 解包检查项目、盘面 XML 和厂商 sidecar 值一致。

真实验收对每款可运行切片软件使用非默认打印板生成代表性 PLA/PETG 文件，至少在 Bambu Studio、OrcaSlicer、Snapmaker Orca 中打开；若取得 ElegooSlicer 可运行版本则同时覆盖。逐项确认打印板、机器、喷嘴、耗材映射、无损打开和正常切片，不能以单元测试代替实际打开结果。
