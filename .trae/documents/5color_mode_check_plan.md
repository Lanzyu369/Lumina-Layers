# 5色模式检查计划报告

## 检查目标
检查正在构建的5色模式（5-Color Extended）是否对其他现有模式造成误改。

## 检查日期
2026-03-01

---

## 一、项目支持的颜色模式概览

| 模式名称 | 颜色数量 | 材料槽位 | 层数 | 状态 |
|---------|---------|---------|------|------|
| **BW (Black & White)** | 32 (2^5) | 2 (白/黑) | 5 | ✅ 正常 |
| **4-Color (CMYW/RYBW)** | 1024 (4^5) | 4 | 5 | ✅ 正常 |
| **5-Color Extended** | 2468 (1024+1444) | 5 (RYBWK) | 6 | ⚠️ 实现中 |
| **6-Color (Smart 1296)** | 1296 | 6 (CMYGK+白) | 5 | ✅ 正常 |
| **8-Color Max** | 2738 | 8 | 5 | ✅ 正常 |
| **Merged** | 可变 | 8 | 5 | ✅ 正常 |

---

## 二、检查结果详细分析

### 2.1 配置文件检查 (config.py)

**状态：✅ 正常，无冲突**

- `FIVE_COLOR_EXTENDED` 配置独立添加（第135-150行），未修改其他模式配置
- `ColorSystem.get()` 方法正确添加了5色模式支持（第194-196行）
- 其他模式配置（BW、4-Color、6-Color、8-Color）保持原样

### 2.2 图像处理模块检查 (core/image_processing.py)

**状态：✅ 正常，新增分支未影响现有分支**

- 5色模式处理分支独立（第271-318行），使用 `elif` 链
- 现有分支（BW、8-Color、6-Color、4-Color）逻辑未修改
- 约定转换逻辑（底到顶 ↔ 顶到底）在5色分支中保持一致

### 2.3 校准板生成模块检查 (core/calibration.py)

**状态：✅ 正常，新增函数未影响现有函数**

- `generate_5color_extended_board()` 函数独立实现（第1083-1227行）
- 现有校准板生成函数未修改：
  - `generate_calibration_board()` - 4色标准校准板
  - `generate_smart_board()` - 6色Smart 1296校准板
  - `generate_8color_board()` - 8色校准板
  - `generate_bw_calibration_board()` - 黑白校准板

### 2.4 LUT合并模块检查 (core/lut_merger.py)

**状态：✅ 正常，新增映射未影响现有映射**

- `_SIZE_TO_MODE` 添加5色大小映射（第24行）：`2468: "5-Color Extended"`
- `_MODE_PRIORITY` 添加5色优先级（第46行）：`"5-Color Extended": 1`
- `_MODE_MAX_MATERIAL` 添加5色最大材料ID（第56行）：`"5-Color Extended": 4`
- `_REMAP_TO_8COLOR` 添加5色重映射表（第68行）
- 现有模式映射保持原样

### 2.5 颜色提取模块检查 (core/extractor.py)

**状态：⚠️ 发现问题 - 5色模式缺少网格大小处理**

```python
# 第170-186行：动态确定网格大小
if color_mode == "BW (Black & White)" or color_mode == "BW":
    grid_size = 6
    physical_grid = 8
    total_cells = 32
elif "8-Color" in color_mode:
    grid_size = 37
    physical_grid = 39
    total_cells = 1369
elif "6-Color" in color_mode:
    grid_size = 36
    physical_grid = 38
    total_cells = 1296
else:
    grid_size = DATA_GRID_SIZE  # 32
    physical_grid = PHYSICAL_GRID_SIZE  # 34
    total_cells = 1024
```

**问题**：5-Color Extended 模式没有特定的网格大小处理，会落入默认的4色模式逻辑（32x32网格），这可能导致提取不正确。

**影响评估**：中等 - 如果用户尝试提取5色校准板，会使用错误的网格大小

### 2.6 UI布局检查 (ui/layout_new.py)

**状态：⚠️ 发现问题 - UI不一致**

| TAB | 5色模式选项 | 状态 |
|-----|------------|------|
| 校准板生成 | 有 | ✅ 正常 |
| 颜色提取 | 无 | ⚠️ 缺失 |
| 图像转换 | 无 | ⚠️ 缺失 |

**校准板生成TAB**（第3345-3355行）：
- 正确包含 `("5-Color Extended (2468)", "5-Color Extended")` 选项

