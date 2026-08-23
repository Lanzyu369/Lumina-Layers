# 3MF Metadata Export

## Purpose

This document describes how Lumina Studio exports slicer-specific 3MF metadata,
how native nozzle variants are selected, and how to verify that an
exported 3MF matches the intended template.

本文说明 Lumina Studio 如何导出切片器相关的 3MF 元数据、如何选择
原生喷嘴模板，以及如何验证导出的 3MF 是否与目标模板一致。

## Scope

The current export stack covers all printer/slicer combinations registered in
`config.py`.

当前导出链路覆盖 `config.py` 中已注册的全部机型/切片器组合。

At the time of writing:

- 30 printer profiles are registered
- 41 base metadata templates exist under `printer_profiles/`
- 34 sibling `*_0_2.json` templates exist for `0.2` nozzle exports
- Flashforge AD5X / Creator 5 / Creator 5 Pro / Guider4 / Guider4 Pro provide
  native `0.25` / `0.4` templates for Flash Studio Desktop
- Flashforge Guider 3 Ultra provides a native `0.4` template
- QIDI Q2 / Q2C / X-Max 4 provide native `0.2` / `0.4` templates for
  QIDI Studio; X-Plus 5 provides its native `0.4` template

## Core Files

- `machine_registry/`
  Generated Machine Adapter V2 registry and slicer-native metadata templates.
  For upgrade/update operations, use `docs/machine-adapter-v2-maintenance.md`
  as the maintenance checklist.
- `config.py`
  Resolves printer profiles, supported slicers, and nozzle-size-aware template paths.
- `printer_profiles/*.json`
  Checked-in metadata templates. Base files are treated as `0.4` truth; sibling
  `*_0_2.json` files are the `0.2` variants.
- `utils/bambu_3mf_writer.py`
  Loads the selected template and builds the embedded 3MF metadata payloads.
- `core/pipeline/s09_export_3mf.py`
  Raster export stage that forwards `printer_id`, `slicer`, and `nozzle_size`
  to the writer.
- `api/routers/converter/generate.py`
  Receives the frontend generate request and threads the metadata selectors into
  worker params.
- `api/routers/slicer.py`
  Launches the slicer against an isolated temporary copy so the canonical file
  in `output/models/` is not mutated by the slicer.
- `scripts/derive_nozzle_0_2_templates.py`
  Deterministic derivation script for the `*_0_2.json` template set.
- `scripts/verify_3mf_template_matrix.py`
  Full matrix verifier over all supported printer/slicer/nozzle combinations.

## Template Selection

3MF metadata selection is driven by this tuple:

```text
(printer_id, slicer, nozzle_size)
```

Resolution flow:

1. `config.get_printer_profile(printer_id)` resolves the canonical printer profile.
2. `PrinterProfile.get_template_file(slicer, nozzle_size)` maps the tuple to a
   concrete template filename under `printer_profiles/`.
3. `utils.bambu_3mf_writer.load_printer_template(...)` loads and caches that JSON.
4. `BambuStudio3MFWriter._build_project_settings_bytes()` uses the loaded
   template as the base project settings payload.

Important:

- `0.4` remains the base template truth.
- `0.2` always uses a checked-in sibling `*_0_2.json`.
- A slicer-native size explicitly declared by a printer profile is preserved;
  Flashforge `0.25` therefore selects `*_0_25.json` instead of being rounded
  into the legacy `0.2` slot.
- Flash Studio profiles are selected from its formal vendor `machine_list`, not
  by scanning every JSON left in the install directory. Only native presets at
  or below Lumina's `0.4` mm boundary are bundled; same-diameter standard and HF
  Guider4 presets are de-duplicated in favor of the standard preset.
- QIDI Studio profiles are bounded by the formal `Q Series`, `X 4 Series`, and
  `X 5 Series` manifests. Lumina exposes the four models backed by supplied
  native 3MF fixtures and keeps only native nozzle presets at or below `0.4` mm.
- `supported_nozzle_sizes` is exposed for every currently supported printer.

## Metadata Package Layout

The writer produces a core 3MF plus slicer-specific metadata sidecars.

Common files:

