# 5-Color 校准板流程翻转逻辑检查与修复计划

经过对 `core/calibration.py`、`core/extractor.py` 和 `core/lut_merger.py` 的详细代码审查，发现 5-Color Extended 模式在生成、提取和合并过程中存在以下翻转逻辑及一致性问题。

## 核心发现

### 1. 颜色仿真翻转逻辑错误 (`core/calibration.py`)

在 `select_extended_1444_colors` 函数中，`simulate_color` 子函数用于预测堆叠颜色的最终效果。

* **现状**：代码直接遍历 `stack`（Top -> Bottom），并将其应用在 `BACKING`（底板）上。

* **问题**：物理上，光线是从观赏面（Top）射入并反射回来的。模拟时应从底层（Bottom）开始向上叠加到顶层（Top）。当前的顺序导致底层颜色被模拟成了最外层颜色。

* **修复**：在 `simulate_color` 中使用 `reversed(stack)` 进行遍历。

<br />

### 2. LUT 合并时的堆叠重构逻辑不一致 (`core/lut_merger.py`)

* **现状**：`lut_merger.py` 中的 Fallback 逻辑（在没有 .npz 文件时手动重构堆叠）对 1444 色使用了简单的线性排列。

* **问题**：生成板时使用的是贪婪选择算法（`select_extended_1444_colors`），其顺序并非简单的线性排列。如果触发 Fallback，会导致索引与堆叠数据错位。

* **修复**：修复该 Fallback 逻辑，确保其与生成时的算法逻辑一致。

### 3. 代码注释歧义 (`core/calibration.py`)

* **现状**：`_generate_5color_base_page` 中注释为 `[bottom...top]`。

* **问题**：代码实际使用的是 `[top...bottom]`（`stack[0]` 对应 `Z=0` 观赏面）。

* **优化**：修正注释，避免后续维护误解。

***

## 实施步骤

### 第一阶段：逻辑修复

1. **修复** **`simulate_color`**：在 `core/calibration.py` 的 `select_extended_1444_colors` 中，修改仿真遍历顺序。
2. **优化 Page 2 角点**：在 `core/calibration.py` 的 `_generate_5color_extended_page` 中，增加角点标记的层数。
3. **修复** **`lut_merger.py`**：更新 `5-Color Extended` 的堆叠重构逻辑。

### 第二阶段：一致性清理

1. **修正注释**：更新 `calibration.py` 中关于 Face-Down 堆叠顺序的注释。

### 第三阶段：验证

1. **运行测试脚本**：编写并运行 `test_5color_extended_quickcheck.py`，模拟生成 1444 色并验证索引 -> RGB -> 堆叠的闭环一致性。
2. **检查合并结果**：手动触发合并流程，对比生成的 `.npz` 文件内容是否符合预期。

***

## 预期结果

* 5-Color 模式下生成的校准板堆叠顺序与 LUT 合并时的堆叠数据完全一致。

* 仿真颜色算法能更准确地指导 1444 色的筛选。

* 校准板在提取过程中具有更好的物理鲁棒性。

