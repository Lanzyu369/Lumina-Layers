# 5color 模式校准板流程检查计划

## 目标

检查 `5color` 模式下两个校准板的生成、提取及 LUT 合并流程，重点排查翻转逻辑（Flip/Rotation）是否存在不一致或错误。

## 分析步骤

1. **代码定位与理解**

   * [x] 搜索并定位 `5color` 相关的核心逻辑文件。

   * [x] 找到校准板生成（Generation）的代码：`core/calibration.py`

   * [x] 找到校准板提取（Extraction）的代码：`core/extractor.py`

   * [x] 找到 LUT 合并（Merge）的代码：`core/lut_merger.py`

2. **详细逻辑审查（基于最新代码）**

   * [x] **生成阶段 (`core/calibration.py`)**

     * **Page 1**: Face-Down (Z=0 观赏面)。

     * **Page 2**: **已更新为 Face-Down** (Z=0 观赏面)。

     * 结论：生成的 Stack 数据在逻辑上统一为 `stack[0]=观赏面`。

   * [x] **提取阶段 (`core/extractor.py`)**

     * **新发现的问题**：Page 2 的角点颜色已变更为 TL=Blue, TR=Red, BR=Black, BL=Yellow，但 `extractor.py` 中缺乏对应的提示逻辑，仍会提示默认的 White/Red/Blue/Yellow，可能导致用户无法正确识别方向。

   * [x] **合并阶段 (`core/lut_merger.py`)**

     * **问题 1 (L266)**: 加载 `.npz` 时，代码错误地对 `stacks` 进行了 `reversed` 翻转。由于生成端已经是 `stack[0]=观赏面`，这一翻转会导致合并后的数据变成 `stack[0]=背面`，**必须移除**。

     * **问题 2 (L292)**: Fallback 逻辑中，Page 2 的 stack 构建顺序错误。`(tuple(reversed(digits)) + (layer6,))` 把观赏面 `layer6` 放在了末尾。在 Face-Down 模式下（以及统一约定下），观赏面应在 `stack[0]`。**必须修正为** **`(layer6,) + ...`**。

3. **问题影响分析**

   * **颜色层序颠倒**：Stack 顺序反转意味着“观赏面”与“背面/底层”互换。

   * **打印结果错误**：打印出的颜色将完全错误。

   * **提取困难**：Page 2 角点提示不匹配可能导致用户旋转错误，进而导致提取数据错位。

4. **修复方案**

   * [ ] **修复** **`core/lut_merger.py`**:

     * L266: 去除 `reversed` 操作。

     * L292: 修正 Page 2 Fallback 的 stack 构建顺序，将 `layer6` 移至 tuple 开头。

   * [ ] **(可选) 修复** **`core/extractor.py`**:

     * 更新 `draw_corner_points`，增加对 5-Color Page 2 特定角点颜色的支持。

5. **验证**

   * 修复后，5-Color Extended 的合并行为将与其他模式保持一致，且提取过程引导正确。

