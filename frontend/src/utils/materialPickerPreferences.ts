import type { SavedMaterialLibraryItem } from "../api/types";

const MATERIAL_PROFILE_FAVORITES_KEY =
  "lumina_material_profile_favorites_v1";

export function favoriteKeyForMaterial(
  material: SavedMaterialLibraryItem,
): string {
  const profileId = material.material_profile_id?.trim();
  return profileId
    ? `profile:${profileId}`
    : `dir:${material.directory_name}`;
}

export function loadMaterialProfileFavorites(): Set<string> {
  try {
    const raw = localStorage.getItem(MATERIAL_PROFILE_FAVORITES_KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(
      parsed.filter(
        (value): value is string =>
          typeof value === "string" && value.trim().length > 0,
      ),
    );
  } catch {
    return new Set();
  }
}

export function saveMaterialProfileFavorites(
  favorites: ReadonlySet<string>,
): void {
  try {
    localStorage.setItem(
      MATERIAL_PROFILE_FAVORITES_KEY,
      JSON.stringify(Array.from(favorites)),
    );
  } catch {
    // Browser storage is best-effort; selection must remain usable.
  }
}
