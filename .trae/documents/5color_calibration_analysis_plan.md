# 5-Color 模式校准板问题分析计划

## 分析目标
仔细检查5color模式的两个校准板（Page 1: 1024色基础版 和 Page 2: 1444色扩展版），从生成校准板到提取校准板再到合并LUT的整套流程中是否存在问题，特别是：
1. 设计生成过程中的翻转逻辑问题
2. 合并LUT过程中的翻转逻辑问题

---

## 1. 代码结构分析

### 1.1 5-Color Extended 校准板生成函数
- **文件**: `core/calibration.py`
- **函数**: 
  - `generate_5color_extended_board()` - 主入口函数
  - `_generate_5color_base_page()` - Page 1 (1024色基础版)
  - `_generate_5color_extended_page()` - Page 2 (1444色扩展版)
  - `select_extended_1444_colors()` - 扩展颜色选择算法
  - `merge_5color_extended()` - LUT合并函数

### 1.2 LUT合并相关
- **文件**: `core/lut_merger.py`
- **函数**:
  - `LUTMerger.load_lut_with_stacks()` - 加载LUT并重建堆叠
  - `_remap_stacks()` - 材料ID重映射

### 1.3 图像处理
- **文件**: `core/image_processing.py`
- **函数**:
  - `LuminaImageProcessor._load_lut()` - 加载LUT并重建堆叠

---

## 2. 发现的问题

### 问题1: Page 1 (基础版) 堆叠顺序不一致

**位置**: `core/calibration.py` 第1150-1168行

**问题描述**:
在 `_generate_5color_base_page()` 函数中：
```python
# 生成1024 base stacks (4^5 combinations of RYBW)
# Face-Down mode: Z=0 is viewing surface (top), Z=4 is bottom
for i in range(1024):
    digits = []
    temp = i
    for _ in range(5):
        digits.append(temp % 4)
        temp //= 4
    stack = digits[::-1]  # [bottom...top] for Face-Down mode  <-- 注释说bottom...top
    
    # ...
    
    # Fill 5 color layers (Face-Down mode: Z=0 is viewing surface)
    for z in range(color_layers):
        mat_id = stack[z]  # <-- 但这里直接用了stack[z]，如果stack是bottom...top，那么stack[0]是bottom
        if mat_id < 4:
            full_matrix[z, py:py+pixels_per_block, px:px+pixels_block] = mat_id
```

**矛盾点**:
- 注释说 `stack = digits[::-1]` 是 `[bottom...top]` for Face-Down mode
- 但后续使用 `stack[z]` 直接映射到 `full_matrix[z]`，如果stack[0]是bottom，那么Z=0(第一层打印)应该是bottom，但注释又说Z=0是viewing surface

**对比标准4色模式** (`generate_calibration_board` 第121-135行):
```python
for i in range(1024):
    digits = []
    temp = i
    for _ in range(5):
        digits.append(temp % 4)
        temp //= 4
    stack = digits[::-1]  # [顶...底] format
    
    # ...
    
    for z in range(PrinterConfig.COLOR_LAYERS):
        full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = stack[z]
```

标准4色模式的注释明确说是 `[顶...底]` format，且Z=0对应stack[0](顶/观赏面)。

### 问题2: Page 2 (扩展版) 堆叠顺序反转逻辑

**位置**: `core/calibration.py` 第1268-1272行

**问题描述**:
```python
# Map stack to physical layers
for z in range(6):
    mat_id = stack[5 - z]  # Reverse for physical stacking
    if mat_id < 5:
        full_matrix[backing_layers + z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
```

这里明确使用了 `stack[5 - z]` 进行反转，但我们需要确认 `stack` 的约定方向。

**查看 `select_extended_1444_colors()`** (第731-748行):
```python
for base_stack in base_1024_stacks:
    for layer6 in [1, 2, 3]:  # R, Y, B (viewing surface, outermost layer)
        # stack format: [top...bottom] where top is viewing surface
        # layer6 should be at index 0 (viewing surface), base_stack follows
        stack = (layer6,) + tuple(base_stack)
```

这里明确说明 `stack format: [top...bottom]`，layer6在index 0(观赏面)。

**问题**: 如果stack已经是[top...bottom]，那么在 `_generate_5color_extended_page()` 中使用 `stack[5 - z]` 反转后：
- z=0 (物理第一层) -> stack[5] (bottom)
- z=5 (物理第六层) -> stack[0] (top/观赏面)

但 `full_matrix[backing_layers + z]` 中，z=0对应的是backing层之上的第一层，如果Face-Up模式，这应该是观赏面。