- `3D/3dmodel.model`
- `3D/_rels/3dmodel.model.rels`
- `Metadata/project_settings.config`
- `Metadata/model_settings.config`
- `Metadata/slice_info.config`
- preview PNG placeholders under `Metadata/`

Family-specific rules:

- `BambuStudio`
  Includes `Metadata/filament_sequence.json` and `Metadata/cut_information.xml`.
- `OrcaSlicer`
  Omits Bambu-only aux sidecars.
- `SnapmakerOrca`
  Omits Bambu-only aux sidecars.
- `ElegooSlicer`
  Omits Bambu-only aux sidecars and uses the Elegoo client-name/version stamp.
- `AnycubicSlicerNext`
  Uses `Metadata/custom_gcode_per_layer.xml` instead of Bambu aux sidecars.
- `FlashStudio`
  Omits Bambu-only aux sidecars, uses the native BBL client header, and does
  not emit an `OrcaSlicer-Version` tag.
- `QIDIStudio`
  Uses the native QDT client header, retains `filament_sequence.json` and
  `cut_information.xml`, emits `plate_1.json`, and uses QIDI package-cover
  relationship URIs.

## Nozzle Variant Rules

### General

The nozzle variant must affect both printer identity and process parameters.

喷嘴尺寸不仅要影响打印机身份字段，还必须影响工艺参数字段。

Minimum required `0.2` signals include:

- `printer_settings_id`
- `printer_variant`
- `nozzle_diameter`
- `default_print_profile`
- `print_settings_id`
- `initial_layer_line_width`
- `outer_wall_line_width`
- `inner_wall_line_width`
- `top_surface_line_width`
- `sparse_infill_line_width`
- `internal_solid_infill_line_width`
- `support_line_width`
- `line_width`

### H2 Family Official Process Presets

For Bambu H2-family printers, the `0.2` templates must align with official
system process preset names that Bambu Studio can recognize directly.

当前已对齐的官方 `0.2` process preset 名称：

- `bambu-h2d`
  `0.08mm Extra Fine @BBL H2D 0.2 nozzle`
- `bambu-h2c`
  `0.08mm High Quality @BBL H2C 0.2 nozzle`
- `bambu-h2s`
  `0.08mm High Quality @BBL H2S 0.2 nozzle`
- `bambu-h2d-pro`
  `0.08mm Extra Fine @BBL H2DP 0.2 nozzle`

Important details:

- `H2D Pro` uses the official short code `H2DP` inside process / filament preset
  names, even though the machine name remains `Bambu Lab H2D Pro 0.2 nozzle`.
- Using a custom `print_settings_id` or a stale `inherits_group` string can lead
  to Bambu Studio showing locked `0.4`-style line widths even when the raw
  template line-width fields are already `0.22`.

## Bambu Client Version Stamps

The `Application` metadata and `Metadata/slice_info.config` client-version stamp
must match the target family.

Rules currently used by the writer:

- Bambu `0.2` for non-H2 family: `02.04.00.70`
- Bambu `0.4`: `02.05.00.66`
- Bambu H2 family `0.2`: `02.05.00.66`
- Orca: `BambuStudio-2.3.2-rc2`
- Snapmaker: `SnapmakerOrca-02.02.49.02`
- Elegoo: `ElegooSlicer-1.3.2.9`
- Anycubic: `BambuStudio-1.3.9.4`
- Flash Studio Desktop: `BambuStudio-2.3.2`
- QIDI Studio: `QIDIStudio-02.07.02.60`

Flash Studio keeps three versions separate:

- desktop product version: `1.7.11` (installation detection/display only)
- bundled Flashforge profile version: `02.01.01.00` (`source_version`)
- native 3MF project/Application version: `2.3.2`
- native `X-BBL-Client-Version`: empty string

Its native 3MF identity is intentionally Bambu-compatible: `Application` is
`BambuStudio-2.3.2`, `project_settings.version` is `2.3.2`, and
`slice_info.config` keeps `X-BBL-Client-Version` empty. Do not rewrite these
as `FlashStudio-*` or add Orca-only version tags. Native Flash Studio packages
also contain `Metadata/plate_1.json`, a 128×128 `Metadata/plate_1_small.png`,
and a 32-character UUID in the slice header. A manually configured and saved
multi-material project additionally confirms that Lumina's three
`Auxiliaries/.thumbnails/*.png` cover assets and their package relationships
must be retained alongside the Flash-specific plate sidecars. Flash project
filament arrays are contracted to the active project palette rather than a
generic eight-slot template. These are format metadata only;
Lumina remains authoritative for layer height, line widths, wall generation,
temperatures, speeds, infill, support, and brim.

