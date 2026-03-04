# 修正注释计划

## 问题说明

用户指出："Face-Down 就是先打印底板的"

但当前代码注释有混淆：
- Face-Down 模式 = 先打印观赏面（Z=0），后打印底板
- Face-Up 模式 = 先打印底板（Z=0），后打印观赏面

## 需要修正的注释

### 1. Smart 1296 (6-Color) 模式

**当前注释（错误/混淆）：**
```python
# Z=0 (physical first layer) = viewing surface = stack[0] (顶到底约定)
...
# Place markers on viewing surface (topmost color layer) for visual identification after printing
viewing_surface_z = total_layers - 1  # Z index of viewing surface (last printed layer)
```

**问题：**
- 第362行说 Z=0 是 viewing surface（正确）
- 第380行说 viewing_surface_z = total_layers - 1 是 "last printed layer"（错误！）

对于 Face-Down 模式：
- 先打印的是 viewing surface（Z=0）
- 后打印的是 backing（Z=total_layers-1）
- 所以 "last printed layer" 是底板，不是观赏面

**应该改为：**
```python
# Z=0 (physical first layer) = viewing surface = stack[0] (顶到底约定)
# Face-Down: 先打印观赏面(Z=0)，后打印底板(Z=total_layers-1)
...
# Place markers on viewing surface (Z=0) for visual identification after printing
viewing_surface_z = 0  # Z index of viewing surface (first printed layer in Face-Down mode)
```

### 2. 5-Color Extended 模式

**当前注释（正确）：**
```python
# Fill backing layer first (Face-Up: white base at bottom Z=0)
...
# stack[0] (top/viewing surface) → Z=total_layers-1
...
# Place markers on viewing surface (topmost layer) for visual identification after printing
viewing_surface_z = total_layers - 1  # Viewing surface is the last printed layer (top)
```

这个注释是正确的：
- Face-Up = 先打印底板（Z=0）
- 后打印观赏面（Z=total_layers-1）
- "last printed layer" = 观赏面（正确）

**不需要修改。**

### 3. 其他 Face-Down 模式

4-Color、8-Color、BW 模式的注释也需要检查是否混淆了打印顺序。

## 修复步骤

### 步骤 1: 修复 Smart 1296 注释
**文件**: `core/calibration.py`
**行号**: 362, 379-380

修改内容：
1. 第362行后添加注释说明 Face-Down 打印顺序
2. 第379-380行修正角标位置注释

### 步骤 2: 检查并修复其他 Face-Down 模式注释
检查 4-Color、8-Color、BW 模式是否有类似混淆

## 修正后的理解

| 模式 | 方向 | 先打印 | 后打印 | 观赏面位置 |
|------|------|--------|--------|-----------|
| 4-Color | Face-Down | 观赏面 (Z=0) | 底板 (Z=bottom) | Z=0 |
| Smart 1296 | Face-Down | 观赏面 (Z=0) | 底板 (Z=bottom) | Z=0 |
| 8-Color | Face-Down | 观赏面 (Z=0) | 底板 (Z=bottom) | Z=0 |
| BW | Face-Down | 观赏面 (Z=0) | 底板 (Z=bottom) | Z=0 |
| 5-Color Extended | Face-Up | 底板 (Z=0) | 观赏面 (Z=top) | Z=total_layers-1 |

**关键理解：**
- Face-Down = 观赏面朝下 = 先打印观赏面
- Face-Up = 观赏面朝上 = 后打印观赏面