### 问题3: LUT合并时的堆叠方向

**位置**: `core/calibration.py` 第1050-1067行 `merge_5color_extended()`

```python
# Generate stacks
# Base 1024: 5-layer stacks (pad to 6 layers with White)
base_stacks = []
for i in range(len(base_rgb)):
    digits = []
    temp = i
    for _ in range(5):
        digits.append(temp % 4)
        temp //= 4
    stack = tuple(reversed(digits)) + (0,)  # Pad with White
    base_stacks.append(stack)

# Extended 1444: 6-layer stacks
base_5layer = [tuple(reversed([i//4**j%4 for j in range(5)])) for i in range(1024)]
extended_stacks = select_extended_1444_colors(base_5layer)
```

**问题**:
- `tuple(reversed(digits))` - digits是[底, ..., 顶]（因为digits.append(temp % 4)先取最低位），reversed后变成[顶, ..., 底]
- 但 `base_5layer` 也使用了 `tuple(reversed(...))`，这与 `select_extended_1444_colors()` 期望的输入一致吗？

查看 `select_extended_1444_colors()` 第731行:
```python
stack = (layer6,) + tuple(base_stack)
# stack format: [top...bottom] where top is viewing surface
```

它期望 `base_stack` 是 `[top...bottom]` 格式，然后 layer6 加到前面形成新的 `[top...bottom]`。

但 `base_5layer` 的生成:
```python
base_5layer = [tuple(reversed([i//4**j%4 for j in range(5)])) for i in range(1024)]
```

这里 `[i//4**j%4 for j in range(5)]` 生成的是 [第0层, 第1层, ..., 第4层] 其中第0层是最低位（底），第4层是最高位（顶）。
然后 `reversed()` 变成 [顶, ..., 底]。

这与 `select_extended_1444_colors()` 的期望一致。

### 问题4: LUTMerger中的5-Color Extended处理

**位置**: `core/lut_merger.py` 第257-295行

```python
elif color_mode == "5-Color Extended":
    # 5-Color Extended: 2468 colors (1024 base + 1444 extended)
    # Load from .npz file with 6-layer stacks
    if lut_path.endswith('.npz'):
        data = np.load(lut_path)
        stacks = data['stacks']
        # Ensure 6-layer stacks
        if stacks.shape[1] == 6:
            # 约定转换：底到顶 → 顶到底
            stacks = np.array([tuple(reversed(s)) for s in stacks])
            return (rgb, _remap_stacks(stacks, color_mode, lut_path))
```

**问题**: 这里假设 `.npz` 文件中的 stacks 是 "底到顶" 约定，然后进行反转。

但查看 `merge_5color_extended()` 第1078行:
```python
np.savez(output_path, rgb=rgb_array, stacks=stacks_array)
```

它直接保存了 `stacks_array`，没有说明是哪种约定。

而 `stacks_array` 的来源 (第1072行):
```python
stacks_array = np.array(merged_stacks, dtype=np.int32)
```

`merged_stacks` 是 `base_stacks + extended_stacks`:
- `base_stacks`: `tuple(reversed(digits)) + (0,)` = [顶, ..., 底] + (0,) = [顶, ..., 底, 0]
- `extended_stacks`: 来自 `select_extended_1444_colors()`，明确是 [顶, ..., 底] 格式

所以 `stacks_array` 应该是 [顶, ..., 底] 格式，但 `LUTMerger` 却假设它是 [底, ..., 顶] 并进行反转！

### 问题5: image_processing.py中的5-Color Extended处理

**位置**: `core/image_processing.py` 第272-318行

```python
# For .npz files, load stacks directly
if lut_path.endswith('.npz'):
    try:
        data = np.load(lut_path)
        stacks = data['stacks']
        # Ensure 6-layer stacks and convert to top-to-bottom convention
        if stacks.shape[1] == 6:
            self.ref_stacks = np.array([tuple(reversed(s)) for s in stacks])
```

**同样的问题**: 假设 `.npz` 中的 stacks 是底到顶，然后进行反转。

但 `merge_5color_extended()` 保存的是 [顶, ..., 底] 格式！

---

## 3. 问题总结

### 关键问题: 约定不一致

| 函数/文件 | 约定 | 问题 |
|-----------|------|------|
| `generate_calibration_board()` (4色标准) | stack[0]=顶(观赏面) | 参考标准 |
| `_generate_5color_base_page()` | 声称[bottom...top]，但用法与4色相同 | **矛盾** |
| `_generate_5color_extended_page()` | 使用 `stack[5-z]` 反转 | 需要确认输入约定 |
| `select_extended_1444_colors()` | stack[0]=顶(观赏面) | 明确说明 |
| `merge_5color_extended()` | [顶...底] | 生成正确 |
| `LUTMerger.load_lut_with_stacks()` | 假设.npz是[底...顶]，然后反转 | **错误假设** |
| `LuminaImageProcessor._load_lut()` | 假设.npz是[底...顶]，然后反转 | **错误假设** |

