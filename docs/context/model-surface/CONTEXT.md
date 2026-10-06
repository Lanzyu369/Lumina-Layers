# 模型覆面：坐标与操作状态

模型覆面的方向和开槽问题不能分别靠旋转图片、修补网格来处理。
选面、摆图、观察和生成必须沿用同一份表面坐标；模型姿态必须由同一份状态驱动。
本次修复针对工单中底面观察反向、视图重建丢失姿态和细小孔洞开槽失败三条真实路径。

## 坐标的归属

| 数据 | 唯一含义与负责位置 | 下游约定 |
| --- | --- | --- |
| 表面 frame | `core/model_surface/footprint.py` 根据所选面生成 origin、normal、U、V，满足 U × V = normal | U 向二维图右侧，V 向上；不按世界坐标的正负再次翻转 |
| 图案摆放 | `core/model_surface/artwork.py` 和前端 `modelSurface/artworkPlacement.ts` | 位移用局部毫米；图片向下的 Y 与表面向上的 V 只在图片边界转换 |
| 原图与已摆好的预览 | `modelSurface/artworkAsset.ts` 区分 source-image 和 surface-preview | 后者已包含旋转、缩放、位移和遮罩，不能重复应用摆放 |
| 模型旋转 | converter store 的 `modelSurfaceModelRotation`，单位为度 | Scene3D 把它传给 selector；预览与生成发送相同值，selector 不另存一份产品姿态 |
| 可打印轮廓 | `PreparedSurfacePattern.printable_footprint` | 来自实际生成的颜色网格或体素；扣除 Air，保留清理结果和小孔；不能用原图外接矩形替代 |
| 开槽 | `core/model_surface/assembly.py` | 将上述轮廓挤出为原生实体，按 frame 放到模型表面，一次相减后再导出网格 |
| 打印朝向 | `core/model_surface/pipeline.py` | 先对整个装配应用用户模型旋转，再对整个装配调整打印朝向，不能只转图案 |
| 材料与几何对象 | pipeline 沿用 `resolve_material_preview`；`OverlaySceneResult.project_slot_names` 保留所选材料顺序 | `surface_base` 是对象名；用 `bambu_material_name` 绑定底色材料，不能额外生成一个默认 PLA 槽 |

## 选面与恢复是不同操作

| 操作 | 模型姿态 | 相机 |
| --- | --- | --- |
| 新选择一个平面 | 仅做一次最小旋转，使所选面朝上；写入 store | 等待该姿态生效，再从表面正侧聚焦一次，以旋转后的 V 为屏幕向上 |
| 重建已有选择的视图 | 直接读取 store，不能再次翻面或写回零值 | 模型加载后恢复表面检查视角，包括 V 方向 |
| 手动旋转模型 | 通过原有回调更新 store | 不因姿态更新反复自动聚焦 |
| 普通视图导航 | 不修改模型姿态 | 沿用视图导航规则，允许自由观察 |
| 清除选择、上传新模型 | 上传流程按原约定重置选择和姿态 | 默认加载视图恢复原相机向上方向和视角大小 |
| 退出模型覆面 | store 保留已有选择和姿态 | 释放共享相机的表面方向和检查视角大小，普通预览不继承它们 |

新选择由稳定的 `selectionId` 识别；组件首次挂载已有受控选择属于恢复。
等待相机聚焦的记录只描述本次选面操作，不是对后续用户旋转的持续约束。
二维与三维方向一致指表面检查视角；用户自由旋转后的透视变化是正常观察结果。

## 为什么之前的修复没有覆盖这次问题

[PR #605](https://github.com/lumina-layer-studio/Lumina-studio/pull/605)
修复的是原图到表面预览的重复摆放、图片方向符号和宽高比。本次保留这些修正。
这次的 180 度差异发生在模型自动翻面后的相机方向：表面 V 已随模型旋转，
旧代码却按世界 Y 的正负再次翻转相机向上方向，而且自动翻面后还跳过聚焦。
只替换相机方向函数会漏掉第一次选面和重新进入页面的路径。

生成失败是另一条路径。用户模型是合法封闭实体，原生开槽实体也报告成功；
但旧流程先把开槽实体导成普通三角网格，再检查体积并重新导入几何引擎。
在细小孔洞和重合点处，中间网格可能出现退化三角形或拓扑合并，检查会提前拒绝它。
单纯删掉体积检查仍会遇到普通网格布尔适配器的相同要求。

现在基础模型只转换一次，开槽实体一直留在 Manifold 中完成变换与相减，
最终结果用双精度网格导出。保留有效的输入模型校验、厚度判断和原生运算错误；
没有增加重试、填洞、缩小图案或重复网格体积拦截。内部计算失败的通用提示也不再要求用户修复模型。

真实 3MF 验证还发现底模材料身份没有沿用用户选择：四种 PETG 加上底模变成五种材料，
底模按模板默认 PLA 导出。现在清空转换上下文前保存精确材料身份和完整所选调色板；
显式底色索引优先，否则沿用已解析的 `material_base_channel_idx`，不假设底色为第 0 项。
几何对象仍有五个，底模与对应色层共享同一个材料槽。材料档案模式同时沿用普通导出的
`preserve_template_filament_slots=False`，设备模板多余的耗材槽不会被带入成品。

## 回归入口

| 行为 | 测试 |
| --- | --- |
| 顶面、底面、四个侧面和倾斜面，在四种初始水平角度下 U 向右、V 向上 | `frontend/src/__tests__/ModelSurfaceSelector3D.test.tsx` |
| 新选底面前相机在模型背侧，选面后仍从正侧显示 | 同上 |
| 已有非零姿态重挂载，不写回、不再次翻面，并恢复相机方向 | 同上 |
| 受控新选择只写回一次，后续手动旋转不触发相机聚焦 | 同上 |
| 直接更换文件、退出覆面后释放相机方向与检查视角 | 同上 |
| store 姿态和选择身份接入 3D 组件 | `frontend/src/__tests__/Scene3D.test.tsx` |
| 摆放变化使旧预览失效，迟到响应不能覆盖新状态；原图与已摆好预览不重复转换 | `frontend/src/stores/__tests__/modelSurfaceStore.test.ts`、`frontend/src/components/modelSurface/artworkAsset.test.ts` |
| 五个微小孔洞、几乎重合的边界点、内部反向空腔，切后封闭、体积正确、材料身份保留 | `tests/test_model_surface_boolean_unit.py` |
| 实际打印轮廓、透明余白、嵌入厚度、整套装配旋转、3MF 接触壳体和多材料 | `tests/test_model_surface_assembly_unit.py` |
| 显式底色为第 0 或第 3 项、默认底色为第 2 项、未使用的所选材料仍保留、底模共享材料槽 | 同上；生成 worker 测试同时覆盖设备配置与模板槽裁剪参数转发 |
| 上传、缓存选择、预览和生成请求、错误与资源生命周期 | 其他 `tests/test_model_surface*` |

非 watch 前端测试必须从根目录调用 `python scripts/run_vitest.py run ...`。
后端运行 `python -m pytest tests/test_model_surface* -q`。
涉及本工作流的后续改动，应按上述行为选择回归场景；不能只验证单个变换函数或“未抛异常”。

## 本次验证记录

验证以执行结果为准。本地私人源文件、材料档案和生成文件保存在 `.scratch/model-surface-d9c61a20/`，不提交用户模型或图案。
材料使用工单同名的本地档案快照，无法证明与用户当时档案逐字节相同。
自动化和真实生成结果汇总在本目录的 `TEST_REPORT.md`。
