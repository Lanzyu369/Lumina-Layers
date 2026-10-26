import { ColorMode } from "../../api/types";
import type {
  LutDetailsCatalogGroup,
  LutDetailsCatalogItem,
} from "../../api/types";

export const COLOR_MODE_BUCKETS = [
  ColorMode.BW,
  ColorMode.FOUR_COLOR_CMYW,
  ColorMode.FOUR_COLOR_RYBW,
  "5-Color Extended",
  "5-Color Extended (1444)",
  ColorMode.SIX_COLOR,
  ColorMode.SIX_COLOR_RYBW,
  ColorMode.EIGHT_COLOR,
  ColorMode.MERGED,
] as const;

export type ColorModeBucket = string;

export interface LutCatalogIndex {
  groups: LutDetailsCatalogGroup[];
  byManufacturer: Record<string, LutDetailsCatalogItem[]>;
  byManufacturerAndBucket: Record<
    string,
    Record<ColorModeBucket, LutDetailsCatalogItem[]>
  >;
  manufacturerOf: Record<string, string>;
  bucketOf: Record<string, ColorModeBucket>;
  manufacturerByPath: Record<string, string>;
  bucketByPath: Record<string, ColorModeBucket>;
  colorModeByManufacturerAndBucket: Record<
    string,
    Record<ColorModeBucket, string>
  >;
}

export function normalizeLutPath(path: string): string {
  return path.replace(/\\/g, "/").toLowerCase();
}

export function getColorModeBucket(colorMode: string): ColorModeBucket {
  return colorMode.trim() || "Unknown";
}

export function getCompatibilityBucket(
  item: LutDetailsCatalogItem,
): ColorModeBucket {
  return item.compatibility_key?.trim() || getColorModeBucket(item.color_mode);
}

function getColorModeSortIndex(bucket: string): number {
  const exactIndex = COLOR_MODE_BUCKETS.findIndex((candidate) => candidate === bucket);
  if (exactIndex >= 0) {
    return exactIndex;
  }

  const normalized = bucket.toLowerCase();
  if (normalized.includes("bw")) return 0;
  if (normalized.includes("4-color")) return 1;
  if (normalized.includes("5-color")) return 3;
  if (normalized.includes("6-color")) return 5;
  if (normalized.includes("8-color")) return 7;
  if (normalized.includes("merged")) return 8;
  return COLOR_MODE_BUCKETS.length;
}

export function buildLutCatalogIndex(
  groups: LutDetailsCatalogGroup[],
): LutCatalogIndex {
  const byManufacturer: Record<string, LutDetailsCatalogItem[]> =
    Object.create(null);
  const byManufacturerAndBucket: Record<
    string,
    Record<ColorModeBucket, LutDetailsCatalogItem[]>
  > = Object.create(null);
  const manufacturerOf: Record<string, string> = Object.create(null);
  const bucketOf: Record<string, ColorModeBucket> = Object.create(null);
  const manufacturerByPath: Record<string, string> = Object.create(null);
  const bucketByPath: Record<string, ColorModeBucket> = Object.create(null);
  const colorModeByManufacturerAndBucket: Record<
    string,
    Record<ColorModeBucket, string>
  > = Object.create(null);

  for (const group of groups) {
    const manufacturer = group.manufacturer;
    byManufacturer[manufacturer] ??= [];
    byManufacturerAndBucket[manufacturer] ??= Object.create(null);
    colorModeByManufacturerAndBucket[manufacturer] ??= Object.create(null);

    for (const item of group.items ?? []) {
      const bucket = getColorModeBucket(item.color_mode);
      byManufacturerAndBucket[manufacturer][bucket] ??= [];
      colorModeByManufacturerAndBucket[manufacturer][bucket] ??=
        getColorModeBucket(item.color_mode);
      byManufacturer[manufacturer].push(item);
      byManufacturerAndBucket[manufacturer][bucket].push(item);
      manufacturerOf[item.name] = manufacturer;
      bucketOf[item.name] = bucket;
      manufacturerByPath[normalizeLutPath(item.path)] = manufacturer;
      bucketByPath[normalizeLutPath(item.path)] = bucket;
    }
  }

  return {
    groups,
    byManufacturer,
    byManufacturerAndBucket,
    manufacturerOf,
    bucketOf,
    manufacturerByPath,
    bucketByPath,
    colorModeByManufacturerAndBucket,
  };
}

export function findLutLocation(
  index: LutCatalogIndex,
  lutName: string,
): { manufacturer: string; bucket: ColorModeBucket } | null {
  const manufacturer = index.manufacturerOf[lutName];
  const bucket = index.bucketOf[lutName];
  if (!manufacturer || !bucket) {
    return null;
  }
  return { manufacturer, bucket };
}

export function findLutLocationByPath(
  index: LutCatalogIndex,
  path: string,
): { manufacturer: string; bucket: ColorModeBucket } | null {
  const key = normalizeLutPath(path);
  const manufacturer = index.manufacturerByPath[key];
  const bucket = index.bucketByPath[key];
  if (!manufacturer || !bucket) {
    return null;
  }
  return { manufacturer, bucket };
}

export function listLutsForManufacturer(
  index: LutCatalogIndex,
  manufacturer: string,
): LutDetailsCatalogItem[] {
  return index.byManufacturer[manufacturer] ?? [];
}

export function listBucketsForManufacturer(
  index: LutCatalogIndex,
  manufacturer: string,
): ColorModeBucket[] {
  const buckets = index.byManufacturerAndBucket[manufacturer];
  if (!buckets) {
    return [];
  }
  const colorModes = index.colorModeByManufacturerAndBucket[manufacturer] ?? {};
  return Object.keys(buckets)
    .filter((bucket) => buckets[bucket].length > 0)
    .sort((left, right) => {
      const leftMode = colorModes[left] ?? left;
      const rightMode = colorModes[right] ?? right;
      const rankDiff =
        getColorModeSortIndex(leftMode) - getColorModeSortIndex(rightMode);
      if (rankDiff !== 0) {
        return rankDiff;
      }
      const modeDiff = leftMode.localeCompare(rightMode);
      if (modeDiff !== 0) {
        return modeDiff;
      }
      return left.localeCompare(right);
    });
}

export function getBucketDisplayColorMode(
  index: LutCatalogIndex,
  manufacturer: string,
  bucket: ColorModeBucket,
): string {
  return (
    index.colorModeByManufacturerAndBucket[manufacturer]?.[bucket] ?? bucket
  );
}
