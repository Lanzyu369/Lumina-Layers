import { create } from "zustand";
import type { MaterialSummary } from "../api/types";
import {
  deleteMaterial,
  exportMaterials,
  fetchMaterials,
  importMaterials,
} from "../api/materials";

function materialDirName(m: MaterialSummary): string {
  return String(m.directory_name ?? m.name ?? m.material_name ?? "");
}

function materialDisplayName(m: MaterialSummary): string {
  return String(m.material_name ?? m.name ?? m.directory_name ?? "");
}

interface MaterialsState {
  materials: MaterialSummary[];
  loading: boolean;
  error: string | null;
  selected: Set<string>;
  notice: string | null;
  load: () => Promise<void>;
  toggleSelect: (directoryName: string) => void;
  toggleSelectAll: () => void;
  clearSelection: () => void;
  remove: (directoryName: string) => Promise<void>;
  exportSelected: () => Promise<string | null>;
  importArchives: (files: File[]) => Promise<void>;
  clearNotice: () => void;
}

function errorMessage(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return String((err as { message: unknown }).message);
  }
  return "Failed";
}

export { materialDirName, materialDisplayName };

export const useMaterialsStore = create<MaterialsState>((set, get) => ({
  materials: [],
  loading: false,
  error: null,
  selected: new Set(),
  notice: null,

  load: async () => {
    set({ loading: true, error: null });
    try {
      const response = await fetchMaterials();
      set({ materials: response.materials, loading: false });
    } catch (err) {
      set({ loading: false, error: errorMessage(err) });
    }
  },

  toggleSelect: (directoryName) => {
    const next = new Set(get().selected);
    if (next.has(directoryName)) {
      next.delete(directoryName);
    } else {
      next.add(directoryName);
    }
    set({ selected: next });
  },

  toggleSelectAll: () => {
    const { materials, selected } = get();
    const allNames = materials.map(materialDirName).filter(Boolean);
    if (selected.size === allNames.length) {
      set({ selected: new Set() });
    } else {
      set({ selected: new Set(allNames) });
    }
  },

  clearSelection: () => set({ selected: new Set() }),

  remove: async (directoryName) => {
    await deleteMaterial(directoryName);
    const next = new Set(get().selected);
    next.delete(directoryName);
    set({ selected: next });
    await get().load();
  },

  exportSelected: async () => {
    const names = Array.from(get().selected);
    if (names.length === 0) return null;
    const result = await exportMaterials(names);
    return result.download_url;
  },

  importArchives: async (files) => {
    await importMaterials(files);
    await get().load();
  },

  clearNotice: () => set({ notice: null }),
}));
