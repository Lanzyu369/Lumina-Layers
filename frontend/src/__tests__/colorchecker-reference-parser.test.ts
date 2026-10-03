import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  loadSelectedColorcheckerReferenceKey,
  loadStoredColorcheckerReferences,
  makeStoredColorcheckerReference,
  parseColorcheckerReferenceRows,
  saveSelectedColorcheckerReferenceKey,
  saveStoredColorcheckerReferences,
  upsertStoredColorcheckerReference,
} from "../utils/colorcheckerReferences";

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

  it("accepts Number as the patch index header", () => {
    const numberOnlyRows = [
      ["Number", "sRGB", null, null, "Lab D50", null, null],
      [null, "R", "G", "B", "L*", "a*", "b*"],
      ...Array.from({ length: 24 }, (_item, index) => [
        index + 1,
        10 + index,
        20 + index,
        30 + index,
        50,
        0,
        0,
      ]),
    ];

    const parsed = parseColorcheckerReferenceRows(numberOnlyRows, "number-only.xlsx");

    expect(parsed.patches).toHaveLength(24);
    expect(parsed.patches[0]).toEqual({
      index: 1,
      label: "Patch 1",
      sRGB: [10, 20, 30],
      Lab_d50: [50, 0, 0],
    });
  });

  it("rejects incomplete triplets", () => {
    const badRows = rows.map((row) => [...row]);
    badRows[4][4] = null;

    expect(() => parseColorcheckerReferenceRows(badRows, "bad.xlsx")).toThrow(
      "三元组不完整",
    );
  });
});

describe("stored colorchecker references", () => {
  beforeEach(() => window.localStorage.clear());

  it("stores distinct uploaded references when LAN HTTP omits randomUUID", () => {
    const parsed = parseColorcheckerReferenceRows(rows, "reference.xlsx");
    const normalized = { patches: parsed.patches, source: parsed.source, warnings: [] };
    vi.stubGlobal("crypto", { getRandomValues: crypto.getRandomValues.bind(crypto) });
    try {
      const first = makeStoredColorcheckerReference(normalized, "reference");
      const second = makeStoredColorcheckerReference(normalized, "reference");
      expect(first.key).toMatch(/^custom:[\da-f]{32}$/);
      expect(second.key).not.toBe(first.key);
      expect(upsertStoredColorcheckerReference(first).persisted).toBe(true);
      expect(upsertStoredColorcheckerReference(second).persisted).toBe(true);
      expect(loadStoredColorcheckerReferences().map((item) => item.key))
        .toEqual([second.key, first.key]);
      expect(loadStoredColorcheckerReferences()[0].patches).toEqual(parsed.patches);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("uses independent record IDs and preserves reference values across reload", () => {
    const parsed = parseColorcheckerReferenceRows(rows, "reference.xlsx");
    const normalized = { patches: parsed.patches, source: parsed.source, warnings: [] };
    const first = makeStoredColorcheckerReference(normalized, "reference");
    const second = makeStoredColorcheckerReference(normalized, "reference");

    expect(first.key).toMatch(/^custom:.+/);
    expect(second.key).not.toBe(first.key);
    expect(first).not.toHaveProperty("referenceHash");
    expect(first.source).not.toHaveProperty("referenceHash");
    expect(upsertStoredColorcheckerReference(first).persisted).toBe(true);
    expect(upsertStoredColorcheckerReference(second).persisted).toBe(true);
    expect(saveSelectedColorcheckerReferenceKey(second.key)).toBe(true);

    const loaded = loadStoredColorcheckerReferences();
    expect(loaded.map((item) => item.key)).toEqual([second.key, first.key]);
    expect(loaded[0].patches).toEqual(parsed.patches);
    expect(loaded[0].source).toEqual(parsed.source);
    expect(loadSelectedColorcheckerReferenceKey()).toBe(second.key);
  });

  it("keeps legacy record and selection IDs while discarding retired digest metadata", () => {
    const parsed = parseColorcheckerReferenceRows(rows, "legacy.xlsx");
    const key = "custom:legacy-digest-key";
    window.localStorage.setItem("lumina.colorchecker.references.v1", JSON.stringify([{
      key,
      name: "legacy reference",
      patches: parsed.patches,
      source: { ...parsed.source, referenceHash: "old-digest" },
      referenceHash: "old-digest",
      warnings: [],
      createdAt: "2026-10-02T00:00:00Z",
    }]));
    saveSelectedColorcheckerReferenceKey(key);

    const loaded = loadStoredColorcheckerReferences();
    expect(loaded).toHaveLength(1);
    expect(loaded[0].key).toBe(key);
    expect(loaded[0].patches).toEqual(parsed.patches);
    expect(loaded[0].source).toEqual(parsed.source);
    expect(loaded[0]).not.toHaveProperty("referenceHash");
    expect(loadSelectedColorcheckerReferenceKey()).toBe(key);
    saveStoredColorcheckerReferences(loaded);
    expect(JSON.parse(window.localStorage.getItem("lumina.colorchecker.references.v1")!))
      .toEqual(loaded);
  });
});