**颜色提取TAB**（第3451-3460行）：
- 缺少5色模式选项
- 当前选项：BW、4-Color、6-Color、8-Color

**图像转换TAB**（第1985-1997行）：
- 缺少5色模式选项
- 当前选项：BW、4-Color、6-Color、8-Color、Merged

---

## 三、发现的问题汇总

### 问题1：提取器缺少5色模式网格大小处理
- **位置**：`core/extractor.py` 第170-186行
- **严重程度**：中等
- **影响**：5色校准板提取会使用错误的网格参数

### 问题2：提取器UI缺少5色模式选项
- **位置**：`ui/layout_new.py` 第3451-3460行
- **严重程度**：中等
- **影响**：用户无法在提取器中选择5色模式

### 问题3：转换器UI缺少5色模式选项
- **位置**：`ui/layout_new.py` 第1985-1997行
- **严重程度**：中等
- **影响**：用户无法在转换器中使用5色LUT

---

## 四、其他模式完整性验证

### 4.1 BW (Black & White) 模式
- ✅ 配置完整（config.py 第121-133行）
- ✅ 校准板生成正常（calibration.py 第539-678行）
- ✅ 提取器网格大小处理正常（extractor.py 第171-174行）
- ✅ 图像处理分支正常（image_processing.py 第193-216行）
- ✅ LUT合并支持正常（lut_merger.py）

### 4.2 4-Color (CMYW/RYBW) 模式
- ✅ 配置完整（config.py 第64-90行）
- ✅ 校准板生成正常（calibration.py 第85-184行）
- ✅ 提取器网格大小处理正常（extractor.py 第183-186行，默认分支）
- ✅ 图像处理分支正常（image_processing.py 第346-379行）
- ✅ LUT合并支持正常（lut_merger.py）

### 4.3 6-Color (Smart 1296) 模式
- ✅ 配置完整（config.py 第92-108行）
- ✅ 校准板生成正常（calibration.py 第286-418行）
- ✅ 提取器网格大小处理正常（extractor.py 第179-182行）
- ✅ 图像处理分支正常（image_processing.py 第249-269行）
- ✅ LUT合并支持正常（lut_merger.py）

### 4.4 8-Color Max 模式
- ✅ 校准板生成正常（calibration.py 第420-521行）
- ✅ 提取器网格大小处理正常（extractor.py 第175-178行）
- ✅ 图像处理分支正常（image_processing.py 第218-247行）
- ✅ LUT合并支持正常（lut_merger.py）

### 4.5 Merged 模式
- ✅ LUT合并引擎完整（lut_merger.py）
- ✅ 图像处理分支正常（image_processing.py 第321-343行）
- ✅ 转换器UI支持正常

---

## 五、结论

### 5.1 其他模式是否被误改？
**答案：否。** 所有现有模式（BW、4-Color、6-Color、8-Color、Merged）的实现均保持完整，5色模式的添加采用独立分支实现，未对现有代码造成破坏性修改。

### 5.2 5色模式当前状态
**状态：部分实现，存在3个待修复问题**

| 功能模块 | 实现状态 | 备注 |
|---------|---------|------|
| 配置系统 | ✅ 完成 | config.py |
| 校准板生成 | ✅ 完成 | calibration.py |
| LUT合并 | ✅ 完成 | lut_merger.py |
| 图像处理 | ✅ 完成 | image_processing.py |
| 校准板UI | ✅ 完成 | layout_new.py |
| 提取器逻辑 | ⚠️ 缺失 | 需要添加网格大小处理 |
| 提取器UI | ⚠️ 缺失 | 需要添加选项 |
| 转换器UI | ⚠️ 缺失 | 需要添加选项 |

### 5.3 建议修复事项

1. **添加5色模式到提取器网格大小处理**（extractor.py）
2. **添加5色模式到提取器UI**（layout_new.py 提取器TAB）
3. **添加5色模式到转换器UI**（layout_new.py 转换器TAB）

---

## 六、相关文件清单

| 文件路径 | 检查状态 |
|---------|---------|
| config.py | ✅ 已检查 |
| core/calibration.py | ✅ 已检查 |
| core/image_processing.py | ✅ 已检查 |
| core/lut_merger.py | ✅ 已检查 |
| core/extractor.py | ⚠️ 发现问题 |
| ui/layout_new.py | ⚠️ 发现问题 |
| core/converter.py | ✅ 无需修改 |
