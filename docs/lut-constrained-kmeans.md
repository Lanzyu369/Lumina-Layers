# LUT-Constrained K-Means 颜色量化（高精度颜色匹配）

## 概述

将 K-Means 颜色量化的聚类中心约束在打印机 LUT 条目（可达颜色集合）上。标准 `cv2.kmeans` 的聚类中心可以是任意 RGB 值——这些"数学最优"的颜色往往不在打印机实际可打印的色域内，后续 LUT 匹配步骤将其强行吸附到最近 LUT 条目时会引入 **11–23 ΔE** 的额外色差。LUT-Constrained K-Means 在迭代过程中直接将每轮聚类中心投影到 LUT 上，省去事后匹配的精度损失。

前端 AdvancedSettings 中提供"高精度颜色匹配（实验性功能）"复选框，**默认关闭**。仅 LUT 颜色匹配路径生效；耗材档案、批量转换、large-format tiled 路径不受影响。

---

## 算法

### 入口

`quantize_colors(rgb, n_colors, ..., use_lut_constrained=True, lut_lab=..., lut_rgb=..., lut_tree=..., lut_fingerprint=...)`

当 `use_lut_constrained=True` 且 LUT 数据完整时，路由到 `_lut_constrained_quantize()`；否则走原有 `cv2.kmeans` 路径。缺 LUT 数据时不抛异常，自动回退并打 DEBUG 日志。

### `_lut_constrained_quantize` 核心流程

1. **K clamp**：`effective_k = min(n_colors, len(lut_lab))`。n_colors 超过 LUT 条目数时自动截断并打 INFO 日志。

2. **预缩放**：复用 `KMEANS_PIXEL_THRESHOLD = 500_000`。超过 50 万像素的图像先缩小做聚类，再将中心映射回原图分辨率。旧路径 `quantize_colors` 中原有的重复 `KMEANS_PIXEL_THRESHOLD` 定义已上提为模块级常量，两路径共用。

3. **RGB→Lab 转换**：新增 `_rgb_to_lab_quantize(rgb_flat)` 辅助函数，将 `(N, 3) float32 RGB` 经 `cv2.cvtColor(RGB→BGR→Lab)` 转为 `(N, 3) float64 Lab`。所有距离计算在 CIELAB 空间完成。

4. **加权 K-Means++ 初始化**（在 LUT 条目上，非像素上）：
   - 先将所有像素 snap 到最近 LUT 条目，得到每个条目的像素权重 `lut_pixel_counts`
   - 首个中心：按权重随机选一个 LUT 条目
   - 后续中心：LUT 条目间 `cdist(lut_lab, centers, 'sqeuclidean')` 取最小距离平方，乘以权重，按分布采样

5. **迭代**（最多 20 轮，`attempts=3` 取最低 SSE）：
   - **Assignment**：`cdist(work_pixels_lab, centers_lab, 'sqeuclidean').argmin(axis=1)`
   - **Update**：每 cluster 内像素 Lab 均值 → `lut_tree.query(mean_lab)` 取最近 LUT 条目
   - **空 cluster**：直接 `rng.choice(lut_count)` 随机选新中心（早期版本使用了像素距离分布加权 `rng.choice(lut_count, p=...)`，但 `p` 数组长度是像素数而非 LUT 条目数，导致 `'a' and 'p' must have same size` 运行时崩溃，已于实测中修复）
   - 中心不再变化且无空 cluster 时提前终止

6. **中心→RGB**：最优 Lab 中心经 `lut_tree.query → lut_rgb[indices]` 映射为 LUT RGB。

7. **post-blur**：与旧路径一致，受 `skip_post_blur` 参数和 `LUMINA_SKIP_POST_QUANTIZE_BLUR` 环境变量控制。

### 缓存隔离

模块级 LRU 缓存 key 格式：
```
{rgb.shape}_{sample_hash}_{effective_k}_{seed}_lc{flag}_{lut_fingerprint}
```

- `flag`：旧路径 `lc0`，新路径 `lc1`
- `lut_fingerprint`：`hashlib.sha1(lut_lab.tobytes()).hexdigest()[:12]`，由 `_finalize_loaded_lut` 在 LUT 加载时一次性计算并存入 payload，不在量化热路径上重复计算

不同 LUT 指纹或不同开关状态的缓存条目完全隔离，切换开关不会命中脏数据。

---

