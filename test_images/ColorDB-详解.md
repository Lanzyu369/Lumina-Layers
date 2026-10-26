# ColorDB（颜色数据库）详解

## 1. 概述

ColorDB（Color Database，颜色数据库）是 ChromaPrint3D 项目的核心数据结构，用于将**目标颜色映射到多色 3D 打印配方**。它本质上是一张"颜色查找表"：给定任意一个目标颜色，ColorDB 能快速找到最接近的打印配方（即每个颜色通道各打印多少层）。

ColorDB 是连接"用户想要的颜色"和"打印机实际能打出的颜色"之间的桥梁。

## 2. 核心概念

### 2.1 什么是"配方"（Recipe）

在多色 3D 打印中，一个像素点的最终颜色由多层不同颜色的薄层叠加决定。一个"配方"就是一组整数，表示每个颜色通道在该像素位置上打印的层数。

例如，对于一个 4 通道（RYBW）、5 层的配方 `[0, 2, 1, 0, 2]`：
- 第 1 层：通道 0（White）打 0 层
- 第 2 层：通道 1（Yellow）打 2 层
- 第 3 层：通道 2（Red）打 1 层
- 第 4 层：通道 3（Blue）打 0 层
- 第 5 层：通道 3（Blue）打 2 层

配方中每个值的范围是 `0–255`（`uint8_t`），实际常用值通常在 `0–max_color_layers` 之间。

### 2.2 什么是"条目"（Entry）

每个条目是一个 `(Lab颜色, 配方)` 对：
- `lab`：该配方打印后实际呈现的颜色，用 CIE Lab 色彩空间表示（L, a, b 三个浮点数）
- `recipe`：产生该颜色的打印层序列

### 2.3 什么是"调色板"（Palette）

调色板定义了打印机可用的颜色通道，每个通道包含：
- `color`：颜色名称（如 "Red"、"Cyan"、"White"）
- `material`：材料名称（如 "PLA Basic"、"PETG"）
- `hex_color`（可选）：十六进制颜色值（如 "#00AE42"）

## 3. 数据结构

### 3.1 C++ 类定义（`core/include/chromaprint3d/color_db.h`）

```cpp
struct Entry {
    Lab lab;                    // 目标颜色（CIE Lab 色彩空间）
    std::vector<uint8_t> recipe; // 打印配方（每通道层数）
};

struct Channel {
    std::string color;      // 颜色名称
    std::string material;   // 材料名称
    std::string hex_color;  // 十六进制颜色（可选）
};

class ColorDB {
    std::string name;              // 数据库名称
    int max_color_layers;          // 配方中最大颜色层数
    int base_layers;               // 底板层数
    int base_channel_idx;          // 底板使用的通道索引
    float layer_height_mm;         // 层高（毫米）
    float line_width_mm;           // 线宽（毫米）
    LayerOrder layer_order;        // 打印顺序（Top2Bottom / Bottom2Top）
    std::vector<Channel> palette;  // 调色板（通道列表）
    std::vector<Entry> entries;    // 颜色条目列表
};
```

### 3.2 JSON 文件格式

```json
{
    "name": "RYBW_008_5L_PLA_Basic",
    "max_color_layers": 5,
    "base_layers": 10,
    "base_channel_idx": 0,
    "layer_height_mm": 0.08,
    "line_width_mm": 0.42,
    "layer_order": "Top2Bottom",
    "palette": [
        { "color": "White",  "material": "PLA Basic" },
        { "color": "Yellow", "material": "PLA Basic" },
        { "color": "Red",    "material": "PLA Basic" },
        { "color": "Blue",   "material": "PLA Basic" }
    ],
    "entries": [
        {
            "lab": [93.87, -1.51, 1.32],
            "recipe": [0, 0, 0, 0, 0]
        },
        {
            "lab": [90.73, -6.30, 19.01],
            "recipe": [0, 0, 0, 0, 1]
        }
    ]
}
```

### 3.3 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 数据库唯一标识名 |
| `max_color_layers` | int | 每个配方的最大颜色层数（常见值：5 或 10） |
| `base_layers` | int | 底板层数（通常为 10） |
| `base_channel_idx` | int | 底板使用的通道索引（通常为 0，即 White） |
| `layer_height_mm` | float | 每层高度，单位毫米（常见值：0.04 或 0.08） |
| `line_width_mm` | float | 打印线宽，单位毫米（常见值：0.42） |
| `layer_order` | string | 打印顺序：`"Top2Bottom"` 或 `"Bottom2Top"` |
| `palette` | array | 通道调色板，每项含 `color` 和 `material` |
| `entries` | array | 颜色条目列表，每项含 `lab` 和 `recipe` |

## 4. 命名规范

预构建的 ColorDB 文件遵循以下命名规则：

