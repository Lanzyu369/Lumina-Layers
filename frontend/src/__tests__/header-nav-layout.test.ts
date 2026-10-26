import { describe, expect, it } from "vitest";
import {
  HEADER_NAV_GRID_CLASS,
  primaryTabsCellClass,
  primaryTabsCellShift,
  resolveHeaderNavFit,
  subTabRowJustifyClass,
  subTabsCenterShift,
  type HeaderNavFit,
} from "../components/widget/headerNavLayout";

// Widths measured from the Chinese converter header in compact mode.
const CHINESE_HEADER = {
  logoWidth: 32,
  brandTitleWidth: 152,
  primaryTabsWidth: 614,
  toolsWidth: 177,
  columnGap: 24,
};
const PADDING = 16;

// Thresholds that follow from the widths above.
const CENTERED_WITH_TITLE = 614 + 2 * (184 + 24);
const CENTERED_LOGO_ONLY = 614 + 2 * (177 + 24);
const LEFT_WITH_TITLE = 184 + 614 + 177 + 2 * 24;
const SIDE_BY_SIDE_LOGO_ONLY = 32 + 614 + 177 + 2 * 24;

function fit(alignment: "center" | "left", availableWidth: number): HeaderNavFit {
  return resolveHeaderNavFit(alignment, { ...CHINESE_HEADER, availableWidth }, PADDING);
}

function parseShift(shift: string): number {
  return Number.parseFloat(shift);
}