## 改动文件

| 文件 | 改动 |
|------|------|
| `core/pipeline/processing_ops/kmeans_quantizer.py` | 新增 `_lut_constrained_quantize()`、`_rgb_to_lab_quantize()`；扩展 `quantize_colors()` 签名（+`lut_lab`, `lut_rgb`, `lut_tree`, `use_lut_constrained`, `lut_fingerprint`）；缓存 key 增加 `lc` 和 `lut_fingerprint` 维度；`KMEANS_PIXEL_THRESHOLD` 上提为模块级常量 |
| `core/image_processing.py` | `LuminaImageProcessor.__init__` 增加 `use_lut_constrained` 参数；`_apply_lut_data` 提取 `lut_fingerprint`；`_prepare_high_fidelity_images` 透传 LUT 参数到 `kmeans_quantize`；`use_lut_constrained=True` 时强制 `hue_weight=0` 并跳过 `hue_matcher` |
| `core/pipeline/p03_core_processing.py` | `run()` 从 ctx 读取 `use_lut_constrained` 并注入 `LuminaImageProcessor`；`material_archive` 分支不改 |
| `core/pipeline/s02_image_processing.py` | 同上，`run()` 从 ctx 读取并注入 |
| `core/converter.py` | `generate_preview_cached()` 签名增加 `use_lut_constrained` 参数 |
| `core/pipeline/processing_ops/lut_loader.py` | `_finalize_loaded_lut` payload 增加 `lut_fingerprint`（`sha1(lut_lab.tobytes())[:12]`）；文件顶部新增 `import hashlib` |
| `api/schemas/converter.py` | `ConvertPreviewRequest` 和 `ConvertGenerateRequest` 各增加 `use_lut_constrained: bool = Field(False)` |
| `api/routers/converter/preview.py` | 路由签名增加 `use_lut_constrained: bool = Form(False)`；透传给 `worker_generate_preview` |
| `api/routers/converter/generate.py` | 两处 ctx dict 各增加 `"use_lut_constrained": request.use_lut_constrained` |
| `api/workers/converter_workers.py` | `worker_generate_preview` 签名字段数 21→22；透传到 `generate_preview_cached` |
| `frontend/src/stores/converter/store.ts` | 类型 + 初始值 + action `use_lut_constrained` / `setUseLutConstrained`；预览和单图转换 payload 各增加字段（批量/tiled 路径不传） |
| `frontend/src/components/sections/AdvancedSettings.tsx` | 新增"高精度颜色匹配"复选框；色相保护复选框增加 `disabled={use_lut_constrained}` + 条件 tooltip；色度门限滑动条仅在 `hue_enable && !use_lut_constrained` 时渲染 |
| `frontend/src/i18n/translations.ts` | 新增 3 个 key：`adv_precise_color_matching`、`adv_precise_color_matching_hint`、`adv_hue_protection_disabled_hint`（中英双语） |
| `tests/test_kmeans_quantizer_lut_constrained_unit.py` | **新文件**。14 项单元测试：回归契约、LUT 像素归属、K clamp、空 LUT、确定性、缓存隔离（开关+LUT指纹）、预缩放（>500k px）、post-blur |
| `tests/test_converter_workers_unit.py` | worker 参数计数更新（21→22），名称集合增加 `use_lut_constrained` |
| `frontend/src/__tests__/AdvancedSettings.test.tsx` | **新文件**。5 项测试：复选框渲染、默认值、状态切换、色相保护互斥（disable + checked 为 false）、色度滑块隐藏 |
| `scripts/benchmark_lut_constrained.py` | **新文件**。多颜色模式 × 多量化级别矩阵 benchmark |

---

## 测试覆盖

```
后端：test_kmeans_quantizer_lut_constrained_unit.py  ......... 14 passed
      test_kmeans_quantize_blur_skip_unit.py             ......... 20 passed
      test_converter_workers_unit.py (参数回归)          .........  2 passed
前端：AdvancedSettings.test.tsx                         .........  5 passed
```

---

## Benchmark 结果

基于 `LUT_Stress_Test_HD.png`（1920×2160，414万像素），多模式 × 多量化级别矩阵对比。

### 端到端 ΔE（原始像素 → 量化 → LUT匹配 → 最终输出，越小越好）

