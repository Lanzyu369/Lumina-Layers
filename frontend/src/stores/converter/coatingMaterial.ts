import type { CoatingMaterialReference } from "../../api/types";

const STORAGE_KEY = "lumina_coatingMaterial";

/** Restore only a material identity; absence never selects a default filament. */
export function readCoatingMaterialReference(value: unknown): CoatingMaterialReference | null {
  if (!value || typeof value !== "object") return null;
  const reference = value as Partial<CoatingMaterialReference>;
  return (reference.source === "palette" || reference.source === "material_archive")
    && typeof reference.key === "string" && reference.key.trim().length > 0
    ? { source: reference.source, key: reference.key }
    : null;
}

export function loadCoatingMaterial(): CoatingMaterialReference | null {
  try {
    return readCoatingMaterialReference(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null"));
  } catch {
    return null;
  }
}

export function persistCoatingMaterial(material: CoatingMaterialReference | null): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(material));
  } catch {
    // Preferences remain optional in private browsing.
  }
}