```
{颜色缩写}_{层高}_{颜色层数}L[_{序号}].json
```

| 缩写 | 含义 | 通道数 | 颜色组合 |
|------|------|--------|----------|
| `RYBW` | Red-Yellow-Blue-White | 4 | 基础三原色 + 白 |
| `CMYW` | Cyan-Magenta-Yellow-White | 4 | 印刷三原色 + 白 |
| `BRGYKW` | Blue-Red-Green-Yellow-Black-White | 6 | 六色 |
| `CMGYKW` | Cyan-Magenta-Green-Yellow-Black-White | 6 | 六色 |
| `RYBWCMKG` | Red-Yellow-Blue-White-Cyan-Magenta-Black-Green | 8 | 全八色 |

层高编码：`008` = 0.08mm，`004` = 0.04mm

示例：`RYBWCMKG_004_10L` = 8 色、0.04mm 层高、10 层配方

## 5. 预构建数据库清单

所有预构建 ColorDB 存放在 `data/dbs/` 目录，按 `材料/厂商` 组织：

```
data/dbs/
├── PLA/
│   ├── Aliz/          (5 个 DB)
│   ├── BambooLab/     (4 个 DB)
│   ├── Creality/      (1 个 DB)
│   ├── Elegoo/        (1 个 DB)
│   ├── Jayo/          (1 个 DB)
│   └── R3D/           (1 个 DB)
└── PETG/
    ├── Aliz/          (5 个 DB)
    ├── CooBeen/       (1 个 DB)
    └── TianRui/       (1 个 DB)
```

### 完整清单

| 名称 | 条目数 | 通道 | 层数 | 层高 | 调色板 |
|------|--------|------|------|------|--------|
| RYBW_008_5L_PLA_Basic | 1024 | 4 | 5 | 0.08 | White, Yellow, Red, Blue |
| CMYW_008_5L_PLA_Basic | 1024 | 4 | 5 | 0.08 | White, Yellow, Magenta, Cyan |
| RYBWCMKG_008_5L_PLA_Basic_001 | 1024 | 8 | 5 | 0.08 | 8 色全通道 |
| RYBWCMKG_004_10L_PLA_Basic_1 | 1024 | 8 | 10 | 0.04 | 8 色全通道 |
| RYBW_008_5L_Aliz_PLA | 1024 | 4 | 5 | 0.08 | White, Red, Yellow, Blue |
| CMYW_008_5L_Aliz_PLA | 1007 | 4 | 5 | 0.08 | White, Cyan, Magenta, Yellow |
| BRGYKW_008_5L_Aliz_PLA | 1296 | 6 | 5 | 0.08 | White, Blue, Red, Green, Yellow, Black |
| CMGYKW_008_5L_Aliz_PLA | 1296 | 6 | 5 | 0.08 | White, Cyan, Magenta, Green, Yellow, Black |
| RYBWCMKG_008_5L_Aliz_PLA | 2738 | 8 | 5 | 0.08 | 8 色全通道 |
| RYBW_008_5L_PLA_Matte | 1024 | 4 | 5 | 0.08 | White, Red, Yellow, Blue |
| RYBW_008_5L_PLA_Plus | 1024 | 4 | 5 | 0.08 | White, Red, Yellow, Cyan |
| RYBW_008_5L_Hyper_PLA | 1024 | 4 | 5 | 0.08 | White, Red, Yellow, Cyan |
| RYBW_008_5L_Elegoo_PLA | 1024 | 4 | 5 | 0.08 | White, Red, Yellow, Blue |
| RYBW_008_5L_Aliz_PETG | 1024 | 4 | 5 | 0.08 | White, Red, Yellow, Blue |
| CMYW_008_5L_PETG | 951 | 4 | 5 | 0.08 | White, Cyan, Magenta, Yellow |
| BRGYKW_008_5L_PETG | 1296 | 6 | 5 | 0.08 | White, Blue, Red, Green, Yellow, Black |
| CMGYKW_008_5L_PETG | 1296 | 6 | 5 | 0.08 | White, Cyan, Magenta, Green, Yellow, Black |
| RYBWCMKG_008_5L_PETG | 2738 | 8 | 5 | 0.08 | 8 色全通道 |
| RYBW_008_5L_PETG_ECO | 1024 | 4 | 5 | 0.08 | White, Red, Yellow, Blue |
| RYBW_008_5L_CooBeen_PETG | 1024 | 4 | 5 | 0.08 | White, Red, Yellow, Cyan |


## 6. 生成流程

ColorDB 的生成遵循"校准板 → 拍照 → 提取颜色 → 建库"的流程：

### 6.1 步骤一：生成校准板

使用 `gen_calibration_board` 工具生成一个包含所有配方组合色块的 3MF 校准板模型：