### 具体问题

1. **LUTMerger 和 ImageProcessor 错误地假设 .npz 文件是 [底...顶] 格式**，但实际上 `merge_5color_extended()` 保存的是 [顶...底] 格式。这导致加载时会多反转一次，使堆叠顺序完全颠倒。

2. **Page 1 (基础版) 的注释与代码不一致**，注释说 `[bottom...top]`，但代码用法与4色模式（`[顶...底]`）相同。

3. **Page 2 (扩展版) 的反转逻辑需要验证**，`stack[5-z]` 的反转是否正确取决于 `stack` 的输入约定。

---

## 4. 修复建议

### 修复1: 统一约定声明
在 `merge_5color_extended()` 中添加明确注释:
```python
# stacks_array 格式: [顶(观赏面), ..., 底]
# stack[0] = 观赏面 (第一层打印在Face-Down模式下)
# stack[5] = 最底层 (最后一层打印)
```

### 修复2: 修正 LUTMerger 的假设
`core/lut_merger.py` 第265-267行:
```python
if stacks.shape[1] == 6:
    # stacks 已经是 [顶...底] 格式，无需反转
    # 移除: stacks = np.array([tuple(reversed(s)) for s in stacks])
    return (rgb[:min_len], _remap_stacks(stacks, color_mode, lut_path))
```

### 修复3: 修正 ImageProcessor 的假设
`core/image_processing.py` 第280-284行:
```python
if stacks.shape[1] == 6:
    # stacks 已经是 [顶...底] 格式，无需反转
    # 移除: self.ref_stacks = np.array([tuple(reversed(s)) for s in stacks])
    self.ref_stacks = stacks
    self.lut_rgb = measured_colors
```

### 修复4: 修正 fallback 堆叠生成
`core/image_processing.py` 第302-303行:
```python
# 5-layer stack in [top...bottom] format, pad with White(0) for layer 6
stack = tuple(reversed(digits)) + (0,)
```
这里 `reversed(digits)` 是正确的，因为 digits 是 [底, ..., 顶]。

### 修复5: 验证 Page 2 的反转逻辑
需要确认 `_generate_5color_extended_page()` 中的 `stack[5-z]` 是否正确:
- 如果 `stack` 是 [顶, ..., 底] (index 0=顶, index 5=底)
- 且 Face-Up 模式下 Z=0 是底层（白色支撑），Z=5 是观赏面
- 那么:
  - Z=0 (底层) 应该放 stack[5] (底)
  - Z=5 (观赏面) 应该放 stack[0] (顶)
  - 所以 `mat_id = stack[5 - z]` 是正确的

---

## 5. 验证计划

### 5.1 生成测试校准板
生成5-Color Extended的两个页面，检查:
1. 角标颜色是否正确（Page 1: TR=Red, Page 2: TR=Black）
2. 第一层(Z=0)的材料分布是否符合预期

### 5.2 提取测试
使用模拟图像提取LUT，验证:
1. 提取的RGB值与预期是否一致
2. 重建的堆叠顺序是否正确

### 5.3 合并LUT测试
合并两个LUT文件，验证:
1. 生成的.npz文件中的stacks格式
2. 加载时是否正确解析

### 5.4 图像处理测试
使用合并后的LUT处理图像，验证:
1. 颜色匹配是否正确
2. 生成的3MF模型的层顺序是否正确

---

## 6. 相关代码行号汇总

| 文件 | 行号 | 内容 |
|------|------|------|
| `core/calibration.py` | 1150-1168 | Page 1 堆叠生成 |
| `core/calibration.py` | 1268-1272 | Page 2 堆叠映射 |
| `core/calibration.py` | 731-748 | `select_extended_1444_colors()` |
| `core/calibration.py` | 1050-1081 | `merge_5color_extended()` |
| `core/lut_merger.py` | 257-295 | 5-Color Extended LUT加载 |
| `core/lut_merger.py` | 265-267 | 错误的反转假设 |
| `core/image_processing.py` | 272-318 | 5-Color Extended LUT加载 |
| `core/image_processing.py` | 280-284 | 错误的反转假设 |

---

*计划创建时间: 2026-03-01*
*分析状态: 完成*
