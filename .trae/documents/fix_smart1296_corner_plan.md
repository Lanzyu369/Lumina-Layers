# Smart 1296 角标位置修复计划

## 问题确认

经过仔细检查代码，确认以下问题：

### Smart 1296 (6-Color) 模式

**数据填充逻辑（正确）：**
```python
# Fill 5 color layers (直接映射，与 4 色模式一致)
# Z=0 (physical first layer) = viewing surface = stack[0] (顶到底约定)
# Z=4 (physical fifth layer) = internal layer = stack[4] (顶到底约定)
for z in range(color_layers):
    mat_id = stack[z]
    full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
```
- Z=0 = viewing surface（观赏面）
- Z=4 = internal layer（内部层）
- 这是 **Face-Down** 模式（观赏面在 Z=0，最先打印）

**角标位置（错误）：**
```python
# Place markers on viewing surface (topmost color layer) for visual identification after printing
viewing_surface_z = total_layers - 1  # Z index of viewing surface (last printed layer)
for r, c, mat_id in corners:
    full_matrix[viewing_surface_z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
```

**问题分析：**
1. 注释说 "viewing surface"，但代码设置的是 `total_layers - 1`
2. 注释说 "last printed layer"，但对于 Face-Down 模式，last printed layer 是底板，不是观赏面
3. 实际上 `total_layers - 1` 是底板层（backing layer）
4. 角标错误地放在了底板层，而不是观赏面层

## 正确的逻辑

对于 Face-Down 模式：
- 先打印 viewing surface（Z=0）
- 后打印 backing layer（Z=total_layers-1）
- 角标应该在 viewing surface（Z=0）

## 修复内容

### 文件: `core/calibration.py`
### 函数: `generate_smart_board()`
### 行号: 377-384

**当前代码（错误）：**
```python
# Set corner alignment markers (in outermost ring)
# TL: White (0), TR: Red (1), BR: Yellow (2), BL: Blue (3)
# Place markers on viewing surface (topmost color layer) for visual identification after printing
viewing_surface_z = total_layers - 1  # Z index of viewing surface (last printed layer)
for r, c, mat_id in corners:
    px = c * (pixels_per_block + pixels_gap)
    py = r * (pixels_per_block + pixels_gap)
    full_matrix[viewing_surface_z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
```

**修复后代码（正确）：**
```python
# Set corner alignment markers (in outermost ring)
# TL: White (0), TR: Cyan (1), BR: Magenta (2), BL: Yellow (4)
# Place markers on viewing surface (Z=0) for visual identification after printing
# Face-Down mode: viewing surface is at Z=0 (first printed layer)
viewing_surface_z = 0  # Z index of viewing surface (first printed layer in Face-Down mode)
for r, c, mat_id in corners:
    px = c * (pixels_per_block + pixels_gap)
    py = r * (pixels_per_block + pixels_gap)
    full_matrix[viewing_surface_z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
```

## 修复总结

1. **角标位置**: `total_layers - 1` → `0`
2. **注释修正**: 
   - "topmost color layer" → "Z=0"
   - "last printed layer" → "first printed layer in Face-Down mode"
   - 角标颜色注释: "Red (1), Yellow (2), Blue (3)" → "Cyan (1), Magenta (2), Yellow (4)"（与 corners 变量一致）

## 验证

修复后：
- Face-Down 模式
- 观赏面在 Z=0
- 角标在 Z=0（观赏面）
- 与 4-Color、8-Color、BW 模式一致