QIDI Studio `02.07.02.60` uses the same value for its installed profile bundle,
`Application`, project settings version, and `X-QDT-Client-Version`. Its native
model metadata also contains `QIDIStudio:3mfVersion=1` and
`OrcaSlicer=2.1.0.14`. The four supplied saved projects establish the supported
machine boundary: Q2, Q2C, X-Max 4, and X-Plus 5. Q2, Q2C, and X-Max 4 expose
`0.2` / `0.4`; X-Plus 5 exposes `0.4` only. The QIDI-specific fields are routing
and package metadata; Lumina remains authoritative for process values.
All four native reference projects explicitly disable the skirt
(`skirt_loops=0`) and draft shield; Lumina writes those fields explicitly so
QIDI Studio cannot fall back to a local process default that enables them.

The H2-family `0.2` branch intentionally uses the newer Bambu client stamp
because those machine/process presets are aligned to the newer H2 system family.

## Frontend and API Propagation

The frontend must send the selected metadata tuple explicitly in every 3MF-producing flow:

- `printer_id`
- `slicer`
- `nozzle_size`

Relevant path:

1. `frontend/src/stores/settingsStore.ts`
   Stores the user-facing printer / slicer / nozzle selection.
2. `frontend/src/App.tsx`
   Backfills missing local device settings from `/api/system/settings`.
3. `frontend/src/stores/converter/store.ts`
   Injects `printer_id`, `slicer`, and `nozzle_size` into generate requests.
4. `frontend/src/stores/fiveColorStore.ts`
   Injects the same tuple into recipe swatch 3MF generation.
5. `api/routers/converter/generate.py`
   Copies those fields into worker params without reading them from session state.
6. `core/pipeline/s09_export_3mf.py`
   Passes the tuple to `export_scene_with_bambu_metadata(...)`.

When printer / slicer / nozzle selection changes, any already-generated 3MF artifact
must be invalidated on the frontend so stale files cannot be reopened or redownloaded
under a new device tuple.

## Slicer Launch Isolation

Some slicers may rewrite a 3MF file after opening it.

部分切片器在打开 3MF 后可能会直接改写文件。

To keep `output/models/` as the canonical export artifact:

- `/api/slicer/launch` now creates a temporary launch copy under `output/temp/`
- the slicer opens that copy
- the original file under `output/models/` remains unchanged

This prevents post-launch metadata drift from corrupting the canonical export.

## Verification Workflow

### Fast automated checks

Use focused tests when changing template selection, writer behavior, or launch isolation:

```powershell
python -m pytest tests/test_printer_profile_unit.py -q
python -m pytest tests/test_bambu_3mf_writer_unit.py -q
python -m pytest tests/test_lut_api_unit.py tests/test_color_mode_propagation_unit.py -q
python -m pytest tests/test_slicer_unit.py tests/test_slicer_properties.py -q
```

### Full metadata matrix

```powershell
python scripts/verify_3mf_template_matrix.py
```

This verifies:

- every supported `(printer_id, slicer, nozzle_size)` export
- canonical family `Application` and slice-header fields
- sidecar presence rules
- selected project-settings subset against the chosen template

### Manual inspection

For one exported file:

1. Open the `.3mf` as a ZIP archive.
2. Inspect:
   - `Metadata/project_settings.config`
   - `Metadata/slice_info.config`
   - `3D/3dmodel.model`
3. Compare the target fields against the intended template JSON under
   `printer_profiles/`.

Suggested Python snippet:

