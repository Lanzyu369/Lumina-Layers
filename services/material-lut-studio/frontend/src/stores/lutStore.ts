import { create } from "zustand";
import type {
  CompareResponse,
  LutInfo,
  LutInfoResponse,
} from "../api/types";
import {
  compareLuts,
  fetchLutInfo,
  fetchLutList,
  uploadLut,
} from "../api/lut";

interface LutState {
  list: LutInfo[];
  listLoading: boolean;
  error: string | null;
  selectedName: string;
  selectedInfo: LutInfoResponse | null;
  infoLoading: boolean;
  // compare
  compareA: string;
  compareB: string;
  comparing: boolean;
  compareResult: CompareResponse | null;
  compareError: string | null;
  notice: string | null;

  loadList: () => Promise<void>;
  selectLut: (name: string) => Promise<void>;
  setCompareA: (name: string) => void;
  setCompareB: (name: string) => void;
  runCompare: () => Promise<void>;
  upload: (file: File) => Promise<void>;
  clearNotice: () => void;
}

function errorMessage(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return String((err as { message: unknown }).message);
  }
  return "Failed";
}

export const useLutStore = create<LutState>((set, get) => ({
  list: [],
  listLoading: false,
  error: null,
  selectedName: "",
  selectedInfo: null,
  infoLoading: false,
  compareA: "",
  compareB: "",
  comparing: false,
  compareResult: null,
  compareError: null,
  notice: null,

  loadList: async () => {
    set({ listLoading: true, error: null });
    try {
      const response = await fetchLutList();
      set({ list: response.luts, listLoading: false });
    } catch (err) {
      set({ listLoading: false, error: errorMessage(err) });
    }
  },

  selectLut: async (name) => {
    set({ selectedName: name, selectedInfo: null, infoLoading: Boolean(name) });
    if (!name) return;
    try {
      const info = await fetchLutInfo(name);
      if (get().selectedName !== name) return;
      set({ selectedInfo: info, infoLoading: false });
    } catch (err) {
      if (get().selectedName !== name) return;
      set({ infoLoading: false, error: errorMessage(err) });
    }
  },

  setCompareA: (name) => set({ compareA: name, compareResult: null }),
  setCompareB: (name) => set({ compareB: name, compareResult: null }),

  runCompare: async () => {
    const { compareA, compareB } = get();
    if (!compareA || !compareB) return;
    set({ comparing: true, compareError: null, compareResult: null });
    try {
      const result = await compareLuts({
        lut_a_name: compareA,
        lut_b_name: compareB,
        top_n: 10,
      });
      set({ comparing: false, compareResult: result });
    } catch (err) {
      set({ comparing: false, compareError: errorMessage(err) });
    }
  },

  upload: async (file) => {
    const result = await uploadLut(file);
    set({ notice: result.name });
    await get().loadList();
  },

  clearNotice: () => set({ notice: null }),
}));
