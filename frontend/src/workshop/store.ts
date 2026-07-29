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
  diagnosticsModuleId: string | null;
  diagnosticsModuleVersion: string | null;
  openModule(moduleId: string): void;
  returnHome(): void;
  rememberProject(moduleId: string, projectId: string): void;
  openRecipe(source: WorkshopRecipeSource): void;
  clearPendingRecipe(): void;
  setDiagnostics(
    summary: WorkshopDiagnosticSummary | null,
    identity?: {
      moduleId: string;
      moduleVersion: string;
    },
  ): void;
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
      diagnosticsModuleId: null,
      diagnosticsModuleVersion: null,
      openModule: (moduleId) =>
        set({
          activeModuleId: moduleId,
          diagnostics: null,
          diagnosticsModuleId: null,
          diagnosticsModuleVersion: null,
        }),
      returnHome: () =>
        set({
          activeModuleId: null,
          pendingRecipeSource: null,
          diagnostics: null,
          diagnosticsModuleId: null,
          diagnosticsModuleVersion: null,
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
          diagnosticsModuleId: null,
          diagnosticsModuleVersion: null,
        }),
      clearPendingRecipe: () => set({ pendingRecipeSource: null }),
      setDiagnostics: (diagnostics, identity) =>
        set((state) =>
          diagnostics
            ? {
                diagnostics,
                diagnosticsModuleId:
                  identity?.moduleId ?? state.diagnosticsModuleId,
                diagnosticsModuleVersion:
                  identity?.moduleVersion ??
                  state.diagnosticsModuleVersion,
              }
            : {
                diagnostics: null,
                diagnosticsModuleId: null,
                diagnosticsModuleVersion: null,
              },
        ),
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
