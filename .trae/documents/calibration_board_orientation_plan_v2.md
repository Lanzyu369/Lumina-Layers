# 校准板打印方向分析计划 (修正版)

## 用户确认
**5-Color Extended 是唯一的 Face-Up 模式，其他所有模式都是 Face-Down！**

## 重新分析

### 关键理解
- **Face-Up** = 观看面朝上 = 先打印底板，后打印观看面（观看面在顶部/Z=最大）
- **Face-Down** = 观看面朝下 = 先打印观看面，后打印底板（观看面在底部/Z=0）

### 5-Color Extended (Face-Up)
```python
# 显式先填充底板在 Z=0
for z in range(backing_layers):
    full_matrix[z, :, :] = 0  # White backing at Z=0

# 颜色层在底板之上
# stack[5] → Z=backing_layers
# stack[0] → Z=total_layers-1 (观看面)
for z in range(6):
    mat_id = stack[5 - z]
    full_matrix[backing_layers + z, ...] = mat_id
```
- **打印顺序**: 底板(Z=0) → 内部层 → 观看面(Z=top)
- **观看面位置**: Z=total_layers-1（最后打印，在顶部）
- **方向**: **Face-Up** ✓

### 其他模式 (Face-Down)
```python
# 初始化：用 backing/white 填充所有层
full_matrix = np.full((total_layers, ...), backing_id, dtype=int)

# 颜色从 Z=0 开始填充（覆盖底板）
for z in range(color_layers):
    full_matrix[z, ...] = stack[z]  # Z=0 是观看面
```
- **打印顺序**: 观看面(Z=0) → 内部层 → 底板(Z=bottom)
- **观看面位置**: Z=0（最先打印，在底部）
- **方向**: **Face-Down**

## 需要修复的问题

### 1. Smart 1296 的 docstring 错误
当前: "Face Down printing optimization"
应该: "Face Up printing optimization" → 不对，用户说其他都是 Face-Down

等等，让我重新理解：
- 如果 5-Color 是唯一的 Face-Up
- 那么 Smart 1296 应该是 Face-Down
- 但 Smart 1296 的代码是 Z=0 开始填充（观看面在Z=0）

这说明 Smart 1296 的代码逻辑是：观看面在 Z=0（底部）= Face-Down

但用户说其他都是 Face-Down，这意味着 Smart 1296 的 docstring "Face Down" 是正确的！

## 修正后的结论

| 模式 | 代码逻辑 | 观看面位置 | 方向 | Docstring |
|------|---------|-----------|------|-----------|
| 4-Color | Z=0 填充 | Z=0 (底部) | **Face-Down** | 未标明 |
| Smart 1296 | Z=0 填充 | Z=0 (底部) | **Face-Down** | "Face Down" ✓ |
| 8-Color | Z=0 填充 | Z=0 (底部) | **Face-Down** | 未标明 |
| BW | Z=0 填充 | Z=0 (底部) | **Face-Down** | "Face Up" ✗ 错误 |
| 5-Color 1444 | Z=0 填充 | Z=0 (底部) | **Face-Down** | 未标明 |
| **5-Color Extended** | 底板先填充 | Z=top (顶部) | **Face-Up** | "Face Down" ✗ 错误 |

## 需要修复的文档字符串

1. **BW 模式**: "Face Up" → "Face Down"
2. **5-Color Extended**: "Face Down" → "Face Up"
