import { describe, expect, it } from "vitest";
import * as fc from "fast-check";
import type {
  LutDetailsCatalogGroup,
  LutDetailsCatalogItem,
} from "../../api/types";
import { ColorMode } from "../../api/types";
import {
  COLOR_MODE_BUCKETS,
  buildLutCatalogIndex,
  findLutLocation,
  findLutLocationByPath,
  getColorModeBucket,
  listBucketsForManufacturer,
  listLutsForManufacturer,
  normalizeLutPath,
} from "../converter/legacyLutSelection";

const colorModes = [
  ColorMode.BW,
  ColorMode.FOUR_COLOR_CMYW,
  ColorMode.FOUR_COLOR_RYBW,
  ColorMode.FIVE_COLOR_EXT,
  ColorMode.SIX_COLOR,
  ColorMode.SIX_COLOR_RYBW,
  ColorMode.EIGHT_COLOR,
  ColorMode.MERGED,
  "5-Color Extended (1444)",
  "8-Color Max",
] as const;

const nameArb = fc
  .string({ minLength: 1, maxLength: 24 })
  .map((value) => value.trim())
  .filter((value) => value.length > 0);

function makeItem(
  name: string,
  manufacturer: string,
  colorMode: string,
  compatibilityKey = colorMode,
): LutDetailsCatalogItem {
  return {
    name,
    path: `/lut/${name}.npy`,
    color_mode: colorMode,
    compatibility_key: compatibilityKey,
    source_kind: "legacy_lookup",
    manufacturer,
    material_type: "",
    manufacturer_source: "metadata",
    material_source: "metadata",
    search_tokens: [name.toLowerCase(), manufacturer.toLowerCase()],
  };
}

function rowsToGroups(
  rows: Array<{
    name: string;
    manufacturer: string;
    colorMode: string;
    compatibilityKey?: string;
  }>,
): LutDetailsCatalogGroup[] {
  const grouped = new Map<string, LutDetailsCatalogItem[]>();
  for (const row of rows) {
    const items = grouped.get(row.manufacturer) ?? [];
    items.push(
      makeItem(
        row.name,
        row.manufacturer,
        row.colorMode,
        row.compatibilityKey ?? row.colorMode,
      ),
    );
    grouped.set(row.manufacturer, items);
  }
  return Array.from(grouped, ([manufacturer, items]) => ({
    manufacturer,
    items,
  }));
}

function expectedBucket(colorMode: string) {
  return colorMode.trim() || "Unknown";
}

