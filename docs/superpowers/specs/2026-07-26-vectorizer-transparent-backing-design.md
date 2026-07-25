# 图像转矢量透明底板修复设计

## 结论

图像转矢量生成的 SVG 同时包含两类边界：

- `analysis.silhouette`：由最终可见、已裁剪的 SVG 色块合并得到，是可以打印的物理轮廓。
- `analysis.image_vectorizer_bounds`：由带
  `data-lumina-origin="image-vectorizer"` 标记的 SVG `viewBox` 得到，是原图完整画布的坐标范围。

当前代码把第二类边界覆盖到第一类边界上，导致透明 PNG 的完整矩形画布被挤出成
`Board` 和 `Coating`。修复采用“物理几何与坐标锚点分离”的方案：底板、涂层和
2D 底板掩膜只使用可见轮廓；完整画布只作为不可见的 3D 预览坐标锚点。

该问题与外置 C++ 图像矢量化库升级无关。对用户提供的 160×160 异形 PNG，
0.1.1 与 0.2.0 的可见像素结果一致；错误发生在 SVG 进入 Lumina 后的 mesh
构建阶段。

## 问题链路

1. 图像矢量化服务保留原图 `viewBox`，并给 SVG 写入 Lumina 来源标记。
2. SVG 解析器正确记录完整画布到 `image_vectorizer_bounds`，同时正确生成可见
   `silhouette`。
3. `VectorProcessor.build_mesh()` 用完整画布替换可见轮廓。
4. 替换后的矩形继续进入底板和透明涂层挤出，并最终写入 3MF。
5. 2D 预览缓存也优先栅格化完整画布，因此预览与错误 3MF 保持了错误的一致性。

完整画布最初用于解决拼图叠线坐标缩小问题，但把它做成实体底板混合了两个职责。
仓库的位图 GLB 路径已经使用独立的透明 `preview_canvas_bounds` 节点解决同类坐标
问题，矢量路径应复用同一契约。

## 设计

### 1. 物理底板和涂层

`build_mesh()` 的物理轮廓来源固定为：

1. 非空的 `analysis.silhouette`；
2. 若缺失，则合并非空的 `analysis.clipped_shapes[*].geometry`；
3. 两者都缺失时不生成底板。

`image_vectorizer_bounds` 不再参与 `Board`、`Coating`、冰箱贴底板凹槽或其他
实体几何推断。现有轮廓闭合、孔洞过滤和 0.15 mm 外扩保持不变。

### 2. 2D 预览

`build_preview_cache()` 使用与 3MF 相同的可见轮廓优先级生成 `backing_mask`。
透明画布区域继续保持 Air，不进入材料矩阵。

### 3. 3D 预览与拼图坐标

矢量 GLB 导出器读取 `image_vectorizer_bounds` 和 `analysis.scale_factor`，生成一个
完整画布大小、完全透明的平面，名称固定为 `preview_canvas_bounds`。

该节点：

- 不属于底板或颜色材料；
- 不计入前端可见模型 bounds；
- 只向 `PuzzleOverlay3D` 提供完整画布的 XY 坐标；
- 同时加入 V1 和 V2 scene-reuse GLB 导出路径；
- 在没有合法 `image_vectorizer_bounds` 时不生成，普通 SVG 行为不变。

分析描述型 V2 辅助路径也改为使用可见轮廓生成 backing footprint，避免未来重新
启用该路径时恢复矩形底板。

## 兼容与非目标

- 不修改外置 C++ 矢量库版本或输出算法。
- 不裁剪 SVG `viewBox`，因此原图定位和拼图纹理坐标保持不变。
- 不修改公开 API、缓存字段或分享卡配方。
- 不改变普通原生 SVG、位图高保真、材料档案和 LUT 的参数语义。
- 不把透明锚点写入 3MF；它只存在于前端 GLB 预览。

## 验证

自动化回归必须证明：

1. 带图像矢量化标记的 SVG 仍记录完整 viewport bounds。
2. 同一分析对象生成的 `Board` 和 `Coating` 只覆盖可见轮廓，不连接透明间隙。
3. 2D `backing_mask` 不填充透明画布。
4. 描述型 V2 backing footprint 使用可见轮廓。
5. V1 和默认 V2 GLB 都包含完整画布大小的透明
   `preview_canvas_bounds`，同时 `backing_plate` 保持异形。
6. 普通 SVG 和缺失 viewport metadata 的回退行为不变。

真人流程使用用户提供的
`/Users/min/Downloads/Totem_of_Undying_JE2_BE2.png`，在本地前后端完成上传、
图像转矢量、材料选择、3D 预览、生成和下载。最终重新读取 GLB 与 3MF，确认：

- 没有 60.112×60.112 mm 的完整矩形实体底板；
- 底板 XY footprint 与可见图案轮廓一致；
- GLB 仍有约 60×60 mm 的透明画布锚点；
- 拼图叠线使用完整画布坐标；
- 下载链接在源会话仍有效的正常真人流程中可获取。