describe("header navigation layout rules", () => {
  it.each([[100, 24], [24, 192]])("centers on the window with asymmetric padding %s/%s", (left, right) => {
    const width = 1600;
    const result = resolveHeaderNavFit("center", { ...CHINESE_HEADER, availableWidth: width - left - right }, left, right);
    const brandSide = CHINESE_HEADER.logoWidth + CHINESE_HEADER.brandTitleWidth + CHINESE_HEADER.columnGap;
    const toolsSide = CHINESE_HEADER.toolsWidth + CHINESE_HEADER.columnGap;
    const cellCenter = (left + brandSide + width - right - toolsSide) / 2;
    expect(cellCenter + parseShift(primaryTabsCellShift(result))).toBe(width / 2);
    expect(result.showBrandTitle).toBe(true);
  });

  it("keeps the window axis when tabs wrap to their own row", () => {
    const result = resolveHeaderNavFit("center", { ...CHINESE_HEADER, availableWidth: 700 }, 100, 24);
    expect(result.singleRow).toBe(false);
    expect(primaryTabsCellShift(result)).toBe("-38px");
    expect(subTabsCenterShift(result)).toBe("-38px");
  });

  it("collapses the brand title before centered tabs leave the axis or wrap", () => {
    expect(fit("center", CENTERED_WITH_TITLE)).toMatchObject({
      singleRow: true,
      showBrandTitle: true,
    });
    expect(fit("center", CENTERED_WITH_TITLE - 1)).toMatchObject({
      singleRow: true,
      showBrandTitle: false,
    });
    expect(fit("center", CENTERED_LOGO_ONLY - 1)).toMatchObject({
      singleRow: true,
      showBrandTitle: false,
    });
    expect(fit("center", SIDE_BY_SIDE_LOGO_ONLY)).toMatchObject({
      singleRow: true,
      showBrandTitle: false,
    });
  });

  it("keeps the title while the tools are the tighter side and hiding it would not help", () => {
    // English header: the tools are wider than the brand, so the tabs must
    // leave the axis towards the brand whether or not the title is shown.
    const english = { logoWidth: 32, brandTitleWidth: 152, primaryTabsWidth: 887, toolsWidth: 223, columnGap: 24 };
    const sideBySideWithTitle = 184 + 887 + 223 + 2 * 24;
    const atWidth = (availableWidth: number) =>
      resolveHeaderNavFit("center", { ...english, availableWidth }, PADDING);

    expect(atWidth(887 + 2 * (223 + 24) - 1)).toMatchObject({ singleRow: true, showBrandTitle: true });
    expect(atWidth(sideBySideWithTitle)).toMatchObject({ singleRow: true, showBrandTitle: true });
    expect(atWidth(sideBySideWithTitle - 1)).toMatchObject({ singleRow: true, showBrandTitle: false });
  });

  it("moves the primary tabs to their own row only when they no longer fit beside the logo", () => {
    for (const alignment of ["center", "left"] as const) {
      expect(fit(alignment, SIDE_BY_SIDE_LOGO_ONLY - 1)).toMatchObject({
        singleRow: false,
        showBrandTitle: true,
        primaryTabsInsetPx: PADDING,
        centerLineClearance: null,
      });
    }
  });

  it("starts left-aligned tabs after the brand, or after the logo once the title is hidden", () => {
    expect(fit("left", LEFT_WITH_TITLE)).toMatchObject({
      singleRow: true,
      showBrandTitle: true,
      primaryTabsInsetPx: PADDING + 184 + 24,
      centerLineClearance: null,
    });
    expect(fit("left", LEFT_WITH_TITLE - 1)).toMatchObject({
      singleRow: true,
      showBrandTitle: false,
      primaryTabsInsetPx: PADDING + 32 + 24,
      centerLineClearance: null,
    });
  });

  it("keeps the title when a breakpoint already hides it", () => {
    const narrowBrand = { ...CHINESE_HEADER, brandTitleWidth: 0 };
    const result = resolveHeaderNavFit(
      "left",
      { ...narrowBrand, availableWidth: SIDE_BY_SIDE_LOGO_ONLY },
      PADDING,
    );
    expect(result.showBrandTitle).toBe(true);
  });

  it("reports how close the centre line may come to the brand and the tools", () => {
    expect(fit("center", CENTERED_WITH_TITLE).centerLineClearance).toMatchObject({
      brandSidePx: 184 + 24 + 307,
      toolsSidePx: 177 + 24 + 307,
    });
    expect(fit("center", CENTERED_WITH_TITLE - 1).centerLineClearance).toMatchObject({
      brandSidePx: 32 + 24 + 307,
      toolsSidePx: 177 + 24 + 307,
    });
  });

  it("describes both rows' shifts as CSS lengths", () => {
    const logoOnly = fit("center", CENTERED_WITH_TITLE - 1);
    expect(primaryTabsCellShift(logoOnly)).toBe(`${(508 - 363) / 2}px`);
    expect(subTabsCenterShift(logoOnly)).toBe("clamp(363px - 50%, 0px, 50% - 508px)");

    const wrapped = fit("center", SIDE_BY_SIDE_LOGO_ONLY - 1);
    expect(primaryTabsCellShift(wrapped)).toBe("0px");
    expect(subTabsCenterShift(wrapped)).toBe("0px");
    expect(subTabsCenterShift(fit("left", LEFT_WITH_TITLE))).toBe("0px");
  });

  it("puts both centered rows on the same centre line at every single-row width", () => {
    for (let width = SIDE_BY_SIDE_LOGO_ONLY; width <= CENTERED_WITH_TITLE + 40; width += 13) {
      const result = fit("center", width);
      const clearance = result.centerLineClearance;
      expect(clearance).not.toBeNull();
      if (!clearance) continue;

      // Header: the cell spans from the brand to the tools and its spacers
      // centre the tabs moved by the cell shift, stopping at the cell edges.
      const brandWidth = result.showBrandTitle ? 184 : 32;
      const cellStart = brandWidth + 24;
      const cellWidth = width - brandWidth - 177 - 2 * 24;
      const freeSpace = cellWidth - 614;
      const shift = parseShift(primaryTabsCellShift(result));
      const startSpacer = Math.min(
        Math.max(freeSpace / 2 + shift, 0),
        freeSpace,
      );
      const primaryCentre = cellStart + startSpacer + 614 / 2;

      // Sub row: clamp(brandSide - 50%, 0, 50% - toolsSide) across the row.
      const subShift = Math.max(
        clearance.brandSidePx - width / 2,
        Math.min(0, width / 2 - clearance.toolsSidePx),
      );

      expect(primaryCentre - width / 2).toBeCloseTo(subShift, 6);
    }
  });

  it("maps alignment to cell placement and row justification", () => {
    expect(HEADER_NAV_GRID_CLASS).toBe("grid-cols-[auto_minmax(0,1fr)_auto]");
    expect(primaryTabsCellClass("center", true)).toContain("col-start-2 row-start-1");
    expect(primaryTabsCellClass("center", true)).toContain("justify-center");
    expect(primaryTabsCellClass("left", false)).toContain("col-span-3 row-start-2");
    expect(primaryTabsCellClass("left", false)).toContain("justify-start");
    expect(subTabRowJustifyClass("center")).toBe("justify-center");
    expect(subTabRowJustifyClass("left")).toBe("justify-start");
  });
});
