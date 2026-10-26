# 自动动态范围压缩（Auto Dynamic Range）— 算法文档

## 1. 算法目的

FDM 多色打印的每种耗材/色号组合都有其可达的 CIELAB 亮度范围。当原图的 L\* 跨度超出所选 LUT 或耗材档案的可达范围时，超出部分的像素在颜色匹配时会被强制钳制到最近可达色，导致高光/阴影区域丢失细节和层次感。

自动动态范围压缩算法将原图的 L\* 通道**平滑地**重映射到目标可达范围，使得：

1. **端点精确吸附**：源图最暗/最亮像素精确落到目标 L\* 下限/上限，保证纯黑区域与"全黑层组合"等专属配方之间的吸附关系不漂移；
2. **中间调对比度保留**：轻度压缩时中段严格恒等（斜率 1），不损失中灰对比度；
3. **端点柔化过渡**：高光与阴影使用指数滚降（toe / shoulder），避免硬截断造成的色带和色调跳跃；
4. **色度不变**：仅修改 L\* 通道，a\*b\* 保持不变，避免色相/饱和度漂移。

## 2. 理论依据

### 2.1 为什么需要滚降而非线性压缩

线性压缩（`y = tgt_lo + (x - src_lo) * tgt_span / src_span`）虽然简单，但存在两个问题：

- **端点斜率突变**：线性映射在端点处斜率 = `tgt_span / src_span < 1`，与端点外钳制区域（斜率 0）形成硬拐点，视觉上产生色带；
- **全局对比度衰减**：所有亮度级的对比度被均匀压缩，中间调的视觉层次感下降。

Cineon 风格的指数滚降借鉴了胶片扫描领域的对数响应曲线思想：**在端点处用指数函数柔化过渡，在中段保持恒等映射**，从而在压缩高光/阴影溢出的同时，最大限度地保留中间调的视觉对比度。

### 2.2 Cineon 形状常数的推导

指数 toe/shoulder 的通用形式为：

```
y = offset + amplitude · (exp(k · u) − 1) / (exp(k) − 1)
```

其中 `u ∈ [0, 1]` 是归一化位置，`k` 控制曲率。内边界（`u = 1`）处的斜率为：

```
dy/dx = (amplitude / width) · k · exp(k) / (exp(k) − 1) = (H/W) · k · exp(k) / E
```

其中 `H = amplitude`（y 方向的振幅），`W = width`（x 方向的宽度），`E = exp(k) − 1`。

**C1 连续性约束**：要求内边界斜率等于中段斜率。在轻度压缩时中段斜率 = 1，且 `H/W = shadow_amt / W_s = 1/2`（因为 `W_s = 2 · shadow_amt`），因此：

```
(1/2) · k · exp(k) / E = 1
```

化简得：

```
k · exp(k) = 2 · E = 2 · (exp(k) − 1)
```

即 `k · exp(k) = 2 · (exp(k) − 1)`。该方程的数值解为：

```
k ≈ 1.593624260040
E = exp(k) − 1 ≈ 3.9215
```

**关键性质**：同一个 `k` 在重度压缩情况下也成立——因为约束方程 `(H/W) · k · exp(k) / E = m` 中 `H/W` 始终等于 `tgt_span / src_span`，而我们选的 `m` 总是 `2 · tgt_span / src_span`，二者相除恰好消去，留下 `k · exp(k) / E = 2`，与轻度压缩的约束完全相同。

### 2.3 端点斜率

硬端点处（`u = 0`）的斜率：

- **轻度压缩**：`(H/W) · k / E = (1/2) · 1.5936 / 3.9215 ≈ 0.203`
- **重度压缩**：`(tgt_span / src_span) · k / E ≈ 0.406 · (tgt_span / src_span)`

斜率接近 0 意味着端点处曲线趋于平坦，实现了对极端值的柔和吸收。

## 3. 从前端到后端的完整调用链

### 3.1 前端入口

**UI 组件**：`frontend/src/components/sections/AdvancedSettings.tsx`

用户在"高级设置"面板中勾选"自动动态范围（实验性功能）"复选框，状态通过 Zustand store 管理：

```
AdvancedSettings.tsx (Checkbox)
  → useConverterStore.setAutoDynamicRange(true)
    → store.auto_dynamic_range = true
```

**国际化文案**（`frontend/src/i18n/translations.ts`）：

| 键 | 中文 | English |
|----|------|---------|
| `adv_auto_dynamic_range` | 自动动态范围（实验性功能） | Auto Dynamic Range (Experimental) |
| `adv_auto_dynamic_range_hint` | 根据所选 LUT 或耗材档案的可达亮度范围，对原图 L\* 进行压缩映射… | Compresses the source image's L\* into the luminance range achievable… |

### 3.2 请求传递

