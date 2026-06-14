# 机器适配 V2 维护手册

## 目的

本文档给下一次升级切片软件、同步新机型、准备 PR 时使用。它描述的是实际维护流程，不是早期设计讨论。

机器适配 V2 的目标是：

- 开发期读取 Bambu/Orca/Snapmaker/Elegoo/Anycubic 的原生 profile JSON。
- 生成 Lumina 内置 `machine_registry/`，随仓库发布。
- 用户端只读取 Lumina 内置 registry，不扫描用户本机切片器安装目录。
- 严格按 `切片软件 -> 机器型号 -> 喷嘴 -> revision` 区分 profile，避免同名机型串模板。
- 保留 Lumina 当前工艺要求，例如细层高、材料槽位、底板层高修改器和 3MF sidecar 规则。

## 当前数据边界

核心运行数据：

- `machine_registry/registry.json`
- `machine_registry/slicers/<Slicer>/<source_version>/metadata_templates/*.json`
- `machine_registry/slicers/<Slicer>/<source_version>/assets/*_cover.*`
- `printer_profiles/*.json`
- `config.py`
- `utils/bambu_3mf_writer.py`
- `api/routers/system.py`
- `frontend/src/components/SettingsPanel.tsx`
- `frontend/src/utils/settingsOptionIds.ts`

开发期工具：

- `tools/machine_adapter/resolver.py`
- `tools/machine_adapter/providers.py`
- `tools/machine_adapter/emitter.py`
- `tools/machine_adapter/import_profiles.py`
- `tools/machine_adapter/sync_local_profiles.py`

重要约束：

- 不要提交本机安装路径、用户设置、临时 3MF/GLB、`output/`、`materials/*/usage_stats.json`。
- `machine_registry/` 是生成结果，允许提交。
- `materials/` 是用户耗材数据，本工作流默认不碰。
- ElegooSlicer 和 AnycubicSlicerNext 虽然是换皮 Orca，但 3MF header、Application、sidecar 规则仍要按各自切片器处理。

## Registry 粒度

每个可选设备 profile 的身份是：

```text
device_profile_id = <slicer_id>:<vendor_slug>:<machine_slug>:<nozzle_size>
```

示例：

```text
BambuStudio:bbl:bambu-lab-h2d:0.2
ElegooSlicer:elegoo:elegoo-centauri-carbon-2:0.2
AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.25
```

注意：`device_profile_id` 的最后一段必须保留切片软件原生喷嘴值，而不是使用 Lumina 老模板的 0.1mm 归一化结果。Anycubic Kobra X 使用 `0.25`，如果被归并成 `0.2`，UI 文案和 3MF writer 的 registry 校验都会产生误导。

## 当前支持范围

当前 registry 覆盖：

- BambuStudio
- OrcaSlicer
- SnapmakerOrca
- ElegooSlicer
- AnycubicSlicerNext

当前已经人工验收过的代表机型：

- Bambu Lab H2D `0.2` / `0.4`
- Bambu Lab X2D `0.4`
- Bambu Lab A2L `0.4`
- Elegoo Centauri Carbon 2 `0.2` / `0.4`
- Anycubic Kobra X `0.25` / `0.4`
- Snapmaker U1 `0.4`

## 升级前准备

1. 从 `origin/dev-refactor` 新建分支，例如：

```powershell
git fetch origin
git switch -c Min/feat/machine-adapter-v2-refresh origin/dev-refactor
```

2. 打开各切片软件一次，让它们完成 profile 下载/迁移。

3. 记录版本：

```powershell
$env:LUMINA_BAMBU_STUDIO_EXE = '<path-to-bambu-studio.exe>'
$env:LUMINA_ELEGOO_SLICER_EXE = '<path-to-elegoo-slicer.exe>'
$env:LUMINA_ANYCUBIC_SLICER_EXE = '<path-to-AnycubicSlicerNext.exe>'

(Get-Item $env:LUMINA_BAMBU_STUDIO_EXE).VersionInfo | Select-Object ProductVersion,FileVersion
(Get-Item $env:LUMINA_ELEGOO_SLICER_EXE).VersionInfo | Select-Object ProductVersion,FileVersion
(Get-Item $env:LUMINA_ANYCUBIC_SLICER_EXE).VersionInfo | Select-Object ProductVersion,FileVersion
```

Anycubic 还要记录：

