# 模型覆面透明区域开槽修复设计

## 结论

`LUM-20260725-003` 的问题不是透明通道渲染错误，而是开槽范围错误：
当前装配阶段按整个选中表面开槽，图案阶段却只为实际有材料的区域生成
几何。透明区域没有图案回填，因此会露出下沉后的基板，让非透明图案看起来
整体凸起。

修复后，图案生成阶段必须同时产出两项不可分割的数据：

1. 可导出的多材料 `trimesh.Scene`。
2. 与该场景完全对应的二维 `printable_footprint`。

装配阶段只允许按 `printable_footprint` 开槽。透明像素、透明 SVG 区域、
全 Air 配方和无效材料槽均不属于可打印覆盖范围，不得改变原模型表面。

## 根因与可观察现象

当前 `build_embedded_overlay_scene()` 调用 `cut_surface_pocket()`，后者直接使用
`SurfaceFootprint.outer` 和 `SurfaceFootprint.holes` 构造切割体。这等同于把
整个选中平面下挖。

栅格和原生 SVG 图案只为实际材料生成网格：

- 栅格透明区域在体素矩阵中为 `-1`。
- SVG 透明区域没有匹配形状。
- JPG 没有透明通道，整个画布通常都会被材料填充，因此整面开槽被图案完全
  回填，缺陷不明显。

用户提供的真实 SVG 约有三成透明画布。原实现导出的基板表面整体下降约
`图案厚度 + 布尔容差`，与反馈截图中的“凸起”一致。

## 领域模型

新增内部强类型中间产物 `PreparedSurfacePattern`：

```python
@dataclass(frozen=True)
class PreparedSurfacePattern:
    scene: trimesh.Scene
    printable_footprint: BaseGeometry
```

它表达一个必须始终成立的不变量：`scene` 中任何可打印 XY 区域都包含在
`printable_footprint` 中，`printable_footprint` 中不存在无材料区域。

不把轮廓藏入 `Scene.metadata`，因为 metadata 没有类型约束，也容易在场景
复制、序列化或重构时静默丢失。现有直接传入 `trimesh.Scene` 的装配调用保留
兼容适配，继续使用历史上的完整逻辑画布轮廓；正式转换管线改为只传入
`PreparedSurfacePattern`。

## 可打印轮廓来源

### 栅格与 PNG

从最终展示体素栈计算覆盖掩码，而不是重新读取源图 Alpha：

```text
valid = 0 <= material_id < len(slot_names)
printable_mask = any(valid, axis=Z)
```

这样配方覆盖、Air 层和材料槽校验都与最终网格保持一致。二维掩码使用与
槽位网格相同的像素边界和 Y 轴翻转规则，合并成精确的 Shapely 多边形，再
乘以 `pixel_scale`。不使用像素中心轮廓，避免一像素细线退化。

### 原生 SVG

从已经完成遮挡裁剪、颜色匹配、配方覆盖、轮廓归一化和坐标修正的最终矢量
材料网格提取向上的水平端面，把端面三角形投影到 XY 后求并集。

这里不直接使用原始 SVG Alpha、外层 silhouette 或尚未挤出的
`VectorAnalysis.matched_shapes`。矢量引擎会在同材料、同层段合并时做细小的
轮廓归一化；只有最终网格投影才与实际导出的可打印几何严格一致。使用
Shapely 2 的向量化三角形构造和 `union_all`，避免逐三角 Python 布尔循环。

## 装配与开槽

装配阶段使用同一逻辑画布变换将 `printable_footprint` 映射到选中表面的
二维局部坐标：

```text
surface_x = bounds_min_x + (pattern_x - logical_min_x) * scale_x
surface_y = bounds_min_y + (pattern_y - logical_min_y) * scale_y
```

映射结果必须与 `SurfaceFootprint` 多边形求交：

- 外轮廓之外不允许开槽。
- 原模型孔洞保持孔洞。
- contain 留白和旋转后产生的透明区域保持原始高度。

随后复用现有 Manifold 布尔差集，只把切割多边形从“整个表面”替换为
“实际可打印覆盖区域”。图案的三维放置变换不变，外表面仍与原模型齐平。

现有 `cut_surface_pocket()` 保留完整表面开槽语义和函数签名，避免破坏其他
调用；新增按图案轮廓开槽的路径供覆面装配使用，两者复用同一个底层布尔
实现。

## 错误与兼容策略

- 可打印轮廓为空时，返回现有领域错误，不导出只有基板的结果。
- 轮廓无效时先做几何修复；修复后仍为空则确定性失败。
- 全不透明图案的轮廓等于完整逻辑画布，结果与当前正确场景一致。
- `allow_uncut_base=True` 继续跳过布尔开槽，主要供已有测试和明确的内部
  调试路径使用。
- 不修改 API 请求结构、持久化设置、前端文案或分享卡协议，因为修复只改变
  已有参数下的错误几何结果。

## 验证标准

自动回归必须验证：

1. 带透明留白的 PNG/栅格图案只在有材料区域开槽。
2. 稀疏 SVG 只在合法配方形状下方开槽。
3. 透明位置的基板顶面仍处于原始 Z，高度和外部包围盒不变。
4. 图案位置的槽深等于逻辑显示栈深度，图案顶面与原模型表面齐平。
5. 孔洞、全不透明画布、朝上/朝下和已有材料层顺序测试不回归。

真人式验收必须使用用户提供的 `vectorized.svg`、`MSkadis_160.stl` 和四色
LUT 走实际覆面生成链路。导出的 3MF 要再次解析，确认透明区域仍存在原始
顶面、开槽面积不再等于整个选中表面，并检查所有材料对象与总体尺寸。复杂
SVG 的切割棱柱必须由 Manifold 截面生成闭合实体，避免近重合边界点让
Earcut 端面出现非流形重边。
