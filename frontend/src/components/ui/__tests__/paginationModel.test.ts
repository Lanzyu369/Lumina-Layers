import { describe, expect, it } from "vitest";

import { buildPaginationItems, clampPage, resolvePageCount } from "../paginationModel";

describe("paginationModel", () => {
  it("resolves at least one page", () => {
    expect(resolvePageCount(0, 24)).toBe(1);
    expect(resolvePageCount(24, 24)).toBe(1);
    expect(resolvePageCount(25, 24)).toBe(2);
    expect(resolvePageCount(682, 24)).toBe(29);
  });

  it("clamps pages into range", () => {
    expect(clampPage(0, 5)).toBe(1);
    expect(clampPage(9, 5)).toBe(5);
    expect(clampPage(Number.NaN, 5)).toBe(1);
  });

  it("lists every page when there are few pages", () => {
    expect(buildPaginationItems(3, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  it("keeps first, last, and neighbours with gaps for many pages", () => {
    expect(buildPaginationItems(1, 29)).toEqual([1, 2, 3, 4, 5, "gap-end", 29]);
    expect(buildPaginationItems(4, 29)).toEqual([1, 2, 3, 4, 5, "gap-end", 29]);
    expect(buildPaginationItems(15, 29)).toEqual([1, "gap-start", 14, 15, 16, "gap-end", 29]);
    expect(buildPaginationItems(29, 29)).toEqual([1, "gap-start", 25, 26, 27, 28, 29]);
  });

  it("never hides a single page behind a gap", () => {
    for (let pageCount = 8; pageCount <= 12; pageCount += 1) {
      for (let page = 1; page <= pageCount; page += 1) {
        const items = buildPaginationItems(page, pageCount);
        const numbers = items.filter((item): item is number => typeof item === "number");
        items.forEach((item, index) => {
          if (typeof item !== "number") {
            const before = items[index - 1] as number;
            const after = items[index + 1] as number;
            expect(after - before).toBeGreaterThan(2);
          }
        });
        expect(numbers).toContain(page);
        expect(numbers[0]).toBe(1);
        expect(numbers[numbers.length - 1]).toBe(pageCount);
      }
    }
  });
});
