// TODO: Split into light/dark variants via CSS custom properties or a
// theme-aware getter so these tokens respect the active theme.
export const UI_COLOR_TOKENS = {
  extractorMarkerFill: "rgba(255, 50, 50, 0.85)",
  extractorMarkerStroke: "#ffffff",
  extractorMarkerText: "#ffffff",
  extractorFixColorDefault: "#000000",
  extractorCellOverlayBorder: "2px solid rgba(96, 165, 250, 0.92)",
  extractorCellOverlayShadow: "0 0 0 1px rgba(255, 255, 255, 0.55)",
  fiveColorFallbackHex: "#666666",
} as const