```python
import ast, json, re, zipfile
from pathlib import Path

three_path = Path("output/models/example.3mf")
template_path = Path("printer_profiles/bambu_h2d_0_2.json")

with zipfile.ZipFile(three_path) as zf:
    project = ast.literal_eval(zf.read("Metadata/project_settings.config").decode("utf-8"))
    model_xml = zf.read("3D/3dmodel.model").decode("utf-8", errors="ignore")

template = json.loads(template_path.read_text(encoding="utf-8"))
app = re.search(r'<metadata name="Application">([^<]+)</metadata>', model_xml).group(1)

for key in [
    "print_settings_id",
    "line_width",
    "outer_wall_line_width",
    "top_surface_line_width",
    "internal_solid_infill_line_width",
]:
    print(key, project.get(key), template.get(key))

print("Application:", app)
```

## Known Debugging Pitfalls

- A file may look correct before slicer launch and wrong after launch if the
  slicer rewrites the same path.
- If Bambu Studio shows locked `0.42` line widths while the raw template fields
  are `0.22`, check the process preset identity fields first:
  - `print_settings_id`
  - `inherits_group`
  - `default_print_profile`
- If frontend-generated files differ from direct API exports, inspect the actual
  request body sent from the frontend store, especially:
  - `printer_id`
  - `slicer`
  - `nozzle_size`
  - `color_mode`

## Maintenance Rules

- When adding a new printer or slicer family, update:
  - `config.py`
  - `printer_profiles/`
  - frontend settings exposure
  - verification tests
- When deriving a new `0.2` template, prefer official system preset names over
  custom labels if the slicer family is known to key off preset identity.
- Re-run the metadata matrix after any change to:
  - template JSON
  - writer family stamps
  - launch behavior
  - frontend request propagation

## Base-plate Layer-Height Modifier / 底板层高修改器

### Motivation / 动机

For multi-color FDM prints, the solid-color base plate often dominates print
time while contributing nothing to color fidelity. Bambu-family slicers accept
a per-Z-range `layer_height` override via `Metadata/layer_config_ranges.xml`.
Lumina Studio targets half the nozzle diameter, then selects the nearest safe
height that lands exactly on the backing boundary and stays inside the selected
printer's limits. For a backing that starts on the build plate, the slicer's
fixed first-layer height is accounted for separately. Colored layers keep the
configured fine height. Relief exports skip this optimization because their
backing boundary can vary across the model, so one global Z range cannot be
proven safe; the writer emits no `layer_config_ranges.xml` when
`enable_relief=True`. Measured base-plate time savings for compatible flat
geometry are 40–60% depending on geometry.

对于多色 FDM 打印，纯色底板往往占据最大打印耗时，却对最终色彩效果
没有贡献。Bambu 系切片器支持通过 `Metadata/layer_config_ranges.xml`
按 Z 区间覆盖 `layer_height`。Lumina Studio 以喷嘴直径的一半为目标，随后
选择既能准确落在底板边界、又符合当前机型限制的最接近层高。底板贴着热床
时，切片器固定的首层层高会单独计入。彩色层仍保持原层高，底板耗时通常可
节省 40–60%。浮雕模型的底板边界可能随位置变化，无法证明单个全局 Z 区间
安全，因此浮雕会跳过这项优化；`enable_relief=True` 时 writer 不会生成
`layer_config_ranges.xml`。

### Formula / 计算规则

| Input / 输入 | Value / 值 |
|---|---|
| `target_layer_height` | `nozzle_diameter × 0.5` |
| Candidate grid / 候选网格 | `0.02 mm` increments / 以 `0.02 mm` 递增 |
| Backing above colours (`face=down`) / 底板在彩色层上方 | `base_height_mm % candidate == 0` |
| Backing on build plate (`face=up`) / 底板贴热床 | `(base_height_mm - initial_layer_print_height) % candidate == 0` |
| Printer bounds / 机型限制 | shared `min_layer_height` / `max_layer_height`, plus `candidate ≤ nozzle_diameter × 0.7` |
| Minimum backing layers / 最少底板层数 | two coarse layers for `face=down`; one fixed first layer + one coarse layer for `face=up` / `face=down` 至少两层粗层，`face=up` 至少一层固定首层加一层粗层 |
| Selection / 选择方式 | nearest to target; lower value wins a tie / 最接近目标，等距时取较小值 |
| `face=down`, `0.4` nozzle + `0.40` base | `0.20 mm` |
| `face=down`, `0.2` nozzle + `0.40` base | `0.10 mm` |
| `face=down`, `0.2` or `0.4` nozzle + `0.24` base | `0.12 mm` |
| `face=up`, `0.4` nozzle + `0.24` base + `0.08` first layer | `0.16 mm` after the `0.08 mm` first layer / `0.08 mm` 首层后使用 `0.16 mm` |
| `face=up`, `0.2` nozzle + `0.24` base + `0.08` first layer | skip (the required `0.16 mm` exceeds the printer limit) / 跳过（所需 `0.16 mm` 超出机型限制） |
| `base_height_mm` | `backing_layer_count × PrinterConfig.LAYER_HEIGHT` |
| `color_height_mm` | `num_color_layers × PrinterConfig.LAYER_HEIGHT` |