| n_colors | BW (LUT 1024) | 4-Color (LUT 1024) | 6-Color (LUT 1296) | 8-Color (LUT 2738) |
|----------|---------------|---------------------|---------------------|---------------------|
| 36 | 27.30 → **25.34** (−1.97) | 27.30 → **25.34** (−1.97) | 21.71 → **19.44** (−2.27) | 16.96 → **15.48** (−1.47) |
| 72 | 25.55 → **24.18** (−1.36) | 25.55 → **24.18** (−1.36) | 19.87 → **18.20** (−1.67) | 14.99 → **13.59** (−1.39) |
| 144 | 24.73 → **23.61** (−1.12) | 24.73 → **23.61** (−1.12) | 18.75 → **17.51** (−1.25) | 13.76 → **12.58** (−1.19) |
| 256 | 24.19 → **23.46** (−0.74) | 24.19 → **23.46** (−0.74) | 18.04 → **17.29** (−0.75) | 13.01 → **12.15** (−0.86) |
| 1024 | 23.46 → **23.40** (−0.06) | 23.46 → **23.40** (−0.06) | 17.24 → **17.17** (−0.07) | 13.67 → **13.48** (−0.19) |

> 旧路径量化后的颜色本身不在 LUT 中，事后 LUT 匹配引入 **11–23 ΔE** 的附加损失（LUT-match penalty）。新路径的聚类中心本身就是 LUT 条目，端到端 ΔE 在所有格子上都更低。

### 速度

| LUT 大小 | 36–256 色 | 1024 色 |
|----------|-----------|---------|
| 1024 条目 | 新路径 1.05–1.11×（略慢 5–11%） | 1.10–1.30× |
| 1296 条目 | 0.89–1.19× | 1.30–1.40× |
| 2738 条目 | 0.96–2.22×（72 色时最慢） | 1.80–2.00× |

大 LUT（2738 条目）+ 中等量化色数（72–144）时新路径最慢（`cdist` 矩阵 `500K×2738` 每轮迭代 ~14 亿次浮点运算），但 256 色时基本打平。小 LUT 下性能代价可忽略。

### 规律

- **新路径 ΔE 始终优于旧路径**，收益随 n_colors 增大而递减（36 色时 −1.5~−2.3，1024 色时接近 0）
- **LUT 条目越密，事后匹配的惩罚越小**，新路径的精度优势也越小——但绝不会更差
- **速度瓶颈在大 LUT × 中等量化色数**组合，符合"实验性功能"定位

---

## 参数透传链路

```
UI (AdvancedSettings checkbox)
  → converter store.use_lut_constrained
  → POST /api/convert/preview  (payload.use_lut_constrained)    ← 仅预览 + 单图转换
  → ConvertPreviewRequest schema
  → worker_generate_preview(..., use_lut_constrained=...)
  → generate_preview_cached(..., use_lut_constrained=...)
  → p03 / s02 ctx["use_lut_constrained"]
  → LuminaImageProcessor(..., use_lut_constrained=...)
  → _prepare_high_fidelity_images
      → kmeans_quantize(
          ..., use_lut_constrained=...,
          lut_lab=self.lut_lab, lut_rgb=self.lut_rgb, lut_tree=self.kdtree,
          lut_fingerprint=self.lut_fingerprint,
        )
```

---

## 互斥策略

- **后端**：`LuminaImageProcessor.__init__` 中，`use_lut_constrained=True` 时强制 `hue_weight=0` 并跳过 `_init_hue_matcher()`，打 INFO 日志
- **前端**：色相保护复选框 `disabled={use_lut_constrained}` + tooltip 切换为 `adv_hue_protection_disabled_hint`；色度门限滑动条隐藏

---

## 未触及

- `material_archive` 分支 / `MaterialSolverCache`：完全不改
- `core/gradient_region_requantize.py`：保持原行为
- 批量转换路径：不传 `use_lut_constrained`
- Large-format tiled 路径：不传 `use_lut_constrained`
- 预测模型路径：不改语义

---

## 已知 Bug 修复记录

**`'a' and 'p' must have same size` 运行时崩溃**：`_lut_constrained_quantize` 空 cluster 重采样逻辑中，`rng.choice(lut_count, p=pixel_dists / d_sum)` 的 `p` 数组来自 `dist_sq.min(axis=1)`（长度 = 像素数），而 `a=lut_count`（LUT 条目数），长度不匹配。已修复为 `rng.choice(lut_count)` 不带 `p=` 参数。
