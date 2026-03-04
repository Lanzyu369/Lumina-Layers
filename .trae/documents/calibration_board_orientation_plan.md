# 校准板打印方向分析计划

## 核心原则

**观看面在哪边由底板填充顺序决定，不是由角标决定！**

## 各模式详细分析

### 1. 4-Color (标准模式)

```python
# 初始化：用 backing_id 填充所有层
full_matrix = np.full((total_layers, voxel_h, voxel_w), backing_id, dtype=int)

# 颜色填充：Z=0 开始
for z in range(PrinterConfig.COLOR_LAYERS):
    full_matrix[z, ...] = stack[z]  # Z=0 是观看面

# 角标：在所有颜色层 (Z=0 到 4)
for z in range(PrinterConfig.COLOR_LAYERS):
    full_matrix[z, ...] = mat_id
```

* **底板**: 初始化时填充，但会被颜色层覆盖（除了底层）

* **观看面**: Z=0（最先打印）

* **打印顺序**: 观看面 → 内部层 → 底板

* **方向**: **Face-Up** (观看面朝上)

### 2. Smart 1296 (6-Color)

```python
# 初始化：用 White(0) 填充所有层
full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)

# 颜色填充：Z=0 开始
for z in range(color_layers):
    full_matrix[z, ...] = stack[z]  # Z=0 是观看面

# 角标：在观看面 (Z=total_layers-1)
viewing_surface_z = total_layers - 1
```

* **底板**: White，初始化时填充，会被覆盖

* **观看面**: Z=0（最先打印）

* **打印顺序**: 观看面 → 内部层 → 底板

* **方向**: **Face-Up** (观看面朝上)

* **注意**: Docstring 说 "Face Down" 是**错误**的！

### 3. 8-Color

```python
# 初始化：用 White(0) 填充
full_matrix = np.full((5 + backing_layers, v_w, v_w), 0, dtype=int)

# 颜色填充：Z=0 开始
for z, mid in enumerate(stack):
    full_matrix[z, ...] = mid  # Z=0 是观看面

# 角标：在所有层 (Z=0 到 4)
for z in range(5):
    full_matrix[z, ...] = mid
```

* **底板**: White，初始化时填充

* **观看面**: Z=0（最先打印）

* **打印顺序**: 观看面 → 内部层 → 底板

* **方向**: **Face-Up** (观看面朝上)

### 4. BW (2-Color)

```python
# 初始化：用 White(0) 填充所有层
full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)

# 颜色填充：Z=0 开始
for z in range(color_layers):
    full_matrix[z, ...] = stack[z]  # Z=0 是观看面

# 角标：在所有层 (Z=0 到 4)
for z in range(color_layers):
    full_matrix[z, ...] = mat_id
```

* **底板**: White，初始化时填充

* **观看面**: Z=0（最先打印）

* **打印顺序**: 观看面 → 内部层 → 底板

* **方向**: **Face-Up** (观看面朝上) - Docstring 正确

### 5. 5-Color 1444

```python
# 初始化：用 White(0) 填充所有层
full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)

# 颜色填充：Z=0 开始
for z in range(min(stack_len, color_layers)):
    full_matrix[z, ...] = mat_id  # Z=0 是观看面

# 角标：在所有层 (Z=0 到 5)
for z in range(color_layers):
    full_matrix[z, ...] = mat_id
```

* **底板**: White，初始化时填充

* **观看面**: Z=0（最先打印）

* **打印顺序**: 观看面 → 内部层 → 底板

* **方向**: **Face-Up** (观看面朝上)

### 6. 5-Color Extended (2468)

```python
# 初始化：用 White(0) 填充所有层
full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)

# 显式填充底板：Z=0 开始
for z in range(backing_layers):
    full_matrix[z, :, :] = 0  # White backing at Z=0

# 颜色填充：在底板之上
# stack[5] → Z=backing_layers
# stack[0] → Z=total_layers-1
for z in range(6):
    mat_id = stack[5 - z]
    full_matrix[backing_layers + z, ...] = mat_id

# 角标：在观看面 (Z=total_layers-1)
viewing_surface_z = total_layers - 1
```

* **底板**: White，**显式填充在 Z=0**

* **观看面**: Z=total\_layers-1（最后打印）

* **打印顺序**: 底板 → 内部层 → 观看面

* **方向**: **Face-Down** (观看面朝下)

## 关键区别

| 模式                   | 底板填充方式        | 观看面位置                 | 方向                    |
| -------------------- | ------------- | --------------------- | --------------------- |
| 4-Color              | 初始化时填充，被覆盖    | Z=0                   | Face-Up               |
| Smart 1296           | 初始化时填充，被覆盖    | Z=0                   | Face-Up (docstring错误) |
| 8-Color              | 初始化时填充，被覆盖    | Z=0                   | Face-Up               |
| BW                   | 初始化时填充，被覆盖    | Z=0                   | Face-Up               |
| 5-Color 1444         | 初始化时填充，被覆盖    | Z=0                   | Face-Up               |
| **5-Color Extended** | **显式填充在 Z=0** | **Z=total\_layers-1** | **Face-Down**         |

## 结论

1. **5-Color Extended 是唯一的 Face-Down 模式**

   * 因为它是唯一显式先填充底板的模式

   * 观看面在 Z=total\_layers-1（最后打印）

2. **其他所有模式都是 Face-Up**

   * 底板在初始化时填充，但会被颜色层覆盖

   * 观看面在 Z=0（最先打印）

   * Smart 1296 的 docstring "Face Down" 是**错误**的

3. **5-Color Extended 的当前实现是正确的**

   * 角标在观看面 (Z=total\_layers-1) 是正确的

   * Docstring "Face Down" 是正确的

## 需要修复的问题

1. Smart 1296 的 docstring "Face Down" → 应该改为

