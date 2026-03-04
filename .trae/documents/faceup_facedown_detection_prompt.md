# Face-Up vs Face-Down 检测 Prompt

## 任务
判断校准板生成代码是 Face-Up 还是 Face-Down 模式。

## 核心原则
**不要看角标位置，不要看注释，只看底板填充顺序！**

## 判断步骤

### 步骤1: 找到矩阵初始化
```python
full_matrix = np.full((total_layers, ...), 填充值, dtype=int)
```

### 步骤2: 找到第一层填充逻辑
检查代码如何填充 Z=0 层：

**情况A: Face-Down（先打印观赏面）**
```python
# 观赏面直接填充在 Z=0
for z in range(color_layers):
    full_matrix[z, ...] = stack[z]  # stack[0]=观赏面 → Z=0
```
- Z=0 = 观赏面（最先打印）
- Z=top = 底板（最后打印）

**情况B: Face-Up（先打印底板）**
```python
# 显式先填充底板在 Z=0
for z in range(backing_layers):
    full_matrix[z, :, :] = 底板材料  # 底板在 Z=0

# 颜色层在底板之上
for z in range(color_layers):
    full_matrix[backing_layers + z, ...] = stack[反转索引]
# stack[0]=观赏面 → Z=total_layers-1
```
- Z=0 = 底板（最先打印）
- Z=top = 观赏面（最后打印）

### 步骤3: 确认方向
| Z=0 是什么 | 方向 | 观赏面位置 |
|-----------|------|-----------|
| 观赏面 | Face-Down | Z=0 |
| 底板 | Face-Up | Z=total_layers-1 |

### 步骤4: 验证角标位置（可选）
- Face-Down: 角标应该在 Z=0（观赏面）
- Face-Up: 角标应该在 Z=total_layers-1（观赏面）

## 常见陷阱

❌ **错误方法**:
- 只看注释（可能错误）
- 只看角标位置（可能错误）
- 看 stack 是否翻转（只是约定转换，不决定方向）

✅ **正确方法**:
- 看 Z=0 先填充的是什么（观赏面 vs 底板）

## 代码示例分析

### 示例1: Face-Down
```python
full_matrix = np.full((total_layers, ...), backing_id, dtype=int)
for z in range(5):
    full_matrix[z, ...] = stack[z]  # stack[0]=观赏面 → Z=0
# 结果: Z=0=观赏面, Z=top=底板 → Face-Down ✓
```

### 示例2: Face-Up
```python
full_matrix = np.full((total_layers, ...), 0, dtype=int)
for z in range(backing_layers):
    full_matrix[z, :, :] = 0  # 底板在 Z=0
for z in range(6):
    full_matrix[backing_layers + z, ...] = stack[5-z]  # 观赏面在 Z=top
# 结果: Z=0=底板, Z=top=观赏面 → Face-Up ✓
```

## 输出格式

分析后输出:
```
方向: [Face-Up / Face-Down]
Z=0: [观赏面 / 底板]
Z=top: [底板 / 观赏面]
先打印: [观赏面 / 底板]
后打印: [底板 / 观赏面]
```

## 当前项目状态参考

| 模式 | 方向 | Z=0 |
|------|------|-----|
| 4-Color | Face-Down | 观赏面 |
| Smart 1296 | Face-Down | 观赏面 |
| 8-Color | Face-Down | 观赏面 |
| BW | Face-Down | 观赏面 |
| 5-Color Extended | Face-Up | 底板 |

**5-Color Extended 是唯一的 Face-Up 模式！**
