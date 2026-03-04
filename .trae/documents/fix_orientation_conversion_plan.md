# 校准板方向转换修复计划

## 发现的关键问题

### Smart 1296 (6-Color) 模式的问题

**当前代码逻辑：**
```python
# 1. 从 get_top_1296_colors() 获取 stacks
#    - 返回的是 [底到顶] 约定 (stack[0]=背面，stack[4]=观赏面)

# 2. 约定转换：翻转为 [顶到底] 约定
stacks = [tuple(reversed(s)) for s in stacks]
#    - 转换后: stack[0]=观赏面，stack[4]=背面

# 3. 填充到矩阵 (Z=0 开始)
for z in range(color_layers):
    mat_id = stack[z]
    full_matrix[z, ...] = mat_id
#    - Z=0 = stack[0] = 观赏面
#    - Z=4 = stack[4] = 背面

# 4. 角标放在 Z=total_layers-1 (背面/底板层)
viewing_surface_z = total_layers - 1
```

**矛盾！**
- 数据填充：Z=0 是观赏面（Face-Down）
- 角标位置：Z=total_layers-1（背面层）

这意味着 Smart 1296 的**角标位置是错误的**！

### 8-Color 模式

```python
# 1. 从 .npy 加载 stacks
#    - 存储的是 [底到顶] 约定 (stack[0]=背面，stack[4]=观赏面)

# 2. 约定转换：翻转为 [顶到底] 约定
all_stacks = np.array([s[::-1] for s in all_stacks])
#    - 转换后: stack[0]=观赏面，stack[4]=背面

# 3. 填充到矩阵 (Z=0 开始)
for z, mid in enumerate(stack):
    full_matrix[z, ...] = mid
#    - Z=0 = stack[0] = 观赏面
```

8-Color 也是 Z=0 = 观赏面 = Face-Down

### 4-Color 模式

```python
# 直接生成 stacks [顶到底] 约定
stack = digits[::-1]  # [顶...底]

# 填充到矩阵 (Z=0 开始)
for z in range(PrinterConfig.COLOR_LAYERS):
    full_matrix[z, ...] = stack[z]
#    - Z=0 = stack[0] = 观赏面
```

4-Color 也是 Z=0 = 观赏面 = Face-Down

## 正确的方向分析

| 模式 | Stack 约定 | 翻转后 | Z=0 是什么 | 实际方向 |
|------|-----------|--------|-----------|---------|
| 4-Color | [顶到底] | 无翻转 | 观赏面 | **Face-Down** |
| Smart 1296 | [底到顶] → [顶到底] | reversed() | 观赏面 | **Face-Down** |
| 8-Color | [底到顶] → [顶到底] | [::-1] | 观赏面 | **Face-Down** |
| BW | [顶到底] | 无翻转 | 观赏面 | **Face-Down** |
| 5-Color 1444 | [顶到底] | 无翻转 | 观赏面 | **Face-Down** |
| **5-Color Extended** | [顶到底] | **显式底板先填充** | **底板** | **Face-Up** |

## 结论

**所有模式都是 Face-Down，除了 5-Color Extended 是 Face-Up！**

我的之前的分析是正确的。

## 但是...

用户说 "4色模式和6色模式的结果明确是facedown的"

这意味着：
1. 4-Color 是 Face-Down ✓（符合我的分析）
2. Smart 1296 (6-Color) 是 Face-Down ✓（符合我的分析）
3. 但 Smart 1296 的 docstring 说 "Face Down" ✓（正确）
4. 我的 BW 修复 "Face Up" → "Face Down" ✓（正确）
5. 我的 5-Color Extended 修复 "Face Down" → "Face Up" ✓（正确）

## 需要检查的问题

Smart 1296 的角标位置：**它放在 Z=total_layers-1，但数据填充在 Z=0=观赏面**

这意味着：
- 数据：观赏面在 Z=0（底部）
- 角标：在 Z=total_layers-1（顶部/背面）

**角标和数据不一致！**

对于 Face-Down 模式：
- 观赏面在 Z=0（底部）
- 角标应该在 Z=0（观赏面）
- 但 Smart 1296 把角标放在 Z=total_layers-1

这是 Smart 1296 的 bug！

## 修复计划

### 1. 检查 Smart 1296 的角标位置
当前：角标在 Z=total_layers-1
应该：角标在 Z=0（因为 Face-Down 的观赏面在 Z=0）

### 2. 检查 8-Color 的角标位置
需要查看代码

### 3. 检查 4-Color 的角标位置
当前：角标在所有层 (Z=0 到 4)
这是正确的（Face-Down 的观赏面在 Z=0）

### 4. 检查 BW 的角标位置
当前：角标在所有层 (Z=0 到 4)
这是正确的（Face-Down 的观赏面在 Z=0）

### 5. 检查 5-Color 1444 的角标位置
当前：角标在所有层 (Z=0 到 5)
这是正确的（Face-Down 的观赏面在 Z=0）

### 6. 检查 5-Color Extended 的角标位置
当前：角标在 Z=total_layers-1
这是正确的（Face-Up 的观赏面在 Z=total_layers-1）

## 最终需要修复的

1. **Smart 1296 的角标位置**: Z=total_layers-1 → Z=0