前端在发起预览/生成请求时，将 `auto_dynamic_range` 作为参数传递：

- **预览**：`store.ts` → `POST /api/converter/preview`（Form 参数）
- **生成**：`store.ts` → `POST /api/converter/generate`（JSON body）

### 3.3 API 层

| 文件 | 角色 |
|------|------|
| `api/schemas/converter.py` | `PreviewRequest` / `GenerateRequest` schema 中声明 `auto_dynamic_range: bool = False` |
| `api/routers/converter/preview.py` | 预览端点接收 Form 参数，传给 worker |
| `api/routers/converter/generate.py` | 生成端点接收 JSON body，打包到 params dict 传给 worker |

### 3.4 Worker 层

`api/workers/converter_workers.py`：

- `worker_generate_preview(..., auto_dynamic_range: bool = False)` → 传给 `core.converter.generate_preview_cached`
- `worker_generate_model(...)` → params dict 中包含 `auto_dynamic_range` → 传给 `core.converter.generate_final_model`

### 3.5 Core 业务逻辑层

`core/converter.py` 将 `auto_dynamic_range` 放入 pipeline 上下文 `ctx` dict，由 `coordinator.py` 透传到各步骤。

**两条执行路径**：

**路径 A — 预览管道**（P03）：

```
core/pipeline/p03_core_processing.py
  → 条件导入 apply_auto_dynamic_range + compute_target_l_range
  → 从 cache.lab_centers 取目标 L* 范围
  → apply_auto_dynamic_range(rgb_arr, target_lo, target_hi)
```

**路径 B — 光栅管道**（S02 → ImageProcessor）：

```
core/pipeline/s02_image_processing.py
  → LuminaImageProcessor(auto_dynamic_range=True)
    → _maybe_apply_auto_dynamic_range(rgb_arr)
      → compute_target_l_range(self.lut_lab)
      → apply_auto_dynamic_range(rgb_arr, target_lo, target_hi)
```

### 3.6 调用链总图

```
用户勾选 Checkbox
  │
  ▼
[前端] AdvancedSettings.tsx → setAutoDynamicRange()
  │
  ▼
[前端] store.auto_dynamic_range = true
  │
  ├─▶ 预览请求 → API preview.py → worker_generate_preview
  │     │
  │     ▼
  │   core.converter.generate_preview_cached → ctx → P03
  │     │
  │     ▼
  │   compute_target_l_range(lab_centers) → apply_auto_dynamic_range()
  │
  └─▶ 生成请求 → API generate.py → worker_generate_model
        │
        ▼
      core.converter.generate_final_model → convert_image_to_3d → S02
        │
        ▼
      LuminaImageProcessor._maybe_apply_auto_dynamic_range()
        │
        ▼
      compute_target_l_range(lut_lab) → apply_auto_dynamic_range()
```

## 4. 算法细节

### 4.1 目标范围计算

`compute_target_l_range(lut_lab)` 从 LUT 或耗材调色板的 CIELAB 数组中提取 L\* 的最小/最大值：

```python
l_min = float(np.nanmin(l_channel))
l_max = float(np.nanmax(l_channel))
return (l_min, l_max)
```

返回 `None` 的条件：空数组、无效维度、全 NaN、l_max ≤ l_min。

### 4.2 色彩空间转换

`apply_auto_dynamic_range` 的处理流程：

```
RGB (uint8) → BGR → CIELAB (OpenCV 编码) → L* (真实单位) → 重映射 → CIELAB → BGR → RGB (uint8)
```

OpenCV 的 CIELAB 编码中 L 通道范围是 [0, 255]，对应真实 L\* 的 [0, 100]，缩放因子 `_OPENCV_L_SCALE = 2.55`。

### 4.3 跳过条件

在执行压缩前，以下情况直接返回原图：

| 条件 | reason 字段 | 含义 |
|------|------------|------|
| `rgb is None` | `no_image` | 无图像 |
| `rgb.size == 0` | `empty_image` | 空图像 |
| `rgb.ndim != 3 or rgb.shape[2] != 3` | `invalid_shape` | 维度异常 |
| `target_l_max <= target_l_min` | `invalid_target` | 目标范围无效 |
| `src_span < 1.0` | `source_span_too_small` | 源图接近常量 |
| `tgt_span >= src_span - 1.0` | `target_not_narrower` | 目标不比源窄 |

### 4.4 Cineon 指数三段曲线

#### 常量

```python
_CINEON_K = 1.593624260040   # k·e^k = 2·(e^k − 1) 的数值解
_CINEON_E = exp(k) - 1       # ≈ 3.9215
```

#### 端点与尾部宽度

