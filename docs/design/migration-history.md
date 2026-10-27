# 界面设计迁移记录（历史快照）

本文于 2026-10-26 从根目录 DESIGN.md 移出，保存当时文档中的旧到新映射及迁移状态，不是本次重新核验的实现清单。原记录同时包含 2026-10-14 的核对说明和后续更新，时间与覆盖范围并不统一；不得用其中的 Migrated / Pending 判断当前页面是否符合最新规范。

当前实现与验收要求见 [DESIGN.md](../../DESIGN.md)，早期背景见 [Apple 风格参考](apple-reference.md)及[旧合规审查报告](../design-audit.md)。其中的装饰色点、旧控件引用和后续删除计划仅用于追溯，不构成当前要求。

## 旧到新映射

| Old | New |
|---|---|
| `sectionCardClass` / `resolveSectionCardClass` (28px card) | `cardPadClass` (16px card) |
| `workstationPanelCardClass` (28px muted card) | `cardClass` + explicit padding |
| `workstationInsetCardClass` (22px bordered inset) | `wellPadClass` (borderless well) |
| Colored-border `ToolbarGroup` chips | Borderless group: colored dot + small-caps label |
| `border-t border-slate-200/60 … dark:border-slate-700/60` | `border-t panel-divider` |
| Full-border status box | `.status-banner` left accent bar |

## 原迁移状态

设置页各分类复用 `cardPadClass` 作为唯一外层卡片，内部设备摘要和路径使用 10px 无边框凹槽，选项之间使用 `panel-divider`。普通选项标签统一 14px medium、次要墨色；组标题使用 14px semibold，弹窗标题使用 15px semibold。独立选项间距为 20px，开关行使用 16px 横向间距并垂直居中；开关展开的从属参数使用 `dependentGroupClass`。帮助说明统一由标签旁的 `HelpDot` 或控件的 `tooltip` 提供，兼容限制、当前状态和错误仍直接显示。分类导航复用主导航标签样式；打印机和打印板选项以底色及显式选中标记表达状态，内部不增加卡片描边或阴影。

> Verified against the working tree on 2026-10-14. An earlier revision of this document claimed Settings had already migrated; that was wrong, and is corrected below.
> 2026-10-14 按工作区实际代码核对。此前本文档写“设置页已迁移”与代码不符，已在下方更正。

| Area | Status |
|---|---|
| Colour Adjustment workstation — `PalettePanel`, `LutColorGrid`, `MaterialColorPicker`, `GradientGroupsPanel`, `ColorQuickReplacePanel`, `TargetColorPanel`, `SimilarRecipeList`, `MaterialLayerBenefitCurve`, `SelectionToolPicker` | **Migrated** |
| Colour Adjustment overlay — `Color2DOverlay`, `ColorPreview2D` | **Migrated** |
| Image Conversion — widget shells, `BasicSettings`, `ActionBar`, `BedSizeSelector`, `BatchResultSummary`, `UnifiedUploader`, `LegacyLutSelector`, `ImageUpload`, `FridgeMagnetSettings`, `PuzzleSettings`, `CloisonneSettings`, `Scene3D` toolbar | **Migrated** |
| LUT Management — `LutLibraryPanel`, `LutManagerPanel`, `LutCloudSyncPanel`, `LutDetailsPanel`, `LutComparePanel`, `MaterialCloudSyncPanel` | Migrated |
| Material Management — Lumina Box panels (`LuminaBoxMaterialPanel`, `LuminaBoxLibraryCard`, `LuminaBoxBackingSetup`, `LuminaBoxMaterialCapture`, `LuminaBoxStackSamplesPanel`) | Migrated |
| Material Management — `MaterialLibraryPanel`, `GradientCardGeneratePanel`, `GradientCardExtractPanel`, `MaterialRecipeQueryPanel` | **Pending** |
| LUT Management — `CalibrationPanel`, `ExtractorPanel`, `FiveColorQueryPanel`, `ColorcheckerConfirmDialog` | **Pending** |
| Image to Vector — `VectorizerPanel` | **Pending** |
| Settings — `SettingsPanel`, category navigation, device / build-plate chooser and setting rows | **Migrated** |
| Creative Workshop — `WorkshopPanel`, `ModuleDetails` | **Pending** |
| Dialogs — `CustomRecipeDialog`, `CustomRecipeSidePanel`, `MaterialPickerDialog`, `BugReportModal` | **Pending** (dialog shells keep their single card; inner panels still nest) |

Shared controls (`Button`, `Slider`, `Checkbox`, `RadioGroup`, `Dropdown`, field shells, `.status-banner`) are migrated platform-wide, so every page benefits even where its own containers are still pending.
共享控件已全站迁移，因此即使某一页的容器还没改，这些控件也已经干净。

Legacy helpers scheduled for removal once the last user migrates: `sectionCardClass`, `mutedSectionCardClass`, `workstationPanelCardClass`, `workstationInsetCardClass`, `workstationShellClass`, `resolveSectionCardClass` (all in `frontend/src/components/ui/panelPrimitives.tsx`).
`panelPrimitives.tsx` 里的旧常量在最后一个使用者迁移完成后删除。

## 临时验收入口

原云端仓库规范包含以下阶段性说明，现移出长期规范；这不表示本次已经删除或要求新增该入口：

> 新旧版对比入口是临时验收功能，两个版本共用数据和操作逻辑；切换不得清空搜索或中断正在执行的操作。
