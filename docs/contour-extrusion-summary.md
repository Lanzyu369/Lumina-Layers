# 轮廓拉伸算法探索总结

> S11 GLB 预览 + HighFidelityMesher 的多边形挤出算法
> 目标：将 O(像素数) 面数降为 O(轮廓顶点数)

---

## 1. 原始方案：逐像素体素网格

每个像素一个 1×1×layer_height 的体素盒子，merge 后做 unique_faces。

- **优点**：正确、无间隙、无重叠
- **缺点**：面数 = O(像素数)，1000×1000 图 = 100 万面，性能差
- **状态**：基准

---

## 2. 方向一：标签图 + findContours（一次调用）

用 `matched_rgb` 构建 `uint8` 标签图（值为 1,2,3…），一次 `findContours` 获取所有颜色轮廓。

**遇到的问题**：`cv2.findContours` 不支持多标签图。所有非零值被视为前景，无论 RETR_EXTERNAL / RETR_CCOMP / RETR_LIST / RETR_TREE，均只返回 1 个轮廓。

- **状态**：放弃

---

## 3. 方向二：逐颜色 findContours + 顶点扩展

每个颜色单独建二值掩码 → `findContours(RETR_EXTERNAL)` → 顶点扩展到像素边界 → Shapely Polygon → `trimesh.extrude_polygon`。

### 3.1 像素中心坐标问题

`cv2.findContours` 返回像素中心坐标，相邻色块间有 1px 间隙。

### 3.2 顶点扩展（Vertex Expansion）

沿角平分线向外平移 0.5 单位，将像素中心扩展到像素边界。

公式（OpenCV CCW 轮廓，y-down 坐标系）：
```
外法向：n = (-dy, dx) / |e|
角平分线：b = n1 + n2
扩展距离：d = 0.5 / cos_half
```

### 遇到的问题

**外法向公式错误**：初次实现用了错误公式导致轮廓向内收缩（矩形面积 12 而非 20）。后确认 OpenCV 返回 CCW 轮廓（有符号面积=-12）后修正。

**2x 上采样失败**：CHAIN_APPROX_NONE 仍留间隙，L 形面积损失严重（51.75 vs 64）。更高倍数改善但无法精确匹配。

**当前实现仍有严重问题**：
1. **45 度斜角**：顶点扩展沿角平分线，产生斜边而非直角台阶
2. **Z-fighting 闪烁**：相邻色块斜边重叠，且所有面顶面共面
3. **0.83% 凹角重叠**：角平分线指向内部时反而收缩（已知，可接受）

- **状态**：已放弃

---

## 4. 方向三：Shapely buffer(0.5)

数学上等价于顶点扩展，同样有斜角和凹角问题。

- **状态**：放弃

---

## 5. 方向四：扫描线矩形条

按行扫描每个颜色的二值掩码，生成 AABB 矩形条后合并。

**优点**：边界与像素对齐、无间隙、无重叠
**缺点**：矩形数量可能仍接近 O(像素数)

- **状态**：理论可行但未实现

---

## 6. 核心问题根因

```
findContours 返回轮廓 → 顶点是像素中心
→ 必须扩展才能消除间隙
→ 扩展沿角平分线 → 45度斜角而非直角台阶
→ 相邻色块斜角方向不一致 → 重叠 + Z-fighting
```

---

## 7. 方向五：scipy.ndimage.label + 边界追踪

`label` 分解连通域 + 纯 Python 边界追踪 → Polygon → 拉伸。

- **问题**：纯 Python 逐像素追踪太慢（百万次循环），且边界追踪算法复杂易错
- **状态**：已放弃

---

## 8. 最终方案（已实现）：纯 numpy 逐像素体素 + np.unique 去重

不依赖 findContours、Shapely 或任何几何库，直接用 numpy 生成顶点和面。

```
对每个颜色 C：
  1. 取所有 solid 像素坐标 (xs, ys)
  2. 对每个 z 层，生成 6 类可见面元：
     TOP:    z = z+1，上方是空气
     BOTTOM: z = z，  仅 z==0 时可见
     LEFT:   x = x，  左边是背景
     RIGHT:  x = x+1，右边是背景
     FRONT:  y = y，  上方是背景（图像上方）
     NEAR:   y = y+1，下方是背景（观赏面方向）
  3. 每个面元 → 4 个角点顶点 + 2 个三角形
  4. np.unique 去重（消除共享面）
  5. 构建 Trimesh
```

**去重原理**：相邻像素共享的面被生成两次（如像素 A 的右面 = 像素 B 的左面），`np.unique` 自动消除。

**Z-fighting 消除**：
- 相邻颜色 top face → micro offset `idx * 0.001 * LH`
- backing plate 顶面在 z=0.001*LH（略高于 z=0）
- color mesh 不生成 bottom face（由 backing plate 提供底面）

**分辨率控制**：30K 像素上限（≈173×173），面数 ≈ 12 万，毫秒级生成。

**优势**：
- 完全矢量化的 numpy 操作，无 Python 逐像素循环
- 无几何歧义：逐像素保证正确性
- np.unique 去重自动消除共享面
- Z-fighting 通过 micro offset 彻底消除
- 分辨率降至 30K，生成速度极快

**代价**：
- 面数 = O(像素数 × 可见面比例)，最坏 O(面积)
- 但 30K 像素上限，面数可控

---

## 9. 下一步行动

- [x] Phase 1（S11 GLB）：纯 numpy 逐像素 + np.unique 去重
- [ ] 测试确认无间隙、无重叠、无闪烁
- [ ] Phase 2（HighFidelityMesher）：同方案（可复用面元生成逻辑）
- [ ] 对比性能与原始逐像素方案