Z ranges emitted per `face_orientation`:

| Orientation / 朝向 | Condition / 判定 | Z range |
|---|---|---|
| `down` | Single-sided, non-5-Color-Extended / 单面且非 5-Color Extended | `[color_height_mm, color_height_mm + base_height_mm]` |
| `up` | 5-Color Extended (base on top) / 5-Color Extended（底板在顶部） | `[0, base_height_mm]` |
| `double` | Double-sided / 双面 | Skipped — colored layers exist on both sides / 跳过，正反两面都是彩色层 |

### Skip Conditions / 跳过条件

The writer skips emitting `layer_config_ranges.xml` when any of:

- toggle is off (`enable_base_layer_height_modifier=False`)
- relief is enabled (`enable_relief=True`), because a single global backing
  range could overlap variable-height optical layers
- `base_height_mm ≤ 0` (no backing)
- no `0.02 mm` candidate lands exactly on the backing boundary after accounting
  for the fixed first layer when applicable
- every divisible candidate is outside the selected printer's layer-height
  limits, is not coarser than the configured fine height, or would leave fewer
  than two backing layers
- `face_orientation == "double"`
- puzzle combine path (`core/puzzle_3mf.py` forces it off because object ids
  and Z coordinates differ from single-piece exports)

### Example XML / 样例 XML

```xml
<?xml version="1.0" encoding="UTF-8"?>
<objects>
 <object id="1">
  <range min_z="2.4" max_z="3.2">
   <option opt_key="extruder">0</option>
   <option opt_key="layer_height">0.2</option>
  </range>
 </object>
</objects>
```

### End-to-end Wiring / 全链路

```
SettingsPanel (WikiTooltip + Switch)
  └─► settingsStore.enableBaseLayerHeightModifier
        └─► POST /api/system/settings  → user_settings.json
        └─► ConvertGenerateRequest.enable_base_layer_height_modifier
              └─► worker params dict
                    └─► core.converter.generate_final_model(...)
                          └─► pipeline ctx["enable_base_layer_height_modifier"]
                                ├─► raster/vector ctx guard disables it for relief
                                └─► core/pipeline/s09_export_3mf.py
                                      └─► export boundary rechecks enable_relief
                                            └─► utils/bambu_3mf_writer.export_scene_with_bambu_metadata
                                                  └─► writer omits LCR for enable_relief=True
                                                        └─► build_layer_config_ranges_xml (flat safe cases only)
```

Bambu geometry keys (`bambu_base_height_mm`, `bambu_color_height_mm`,
`bambu_face_orientation`) are populated by `core/pipeline/s06_voxel_building.py`
(raster) and `core/pipeline/coordinator.py::_update_bambu_base_layer_ctx_for_vector`
(vector). Both branches disable the modifier for relief, and the export/writer
boundary repeats that guard so a caller cannot accidentally emit a global LCR
for relief geometry.

几何相关的 Bambu 上下文键由 `s06`（光栅）和 `coordinator` 的
`_update_bambu_base_layer_ctx_for_vector`（矢量）统一写入。两条分支都会在浮雕
模式关闭修改器，导出与 writer 边界还会再次检查，避免任何调用方误给浮雕
写入全局 LCR 区间。

### Backing sparse-infill contract / 背板稀疏填充契约

