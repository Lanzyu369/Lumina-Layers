import { beforeEach, describe, expect, it } from "vitest";
import { useLuminaBoxMaterialNavigation } from "../stores/luminaBoxMaterialNavigation";
import { useConverterStore, DEFAULT_STATE } from "../stores/converter";
import { useWidgetStore } from "../stores/widgetStore";

beforeEach(() => {
  useConverterStore.setState({ ...DEFAULT_STATE });
  useLuminaBoxMaterialNavigation.setState({ libraryProfileKind: "stage_a", captureRequest: null, lastCaptureArchive: null });
});

describe("Lumina Box material navigation", () => {
  it("opens the Box library and restores the requested material collection", () => {
    useLuminaBoxMaterialNavigation.getState().showLibrary();
    expect(useWidgetStore.getState().activeTab).toBe("material-library");
    expect(useLuminaBoxMaterialNavigation.getState().libraryProfileKind).toBe("lumina_box");
    useLuminaBoxMaterialNavigation.getState().resumeCapture("collection-1", "Y");
    expect(useWidgetStore.getState().activeTab).toBe("lumina-box");
    expect(useLuminaBoxMaterialNavigation.getState().captureRequest).toEqual({ datasetId: "collection-1", materialSymbol: "Y" });
  });
  it("adds saved materials to conversion and chooses white as backing", () => {
    useLuminaBoxMaterialNavigation.getState().useForConversion("box/red", "R");
    useLuminaBoxMaterialNavigation.getState().useForConversion("box/white", "W");
    useLuminaBoxMaterialNavigation.getState().useForConversion("box/red", "R");
    expect(useWidgetStore.getState().activeTab).toBe("converter");
    expect(useConverterStore.getState()).toMatchObject({ source_version: "lumina_box", selectedMaterialDirNames: ["box/red", "box/white"], materialBackingMaterialDirName: "box/white" });
  });
  it("retains the saved archive identity after a reload without forcing a navigation", async () => {
    const identity = { name: "PETG红色", brand: "KYNIX", material_type: "PETG", directoryName: "old-directory" };
    useLuminaBoxMaterialNavigation.getState().resumeCapture("collection-1", "R", identity);
    useLuminaBoxMaterialNavigation.setState({ captureRequest: null });
    const stored = localStorage.getItem("lumina-box-material-navigation")!;
    useLuminaBoxMaterialNavigation.setState({ lastCaptureArchive: null });
    localStorage.setItem("lumina-box-material-navigation", stored);
    await useLuminaBoxMaterialNavigation.persist.rehydrate();
    expect(useLuminaBoxMaterialNavigation.getState().captureRequest).toBeNull();
    expect(useLuminaBoxMaterialNavigation.getState().lastCaptureArchive).toEqual({ datasetId: "collection-1", materialSymbol: "R", archive: identity });
  });
});