```powershell
$anycubicRoot = Split-Path -Parent $env:LUMINA_ANYCUBIC_SLICER_EXE
Get-Content -Encoding UTF8 (Join-Path $anycubicRoot 'resources\build-version.txt')
Get-Content -Encoding UTF8 (Join-Path $anycubicRoot 'resources\report\report.ini')
```

4. 备份当前 registry，用于 diff：

```powershell
Copy-Item -Recurse machine_registry output\temp\machine_registry_before_refresh
```

`output/temp/` 不提交，只用于本地对比。

## 重新生成 registry

### 默认同步入口

如果切片器 profile 已同步到 `%APPDATA%/<Slicer>/system`：

```powershell
python tools\machine_adapter\sync_local_profiles.py --output machine_registry
```

只同步某个切片器：

```powershell
python tools\machine_adapter\sync_local_profiles.py --slicer ElegooSlicer --output machine_registry
python tools\machine_adapter\sync_local_profiles.py --slicer AnycubicSlicerNext --output machine_registry
```

### 单来源精确导入

当需要手动指定 `application_metadata` 或 `client_version` 时，用 `import_profiles.py`：

```powershell
python tools\machine_adapter\import_profiles.py `
  --slicer AnycubicSlicerNext `
  --source-root "$env:APPDATA\AnycubicSlicerNext\system" `
  --source-version 1.3.2605.22 `
  --application-metadata AnycubicSlicerNext-1.4.1.2 `
  --client-version "1.4.1.2 20260604104233" `
  --vendor Anycubic `
  --output output\temp\anycubic_registry_check
```

这个命令会生成单切片器 registry。合并多切片器时推荐使用 `run_import_sources(...)` 的 Python 小脚本，而不是手工拼 JSON。

### 源版本和应用版本

不要把这些字段混用：

| 字段 | 含义 | 示例 |
|---|---|---|
| `source_version` | profile 包版本 | `1.3.2605.22` |
| `application_metadata` | 3MF `Application` 字段 | `AnycubicSlicerNext-1.4.1.2` |
| `client_version` | `slice_info.config` header 版本 | `1.4.1.2 20260604104233` |
| `revision` | 原生 profile 源文件 hash | `sha256:...` |

Anycubic 常见情况是 `source_version` 和应用版本不同，必须分开记录。

`tools/machine_adapter/sync_local_profiles.py` 里有两个显式覆盖表：

- `APPLICATION_METADATA_OVERRIDES`
- `CLIENT_VERSION_OVERRIDES`

目前 Anycubic Slicer Next 使用这些覆盖表固定为人工验收过的客户端版本。下次升级 Anycubic 时，必须先用真实切片器打开 3MF 验收，再更新这两个常量和 `tests/test_machine_registry_bundle_unit.py` 的期望值；不要只改 `Anycubic.json` 的 profile 包版本。

## 生成后必须检查

### Registry 完整性

```powershell
python -m pytest tests/test_machine_registry_bundle_unit.py -q
```

这会检查：

- `machine_registry/registry.json` 存在。
- 每个 machine 都有 thumbnail。
- 每个 thumbnail 路径都存在。
- 每个 nozzle template 路径都存在。
- 关键验收 profile 存在。
- 当前 AC/Elegoo 版本戳没有退回旧值。

### 快速统计

```powershell
@'
import json
from pathlib import Path

data = json.loads(Path("machine_registry/registry.json").read_text(encoding="utf-8"))
for slicer in data["slicers"]:
    machines = slicer.get("machines", [])
    nozzles = sum(len(m.get("nozzles", [])) for m in machines)
    missing = [m["display_name"] for m in machines if not m.get("thumbnail")]
    print(slicer["slicer_id"], slicer.get("source_version"), "machines=", len(machines), "nozzles=", nozzles, "missing_thumbnails=", len(missing))
    if missing:
        print("  missing:", missing[:10])
'@ | python -
```

缺缩略图不是 blocker，但提交 PR 前要说明原因。已知目标是 Bambu/Orca/Snapmaker/Elegoo/Anycubic 当前覆盖机型都应有图。

### 喷嘴命名检查

```powershell
@'
import json
from pathlib import Path

root = Path("machine_registry")
data = json.loads((root / "registry.json").read_text(encoding="utf-8"))
for slicer in data["slicers"]:
    for machine in slicer["machines"]:
        for nozzle in machine["nozzles"]:
            template = json.loads((root / nozzle["template"]).read_text(encoding="utf-8-sig"))
            source_name = str(nozzle["source_profile_name"])
            settings_id = str(template.get("printer_settings_id", ""))
            diameter = template.get("nozzle_diameter")
            if str(nozzle["nozzle_size"]) not in source_name and str(nozzle["nozzle_size"]) not in settings_id:
                print("CHECK", nozzle["device_profile_id"], source_name, settings_id, diameter)