`PrinterConfig.VIEWING_SURFACE_SOLID_DEPTH_MM` is the single project-level
source of truth for the protected viewing-surface depth (default `3.0 mm`).
The writer stores the requested deep-backing density in
`Metadata/project_settings.config` as `sparse_infill_density`, then adds
`sparse_infill_density=100%` object-height overrides to
`Metadata/layer_config_ranges.xml` for the protected zones. The range builder
splits overlaps with the existing coarse `layer_height` override into sorted,
non-overlapping ranges.

`PrinterConfig.VIEWING_SURFACE_SOLID_DEPTH_MM` 是观赏面保护深度的唯一项目级
配置来源，默认值为 `3.0 mm`。writer 把用户选择的深层底板填充率写入
`Metadata/project_settings.config` 的 `sparse_infill_density`，再通过
`Metadata/layer_config_ranges.xml` 为观赏面保护区覆盖
`sparse_infill_density=100%`。区间构建器会把该覆盖与已有的粗层高覆盖拆分为
按 Z 排序且互不重叠的区间。

| Orientation / 朝向 | Protected solid range / 实心保护区 |
|---|---|
| `down` | `[0, color_height + solid_depth]` |
| `up` | `[base_height - solid_depth, base_height + color_height]` |
| `double` | Both viewing-side ranges; overlapping ranges are merged / 两侧观赏面区间，相交时合并 |

If the complete backing fits inside the protected depth (or inside both depths
for a double-sided model), the effective global density is promoted to `100%`
and no density-only range is needed. Sparse relief is rejected because its
variable backing boundary cannot be protected by a single global Z range.
Sparse puzzle generation is also rejected because puzzle assembly intentionally
removes source object-height ranges. Raster, vector, native large-format, and
batch exports all forward the same density and geometry context; merged batch
archives remap the one-based model-object indexes while preserving the ranges.

当整块底板不超过保护深度（双面模型则不超过两侧保护深度之和）时，实际全局
填充率会提升为 `100%`，无需额外的密度区间。浮雕底板边界随位置变化，无法用
单一全局 Z 区间可靠保护，因此稀疏浮雕会被拒绝；拼图装配会主动移除源对象的
高度区间，因此也拒绝稀疏拼图。光栅、矢量、原生大画幅和批量导出统一透传
密度与几何上下文，批量合并时会重映射从 1 开始的模型对象序号并保留区间。

### Turning it Off / 关闭方式

- UI: **Settings → Slicer Settings → Base-plate layer-height modifier**（仅当
  所选切片器属于 Bambu 家族时可见）
- Programmatic: send `enable_base_layer_height_modifier=false` in
  `POST /api/convert/generate`
- Config: set `"enable_base_layer_height_modifier": false` in `user_settings.json`

Bambu-family slicer IDs (see `frontend/src/utils/settingsOptionIds.ts`):
`BambuStudio`, `OrcaSlicer`, `SnapmakerOrca`, `ElegooSlicer`,
`AnycubicSlicerNext`, `FlashStudio`, `QIDIStudio`.

### Regression Tests / 回归测试入口

- `tests/test_bambu_layer_config_ranges_unit.py` — formula + XML shape +
  end-to-end writer produces valid XML
- `tests/test_pipeline_bambu_base_layer_ctx_unit.py` — raster/vector ctx
  derivation
- `tests/test_s09_export_3mf_unit.py` — s09 forwards ctx to writer and
  falls back to safe defaults
- `tests/test_puzzle_3mf_unit.py` — combined puzzle explicitly excludes
  `Metadata/layer_config_ranges.xml`
- `tests/test_converter_generate_unit.py::TestConverterEntryAcceptsBaseLayerModifierKwarg`
  — signature contract (prevents API↔worker kwargs drift)
- `tests/test_bambu_3mf_writer_unit.py` — writer-level kwargs plumbing
- `tests/test_backing_infill_contract_unit.py` — 10 mm boundary, canonical
  solid depth, orientation ranges, thin-backing promotion, and generated 3MF
  process metadata
- `frontend/src/components/__tests__/SettingsPanel.baseLayerHeightModifier.test.tsx`
  — UI gating by slicer family + translation assertions
- `frontend/src/__tests__/settingsOptionIds.test.ts` — `isBambuFamilySlicer`
  canonicalization