```python
shadow_amt    = max(0, tgt_lo - src_lo_hard)    # 需提升的阴影量
highlight_amt = max(0, src_hi_hard - tgt_hi)    # 需下压的高光量
W_s           = 2 · shadow_amt                   # toe 在 x 轴的宽度
W_h           = 2 · highlight_amt                # shoulder 在 x 轴的宽度
```

`W_s = 2 · shadow_amt` 的含义：toe 段在 x 轴的宽度是 y 轴振幅的 2 倍，这使得 `H/W = 1/2`，从而内边界斜率恰好等于 1。

#### 情况 A：轻度压缩（W_s + W_h ≤ src_span）

三段曲线，中段严格恒等：

```
Toe      x ∈ [src_lo_hard, src_lo_hard + W_s]:
         u = (x − src_lo_hard) / W_s ∈ [0, 1]
         y = tgt_lo + shadow_amt · (exp(k·u) − 1) / E

Middle   x ∈ [src_lo_hard + W_s, src_hi_hard − W_h]:
         y = x                               (严格恒等，斜率 1)

Shoulder x ∈ [src_hi_hard − W_h, src_hi_hard]:
         u = (src_hi_hard − x) / W_h ∈ [0, 1]
         y = tgt_hi − highlight_amt · (exp(k·u) − 1) / E
```

**端点验证**：

| 位置 | y 值 | 斜率 |
|------|------|------|
| `x = src_lo_hard` (u=0) | `tgt_lo` ✓ | ≈ 0.203 |
| `x = src_lo_hard + W_s` (u=1) | `src_lo_hard + W_s` ✓ | 1.0 (C1) |
| `x = src_hi_hard − W_h` (u=1) | `src_hi_hard − W_h` ✓ | 1.0 (C1) |
| `x = src_hi_hard` (u=0) | `tgt_hi` ✓ | ≈ 0.203 |

#### 情况 B：重度压缩（W_s + W_h > src_span）

两段指数直接相接，无线性中段：

```python
ratio_s = shadow_amt / (shadow_amt + highlight_amt)
ratio_h = 1 - ratio_s
x_meet  = src_lo_hard + src_span · ratio_s
y_meet  = tgt_lo      + tgt_span · ratio_s
```

```
Toe      x ∈ [src_lo_hard, x_meet]:
         u = (x − src_lo_hard) / (src_span · ratio_s)
         y = tgt_lo + (tgt_span · ratio_s) · (exp(k·u) − 1) / E

Shoulder x ∈ [x_meet, src_hi_hard]:
         u = (src_hi_hard − x) / (src_span · ratio_h)
         y = tgt_hi − (tgt_span · ratio_h) · (exp(k·u) − 1) / E
```

**端点验证**：

| 位置 | y 值 | 斜率 |
|------|------|------|
| `x = src_lo_hard` (u=0) | `tgt_lo` ✓ | ≈ 0.406 · (tgt_span/src_span) |
| `x = x_meet` | `y_meet` ✓ | 2 · tgt_span / src_span (C1) |
| `x = src_hi_hard` (u=0) | `tgt_hi` ✓ | ≈ 0.406 · (tgt_span/src_span) |

#### 向量化实现

使用 NumPy 布尔掩码分段计算，避免 Python 循环：

```python
toe_mask = l_star <= x_toe_end
mid_mask = (l_star > x_toe_end) & (l_star < x_shoulder_start)
shoulder_mask = l_star >= x_shoulder_start
```

最终输出 `np.clip(out, tgt_lo, tgt_hi)` 确保不越界。

### 4.5 退化输入处理

- `src_span ≤ 1e-6`：返回目标范围中点（常量映射）
- 重度压缩时 `total_amt ≤ 1e-6`：同上

## 5. 算法设计考量

### 5.1 为什么只用硬端点（min/max），不用百分位

早期版本使用 1%/99% 百分位作为"软端点"来排除极端像素，但这引入了两个问题：

1. **纯黑/纯白漂移**：当图像中 >50% 像素为纯黑时，1% 百分位仍为 0，但软/硬端点分离导致线性段不直接贴到 tgt_lo，而是留出 10% 的 knee 保留带，使纯黑像素被抬离目标下限；
2. **参数冗余**：软端点与硬端点之间的 Reinhard 滚降区间宽度取决于百分位差，难以与目标范围精确对齐。

Cineon 曲线直接用硬端点（min/max）作为源范围边界，尾部宽度完全由 `shadow_amt = tgt_lo - src_lo_hard` 决定——这是源端需要"提升"或"下压"的确切量，无需额外的百分位参数。

### 5.2 为什么选择指数曲线而非 Reinhard 或二次曲线

| 曲线类型 | 端点斜率 | C1 连续 | 中段恒等 | 参数复杂度 |
|----------|---------|---------|---------|-----------|
| Reinhard `u/(u+a)` | 非零（端点不贴零） | 需额外归一化 | 不支持 | a + knee_frac |
| 二次抛物线 | 可为零 | 需手动匹配 | 可支持 | 需分段推导 |
| **Cineon 指数** | **≈ 0.2（自然贴零）** | **自动（单一 k）** | **原生支持** | **k（固定常量）** |

