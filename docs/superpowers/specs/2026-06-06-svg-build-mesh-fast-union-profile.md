# SVG build_mesh fast union 优化说明与 Profile 对比

## 结论

这次优化解决的是 SVG 预览/生成链路里 `build_mesh` 阶段的一个明确热点：同一材料、同一高度区间内的几何合并过去使用 Shapely `unary_union`，复杂 SVG 中大量离散小图形会让这一步变得很慢。

优化后，默认 V1 SVG mesh 生成路径已经变快：

- 用户提供的复杂 SVG：总耗时从 9.44 秒降到 7.81 秒，下降约 17.35%；`mesh_total` 下降约 20.36%。
- 第二张更复杂 SVG：总耗时从 32.85 秒降到 21.26 秒，下降约 35.29%；`mesh_total` 下降约 39.28%。
- 这次收益来自通用 `build_mesh` 路径，不依赖默认启用 SVG GLB V2。

当前判断：**fast union 可以保留；SVG GLB V2 exporter 仍不建议默认启用**。V2 在部分样例上 `mesh_total` 更低，但 GLB exporter 本身耗时仍偏高，复杂 SVG 上总耗时还没有稳定优于 V1。

## 背景

SVG 预览模型生成不是单纯把 SVG 转成一个 3D 文件。现有链路还要保留很多业务规则，包括：

- SVG 绘制顺序、孔洞、重叠和遮挡。
- 单面/双面、底板、描边、钥匙扣、冰箱贴。
- 材料槽命名、`color_RRGGBB` mesh 命名、5 色扩展。
- 拼图模式等依赖模型 bounds 和高度的前端叠加逻辑。

所以优化目标不是绕开 V1 规则重写一套快速路径，而是先找出现有链路中最慢、最安全可替换的局部热点。

## 根因

此前 cProfile 指向第二张复杂 SVG 的主要耗时：

| 项目 | 耗时 |
| --- | ---: |
| 整体 vector branch | 32.30s |
| `build_mesh` | 18.68s |
| `_run_length_extrude` | 18.01s |
| `unary_union` 累计 | 11.02s |
| `_extrude_geometry` | 5.74s |
| `extrude_polygon` | 2.57s |

也就是说，慢点主要在 `_run_length_extrude` 内部的 run group 几何合并，而不是最后写 GLB 文件。

`_run_length_extrude` 会按 `(channel, run_start, run_end)` 把同一材料、同一高度区间的 2D 几何归为一组，再合并后挤出。复杂 SVG 往往有大量彼此分离的小形状，直接用 `unary_union` 会做很多不必要的全局拓扑合并。

## 本次改动

代码改动集中在 `core/vector_engine.py`：

- 新增 `_union_run_group_geometries(geometries)`。
- 如果当前 Shapely 版本提供 `disjoint_subset_union_all`，优先使用它处理稀疏/分离几何集合。
- 如果 `disjoint_subset_union_all` 不存在或执行失败，自动回退到原来的 `unary_union`。
- `_run_length_extrude` 的 run group 合并改为调用这个 helper。

测试覆盖在 `tests/test_vector_engine_fixes_unit.py`：

- 验证同一 run group 在 fast union 可用时会走 `disjoint_subset_union_all`。
- 验证 fast union 抛错时仍回退 `unary_union`，避免新路径导致生成失败。

## V1 Profile 对比

原始日志：

- 优化前：`logs/vector_glb_v2_profile_spatial_batch.json`
- 优化后：`logs/vector_glb_v2_profile_fast_union.json`

| SVG | 优化前 V1 总耗时 | 优化后 V1 总耗时 | 下降 | 降幅 | 优化前 `mesh_total` | 优化后 `mesh_total` | mesh 降幅 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `io_temp_img_1780736845_fcd2a927_vector.svg` | 9.4442s | 7.8057s | 1.6385s | 17.35% | 7.8428s | 6.2462s | 20.36% |
| `6d2945e723b78963fa6b4caa8d937aa2 (1).svg` | 32.8537s | 21.2612s | 11.5925s | 35.29% | 29.6269s | 17.9898s | 39.28% |

