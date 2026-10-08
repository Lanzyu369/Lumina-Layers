# Lumina Box 用户指南 / User Guide

在 **耗材管理 → Lumina Box** 中，一次采集一种耗材，完成后保存到耗材库，
即可在图像转换中选用。

Open **Material Management → Lumina Box**, collect one filament, and save its
profile to the material library for image conversion.

## 准备样片 / Prepare samples

颜色层厚度为 **0.08、0.16、0.24、0.32、0.64、1.28、2.00 mm**。
每档分别使用白色、黑色耗材作背板，共十四张。整张样片总厚为 **3.00 mm**，
背板厚度为 3.00 mm 减去颜色层厚度。测量贴热床的一面。

Print each of the seven overlay thicknesses on white and black filament backings,
making fourteen samples. Every complete sample is **3.00 mm** thick; the backing
fills the remaining thickness. Measure the face that touched the print bed.

首次使用时设置背板，采集白叠黑、黑叠白各七档，以及 3 mm 纯白、纯黑参考片。
之后为其他耗材复用这组背板。已有黑白底采集记录可以直接继续使用。

For the initial backing setup, measure seven white-on-black and seven
black-on-white samples, plus bare 3 mm white and black references. Reuse the
setup for subsequent filaments. Existing backed-gradient readings can be resumed.

## 采集与使用 / Capture and use

1. 点击 **新建耗材**，填写名称、品牌、材质并选择背板耗材。
2. 点击 **连接 Lumina Box**，在表格中选中样片，在设备上选择对应厚度，
   使用 **Reflect** 测量。也可以手动输入 XYZ。
3. 读数自动保存。重测同一格时，之前的读数仍可查看和选用。
4. 完成十四格后点击 **生成耗材档案**，再 **保存到耗材库**。
5. 在耗材库点击 **用于图像转换**，选择一起使用的耗材，以及打印的实际
   背板材料和厚度，再预览、生成。

Create a material, connect the Box, select a table cell and measure with
**Reflect** at the matching thickness. Manual XYZ entry is also available.
Readings save automatically, including previous measurements. Complete the
fourteen cells, generate the profile and save it. Choose **Use in image
conversion**, select the other filaments and physical backing, then preview
and generate.

耗材库支持修改名称、品牌、重新采集和导入导出。导出的档案带有原始读数，
在另一台电脑导入后也能继续采集。

The library supports identity edits, resumed collection, import and export.
Exported profiles retain their original readings for continuing on another computer.
