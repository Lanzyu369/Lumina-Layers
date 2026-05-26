import { describe, expect, it } from "vitest";

import { parseColorcheckerReferenceRows } from "../utils/colorcheckerReferences";

const rows = [
  ["大凡光学", "SN:DF-RCC-01240409"],
  [null],
  ["No", "Number", "sRGB", null, null, "CIE L*a*b*(d50)", null, null, "CIE L*a*b*(d65)", null, null],
  [null, null, "R", "G", "B", "L*", "a*", "b*", "L*", "a*", "b*"],
  ...Array.from({ length: 24 }, (_item, index) => [
    index + 1,
    `Patch ${index + 1}`,
    10 + index,
    20 + index,
    30 + index,
    50,
    1,
    -1,
    51,
    2,
    -2,
  ]),
];

describe("colorchecker reference parser", () => {
  it("parses the two-row merged-header xlsx shape", () => {
    const parsed = parseColorcheckerReferenceRows(rows, "大凡光学色值.xlsx");

    expect(parsed.source.sourceName).toBe("大凡光学色值");
    expect(parsed.source.serialNumber).toBe("DF-RCC-01240409");
    expect(parsed.source.patchCount).toBe(24);
    expect(parsed.patches).toHaveLength(24);
    expect(parsed.patches[0]).toEqual({
      index: 1,
      label: "Patch 1",
      sRGB: [10, 20, 30],
      Lab_d50: [50, 1, -1],
      Lab_d65: [51, 2, -2],
    });
  });

  it("allows partial color spaces when one complete triplet exists", () => {
    const partialRows = [
      ["No", "Number", "Lab D50", null, null],
      [null, null, "L*", "a*", "b*"],
      ...Array.from({ length: 24 }, (_item, index) => [
        index + 1,
        `Patch ${index + 1}`,
        50,
        0,
        0,
      ]),
    ];

    const parsed = parseColorcheckerReferenceRows(partialRows, "lab-only.xlsx");

    expect(parsed.patches[0].sRGB).toBeUndefined();
    expect(parsed.patches[0].Lab_d50).toEqual([50, 0, 0]);
  });

  it("parses compact single-row channel headers", () => {
    const compactRows = [
      ["No", "Number", "sRGB R", "sRGB G", "sRGB B", "Lab D50 L*", "Lab D50 a*", "Lab D50 b*"],
      ...Array.from({ length: 24 }, (_item, index) => [
        index + 1,
        `Patch ${index + 1}`,
        10,
        20,
        30,
        50,
        0,
        0,
      ]),
    ];

    const parsed = parseColorcheckerReferenceRows(compactRows, "compact.xlsx");

    expect(parsed.patches).toHaveLength(24);
    expect(parsed.patches[0].sRGB).toEqual([10, 20, 30]);
    expect(parsed.patches[0].Lab_d50).toEqual([50, 0, 0]);
  });

  it("rejects incomplete triplets", () => {
    const badRows = rows.map((row) => [...row]);
    badRows[4][4] = null;

    expect(() => parseColorcheckerReferenceRows(badRows, "bad.xlsx")).toThrow(
      "三元组不完整",
    );
  });
});
