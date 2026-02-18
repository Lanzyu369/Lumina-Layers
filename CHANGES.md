# 底板分离功能 - 代码修改摘要

## 功能说明

添加了简单的底板分离功能，允许用户通过复选框选择是否将底板作为独立对象导出到3MF文件。

## 核心修改文件

### 1. UI层修改

#### `ui/layout_new.py`
- 添加UTF-8编码声明
- 添加"底板单独一个对象"复选框组件
- 连接复选框到转换函数

#### `ui/callbacks.py`
- 修复导入错误：将 `generate_palette_html` 从 `core.converter` 改为从 `ui.palette_extension` 导入（4处）

### 2. 核心逻辑修改

#### `core/converter.py`
- `convert_image_to_3d()` 函数添加 `separate_backing` 参数（布尔值，默认False）
- 添加条件判断：`backing_color_id = -2 if separate_backing else 0`
- 添加条件性底板网格生成逻辑
- 添加完善的错误处理机制

#### `core/mesh_generators.py`
- 支持 `mat_id=-2` 的特殊底板材质ID处理

#### `core/__init__.py`
- 添加UTF-8编码声明

#### `core/i18n.py`
- 添加底板分离相关的国际化文本

## 功能特点

1. **简单易用**：单个复选框控制，无需复杂配置
2. **固定白色**：底板颜色固定为白色（material_id=0），简化用户选择
3. **非侵入式**：默认值为False，保持原有行为不变
4. **向后兼容**：不传入参数时使用默认值，不影响现有代码

## 使用方法

```python
from core.converter import convert_image_to_3d

# 分离底板（底板作为独立白色对象）
result = convert_image_to_3d(
    image_path="test.png",
    lut_path="lut.npy",
    # ... 其他参数 ...
    separate_backing=True  # 勾选复选框
)

# 不分离底板（默认行为，底板与第一层合并）
result = convert_image_to_3d(
    image_path="test.png",
    lut_path="lut.npy",
    # ... 其他参数 ...
    separate_backing=False  # 或省略此参数
)
```

## 技术实现

- 当 `separate_backing=True` 时，内部使用 `backing_color_id=-2` 标记底板层
- 在网格生成阶段，为 `mat_id=-2` 生成独立的"Backing"对象
- 底板对象应用白色材质（`preview_colors[0]`）
- 当 `separate_backing=False` 时，使用 `backing_color_id=0`，底板与第一层合并

## 错误处理

- 复选框状态读取失败：回退到默认值False
- 底板层标记失败：回退到原始行为（backing_color_id=0）
- 底板网格生成失败：记录日志并继续生成其他材质网格
- 空底板网格：跳过并记录警告

## 注意事项

- 底板颜色固定为白色，不可选择
- 仅在勾选复选框时生成独立底板对象
- 不影响其他材质层的生成
- 与所有颜色系统兼容（CMYW、RYBW、6-Color、8-Color）
