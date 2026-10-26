/**
 * Card-mode layout utilities for LUT color grid.
 * LUT 颜色网格色卡模式布局工具函数。
 */

/**
 * Check whether card mode is available for a given LUT.
 * 判断指定 LUT 是否支持色卡模式。
 *
 * Card mode is available for standard (non-merged) LUTs.
 * 标准（非合并）LUT 支持色卡模式，合并 LUT 禁用。
 *
 * @param colorMode - The LUT's color mode string. (LUT 颜色模式)
 * @returns Whether card mode can be used. (是否可使用色卡模式)
 */
export function isCardModeAvailable(colorMode: string): boolean {
  return colorMode !== "" && colorMode.toLowerCase() !== "merged";
}
