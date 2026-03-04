# 5-Color 模式 Page 2 改为 Face-Down 模式实施计划

## 目标
将5-Color Extended模式的Page 2（扩展版1444色）从Face-Up模式改为Face-Down模式，使其与Page 1保持一致，从而减少系统复杂性，减少潜在bug。

---

## 当前状态分析

### 当前两种模式的区别

| 特性 | Page 1 (基础版 1024色) | Page 2 (扩展版 1444色) |
|------|----------------------|----------------------|
| **打印方向** | Face-Down (面朝下) | Face-Up (面朝上) |
| **观赏面位置** | Z=0 (第一层) | Z=5 (最后一层) |
| **白色支撑层** | 不需要 | 需要 (backing_layers) |
| **Stack映射** | `stack[z]` 直接映射 | `stack[5-z]` 反转映射 |
| **总层数** | 5层 | 6层 + backing层 |

### 代码位置
- **Page 1**: `core/calibration.py` `_generate_5color_base_page()` 函数 [L1122-L1212]
- **Page 2**: `core/calibration.py` `_generate_5color_extended_page()` 函数 [L1215-L1314]

---

## 实施步骤

### 步骤1: 修改 `_generate_5color_extended_page()` 函数

**文件**: `core/calibration.py`

#### 1.1 修改层数配置 [L1249-L1252]

**当前代码**:
```python
# 6 color layers + backing
color_layers = 6
backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
total_layers = color_layers + backing_layers
```

**修改为**:
```python
# 6 color layers (Face-Down mode: no backing needed, viewing surface at Z=0)
color_layers = 6
total_layers = color_layers
```

#### 1.2 修改颜色填充逻辑 [L1268-L1272]

**当前代码**:
```python
# Map stack to physical layers
for z in range(6):
    mat_id = stack[5 - z]  # Reverse for physical stacking
    if mat_id < 5:
        full_matrix[backing_layers + z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
```

**修改为**:
```python
# Map stack to physical layers (Face-Down mode: Z=0 is viewing surface)
for z in range(color_layers):
    mat_id = stack[z]  # Direct mapping: stack[0] at Z=0 (viewing surface)
    if mat_id < 5:
        full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
```

#### 1.3 修改角落标记位置 [L1282-L1286]

**当前代码**:
```python
viewing_surface_z = total_layers - 1  # Viewing surface is the last printed layer (top)
for r, c, mat_id in corners:
    px = c * (pixels_per_block + pixels_gap)
    py = r * (pixels_per_block + pixels_gap)
    full_matrix[viewing_surface_z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
```

**修改为**:
```python
viewing_surface_z = 0  # Face-Down mode: viewing surface is the first printed layer (Z=0)
for r, c, mat_id in corners:
    px = c * (pixels_per_block + pixels_gap)
    py = r * (pixels_per_block + pixels_gap)
    full_matrix[viewing_surface_z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
```

#### 1.4 更新文档字符串 [L1215-L1225]

**当前文档字符串**:
```python
def _generate_5color_extended_page(...):
    """
    Generate Page 2 (Extended) of 5-Color Extended calibration board.
    
    Features:
    - 1444 extended colors (6-layer stacks)
    - 38x38 grid with padding
    - Face Up printing (white base first, viewing surface on top)
    - Corner markers: TL=Yellow, TR=Black, BL=Black, BR=Red
    """
```

**修改为**:
```python
def _generate_5color_extended_page(...):
    """
    Generate Page 2 (Extended) of 5-Color Extended calibration board.
    
    Features:
    - 1444 extended colors (6-layer stacks)
    - 38x38 grid with padding
    - Face Down printing (viewing surface at Z=0, first printed layer)
    - Corner markers: TL=Yellow, TR=Black, BL=Black, BR=Red
    """
```

---

### 步骤2: 更新主函数文档字符串

**文件**: `core/calibration.py`

**位置**: `generate_5color_extended_board()` 函数 [L1084-L1101]

**当前文档字符串**:
```python
def generate_5color_extended_board(...):
    """
    Generate 5-Color Extended calibration board with dual-page support.

    Features:
    - Page 0: Base 1024 colors (5-layer, 32x32 grid)
    - Page 1: Extended 1444 colors (6-layer, 38x38 grid)
    - Corner alignment markers with page ID
    - Face Up printing (white base first, then color layers, viewing surface on top)
    """
```

**修改为**:
```python
def generate_5color_extended_board(...):
    """
    Generate 5-Color Extended calibration board with dual-page support.

    Features:
    - Page 0: Base 1024 colors (5-layer, 32x32 grid)
    - Page 1: Extended 1444 colors (6-layer, 38x38 grid)
    - Corner alignment markers with page ID
    - Face Down printing for both pages (viewing surface at Z=0)
    """
```

---

### 步骤3: 验证和测试

#### 3.1 生成测试校准板
运行校准板生成代码，验证：
- Page 2生成的3MF文件层数是否正确（应为6层，不是6+backing层）
- 角落标记是否在Z=0层
- 颜色堆叠顺序是否正确

#### 3.2 验证LUT合并
- 确认 `merge_5color_extended()` 函数仍然正确工作
- 确认生成的.npz文件格式正确

#### 3.3 验证图像处理
- 确认 `LUTMerger` 和 `LuminaImageProcessor` 能正确加载修改后的LUT

---

## 预期结果

### 修改后的状态

| 特性 | Page 1 (基础版 1024色) | Page 2 (扩展版 1444色) |
|------|----------------------|----------------------|
| **打印方向** | Face-Down (面朝下) | Face-Down (面朝下) ✅ |
| **观赏面位置** | Z=0 (第一层) | Z=0 (第一层) ✅ |
| **白色支撑层** | 不需要 | 不需要 ✅ |
| **Stack映射** | `stack[z]` 直接映射 | `stack[z]` 直接映射 ✅ |
| **总层数** | 5层 | 6层 ✅ |

### 好处
1. **简化代码逻辑**: 两个页面使用相同的打印方向，减少特殊处理
2. **减少bug**: 消除Face-Up和Face-Down模式切换可能带来的错误
3. **一致性**: 与4色标准模式保持一致（都是Face-Down）
4. **易于维护**: 统一的约定使得代码更容易理解和维护

---

## 相关文件清单

| 文件 | 修改内容 |
|------|---------|
| `core/calibration.py` | 修改 `_generate_5color_extended_page()` 函数 |
| `core/calibration.py` | 更新 `generate_5color_extended_board()` 文档字符串 |

---

## 风险评估

### 低风险
- 修改仅影响Page 2的生成逻辑，不影响Page 1
- 修改后两个页面使用相同的Face-Down模式，与4色标准模式一致

### 需要注意
- 需要重新生成Page 2的校准板进行测试
- 需要验证LUT合并和图像处理流程是否正常工作

---

*计划创建时间: 2026-03-01*
*计划状态: 待实施*
