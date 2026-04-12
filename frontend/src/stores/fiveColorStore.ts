import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { BaseColorEntry, FiveColorQueryResponse } from "../api/types";
import { fetchBaseColors, queryFiveColor, generateRecipeSwatch } from "../api/fiveColor";

// ========== Collected Recipe ==========

export interface CollectedRecipe {
  id: string;
  selectedIndices: number[];
  resultHex: string;
  baseColorNames: string[];
  baseColorHexes: string[];
  label: string;
}

// ========== State Interface ==========

export interface FiveColorState {
  lutName: string;
  baseColors: BaseColorEntry[];
  combinations: number[][] | null;
  selectedIndices: number[];
  queryResult: FiveColorQueryResponse | null;
  isLoading: boolean;
  error: string | null;
  collectedRecipes: CollectedRecipe[];
  swatchBlockSize: number;
  swatchGap: number;
  swatchCols: number;
  swatchStructureMode: string;
  isGeneratingSwatch: boolean;
  swatchDownloadUrl: string | null;
  swatchPreviewUrl: string | null;
}

// ========== Actions Interface ==========

export interface FiveColorActions {
  loadBaseColors: (lutName: string) => Promise<void>;
  addSelection: (index: number) => void;
  removeLastSelection: () => void;
  clearSelection: () => void;
  reverseSelection: () => void;
  submitQuery: () => Promise<void>;
  clearError: () => void;
  addToCollection: () => void;
  removeFromCollection: (id: string) => void;
  clearCollection: () => void;
  setSwatchBlockSize: (size: number) => void;
  setSwatchGap: (gap: number) => void;
  setSwatchCols: (cols: number) => void;
  setSwatchStructureMode: (mode: string) => void;
  generateSwatch: () => Promise<void>;
}

// ========== Default State ==========

const DEFAULT_STATE: FiveColorState = {
  lutName: "",
  baseColors: [],
  combinations: null,
  selectedIndices: [],
  queryResult: null,
  isLoading: false,
  error: null,
  collectedRecipes: [],
  swatchBlockSize: 15,
  swatchGap: 2,
  swatchCols: 0,
  swatchStructureMode: "Single-sided",
  isGeneratingSwatch: false,
  swatchDownloadUrl: null,
  swatchPreviewUrl: null,
};

// ========== Store ==========

export const useFiveColorStore = create<FiveColorState & FiveColorActions>()(
  persist(
    (set, get) => ({
      ...DEFAULT_STATE,

      loadBaseColors: async (lutName: string) => {
        set({
          lutName,
          selectedIndices: [],
          queryResult: null,
          combinations: null, // 先清空旧组合，强制拉取最新的
          isLoading: true,
          error: null,
        });
        try {
          const response = await fetchBaseColors(lutName);
          set({ 
            baseColors: response.colors, 
            combinations: response.combinations ?? null, 
            isLoading: false 
          });
        } catch (err) {
          set({
            error: err instanceof Error ? err.message : "加载基础颜色失败",
            isLoading: false,
          });
        }
      },

      addSelection: (index: number) => {
        const { selectedIndices } = get();
        if (selectedIndices.length < 5) {
          set({ selectedIndices: [...selectedIndices, index] });
        }
      },

      removeLastSelection: () => {
        const { selectedIndices } = get();
        set({
          selectedIndices: selectedIndices.slice(0, -1),
          queryResult: null,
        });
      },

      clearSelection: () => {
        set({ selectedIndices: [], queryResult: null });
      },

      reverseSelection: () => {
        const { selectedIndices } = get();
        if (selectedIndices.length === 5) {
          set({
            selectedIndices: [...selectedIndices].reverse(),
            queryResult: null,
          });
        }
      },

      submitQuery: async () => {
        const { selectedIndices, lutName } = get();
        if (selectedIndices.length !== 5) return;
        set({ isLoading: true, error: null });
        try {
          const response = await queryFiveColor({
            lut_name: lutName,
            selected_indices: selectedIndices,
          });
          set({ queryResult: response, isLoading: false });
        } catch (err) {
          set({
            error: err instanceof Error ? err.message : "查询失败",
            isLoading: false,
          });
        }
      },

      clearError: () => {
        set({ error: null });
      },

      addToCollection: () => {
        const { queryResult, selectedIndices, baseColors, lutName, collectedRecipes } = get();
        if (!queryResult?.found || !queryResult.result_hex) return;

        const isDuplicate = collectedRecipes.some(
          (r) =>
            r.selectedIndices.join(",") === selectedIndices.join(",") &&
            r.resultHex === queryResult.result_hex
        );
        if (isDuplicate) return;

        const label = selectedIndices
          .map((idx) => baseColors.find((c) => c.index === idx)?.name ?? `#${idx}`)
          .join(" → ");

        const recipe: CollectedRecipe = {
          id: `${lutName}_${selectedIndices.join("-")}_${Date.now()}`,
          selectedIndices: [...selectedIndices],
          resultHex: queryResult.result_hex,
          baseColorNames: baseColors.map((c) => c.name),
          baseColorHexes: baseColors.map((c) => c.hex),
          label,
        };
        set({ collectedRecipes: [...collectedRecipes, recipe] });
      },

      removeFromCollection: (id: string) => {
        const { collectedRecipes } = get();
        set({ collectedRecipes: collectedRecipes.filter((r) => r.id !== id) });
      },

      clearCollection: () => {
        set({ collectedRecipes: [], swatchDownloadUrl: null, swatchPreviewUrl: null });
      },

      setSwatchBlockSize: (size: number) => {
        set({ swatchBlockSize: Math.max(5, Math.min(50, size)) });
      },

      setSwatchGap: (gap: number) => {
        set({ swatchGap: Math.max(0.5, Math.min(10, gap)) });
      },

      setSwatchCols: (cols: number) => {
        set({ swatchCols: Math.max(0, Math.min(20, Math.round(cols))) });
      },

      setSwatchStructureMode: (mode: string) => {
        set({ swatchStructureMode: mode });
      },

      generateSwatch: async () => {
        const { collectedRecipes, lutName, swatchBlockSize, swatchGap, swatchCols, swatchStructureMode } = get();
        if (collectedRecipes.length === 0) return;
        set({ isGeneratingSwatch: true, error: null, swatchDownloadUrl: null, swatchPreviewUrl: null });
        try {
          const response = await generateRecipeSwatch({
            lut_name: lutName,
            recipes: collectedRecipes.map((r) => ({
              selected_indices: r.selectedIndices,
              result_hex: r.resultHex,
              base_color_names: r.baseColorNames,
              base_color_hexes: r.baseColorHexes,
            })),
            block_size_mm: swatchBlockSize,
            gap_mm: swatchGap,
            cols: swatchCols,
            structure_mode: swatchStructureMode,
          });
          set({
            swatchDownloadUrl: response.download_url,
            swatchPreviewUrl: response.preview_url,
            isGeneratingSwatch: false,
          });
        } catch (err) {
          set({
            error: err instanceof Error ? err.message : "Swatch generation failed",
            isGeneratingSwatch: false,
          });
        }
      },
    }),
    {
      name: "five-color-store",
      partialize: (state) => ({
        lutName: state.lutName,
        baseColors: state.baseColors,
        selectedIndices: state.selectedIndices,
        collectedRecipes: state.collectedRecipes,
        swatchBlockSize: state.swatchBlockSize,
        swatchGap: state.swatchGap,
        swatchCols: state.swatchCols,
        swatchStructureMode: state.swatchStructureMode,
      }),
    },
  ),
);