describe("legacy LUT catalog selection helpers", () => {
  it("builds a stable index for arbitrary catalog input", () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            manufacturer: nameArb,
            items: fc.array(
              fc.record({
                name: nameArb,
                manufacturer: nameArb,
                colorMode: fc.string({ maxLength: 32 }),
              }),
              { maxLength: 12 },
            ),
          }),
          { maxLength: 12 },
        ),
        (groupsInput) => {
          const groups = groupsInput.map((group) => ({
            manufacturer: group.manufacturer,
            items: group.items.map((item) =>
              makeItem(item.name, item.manufacturer, item.colorMode),
            ),
          }));

          expect(() => buildLutCatalogIndex(groups)).not.toThrow();
          const index = buildLutCatalogIndex(groups);
          expect(index.groups).toBe(groups);
          expect(index.byManufacturer).toBeTypeOf("object");
          expect(index.byManufacturerAndBucket).toBeTypeOf("object");
          expect(index.manufacturerOf).toBeTypeOf("object");
          expect(index.bucketOf).toBeTypeOf("object");
        },
      ),
    );
  });

  it("maps every indexed LUT name back to its manufacturer and bucket", () => {
    fc.assert(
      fc.property(
        fc.uniqueArray(
          fc.record({
            name: nameArb,
            manufacturer: nameArb,
            colorMode: fc.constantFrom(...colorModes),
          }),
          { minLength: 1, maxLength: 30, selector: (row) => row.name },
        ),
        (rows) => {
          const groups = rowsToGroups(rows);
          const index = buildLutCatalogIndex(groups);

          for (const row of rows) {
            expect(findLutLocation(index, row.name)).toEqual({
              manufacturer: row.manufacturer,
              bucket: expectedBucket(row.colorMode),
            });
          }
          expect(findLutLocation(index, "__missing__")).toBeNull();
        },
      ),
    );
  });

  it("maps every indexed LUT path back to its manufacturer and bucket", () => {
    fc.assert(
      fc.property(
        fc.uniqueArray(
          fc.record({
            name: nameArb,
            manufacturer: nameArb,
            colorMode: fc.constantFrom(...colorModes),
          }),
          {
            minLength: 1,
            maxLength: 30,
            selector: (row) => normalizeLutPath(`/lut/${row.name}.npy`),
          },
        ),
        (rows) => {
          const groups = rowsToGroups(rows);
          const index = buildLutCatalogIndex(groups);

          for (const row of rows) {
            const item = groups
              .flatMap((group) => group.items)
              .find((candidate) => candidate.name === row.name)!;
            expect(findLutLocationByPath(index, item.path)).toEqual({
              manufacturer: row.manufacturer,
              bucket: expectedBucket(row.colorMode),
            });
          }
          expect(findLutLocationByPath(index, "/missing/path.npy")).toBeNull();
        },
      ),
    );
  });

  it("normalizeLutPath is case- and separator-insensitive", () => {
    expect(normalizeLutPath("E:\\Lumina\\foo.npy")).toBe(
      "e:/lumina/foo.npy",
    );
    expect(normalizeLutPath("E:/lumina/FOO.npy")).toBe("e:/lumina/foo.npy");
  });

  it("lists non-empty buckets in canonical order for each manufacturer", () => {
    fc.assert(
      fc.property(
        fc.uniqueArray(
          fc.record({
            name: nameArb,
            manufacturer: nameArb,
            colorMode: fc.constantFrom(...colorModes),
          }),
          { minLength: 1, maxLength: 30, selector: (row) => row.name },
        ),
        (rows) => {
          const groups = rowsToGroups(rows);
          const index = buildLutCatalogIndex(groups);

          for (const manufacturer of Object.keys(index.byManufacturer)) {
            const buckets = listBucketsForManufacturer(index, manufacturer);
            const bucketSet = new Set(buckets);
            expect(bucketSet.size).toBe(buckets.length);
            expect(
              buckets.every((bucket) =>
                (COLOR_MODE_BUCKETS as readonly string[]).includes(bucket),
              ),
            ).toBe(true);
            expect(buckets).toEqual(
              [...buckets].sort(
                (left, right) =>
                  (COLOR_MODE_BUCKETS as readonly string[]).indexOf(left) -
                  (COLOR_MODE_BUCKETS as readonly string[]).indexOf(right),
              ),
            );
            expect(
              buckets.every(
                (bucket) =>
                  (index.byManufacturerAndBucket[manufacturer]?.[bucket]
                    ?.length ?? 0) > 0,
              ),
            ).toBe(true);
          }
        },
      ),
    );
  });

  it("covers all catalog color_mode values used by the API enum", () => {
    for (const colorMode of colorModes) {
      expect(getColorModeBucket(colorMode)).toBe(expectedBucket(colorMode));
    }
    expect(getColorModeBucket("future custom catalog mode")).toBe(
      "future custom catalog mode",
    );
  });

  it("keeps CMYW and RYBW in separate color-mode buckets", () => {
    const groups = rowsToGroups([
      { name: "A-CMYW", manufacturer: "Brand A", colorMode: ColorMode.FOUR_COLOR_CMYW },
      { name: "A-RYBW", manufacturer: "Brand A", colorMode: ColorMode.FOUR_COLOR_RYBW },
    ]);
    const index = buildLutCatalogIndex(groups);

    expect(listBucketsForManufacturer(index, "Brand A")).toEqual([
      ColorMode.FOUR_COLOR_CMYW,
      ColorMode.FOUR_COLOR_RYBW,
    ]);
    expect(index.byManufacturerAndBucket["Brand A"]?.[ColorMode.FOUR_COLOR_CMYW])
      .toHaveLength(1);
    expect(index.byManufacturerAndBucket["Brand A"]?.[ColorMode.FOUR_COLOR_RYBW])
      .toHaveLength(1);
  });

  it("keeps same-mode LUTs together even when compatibility keys differ", () => {
    const groups = rowsToGroups([
      {
        name: "A-RYBW",
        manufacturer: "Brand A",
        colorMode: ColorMode.FOUR_COLOR_RYBW,
        compatibilityKey: "sig-a",
      },
      {
        name: "B-RYBW",
        manufacturer: "Brand A",
        colorMode: ColorMode.FOUR_COLOR_RYBW,
        compatibilityKey: "sig-b",
      },
    ]);
    const index = buildLutCatalogIndex(groups);

    expect(listBucketsForManufacturer(index, "Brand A")).toEqual([
      ColorMode.FOUR_COLOR_RYBW,
    ]);
    expect(index.byManufacturerAndBucket["Brand A"]?.[ColorMode.FOUR_COLOR_RYBW]?.map((item) => item.name))
      .toEqual(["A-RYBW", "B-RYBW"]);
  });

  it("lists LUTs only for the selected manufacturer", () => {
    const groups = rowsToGroups([
      { name: "A-4", manufacturer: "Brand A", colorMode: ColorMode.FOUR_COLOR_RYBW },
      { name: "A-8", manufacturer: "Brand A", colorMode: ColorMode.EIGHT_COLOR },
      { name: "B-BW", manufacturer: "Brand B", colorMode: ColorMode.BW },
    ]);
    const index = buildLutCatalogIndex(groups);

    expect(listLutsForManufacturer(index, "Brand A").map((item) => item.name))
      .toEqual(["A-4", "A-8"]);
    expect(listLutsForManufacturer(index, "Brand C")).toEqual([]);
  });
});
