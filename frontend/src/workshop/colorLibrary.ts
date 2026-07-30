import type {
  LutColorEntry,
  LutInfoResponse,
  SavedMaterialLibraryItem,
} from "../api/types";
import {
  resolveConverterSourceSelection,
  useConverterStore,
  type ConverterState,
} from "../stores/converter";
import type {
  WorkshopColorEntry,
  WorkshopColorLibrary,
} from "./contracts";


interface PublicMaterialSnapshot {
  lookupKey: string;
  label: string;
  publicMaterialId: string | null;
  hex: string | null;
}

type WorkshopColorState = Pick<
  ConverterState,
  | "source_version"
  | "lut_name"
  | "lut_names"
  | "lutListFull"
  | "legacyCatalogGroups"
  | "selectedLutInfo"
  | "lutColors"
  | "lutColorsLutName"
  | "nativeBrandGroups"
  | "selectedNativeBrandKey"
  | "selectedNativeDbNames"
  | "color_layers"
  | "layer_height_mm"
  | "selectedMaterialDirNames"
  | "materialLayerCount"
  | "materialLayerHeightMm"
>;

let materialCatalog = new Map<string, PublicMaterialSnapshot>();

function stableHash(value: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function publicId(prefix: string, source: unknown): string {
  return `${prefix}:${stableHash(JSON.stringify(source))}`;
}

function normalizeHex(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim().toUpperCase();
  if (/^#[0-9A-F]{6}$/.test(normalized)) {
    return normalized;
  }
  const short = normalized.match(/^#([0-9A-F])([0-9A-F])([0-9A-F])$/);
  if (short) {
    return `#${short[1]}${short[1]}${short[2]}${short[2]}${short[3]}${short[3]}`;
  }
  return null;
}

function hexFromRgb(value: unknown): string | null {
  if (
    !Array.isArray(value) ||
    value.length < 3 ||
    value.slice(0, 3).some(
      (channel) =>
        typeof channel !== "number" || !Number.isFinite(channel),
    )
  ) {
    return null;
  }
  const channels = value.slice(0, 3).map((channel) =>
    Math.max(0, Math.min(255, Math.round(channel as number))),
  );
  return `#${channels
    .map((channel) => channel.toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()}`;
}

function safePublicMaterialId(
  material: SavedMaterialLibraryItem,
): string | null {
  const candidates = [
    material.sync_material_id,
    material.material_product_id,
    material.material_profile_id,
  ];
  return (
    candidates.find(
      (candidate): candidate is string =>
        typeof candidate === "string" &&
        /^[A-Za-z0-9._:-]{1,128}$/.test(candidate),
    ) ?? null
  );
}

export function updateWorkshopMaterialCatalog(
  materials: readonly SavedMaterialLibraryItem[],
): void {
  const next = new Map<string, PublicMaterialSnapshot>();
  for (const material of materials) {
    if (
      typeof material.directory_name !== "string" ||
      material.directory_name.length === 0 ||
      typeof material.material_name !== "string" ||
      material.material_name.length === 0
    ) {
      continue;
    }
    next.set(material.directory_name, {
      lookupKey: material.directory_name,
      label: material.material_name,
      publicMaterialId: safePublicMaterialId(material),
      hex: hexFromRgb(material.estimated_rgb),
    });
  }
  materialCatalog = next;
}

export function clearWorkshopMaterialCatalog(): void {
  materialCatalog = new Map<string, PublicMaterialSnapshot>();
}

function paletteEntries(
  info: LutInfoResponse | null,
  fallback: readonly LutColorEntry[],
): WorkshopColorEntry[] {
  const entries = (info?.palette ?? [])
    .map((entry, index): WorkshopColorEntry | null => {
      const hex = normalizeHex(entry.hex_color);
      if (hex === null) {
        return null;
      }
      const label =
        entry.color_name?.trim() ||
        entry.color?.trim() ||
        `Color ${index + 1}`;
      return {
        id: `slot:${index}`,
        label,
        hex,
        materialId: null,
      };
    })
    .filter((entry): entry is WorkshopColorEntry => entry !== null);
  if (entries.length > 0) {
    return entries;
  }
  return fallback
    .map((entry, index): WorkshopColorEntry | null => {
      const hex = normalizeHex(entry.hex);
      return hex === null
        ? null
        : {
            id: `slot:${index}`,
            label: `Color ${index + 1}`,
            hex,
            materialId: null,
          };
    })
    .filter((entry): entry is WorkshopColorEntry => entry !== null);
}

function legacyLibrary(
  state: WorkshopColorState,
): WorkshopColorLibrary | null {
  const names =
    state.lut_names.length > 0
      ? state.lut_names
      : state.lut_name
        ? [state.lut_name]
        : [];
  const primaryName = names[0] ?? "";
  const info =
    state.selectedLutInfo?.name === primaryName &&
    state.selectedLutInfo.source_kind !== "native_bundle"
      ? state.selectedLutInfo
      : null;
  const fallback =
    state.lutColorsLutName === primaryName ? state.lutColors : [];
  const colors = paletteEntries(info, fallback);
  if (names.length === 0 || colors.length === 0) {
    return null;
  }
  return {
    id: publicId("lut", {
      names,
      colors: colors.map((entry) => entry.hex),
    }),
    label: names.join(", "),
    sourceKind: "lut",
    colors,
  };
}

function materialLibrary(
  state: WorkshopColorState,
): WorkshopColorLibrary | null {
  const colors = state.selectedMaterialDirNames
    .map((directoryName): WorkshopColorEntry | null => {
      const material = materialCatalog.get(directoryName);
      if (material?.hex === null || material === undefined) {
        return null;
      }
      const materialId = material.publicMaterialId;
      return {
        id: materialId
          ? `material:${materialId}`
          : `material:local-${stableHash(material.lookupKey)}`,
        label: material.label,
        hex: material.hex,
        materialId,
      };
    })
    .filter((entry): entry is WorkshopColorEntry => entry !== null);
  if (colors.length === 0) {
    return null;
  }
  return {
    id: publicId("material", {
      entries: colors.map((entry) => [entry.id, entry.hex]),
    }),
    label: colors.map((entry) => entry.label).join(", "),
    sourceKind: "material-archive",
    colors,
  };
}

function nativeLibrary(
  state: WorkshopColorState,
): WorkshopColorLibrary | null {
  const selection = resolveConverterSourceSelection(state);
  const brand = selection.native.brand;
  if (brand === null || !selection.isReady) {
    return null;
  }
  const selectedDbNames = selection.native.db_names;
  const info =
    state.selectedLutInfo?.source_kind === "native_bundle"
      ? state.selectedLutInfo
      : null;
  const fallback = selectedDbNames.includes(
    state.lutColorsLutName,
  )
    ? state.lutColors
    : [];
  const colors = paletteEntries(info, fallback);
  if (colors.length === 0) {
    return null;
  }
  return {
    id: publicId("native", {
      brand: brand.brand_key,
      databases: selectedDbNames,
      mode: selection.native.supported_mode,
      colors: colors.map((entry) => entry.hex),
    }),
    label: brand.display_name,
    sourceKind: "native-bundle",
    colors,
  };
}

export function buildWorkshopColorLibrary(
  state: WorkshopColorState = useConverterStore.getState(),
): WorkshopColorLibrary | null {
  const selection = resolveConverterSourceSelection(state);
  if (!selection.isReady) {
    return null;
  }
  if (state.source_version === "material") {
    return materialLibrary(state);
  }
  if (state.source_version === "native") {
    return nativeLibrary(state);
  }
  return legacyLibrary(state);
}