'@ | python -
```

看到 Anycubic Kobra X `0.25 nozzle` 时不要直接判错；这是当前原生 profile 行为。但 UI 是否应显示 `0.25` 要单独决策。

## 3MF 自动回归

后端最小回归：

```powershell
python -m pytest `
  tests/test_machine_registry_bundle_unit.py `
  tests/test_machine_registry_unit.py `
  tests/test_machine_adapter_import_cli_unit.py `
  tests/test_machine_adapter_emitter_unit.py `
  tests/test_machine_adapter_sync_local_profiles_unit.py `
  tests/test_bambu_3mf_writer_unit.py `
  tests/test_bambu_3mf_cross_slicer_cover_unit.py `
  tests/test_bambu_3mf_png_integrity_unit.py `
  -q
```

前端设置页回归：

```powershell
python scripts\run_vitest.py run `
  src\__tests__\settingsOptionIds.test.ts `
  src\components\__tests__\SettingsPanel.machineAdapter.test.tsx `
  --reporter=verbose
```

更完整的 PR 前回归可追加：

```powershell
python -m pytest tests/test_settings_api_unit.py tests/test_printer_profile_unit.py tests/test_3mf_template_matrix_unit.py -q
python scripts\run_vitest.py run src\__tests__\settings-store-hydration.test.ts --reporter=verbose
```

## 真实 3MF 验收

真实验收必须至少覆盖：

- BambuStudio 打开 H2D `0.2`。
- BambuStudio 打开 X2D/A2L 代表机型。
- ElegooSlicer 打开 Elegoo CC2 `0.2`。
- AnycubicSlicerNext 打开 AC KX `0.25`。

生成示例使用 `core.converter.generate_final_model(...)`，输入图片可以用：

```text
<any-real-acceptance-image.png>
```

关键参数：

```python
target_width_mm=60.0
spacer_thick=0.48
structure_mode="单面"
color_mode="4-Color"
modeling_mode=ModelingMode.HIGH_FIDELITY
quantize_colors=64
enable_base_layer_height_modifier=True
cover_source_path=<source image path>
```

验收后解包检查：

```python
import json, zipfile, xml.etree.ElementTree as ET
from pathlib import Path

path = Path("output/temp/example.3mf")
with zipfile.ZipFile(path) as zf:
    project = json.loads(zf.read("Metadata/project_settings.config").decode("utf-8"))
    slice_root = ET.fromstring(zf.read("Metadata/slice_info.config"))
    header = {item.attrib["key"]: item.attrib.get("value", "") for item in slice_root.findall("./header/header_item")}
    entries = set(zf.namelist())

