import { create } from "zustand";

import { extractSingleStageDataset, fitStageA } from "../api/extractor";
import type { SingleStageDatasetSummary, StageAFitSummary } from "../api/types";
import { normalizeResourceUrl } from "../utils/resourceUrl";

export type ExtractorWorkflow = "legacy" | "single-stage";

interface SingleStageState {
  workflow: ExtractorWorkflow;
  datasetFile: File | null;
  isExtracting: boolean;
  extractError: string | null;
  sessionId: string | null;
  stageJsonUrl: string | null;
  warnings: string[];
  datasetSummary: SingleStageDatasetSummary | null;
  isFitting: boolean;
  fitError: string | null;
  stageAParamsUrl: string | null;
  fitSummary: StageAFitSummary | null;
}

interface SingleStageActions {
  setWorkflow: (workflow: ExtractorWorkflow) => void;
  setDatasetFile: (file: File | null) => void;
  submitExtract: () => Promise<void>;
  submitFit: () => Promise<void>;
  clearMessages: () => void;
}

const DEFAULT_STATE: SingleStageState = {
  workflow: "legacy",
  datasetFile: null,
  isExtracting: false,
  extractError: null,
  sessionId: null,
  stageJsonUrl: null,
  warnings: [],
  datasetSummary: null,
  isFitting: false,
  fitError: null,
  stageAParamsUrl: null,
  fitSummary: null,
};

export const useSingleStageStore = create<SingleStageState & SingleStageActions>(
  (set, get) => ({
    ...DEFAULT_STATE,

    setWorkflow: (workflow: ExtractorWorkflow) =>
      set({
        workflow,
        extractError: null,
        fitError: null,
      }),

    setDatasetFile: (file: File | null) =>
      set({
        datasetFile: file,
        extractError: null,
        fitError: null,
        stageJsonUrl: null,
        stageAParamsUrl: null,
        datasetSummary: null,
        fitSummary: null,
        warnings: [],
        sessionId: null,
      }),

    submitExtract: async () => {
      const state = get();
      if (!state.datasetFile) {
        set({ extractError: "Please choose a dataset zip first." });
        return;
      }

      set({ isExtracting: true, extractError: null, fitError: null });
      try {
        const response = await extractSingleStageDataset(state.datasetFile);
        set({
          sessionId: response.session_id,
          stageJsonUrl: normalizeResourceUrl(response.stage_json_url),
          warnings: response.warnings ?? [],
          datasetSummary: response.dataset_summary ?? null,
          stageAParamsUrl: null,
          fitSummary: null,
          isExtracting: false,
        });
      } catch (err) {
        set({
          extractError:
            err instanceof Error ? err.message : "Single-stage extraction failed",
          isExtracting: false,
        });
      }
    },

    submitFit: async () => {
      const state = get();
      if (!state.sessionId) {
        set({ fitError: "Extract a dataset before fitting Stage A." });
        return;
      }

      set({ isFitting: true, fitError: null });
      try {
        const response = await fitStageA({ sessionId: state.sessionId });
        set({
          stageAParamsUrl: normalizeResourceUrl(response.stage_a_params_url),
          fitSummary: response.fit_summary ?? null,
          isFitting: false,
        });
      } catch (err) {
        set({
          fitError:
            err instanceof Error ? err.message : "Stage A fitting failed",
          isFitting: false,
        });
      }
    },

    clearMessages: () =>
      set({
        extractError: null,
        fitError: null,
      }),
  }),
);
