# 校准板方向转换修复计划 (修正版)

## 关于 5-Color 1444 模式的状态

**5-Color 1444 模式已从 UI 中移除，但代码仍然保留！**

### 当前状态
- **UI 显示**: 只有 "5-Color Extended (2468)"
- **UI 调用**: `generate_5color_extended_board()`
- **遗留代码**: `generate_5color1444_board()` 函数仍在 `calibration.py` 中，但不再被使用
- **遗留导入**: `ui/layout_new.py` 第21行仍然导入了 `generate_5color1444_board`（多余）

### 需要清理的遗留代码
1. `core/calibration.py` 中的 `generate_5color1444_board()` 函数（约903-1015行）
2. `ui/layout_new.py` 第21行的多余导入

## 发现的关键问题

### Smart 1296 (6-Color) 存在角标位置错误！

**代码逻辑分析：**
```python
# 1. 数据填充：Z=0 = 观赏面（Face-Down）
for z in range(color_layers):
    full_matrix[z, ...] = stack[z]  # stack[0]=观赏面 → Z=0

# 2. 角标位置：Z=total_layers-1（错误！）
viewing_surface_z = total_layers - 1
for r, c, mat_id in corners:
    full_matrix[viewing_surface_z, ...] = mat_id
```

**矛盾：**
- 数据：观赏面在 Z=0（底部）
- 角标：在 Z=total_layers-1（顶部/背面）

**对于 Face-Down 模式：**
- 观赏面在 Z=0
- 角标应该在 Z=0（观赏面）
- 但 Smart 1296 把角标放在 Z=total_layers-1

## 正确的方向分析

| 模式 | Stack 约定 | 翻转 | Z=0 是什么 | 实际方向 | 角标位置 |
|------|-----------|------|-----------|---------|---------|
| 4-Color | [顶到底] | 无 | 观赏面 | **Face-Down** | Z=0-4 ✓ |
| Smart 1296 | [底到顶]→[顶到底] | reversed() | 观赏面 | **Face-Down** | Z=total_layers-1 ✗ |
| 8-Color | [底到顶]→[顶到底] | [::-1] | 观赏面 | **Face-Down** | Z=0-4 ✓ |
| BW | [顶到底] | 无 | 观赏面 | **Face-Down** | Z=0-4 ✓ |
| **5-Color Extended** | [顶到底] | **底板先填充** | **底板** | **Face-Up** | Z=total_layers-1 ✓ |

## 需要修复的问题

### 1. Smart 1296 角标位置错误
- **当前**: 角标在 `Z=total_layers-1`
- **应该**: 角标在 `Z=0`（因为 Face-Down 的观赏面在 Z=0）

### 2. 清理遗留代码（可选）
- 移除 `generate_5color1444_board()` 函数
- 移除 `ui/layout_new.py` 的多余导入

## 修复步骤

### 步骤 1: 修复 Smart 1296 角标位置
**文件**: `core/calibration.py`
**函数**: `generate_smart_board()`

```python
# 当前（错误）:
viewing_surface_z = total_layers - 1
for r, c, mat_id in corners:
    px = c * (pixels_per_block + pixels_gap)
    py = r * (pixels_per_block + pixels_gap)
    full_matrix[viewing_surface_z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id

# 修复后（正确）:
# Face-Down 模式：观赏面在 Z=0
viewing_surface_z = 0
for r, c, mat_id in corners:
    px = c * (pixels_per_block + pixels_gap)
    py = r * (pixels_per_block + pixels_gap)
    full_matrix[viewing_surface_z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
```

### 步骤 2: 清理遗留代码（可选）
- 删除 `generate_5color1444_board()` 函数
- 从 `ui/layout_new.py` 移除多余导入