```bash
./build/bin/gen_calibration_board --channels 4 --out board.3mf --meta board.json
```

校准板是一个网格，每个色块对应一种配方组合。同时生成 `board.json` 元数据文件，记录每个色块的位置和对应配方。

### 6.2 步骤二：打印并拍照

将校准板 3MF 文件发送到多色 3D 打印机打印，然后对打印结果拍照。

### 6.3 步骤三：构建 ColorDB

使用 `build_colordb` 工具从校准板照片中提取每个色块的实际颜色：

```bash
./build/bin/build_colordb --image calib_photo.png --meta board.json --out color_db.json
```

内部处理流程：
1. `LocateCalibrationColorRegion()` — 从照片中定位校准板的颜色区域
2. 对每个色块 ROI 取中心区域（去除边缘 10%）的 Lab 均值
3. 将同一配方的多个色块取平均值
4. 构建 `(Lab颜色, 配方)` 条目列表
5. 序列化为 JSON 文件

### 6.4 建模流水线生成（Python）

除了从实拍照片构建，ColorDB 也可以通过建模流水线生成：

```
step2_fit_stage_a.py  →  拟合单通道光学参数（E, k）
step3_fit_stage_b.py  →  拟合多通道叠色参数（gamma, delta, C0）
step4_select_recipes.py  →  从全配方空间中选取代表性配方，预测颜色，生成 ColorDB
step5_build_model_package.py  →  打包为运行时模型包
```

`step4_select_recipes.py` 使用 k-center 覆盖算法从巨大的配方空间中选取有代表性的配方子集（通常 1024 个），确保色域覆盖均匀。

## 7. 颜色匹配机制

### 7.1 KD-Tree 加速查找

ColorDB 内部维护两棵 KD-Tree（Lab 空间和 RGB 空间），用于快速最近邻查找：

```cpp
// 查找最接近目标颜色的单个条目
const Entry& nearest = db.NearestEntry(target_lab);

// 查找 k 个最近的条目
std::vector<const Entry*> top_k = db.NearestEntries(target_lab, 8);
```

KD-Tree 采用懒构建策略：首次查询时构建，之后缓存复用。构建过程线程安全（使用 `std::mutex` + `std::atomic` 双重检查锁定）。

### 7.2 在图像转换中的使用

在 `raster_to_3mf` / `svg_to_3mf` 转换流程中，对图像的每个像素：
1. 将像素颜色转换为 Lab 色彩空间
2. 在 ColorDB 中查找最近的条目（或 top-k 候选）
3. 使用匹配到的配方生成该像素位置的打印层

## 8. 系统集成

### 8.1 CLI 工具

| 工具 | 用途 | 关键参数 |
|------|------|----------|
| `build_colordb` | 从校准板照片构建 ColorDB | `--image`, `--meta`, `--out` |
| `raster_to_3mf` | 栅格图转 3MF（消费 ColorDB） | `--db` |
| `svg_to_3mf` | SVG 转 3MF（消费 ColorDB） | `--db` |
| `gen_calibration_board` | 生成校准板 | `--channels`, `--out`, `--meta` |

### 8.2 后端 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/databases` | GET | 列出所有全局预构建 ColorDB |
| `/api/v1/calibration/colordb` | POST | 从上传的校准板照片构建 ColorDB |
| `/api/v1/session/databases` | GET | 列出当前会话的 ColorDB |
| `/api/v1/session/databases/upload` | POST | 上传自定义 ColorDB 到会话 |
| `/api/v1/session/databases/{name}` | DELETE | 删除会话中的 ColorDB |
| `/api/v1/session/databases/{name}/download` | GET | 下载会话中的 ColorDB |

### 8.3 后端缓存架构

- `ColorDBCache`：启动时从 `data/dbs/` 递归加载所有 JSON 文件，按 `材料/厂商` 推断元数据
- `SessionStore`：管理用户会话级别的 ColorDB，支持上传、删除、过期清理
- 每个会话有最大 ColorDB 数量限制（可配置）

### 8.4 前端组件

- `ColorDBBuildSection.vue`：校准板构建 ColorDB 的 UI 组件
- `useColorDBBuildFlow.ts`：构建流程的 composable（上传图片 + 元数据 → 调用 API → 获取结果）
- `sessionColorDBService.ts`：会话 ColorDB 的 CRUD 服务

### 8.5 TypeScript 类型定义

```typescript
interface ColorDBInfo {
    name: string
    num_channels: number
    num_entries: number
    max_color_layers: number
    base_layers: number
    layer_height_mm: number
    line_width_mm: number
    palette: PaletteChannel[]
    source?: 'global' | 'session'
    material_type?: string
    vendor?: string
}
```
