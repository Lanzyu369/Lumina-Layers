import type {
  LutDetailsCatalogGroup,
  LutDetailsCatalogItem,
} from "../../api/types";

export const COLOR_MODE_BUCKETS = [
  "BW",
  "4-Color",
  "5-Color Extended",
  "6-Color",
  "8-Color",
  "Merged",
] as const;

export type ColorModeBucket = (typeof COLOR_MODE_BUCKETS)[number];

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
}

export function normalizeLutPath(path: string): string {
  return path.replace(/\\/g, "/").toLowerCase();
}

export function getColorModeBucket(colorMode: string): ColorModeBucket {
  const normalized = colorMode.toLowerCase();
  if (normalized.includes("4-color")) return "4-Color";
  if (normalized.includes("5-color")) return "5-Color Extended";
  if (normalized.includes("6-color")) return "6-Color";
  if (normalized.includes("8-color")) return "8-Color";
  if (normalized.includes("merged")) return "Merged";
  if (normalized.includes("bw")) return "BW";
  return "Merged";
}

function createEmptyBucketMap(): Record<ColorModeBucket, LutDetailsCatalogItem[]> {
  const buckets = Object.create(null) as Record<
    ColorModeBucket,
    LutDetailsCatalogItem[]
  >;
  for (const bucket of COLOR_MODE_BUCKETS) {
    buckets[bucket] = [];
  }
  return buckets;
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

  for (const group of groups) {
    const manufacturer = group.manufacturer;
    byManufacturer[manufacturer] ??= [];
    byManufacturerAndBucket[manufacturer] ??= createEmptyBucketMap();

    for (const item of group.items ?? []) {
      const bucket = getColorModeBucket(item.color_mode);
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
  return COLOR_MODE_BUCKETS.filter((bucket) => buckets[bucket].length > 0);
}