## V1 重复热跑结果

原始日志：`logs/vector_fast_union_v1_repeat.json`

| SVG | run | 总耗时 | `mesh_total` | `extrude_bottom` | `export_3mf` | `export_glb` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `io_temp_img_1780736845_fcd2a927_vector.svg` | 1 | 8.2709s | 6.7172s | 3.4890s | 1.0624s | 0.1294s |
| `io_temp_img_1780736845_fcd2a927_vector.svg` | 2 | 4.6582s | 3.4099s | 3.2233s | 1.0846s | 0.1226s |
| `6d2945e723b78963fa6b4caa8d937aa2 (1).svg` | 1 | 21.2346s | 18.0013s | 10.3829s | 2.6189s | 0.3267s |
| `6d2945e723b78963fa6b4caa8d937aa2 (1).svg` | 2 | 13.9537s | 10.9802s | 10.3706s | 2.5539s | 0.3266s |

第二张 SVG 的 `extrude_bottom` 从优化前 cProfile 的 18.0126s 降到优化后 repeat run 的约 10.38s，下降约 42.36%。这说明 fast union 的收益确实打在原热点上。

## V2 对比与当前判断

同一份 fast union 后日志中，SVG GLB V2 的表现如下：

| SVG | V1 总耗时 | V1 `mesh_total` | V1 `export_glb` | V2 总耗时 | V2 `mesh_total` | V2 `export_glb` | 判断 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `io_temp_img_1780736845_fcd2a927_vector.svg` | 7.8057s | 6.2462s | 0.1385s | 7.5082s | 3.3596s | 2.9666s | V2 总耗时略快，但 exporter 明显更慢 |
| `6d2945e723b78963fa6b4caa8d937aa2 (1).svg` | 21.2612s | 17.9898s | 0.4019s | 23.4431s | 11.1436s | 9.5978s | V2 总耗时更慢，exporter 成为新热点 |

这解释了为什么当前不应该直接把 SVG GLB V2 默认打开：V2 的 mesh 部分有潜力，但为了保留材料命名、业务 mesh 分组、bounds、单双面和特殊模式语义，exporter 仍有大量工作；在复杂 SVG 上，这部分成本会抵消甚至超过 mesh 端收益。

## 风险与限制

- `disjoint_subset_union_all` 依赖较新的 Shapely。当前实现有自动 fallback，因此兼容旧环境，但旧环境不会获得 fast union 加速。
- fast union 改变的是合并算法，不改变业务规则；但几何 union 顺序变化可能带来极小面积差异，后续 PR 前仍应做代表性 SVG 的视觉和几何 parity 检查。
- 这次 profile 只覆盖两张复杂 SVG。结论足以说明热点和收益，但不能代表所有 SVG 类型。
- SVG GLB V2 仍应保持 opt-in，本地通过 `LUMINA_VECTOR_GLB_KERNEL=v2` 灰度验证，不应默认替换 V1。

## 已验证

已跑过相关单元测试集合，结果为 `201 passed in 3.50s`：

```powershell
python -m pytest tests/test_vector_engine_fixes_unit.py tests/test_vector_engine_unit.py tests/test_vector_glb_v2_kernel_unit.py tests/test_vector_glb_v2_parity_unit.py tests/test_vector_preview_glb_orientation_unit.py tests/test_vector_cover_and_glb_naming_unit.py tests/test_glb_v2_kernel_unit.py tests/test_local_docker_deploy_contract_unit.py -v
```

## 后续建议

1. 在 PR 前对这两张 SVG 做 V1 fast union 前后 GLB/3MF 几何和视觉 parity 检查。
2. 继续 profile `_extrude_geometry`、`extrude_polygon`、`_normalize_contours`，它们是 fast union 之后剩下的主要候选热点。
3. 单独优化 SVG GLB V2 exporter，目标是降低 `export_glb` 中的 per-mesh 分组、命名、合并和序列化成本。
4. SVG GLB V2 默认启用前，必须覆盖单双面、底板、outline、fridge magnet、5 色扩展、拼图模式、钥匙扣等全链路场景。
