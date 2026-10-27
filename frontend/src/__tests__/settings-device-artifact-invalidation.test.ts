import { beforeEach, describe, expect, it } from "vitest";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";
import { useConverterStore } from "../stores/converter";

describe("device setting changes invalidate generated 3MF artifacts", () => {
  beforeEach(() => {
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    useConverterStore.setState({
      modelUrl: "/api/files/fake-preview-glb",
      threemfDiskPath: "E:/fake/model.3mf",
      downloadUrl: "/api/files/fake-3mf",
    });
  });

  it("clears generated artifacts when printer changes", async () => {
    useSettingsStore.getState().setPrinterModel("bambu-p1s");

    expect(useConverterStore.getState().modelUrl).toBeNull();
    expect(useConverterStore.getState().threemfDiskPath).toBeNull();
    expect(useConverterStore.getState().downloadUrl).toBeNull();
  });

  it("updates the matching printer bed label before the action returns", () => {
    useConverterStore.setState({
      bed_label: "256×256 mm",
      bedSizes: [
        {
          label: "350×320 mm",
          width_mm: 350,
          height_mm: 320,
          is_default: false,
          printer_id: "bambu-h2d",
        },
        {
          label: "256×256 mm",
          width_mm: 256,
          height_mm: 256,
          is_default: true,
          printer_id: "bambu-p1s",
        },
      ],
    });

    useSettingsStore.getState().setPrinterModel("bambu-h2d");

    expect(useConverterStore.getState().bed_label).toBe("350×320 mm");
  });

  it("clears generated artifacts when slicer changes", async () => {
    useSettingsStore.getState().setSlicerSoftware("OrcaSlicer");

    expect(useConverterStore.getState().modelUrl).toBeNull();
    expect(useConverterStore.getState().threemfDiskPath).toBeNull();
    expect(useConverterStore.getState().downloadUrl).toBeNull();
  });

  it("clears generated artifacts when wipe-tower auto placement changes", () => {
    useSettingsStore.getState().setEnableWipeTowerAutoPlacement(false);

    expect(useConverterStore.getState().modelUrl).toBeNull();
    expect(useConverterStore.getState().threemfDiskPath).toBeNull();
    expect(useConverterStore.getState().downloadUrl).toBeNull();
  });

  it("clears generated artifacts when nozzle size changes", async () => {
    useConverterStore.setState({
      previewGlbUrl: "/api/files/nozzle-preview.glb",
      previewImageUrl: "/api/files/nozzle-preview.png",
      layerImages: [
        {
          layer_index: 0,
          name: "Layer 1",
          url: "/api/files/nozzle-layer.png",
        },
      ],
    });
    useSettingsStore.getState().setNozzleSize("0.2");

    expect(useConverterStore.getState().modelUrl).toBeNull();
    expect(useConverterStore.getState().previewGlbUrl).toBeNull();
    expect(useConverterStore.getState().previewImageUrl).toBeNull();
    expect(useConverterStore.getState().layerImages).toEqual([]);
    expect(useConverterStore.getState().threemfDiskPath).toBeNull();
    expect(useConverterStore.getState().downloadUrl).toBeNull();
  });

  it("keeps converter previews while clearing build-plate-specific downloads", () => {
    const batchPreviewItems = [
      {
        url: "/api/files/batch-preview.glb",
        filename: "preview.png",
        tx_mm: 0,
        ty_mm: 0,
        width_mm: 20,
        depth_mm: 20,
      },
    ];
    useConverterStore.setState({
      modelUrl: "/api/files/model-only-preview.glb",
      previewGlbUrl: null,
      batchPreviewItems,
      batchResult: {
        status: "ok",
        message: "old batch",
        download_url: "/api/files/old-batch.3mf",
        threemf_disk_path: null,
        preview_3d_url: null,
        results: [],
        warnings: [],
      },
    });

    useSettingsStore
      .getState()
      .setBuildPlateForMachine(
        "BambuStudio:bbl:bambu-lab-h2d",
        "textured-pei-plate",
      );

    expect(useConverterStore.getState()).toMatchObject({
      modelUrl: "/api/files/model-only-preview.glb",
      previewGlbUrl: null,
      batchPreviewItems,
      batchResult: null,
      threemfDiskPath: null,
      downloadUrl: null,
    });
  });

  it("does not invalidate artifacts when the selected build plate is unchanged", () => {
    useSettingsStore.setState({
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
      buildPlateId: "textured-pei-plate",
      buildPlateSelections: {
        "BambuStudio:bbl:bambu-lab-h2d": "textured-pei-plate",
      },
    });

    useSettingsStore
      .getState()
      .setBuildPlateForMachine(
        "BambuStudio:bbl:bambu-lab-h2d",
        "textured-pei-plate",
      );

    expect(useConverterStore.getState()).toMatchObject({
      modelUrl: "/api/files/fake-preview-glb",
      threemfDiskPath: "E:/fake/model.3mf",
      downloadUrl: "/api/files/fake-3mf",
    });
  });
});