print(project["printer_model"])
print(project["printer_settings_id"])
print(project["nozzle_diameter"])
print(project.get("default_print_profile"))
print(header)
print("filament_sequence", "Metadata/filament_sequence.json" in entries)
print("cut_information", "Metadata/cut_information.xml" in entries)
print("custom_gcode_per_layer", "Metadata/custom_gcode_per_layer.xml" in entries)
```

预期 sidecar：

| 切片器 | `filament_sequence.json` | `cut_information.xml` | `custom_gcode_per_layer.xml` |
|---|---:|---:|---:|
| BambuStudio | yes | yes | no |
| OrcaSlicer | no | no | no |
| SnapmakerOrca | no | no | no |
| ElegooSlicer | no | no | no |
| AnycubicSlicerNext | no | no | yes |

## 前端验收

设置页必须满足：

- 用户先看机器卡片和缩略图，再选择机器。
- 喷嘴按钮在卡片内，当前只展示 Lumina 支持的 `0.2` / `0.4` 档。
- 同名机器在不同 slicer 下不会复用旧 `device_profile_id`。
- H2D、H2D Pro、X2D、A2L、Elegoo CC2、AC KX、Snapmaker U1 的缩略图能加载。
- 切换 slicer 后，当前机器不兼容时自动切到该 slicer 的第一个兼容机型。
- 旧本地设置里没有 `deviceProfileId` 时，不应继续绑定默认 H2D profile。

手工检查路径：

```text
http://localhost:4174/ -> 设置 -> 打印机型号
```

开发环境不要同时保留多个前端端口。发现 `4174`、`5174` 都开着时，先确认当前浏览器实际连的是哪一个。

## 常见问题

### 打开切片器显示 A1 mini

优先检查：

1. 前端请求体是否传了正确 `printer_id`、`slicer`、`nozzle_size`、`device_profile_id`。
2. `load_printer_template(...)` 是否走了 registry，而不是 fallback 到默认 `bambu-h2d` 或旧模板。
3. `project_settings.config` 的 `printer_model` 和 `printer_settings_id`。
4. `3D/3dmodel.model` 的 `Application`。
5. `slice_info.config` 的 client header。

### Anycubic 打开失败或卡死

优先检查：

- `Metadata/top_1.png` / `pick_1.png` / plate PNG 是否可解码。
- 是否存在 `Metadata/custom_gcode_per_layer.xml`。
- 是否误加了 Bambu-only `filament_sequence.json` / `cut_information.xml`。
- `Application` 是否是 `AnycubicSlicerNext-...`。
- `X-ACNext-Client-Version` 是否匹配当前安装版本。

### Elegoo/AC profile 版本显示不一致

区分：

- `source_version`: profile 包版本。
- `application_metadata`: 3MF Application。
- `client_version`: slice header。

不要用 `source_version` 直接推断 Application。

### AC KX 0.25 原生喷嘴

当前原生模板是：

```text
source_profile_name = Anycubic Kobra X 0.25 nozzle
printer_settings_id = Anycubic Kobra X 0.25 nozzle
nozzle_diameter = ["0.25"]
device_profile_id = AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.25
```

维护时必须确认 `registry.json`、模板路径、前端喷嘴卡片、3MF writer 入参、`project_settings.config` 都保留 `0.25`。前端仍会过滤掉 `0.6` / `0.8`，但允许 `0.25`、`0.4` 作为可见选项。

### default_print_profile 仍显示旧喷嘴

如果 `printer_settings_id` 和 `nozzle_diameter` 正确，但 `default_print_profile` 仍显示旧喷嘴，说明 registry machine template 和 Lumina legacy project template 合并时某些工艺字段没有被 registry 覆盖。优先检查：

- `utils/bambu_3mf_writer.py` 中 registry overlay key 列表。
- `default_print_profile`
- `print_settings_id`
- `inherits_group`
- `default_filament_profile`

这类问题必须用解包测试覆盖，不要只凭切片器 UI 判断。

## PR 前 checklist

- [ ] `materials/` 没有被 stage。
- [ ] `output/`、`logs/`、临时 3MF/GLB 没有被 stage。
- [ ] `machine_registry/` 的新增/删除符合本次升级范围。
- [ ] `registry.json` 中 `source_version`、`application_metadata`、`client_version` 被人工确认。
- [ ] 每个支持机型 thumbnail 路径存在。
- [ ] H2D、Elegoo CC2、AC KX 真实 3MF 已打开切片器验收。
- [ ] 后端最小回归通过。
- [ ] 前端设置页回归通过。
- [ ] PR 描述列出已知边界，尤其是 Anycubic KX `0.25` 与 UI `0.2` 的关系。

## 推荐 PR 描述骨架

```markdown
## Summary
- Add Machine Adapter V2 generated registry from native slicer machine profiles.
- Surface registry-driven slicer/machine/nozzle selection with thumbnails.
- Preserve Lumina 3MF process metadata while applying native machine identity and slicer-specific sidecars.

## Verification
- python -m pytest tests/test_machine_registry_bundle_unit.py tests/test_machine_registry_unit.py tests/test_machine_adapter_import_cli_unit.py tests/test_machine_adapter_emitter_unit.py tests/test_machine_adapter_sync_local_profiles_unit.py tests/test_bambu_3mf_writer_unit.py tests/test_bambu_3mf_cross_slicer_cover_unit.py tests/test_bambu_3mf_png_integrity_unit.py -q
- python scripts/run_vitest.py run src/__tests__/settingsOptionIds.test.ts src/components/__tests__/SettingsPanel.machineAdapter.test.tsx --reporter=verbose
- Manually generated and opened Bambu H2D 0.2 in Bambu Studio.
- Manually generated and opened Elegoo CC2 0.2 in ElegooSlicer.
- Manually generated and opened Anycubic Kobra X 0.25 in Anycubic Slicer Next.

## Known Follow-ups
- Anycubic Kobra X native 0.25 profile is currently represented by the normalized `:0.2` device profile id; UI should eventually display registry-native nozzle labels.
- Expand full matrix manual acceptance after future slicer updates.
```
