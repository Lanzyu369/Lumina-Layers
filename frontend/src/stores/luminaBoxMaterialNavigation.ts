import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { BackedGradientSymbol } from "../api/luminaBoxBackedGradient";
import { useConverterStore } from "./converter";
import { useWidgetStore } from "./widgetStore";

interface LuminaBoxMaterialNavigation {
  libraryProfileKind: "stage_a" | "lumina_box";
  captureRequest: { datasetId: string; materialSymbol: BackedGradientSymbol; archive?: LuminaBoxArchiveIdentity } | null;
  lastCaptureArchive: { datasetId: string; materialSymbol: BackedGradientSymbol; archive: LuminaBoxArchiveIdentity } | null;
  showLibrary: () => void;
  resumeCapture: (datasetId: string, materialSymbol: BackedGradientSymbol, archive?: LuminaBoxArchiveIdentity) => void;
  useForConversion: (directoryName: string, materialSymbol?: BackedGradientSymbol) => void;
}

export interface LuminaBoxArchiveIdentity {
  name: string;
  brand: string;
  material_type: string;
  directoryName: string;
}

/** Route saved material actions to their working screens.
 * 将已保存耗材的操作连接到对应工作页面。 */
export const useLuminaBoxMaterialNavigation = create<LuminaBoxMaterialNavigation>()(persist((set) => ({
  libraryProfileKind: "stage_a",
  captureRequest: null,
  lastCaptureArchive: null,
  showLibrary: () => {
    set({ libraryProfileKind: "lumina_box" });
    useWidgetStore.getState().setActiveTab("material-library");
  },
  resumeCapture: (datasetId, materialSymbol, archive) => {
    set({ captureRequest: { datasetId, materialSymbol, ...(archive ? { archive } : {}) },
      lastCaptureArchive: archive ? { datasetId, materialSymbol, archive } : null });
    useWidgetStore.getState().setActiveTab("lumina-box");
  },
  useForConversion: (directoryName, materialSymbol) => {
    const converter = useConverterStore.getState();
    converter.setSourceVersion("lumina_box");
    const selected = useConverterStore.getState().selectedMaterialDirNames;
    converter.setSelectedMaterialDirNames([...new Set([...selected, directoryName])]);
    if (materialSymbol === "W") converter.setMaterialBackingMaterialDirName(directoryName);
    useWidgetStore.getState().setActiveTab("converter");
  },
}), { name: "lumina-box-material-navigation", partialize: (state) => ({ lastCaptureArchive: state.lastCaptureArchive }) }));
