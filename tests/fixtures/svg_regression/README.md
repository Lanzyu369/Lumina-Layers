# SVG Regression Fixtures

## 中文

这个目录用于保存会触发 SVG 转 3D 流程边缘精度、相邻颜色白缝、裁剪顺序或配色异常的最小复现 SVG。当前 Phase 0 只提供复现工具和目录说明，不在这里新增回归测试。

新增坏案例时，请把 SVG 命名为 `case_<n>_<short-slug>.svg`，例如 `case_001_white_seam.svg`。如果需要记录来源、观察到的缺陷、期望结果或相关参数，可以添加同编号说明文件 `case_<n>.notes.md`，例如 `case_001.notes.md`。

重新生成诊断 artefacts 的命令：

```powershell
python scripts/svg_converter_repro.py --svg tests/fixtures/svg_regression/case_<n>_<short-slug>.svg --out-root output/repro/case_<n>
```

如果要复现当前固定样本，请运行：

```powershell
python scripts/svg_converter_repro.py --svg test_images/1.svg --out-root output/repro/phase0
```

## English

This folder stores minimal SVG repro cases for edge precision, white seams between adjacent colors, clipping order, or color-matching regressions in the SVG-to-3D flow. Phase 0 only adds the repro tool and folder guidance; regression tests will be added later.

Name each new bad-case SVG as `case_<n>_<short-slug>.svg`, for example `case_001_white_seam.svg`. If the case needs source notes, observed behavior, expected behavior, or parameter context, add a matching `case_<n>.notes.md` file, for example `case_001.notes.md`.

Regenerate diagnostic artefacts with:

```powershell
python scripts/svg_converter_repro.py --svg tests/fixtures/svg_regression/case_<n>_<short-slug>.svg --out-root output/repro/case_<n>
```

To reproduce the current fixed sample, run:

```powershell
python scripts/svg_converter_repro.py --svg test_images/1.svg --out-root output/repro/phase0
```
