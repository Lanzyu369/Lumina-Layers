import { create } from "zustand";
import type { CompareResponse, LutInfo, LutInfoResponse } from "../api/types";
import { apiErrorToVisibleMessage } from "../api/client";
import { compareLuts, fetchLutInfo } from "../api/lut";
import { fetchLutList as apiFetchLutList } from "../api/converter";

export interface LutCompareState {
  lutList: LutInfo[];
  lutListLoading: boolean;
  lutAName: string;
  lutBName: string;
  lutAInfo: LutInfoResponse | null;
  lutBInfo: LutInfoResponse | null;
  lutAInfoLoading: boolean;
  lutBInfoLoading: boolean;
  comparing: boolean;
  compareResult: CompareResponse | null;
  error: string | null;
}

export interface LutCompareActions {
  fetchLutList: () => Promise<void>;
  selectLutA: (name: string) => Promise<void>;
  selectLutB: (name: string) => Promise<void>;
  executeCompare: () => Promise<void>;
  clearError: () => void;
}

const DEFAULT_STATE: LutCompareState = {
  lutList: [],
  lutListLoading: false,
  lutAName: "",
  lutBName: "",
  lutAInfo: null,
  lutBInfo: null,
  lutAInfoLoading: false,
  lutBInfoLoading: false,
  comparing: false,
  compareResult: null,
  error: null,
};

export const useLutCompareStore = create<LutCompareState & LutCompareActions>(
  (set, get) => ({
    ...DEFAULT_STATE,

    fetchLutList: async () => {
      set({ lutListLoading: true, error: null });
      try {
        const response = await apiFetchLutList();
        set({ lutList: response.luts, lutListLoading: false, error: null });
      } catch (err) {
        set({
          lutListLoading: false,
          error: apiErrorToVisibleMessage(err),
        });
      }
    },

    selectLutA: async (name: string) => {
      set({
        lutAName: name,
        lutAInfo: null,
        lutAInfoLoading: Boolean(name),
        compareResult: null,
        error: null,
      });

      if (!name) {
        return;
      }

      try {
        const info = await fetchLutInfo(name);
        if (get().lutAName !== name) {
          return;
        }
        set({
          lutAInfo: info,
          lutAInfoLoading: false,
        });
      } catch (err) {
        if (get().lutAName !== name) {
          return;
        }
        set({
          lutAInfoLoading: false,
          error: apiErrorToVisibleMessage(err),
        });
      }
    },

    selectLutB: async (name: string) => {
      set({
        lutBName: name,
        lutBInfo: null,
        lutBInfoLoading: Boolean(name),
        compareResult: null,
        error: null,
      });

      if (!name) {
        return;
      }

      try {
        const info = await fetchLutInfo(name);
        if (get().lutBName !== name) {
          return;
        }
        set({
          lutBInfo: info,
          lutBInfoLoading: false,
        });
      } catch (err) {
        if (get().lutBName !== name) {
          return;
        }
        set({
          lutBInfoLoading: false,
          error: apiErrorToVisibleMessage(err),
        });
      }
    },

    executeCompare: async () => {
      const { lutAName, lutBName } = get();
      if (!lutAName || !lutBName) {
        return;
      }

      set({
        comparing: true,
        compareResult: null,
        error: null,
      });

      try {
        const result = await compareLuts({
          lut_a_name: lutAName,
          lut_b_name: lutBName,
          top_n: 10,
        });
        set({
          compareResult: result,
          comparing: false,
        });
      } catch (err) {
        set({
          comparing: false,
          error: apiErrorToVisibleMessage(err),
        });
      }
    },

    clearError: () => set({ error: null }),
  })
);
