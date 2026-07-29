import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type {
  WorkshopDiagnosticSummary,
  WorkshopRecipeSource,
} from "./types";

export interface WorkshopShellState {
  activeModuleId: string | null;
  lastProjectIds: Record<string, string>;
  pendingRecipeSource: WorkshopRecipeSource | null;
  diagnostics: WorkshopDiagnosticSummary | null;
  openModule(moduleId: string): void;
  returnHome(): void;
  rememberProject(moduleId: string, projectId: string): void;
  openRecipe(source: WorkshopRecipeSource): void;
  clearPendingRecipe(): void;
  setDiagnostics(summary: WorkshopDiagnosticSummary | null): void;
}

type PersistedWorkshopShellState = Pick<
  WorkshopShellState,
  "activeModuleId" | "lastProjectIds"
>;

export const useWorkshopStore = create<WorkshopShellState>()(
  persist(
    (set) => ({
      activeModuleId: null,
      lastProjectIds: {},
      pendingRecipeSource: null,
      diagnostics: null,
      openModule: (moduleId) =>
        set({ activeModuleId: moduleId, diagnostics: null }),
      returnHome: () =>
        set({
          activeModuleId: null,
          pendingRecipeSource: null,
          diagnostics: null,
        }),
      rememberProject: (moduleId, projectId) =>
        set((state) => ({
          lastProjectIds: {
            ...state.lastProjectIds,
            [moduleId]: projectId,
          },
        })),
      openRecipe: (source) =>
        set({
          activeModuleId: source.moduleId,
          pendingRecipeSource: source,
          diagnostics: null,
        }),
      clearPendingRecipe: () => set({ pendingRecipeSource: null }),
      setDiagnostics: (diagnostics) => set({ diagnostics }),
    }),
    {
      name: "lumina-workshop-shell",
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: (state): PersistedWorkshopShellState => ({
        activeModuleId: state.activeModuleId,
        lastProjectIds: state.lastProjectIds,
      }),
    },
  ),
);
