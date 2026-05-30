import { create } from "zustand";
import type { SolverCacheEntry } from "../api/types";
import { deleteSolverCache, fetchSolverCaches } from "../api/solverCache";

interface SolverCacheState {
  entries: SolverCacheEntry[];
  loading: boolean;
  error: string | null;
  notice: string | null;
  load: () => Promise<void>;
  remove: (entry: SolverCacheEntry) => Promise<void>;
  clearNotice: () => void;
}

function errorMessage(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return String((err as { message: unknown }).message);
  }
  return "Failed";
}

export const useSolverCacheStore = create<SolverCacheState>((set, get) => ({
  entries: [],
  loading: false,
  error: null,
  notice: null,

  load: async () => {
    set({ loading: true, error: null });
    try {
      const response = await fetchSolverCaches();
      set({ entries: response.entries, loading: false });
    } catch (err) {
      set({ loading: false, error: errorMessage(err) });
    }
  },

  remove: async (entry) => {
    const dirNames = Array.isArray(entry.material_directory_names)
      ? (entry.material_directory_names as string[])
      : [];
    await deleteSolverCache({
      materialDirectoryNames: dirNames,
      layerCount: entry.layer_count,
      layerHeightMm: entry.layer_height_mm,
      substrate: entry.substrate,
      gridResolution: entry.grid_resolution,
    });
    await get().load();
  },

  clearNotice: () => set({ notice: null }),
}));
