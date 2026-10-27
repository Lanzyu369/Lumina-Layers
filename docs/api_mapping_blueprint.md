# API 与前端数据契约

当前接口由 `api/routers/`、`api/schemas/`、`frontend/src/api/` 和对应 store 维护。
以下说明保留需要跨模块一致的行为；字段、类型和范围以实际代码为准。

## 材料求解缓存

持久缓存只由用户显式建缓存操作触发，选择材料不应自动构建完整磁盘缓存。
入口是 `POST /api/extractor/material-solver-cache/build`，对应
[MaterialSolverCacheStatusCard](../frontend/src/components/MaterialSolverCacheStatusCard.tsx)
和 [single_stage 路由](../api/routers/single_stage.py)。没有持久缓存时，预览使用
[material_lut_provider](../core/material_lut_provider.py) 运行时求解，
由 `material_solver_info` 报告实际来源。动态层数使用独立的精确求解路径。

缓存文件、目录、材料身份、有效光学参数及求解设置的匹配规则由
[material_cache.py](../core/material_cache.py) 维护；缓存加载后仍需正确映射配方列。

## LUT 目录

基础设置的两级 LUT 选择器使用 `GET /api/lut/details/catalog` 的厂商分组和
`color_mode`，由 converter store 的 `fetchLegacyCatalog()` 独立获取和缓存。
它不能依赖懒加载的 LUT 详情页 store。

`GET /api/lut/catalog` 负责 legacy/native 来源目录、`lutList`、原生厂商和上传后刷新。
两种目录职责不同，复用 [API 客户端](../frontend/src/api/lut.ts) 和
`LutDetailsCatalogGroup` / `LutDetailsCatalogItem` 类型。

## 校准参数

`POST /api/calibration/generate` 不暴露底板颜色选择；需要底色的路由固定使用白色。
底板厚度默认 1.2 mm、范围 0.4–3.5 mm，UI 步进 0.08 mm。
路由把 `backing_thickness` 作为 `backing_thickness_mm` 传给 core；
省略 core 的该可选参数时仍使用 `PrinterConfig.BACKING_MM`。

参数和颜色模式分别由 [schema](../api/schemas/calibration.py)、
[calibration 路由](../api/routers/calibration.py)、
[store](../frontend/src/stores/calibrationStore.ts) 和
[底板层数解析](../core/calibration.py) 维护。
