# Lumina Studio - EXE打包说明

## 快速打包

### 重要提示

**在打包之前，请确保：**
1. 关闭所有正在运行的 LuminaStudio.exe 进程
2. 如果之前打包过，关闭 dist 文件夹中的所有文件
3. 否则会因为文件被占用而导致打包失败

### 方法1：使用批处理脚本（推荐）

1. 确保已安装所有依赖：
```bash
pip install -r requirements.txt
```

2. 双击运行 `build_exe.bat`

3. 等待打包完成（首次打包可能需要5-10分钟）

4. 打包完成后，在 `LuminaStudio_v1.5.7_Windows` 文件夹中找到可执行文件

### 方法2：手动打包

1. 安装 PyInstaller：
```bash
pip install pyinstaller
```

2. 运行打包命令：
```bash
pyinstaller lumina_studio.spec --clean
```

3. 可执行文件位于：`dist\LuminaStudio\LuminaStudio.exe`

## 打包配置说明

### spec文件配置

`lumina_studio.spec` 文件包含了所有打包配置：

- **包含的数据文件**：
  - `assets/` - 资源文件（参考图像等）
  - `lut-npy预设/` - LUT预设文件
  - `icon.ico` - 应用图标
  - `core/`, `ui/`, `utils/` - 源代码模块
  - `config.py` - 配置文件

- **隐藏导入**：
  - 所有必需的Python包和子模块
  - Gradio及其依赖
  - 科学计算库（NumPy, SciPy）
  - 图像处理库（OpenCV, Pillow）
  - 3D处理库（Trimesh, Shapely）

- **排除的包**：
  - matplotlib, pandas, pytest（减小体积）

### 优化选项

- **UPX压缩**：启用，减小文件大小
- **控制台窗口**：启用（便于调试和查看日志）
- **单文件夹模式**：使用COLLECT模式，兼容性更好

## 兼容性说明

### Windows兼容性

- **支持系统**：Windows 7 SP1 及以上
- **架构**：x64（64位）
- **依赖**：无需安装Python或其他依赖

### 已知问题和解决方案

1. **首次启动慢**
   - 原因：需要解压和初始化所有库
   - 解决：正常现象，后续启动会快很多

2. **杀毒软件误报**
   - 原因：PyInstaller打包的exe可能被误报
   - 解决：添加到白名单，或使用代码签名

3. **缺少DLL错误**
   - 原因：系统缺少Visual C++运行库
   - 解决：安装 Microsoft Visual C++ Redistributable

## 测试清单

打包完成后，请测试以下功能：

- [ ] 程序能正常启动
- [ ] Web界面能正常打开
- [ ] 系统托盘图标显示正常
- [ ] 校准板生成功能正常
- [ ] 颜色提取功能正常
- [ ] 图像转换功能正常
- [ ] LUT文件上传和选择正常
- [ ] 所有模式（4色/6色/8色/黑白）都能正常工作

## 发布准备

### 创建发布包

1. 运行 `build_exe.bat` 完成打包

2. 发布包会自动创建在 `LuminaStudio_v1.5.7_Windows` 文件夹

3. 压缩该文件夹为 `.zip` 或 `.7z` 格式

4. 上传到 GitHub Releases

### 发布说明模板

```markdown
## Lumina Studio v1.5.7 - Windows版

### 下载
- [LuminaStudio_v1.5.7_Windows.zip](链接)

### 使用方法
1. 解压下载的压缩包
2. 双击 `LuminaStudio.exe` 启动程序
3. 等待浏览器自动打开（或手动访问 http://127.0.0.1:7860）

### 系统要求
- Windows 7 SP1 或更高版本
- 64位系统
- 至少 2GB 可用内存
- 至少 500MB 可用磁盘空间

### 新功能
- 6色模式支持（1296色）
- 8色模式支持（2738色）
- 黑白灰度模式（32级）
- 手动颜色修正功能
- 修复RYBW模式识别bug

### 已知问题
- 首次启动可能需要30秒到1分钟
- 部分杀毒软件可能误报（请添加到白名单）
```

## 高级选项

### 减小文件大小

如果需要减小exe大小，可以修改 `lumina_studio.spec`：

1. 禁用UPX压缩（如果UPX导致问题）：
```python
upx=False,
```

2. 排除更多不需要的包：
```python
excludes=[
    'matplotlib',
    'pandas',
    'pytest',
    'IPython',
    'jupyter',
    'tkinter',  # 如果不需要
],
```

### 单文件模式

如果需要打包成单个exe文件（不推荐，启动会更慢）：

修改 `lumina_studio.spec` 中的 EXE 部分：
```python
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,  # 添加这行
    a.zipfiles,  # 添加这行
    a.datas,     # 添加这行
    [],
    name='LuminaStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)

# 删除 COLLECT 部分
```

## 故障排除

### 打包失败

1. 确保所有依赖都已安装：
```bash
pip install -r requirements.txt
pip install pyinstaller
```

2. 清理缓存重新打包：
```bash
pyinstaller lumina_studio.spec --clean
```

3. 检查Python版本（推荐3.9-3.11）

### 运行时错误

1. 查看控制台输出的错误信息

2. 检查是否缺少数据文件（assets, lut-npy预设等）

3. 确保icon.ico文件存在

## 技术支持

如有问题，请访问：
- GitHub Issues: https://github.com/MOVIBALE/Lumina-Layers/issues
- 项目主页: https://github.com/MOVIBALE/Lumina-Layers