Cineon 指数曲线的核心优势：**单一形状常数 k 同时保证两种压缩情况下内边界斜率 = 目标斜率**，无需为轻度/重度压缩分别调参。

### 5.3 为什么 k 固化为常量而非用户可调

- `k ≈ 1.5936` 是 C1 连续性的解析解，不是经验值；
- 调整 k 会破坏内边界斜率匹配，导致曲线出现拐点；
- 用户无需感知这个参数——曲线的"软硬"程度由目标范围与源范围的差值自动决定。

### 5.4 为什么只修改 L\* 通道

在 CIELAB 色彩空间中，L\* 编码感知亮度，a\*b\* 编码色度。如果同时压缩 a\*b\*，会导致：

- 色相偏移（同色异谱区域的颜色漂移）；
- 饱和度衰减（高饱和色被压向中性）。

只压缩 L\* 可以确保"同一种颜色只是变亮/变暗"，不会改变颜色的本质属性。

### 5.5 重度压缩的相接策略

当 `W_s + W_h > src_span` 时，toe 和 shoulder 的 x 轴区间会重叠，无法保留线性中段。此时采用**按比例相接**策略：

- `ratio_s = shadow_amt / total_amt`：阴影量占总压缩量的比例；
- 相接点 `x_meet` 按此比例分配源范围，`y_meet` 按同比例分配目标范围；
- 两段指数在相接点 y 值一致、斜率一致（= `2 · tgt_span / src_span`），保证 C1 连续。

这种策略确保重度压缩下曲线仍然单调且平滑，不会出现 S 形反转。

### 5.6 日志与治理

- 日志事件名：`auto_dynamic_range_applied` / `auto_dynamic_range_skipped`（在 `image_processing.py` 中发出）
- `info` 字典键：`applied`、`reason`、`src_l_range`、`tgt_l_range`
- 不新增 INFO 事件，治理预算不受影响

## 6. 测试覆盖

### 6.1 现有测试（`tests/test_dynamic_range_compressor_unit.py`）

| 测试类 | 数量 | 覆盖内容 |
|--------|------|---------|
| `TestComputeTargetLRange` | 3 | 目标范围计算：正常/空/常量 |
| `TestApplyAutoDynamicRange` | 7 | 跳过条件、压缩触发、单调性、a\*b\* 不变、无效目标、空图、常量图 |
| `TestPureBlackReachesTargetFloor` | 3 | 纯黑/纯白精确吸附、离群像素不主导映射 |
| 参数化 `test_endpoints_clamped_to_target` | 3 | 多组目标范围端点钳制 |
| `TestCineonCurveProperties` | 5 | 中段恒等、C1 连续、尾部宽度自适应、重度压缩相接、指数 toe 凸性 |

### 6.2 演示脚本

`scripts/build_auto_dr_curve_excel.py`：生成 Excel 文件，包含三种典型目标范围下的映射曲线可视化（401 个采样点），用于人工审查曲线形状。

## 7. 涉及文件清单

| 层级 | 文件 | 角色 |
|------|------|------|
| 前端 UI | `frontend/src/components/sections/AdvancedSettings.tsx` | 复选框 UI |
| 前端 i18n | `frontend/src/i18n/translations.ts` | 双语文案 |
| 前端状态 | `frontend/src/stores/converter/store.ts` | Zustand store |
| 前端测试 | `frontend/src/__tests__/AdvancedSettings.test.tsx` | 组件测试 |
| API Schema | `api/schemas/converter.py` | 请求参数校验 |
| API 预览路由 | `api/routers/converter/preview.py` | 预览端点 |
| API 生成路由 | `api/routers/converter/generate.py` | 生成端点 |
| Worker | `api/workers/converter_workers.py` | 进程池入口 |
| Core 入口 | `core/converter.py` | generate_preview_cached / convert_image_to_3d |
| Pipeline 协调器 | `core/pipeline/coordinator.py` | 管道步骤编排 |
| Pipeline S02 | `core/pipeline/s02_image_processing.py` | 光栅管道图像处理步骤 |
| Pipeline P03 | `core/pipeline/p03_core_processing.py` | 预览/光栅核心处理步骤 |
| 图像处理器 | `core/image_processing.py` | LuminaImageProcessor |
| **核心算法** | `core/pipeline/processing_ops/dynamic_range_compressor.py` | 算法实现 |
| 单元测试 | `tests/test_dynamic_range_compressor_unit.py` | 算法测试 |
| 演示脚本 | `scripts/build_auto_dr_curve_excel.py` | 曲线可视化 |
