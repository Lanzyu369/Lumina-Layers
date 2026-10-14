import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/system", () => ({
  getSettings: vi.fn(),
  saveSettings: vi.fn(),
}));

vi.mock("../stores/generatedArtifactInvalidation", () => ({
  invalidateGeneratedArtifacts: vi.fn(),
  registerGeneratedArtifactInvalidator: vi.fn(),
  captureGeneratedArtifactIdentity: vi.fn(
    (deviceProfileId: string, buildPlateId: string) => ({
      revision: 0,
      deviceProfileId,
      buildPlateId,
    }),
  ),
  isGeneratedArtifactIdentityCurrent: vi.fn(() => true),
  invalidatePreviewArtifacts: vi.fn(),
  registerPreviewArtifactInvalidator: vi.fn(),
  invalidateSingleItemDownload: vi.fn(),
  registerSingleItemDownloadInvalidator: vi.fn(),
}));

vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn(),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  convertGenerateLargeFormat: vi.fn(),
  convertGeneratePuzzle: vi.fn(),
  convertPuzzleLayoutPreview: vi.fn(),
  fetchLayerImages: vi.fn(),
  fetchBedSizes: vi.fn(),
  uploadHeightmap: vi.fn(),
  fetchLutColors: vi.fn(),
  cropImage: vi.fn(),
  convertBatch: vi.fn(),
  replaceColor: vi.fn(),
  colorHighlight: vi.fn(),
  detectRegion: vi.fn(),
  regionReplace: vi.fn(),
  applyRecipeOverride: vi.fn(),
  resetReplacements: vi.fn(),
  autoDetectColors: vi.fn(),
  cleanupSessionFiles: vi.fn(),
  uploadLut: vi.fn(),
}));

vi.mock("../api/materialCache", () => ({
  fetchMaterialColorSuggestions: vi.fn(),
}));

async function loadStores() {
  const settingsStoreModule = await import("../stores/settingsStore");
  const converterStoreModule = await import("../stores/converter");
  const systemApi = await import("../api/system");
  const converterApi = await import("../api/converter");
  const artifactModule =
    await import("../stores/generatedArtifactInvalidation");

  settingsStoreModule.useSettingsStore.setState({
    ...settingsStoreModule.DEFAULT_SETTINGS,
  });
  converterStoreModule.useConverterStore.setState({
    ...converterStoreModule.DEFAULT_STATE,
  });

  return {
    settingsStoreModule,
    converterStoreModule,
    systemApi,
    converterApi,
    artifactModule,
  };
}

describe("settings store hydration and base-layer modifier wiring", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    vi.unstubAllEnvs();
    localStorage.clear();
  });

  it("default enableBaseLayerHeightModifier is true", async () => {
    const { settingsStoreModule } = await loadStores();

    expect(
      settingsStoreModule.DEFAULT_SETTINGS.enableBaseLayerHeightModifier,
    ).toBe(true);
    expect(
      settingsStoreModule.useSettingsStore.getState()
        .enableBaseLayerHeightModifier,
    ).toBe(true);
    expect(
      settingsStoreModule.DEFAULT_SETTINGS.enableWipeTowerAutoPlacement,
    ).toBe(true);
    expect(
      settingsStoreModule.useSettingsStore.getState()
        .enableWipeTowerAutoPlacement,
    ).toBe(true);
  });

  it("hydrates older snapshots with completion notifications disabled", async () => {
    localStorage.setItem(
      "lumina-settings",
      JSON.stringify({
        state: {
          theme: "dark",
        },
        version: 1,
      }),
    );

    const settingsStoreModule = await import("../stores/settingsStore");

    expect(
      settingsStoreModule.useSettingsStore.getState()
        .enableCompletionNotifications,
    ).toBe(false);
    expect(
      settingsStoreModule.useSettingsStore.getState()
        .preserveUploadFilenameFor3mf,
    ).toBe(false);
    expect(settingsStoreModule.useSettingsStore.getState().theme).toBe("dark");
    expect(
      settingsStoreModule.useSettingsStore.getState()
        .enableWipeTowerAutoPlacement,
    ).toBe(true);
  });

  it("setEnableBaseLayerHeightModifier updates state and invalidates generated artifacts", async () => {
    const { settingsStoreModule, artifactModule } = await loadStores();

    settingsStoreModule.useSettingsStore
      .getState()
      .setEnableBaseLayerHeightModifier(false);

    expect(
      settingsStoreModule.useSettingsStore.getState()
        .enableBaseLayerHeightModifier,
    ).toBe(false);
    expect(artifactModule.invalidateGeneratedArtifacts).toHaveBeenCalledTimes(
      1,
    );
  });

  it("solver cache grid selection ships disabled with the low-tier default", async () => {
    const { settingsStoreModule } = await loadStores();

    expect(
      settingsStoreModule.DEFAULT_SETTINGS.enableSolverCacheGridSelection,
    ).toBe(false);
    expect(settingsStoreModule.DEFAULT_SETTINGS.solverCacheGridResolution).toBe(
      64,
    );
    expect(settingsStoreModule.SOLVER_CACHE_GRID_RESOLUTIONS).toEqual([
      64, 128, 256, 512, 1024, 2048,
    ]);
  });

  it("drops retired standalone service URL settings from persisted state", async () => {
    localStorage.setItem(
      "lumina-settings",
      JSON.stringify({
        state: {
          mlsBaseUrl: "http://localhost:5180",
          mlsBackendUrl: "http://localhost:8100",
          theme: "dark",
        },
        version: 1,
      }),
    );

    const settingsStoreModule = await import("../stores/settingsStore");
    const state = settingsStoreModule.useSettingsStore.getState() as unknown as Record<
      string,
      unknown
    >;

    expect(state.mlsBaseUrl).toBeUndefined();
    expect(state.mlsBackendUrl).toBeUndefined();
    expect(state.theme).toBe("dark");
  });

  it("does not pair legacy persisted device settings with the default H2D device profile", async () => {
    localStorage.setItem(
      "lumina-settings",
      JSON.stringify({
        state: {
          printerModel: "bambu-p1s",
          slicerSoftware: "OrcaSlicer",
          nozzleSize: "0.2",
        },
        version: 1,
      }),
    );

    const settingsStoreModule = await import("../stores/settingsStore");

    expect(settingsStoreModule.useSettingsStore.getState().printerModel).toBe(
      "bambu-p1s",
    );
    expect(settingsStoreModule.useSettingsStore.getState().slicerSoftware).toBe(
      "OrcaSlicer",
    );
    expect(settingsStoreModule.useSettingsStore.getState().nozzleSize).toBe(
      "0.2",
    );
    expect(settingsStoreModule.useSettingsStore.getState().deviceProfileId).toBe("");
  });

  it("setSolverCacheGridResolution accepts whitelisted tiers and rejects others", async () => {
    const { settingsStoreModule } = await loadStores();
    const { useSettingsStore } = settingsStoreModule;

    // Accepted: every value from the whitelist flips the store state.
    for (const tier of settingsStoreModule.SOLVER_CACHE_GRID_RESOLUTIONS) {
      useSettingsStore.getState().setSolverCacheGridResolution(tier);
      expect(useSettingsStore.getState().solverCacheGridResolution).toBe(tier);
    }

    // Rejected: arbitrary values leave the store at its last accepted tier
    // rather than poisoning it with an unsupported resolution.
    useSettingsStore.getState().setSolverCacheGridResolution(128);
    // TS would normally catch this; the cast emulates a malformed persisted
    // snapshot from an older or hand-edited client.
    useSettingsStore
      .getState()
      .setSolverCacheGridResolution(
        96 as unknown as 64 | 128 | 256 | 512 | 1024 | 2048,
      );
    expect(useSettingsStore.getState().solverCacheGridResolution).toBe(128);
  });

  it("setEnableSolverCacheGridSelection toggles the opt-in flag without touching the tier", async () => {
    const { settingsStoreModule } = await loadStores();
    const { useSettingsStore } = settingsStoreModule;

    useSettingsStore.getState().setSolverCacheGridResolution(256);
    useSettingsStore.getState().setEnableSolverCacheGridSelection(true);

    expect(useSettingsStore.getState().enableSolverCacheGridSelection).toBe(
      true,
    );
    expect(useSettingsStore.getState().solverCacheGridResolution).toBe(256);

    useSettingsStore.getState().setEnableSolverCacheGridSelection(false);
    expect(useSettingsStore.getState().enableSolverCacheGridSelection).toBe(
      false,
    );
    // Tier survives the toggle flip so a user who disables the feature
    // keeps their previous choice pre-filled when they re-enable it.
    expect(useSettingsStore.getState().solverCacheGridResolution).toBe(256);
  });

  it("svgPixelsPerMm defaults to 10.0 and clamps to one decimal", async () => {
    const { settingsStoreModule, artifactModule } = await loadStores();
    const { useSettingsStore } = settingsStoreModule;

    expect(settingsStoreModule.DEFAULT_SETTINGS.svgPixelsPerMm).toBe(10);

    useSettingsStore.getState().setSvgPixelsPerMm(25.54);
    expect(useSettingsStore.getState().svgPixelsPerMm).toBe(25.5);

    useSettingsStore.getState().setSvgPixelsPerMm(99);
    expect(useSettingsStore.getState().svgPixelsPerMm).toBe(50);

    useSettingsStore.getState().resetSvgPixelsPerMm();
    expect(useSettingsStore.getState().svgPixelsPerMm).toBe(10);
    expect(artifactModule.invalidateGeneratedArtifacts).toHaveBeenCalledTimes(
      3,
    );
  });

  it("material Delta-E00 tolerance defaults to 0.5 and normalizes finite setter input", async () => {
    const { settingsStoreModule, artifactModule } = await loadStores();
    const { useSettingsStore } = settingsStoreModule;

    expect(settingsStoreModule.DEFAULT_SETTINGS.materialDeltaE00Tolerance).toBe(
      0.5,
    );

    useSettingsStore.getState().setMaterialDeltaE00Tolerance(0.56);
    expect(useSettingsStore.getState().materialDeltaE00Tolerance).toBe(0.6);

    useSettingsStore.getState().setMaterialDeltaE00Tolerance(99);
    expect(useSettingsStore.getState().materialDeltaE00Tolerance).toBe(5);

    useSettingsStore.getState().setMaterialDeltaE00Tolerance(-1);
    expect(useSettingsStore.getState().materialDeltaE00Tolerance).toBe(0);

    useSettingsStore.getState().setMaterialDeltaE00Tolerance(Number.NaN);
    expect(useSettingsStore.getState().materialDeltaE00Tolerance).toBe(0.5);

    useSettingsStore.getState().setMaterialDeltaE00Tolerance(Number.POSITIVE_INFINITY);
    expect(useSettingsStore.getState().materialDeltaE00Tolerance).toBe(0.5);
    expect(artifactModule.invalidatePreviewArtifacts).toHaveBeenCalledTimes(5);
  });

  it("hydrates an old version-1 snapshot without tolerance at the new default", async () => {
    localStorage.setItem(
      "lumina-settings",
      JSON.stringify({
        state: { theme: "dark" },
        version: 1,
      }),
    );

    const settingsStoreModule = await import("../stores/settingsStore");

    expect(settingsStoreModule.useSettingsStore.getState()).toMatchObject({
      theme: "dark",
      materialDeltaE00Tolerance: 0.5,
    });
  });

  it.each([
    [0.56, 0.6],
    [99, 5],
    [-1, 0],
    ["not-a-number", 0.5],
  ])(
    "normalizes persisted material Delta-E00 tolerance %s to %s",
    async (persistedValue, expectedValue) => {
      localStorage.setItem(
        "lumina-settings",
        JSON.stringify({
          state: { materialDeltaE00Tolerance: persistedValue },
          version: 1,
        }),
      );

      const settingsStoreModule = await import("../stores/settingsStore");

      expect(
        settingsStoreModule.useSettingsStore.getState()
          .materialDeltaE00Tolerance,
      ).toBe(expectedValue);
    },
  );

  it("syncToBackend includes device slicer payload fields", async () => {
    const { settingsStoreModule, systemApi } = await loadStores();

    settingsStoreModule.useSettingsStore.setState({
      enableBaseLayerHeightModifier: false,
      enableWipeTowerAutoPlacement: false,
      customSlicerPath: "/Applications/Bambu Studio.app",
      customSlicerId: "bambu_studio",
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.2",
    });

    await settingsStoreModule.useSettingsStore.getState().syncToBackend();

    expect(systemApi.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        enable_base_layer_height_modifier: false,
        enable_wipe_tower_auto_placement: false,
        custom_slicer_path: "/Applications/Bambu Studio.app",
        custom_slicer_id: "bambu_studio",
        device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.2",
      }),
    );
  });

  it("persists and synchronizes Lumina Box diffuser backing percentages", async () => {
    const { settingsStoreModule, systemApi } = await loadStores();
    const { useSettingsStore } = settingsStoreModule;

    expect(useSettingsStore.getState().luminaBoxMeasurementBackingPercentXYZ).toEqual([
      "19.8",
      "19.7",
      "24.7",
    ]);
    useSettingsStore
      .getState()
      .setLuminaBoxMeasurementBackingPercentXYZ(["31.2", "32", "33"]);

    const persisted = JSON.parse(localStorage.getItem("lumina-settings") ?? "{}");
    expect(persisted.state.luminaBoxMeasurementBackingPercentXYZ).toEqual([
      "31.2",
      "32",
      "33",
    ]);

    await useSettingsStore.getState().syncToBackend();
    expect(systemApi.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ measurement_backing_percent_xyz: [31.2, 32, 33] }),
    );
  });

  it("hydrates the Lumina Box diffuser backing only when no local choice exists", async () => {
    const { settingsStoreModule } = await loadStores();
    const { useSettingsStore, DEFAULT_SETTINGS, deriveBackendDeviceSettingsPatch } = settingsStoreModule;

    useSettingsStore.getState().hydrateDeviceSettingsFromBackend({
      measurement_backing_percent_xyz: [17.5, 18.5, 19.5],
    });
    expect(useSettingsStore.getState().luminaBoxMeasurementBackingPercentXYZ).toEqual([
      "17.5",
      "18.5",
      "19.5",
    ]);

    expect(
      deriveBackendDeviceSettingsPatch(
        { ...DEFAULT_SETTINGS, luminaBoxMeasurementBackingPercentXYZ: ["31.2", "32", "33"] },
        { measurement_backing_percent_xyz: [17.5, 18.5, 19.5] },
        { luminaBoxMeasurementBackingPercentXYZ: ["31.2", "32", "33"] },
      ),
    ).toEqual({});
  });

  it("retains and synchronizes diffuser-free capture across reloads", async () => {
    const { settingsStoreModule, systemApi } = await loadStores();
    const { useSettingsStore } = settingsStoreModule;

    useSettingsStore.getState().hydrateDeviceSettingsFromBackend({
      measurement_backing_percent_xyz: [0, 0, 0],
    });
    expect(useSettingsStore.getState().luminaBoxMeasurementBackingPercentXYZ).toEqual([
      "0", "0", "0",
    ]);
    await useSettingsStore.getState().syncToBackend();
    expect(systemApi.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ measurement_backing_percent_xyz: [0, 0, 0] }),
    );
    const persisted = JSON.parse(localStorage.getItem("lumina-settings") ?? "{}");
    expect(persisted.state.luminaBoxMeasurementBackingPercentXYZ).toEqual(["0", "0", "0"]);

    useSettingsStore.setState({ luminaBoxMeasurementBackingPercentXYZ: ["19.8", "19.7", "24.7"] });
    localStorage.setItem("lumina-settings", JSON.stringify(persisted));
    await useSettingsStore.persist.rehydrate();
    expect(useSettingsStore.getState().luminaBoxMeasurementBackingPercentXYZ).toEqual([
      "0", "0", "0",
    ]);
    useSettingsStore.getState().hydrateDeviceSettingsFromBackend({
      measurement_backing_percent_xyz: [19.8, 19.7, 24.7],
    });
    expect(useSettingsStore.getState().luminaBoxMeasurementBackingPercentXYZ).toEqual([
      "0", "0", "0",
    ]);
  });

  it.each([
    ["", "", ""],
    [" ", "0", "0"],
    ["0", "19.7", "24.7"],
    ["-1", "19.7", "24.7"],
    ["NaN", "19.7", "24.7"],
    ["101", "19.7", "24.7"],
  ])("does not synchronize an invalid diffuser snapshot %s/%s/%s", async (x, y, z) => {
    const { settingsStoreModule, systemApi } = await loadStores();
    settingsStoreModule.useSettingsStore.getState()
      .setLuminaBoxMeasurementBackingPercentXYZ([x, y, z]);
    await settingsStoreModule.useSettingsStore.getState().syncToBackend();
    expect(systemApi.saveSettings).toHaveBeenCalled();
    expect(systemApi.saveSettings).toHaveBeenLastCalledWith(
      expect.not.objectContaining({ measurement_backing_percent_xyz: expect.anything() }),
    );
  });

  it("keeps a persisted Lumina Box diffuser choice during repeated backend hydration", async () => {
    localStorage.setItem(
      "lumina-settings",
      JSON.stringify({
        state: {
          luminaBoxMeasurementBackingPercentXYZ: ["31.2", "32", "33"],
        },
        version: 1,
      }),
    );

    const settingsStoreModule = await import("../stores/settingsStore");
    const { useSettingsStore } = settingsStoreModule;
    useSettingsStore.getState().hydrateDeviceSettingsFromBackend({
      measurement_backing_percent_xyz: [17.5, 18.5, 19.5],
    });

    expect(useSettingsStore.getState().luminaBoxMeasurementBackingPercentXYZ).toEqual([
      "31.2",
      "32",
      "33",
    ]);
  });

  it("syncToBackend includes cross-version user-interface preferences", async () => {
    const { settingsStoreModule, systemApi } = await loadStores();

    settingsStoreModule.useSettingsStore.setState({
      language: "en",
      theme: "dark",
      enableBlur: false,
      enableCompletionNotifications: true,
      solverCacheGridResolution: 512,
      svgPixelsPerMm: 22.5,
      materialDeltaE00Tolerance: 1.2,
    });

    await settingsStoreModule.useSettingsStore.getState().syncToBackend();

    expect(systemApi.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        language: "en",
        theme: "dark",
        enable_blur: false,
        enable_completion_notifications: true,
        solver_cache_grid_resolution: 512,
        svg_pixels_per_mm: 22.5,
        material_delta_e00_tolerance: 1.2,
      }),
    );
  });

  it("hydrates all shared backend settings for a fresh launcher origin", async () => {
    const { settingsStoreModule } = await loadStores();

    settingsStoreModule.useSettingsStore
      .getState()
      .hydrateDeviceSettingsFromBackend({
        language: "en",
        theme: "dark",
        last_lut: "Custom - shared",
        last_bed_label: "180×180 mm",
        enable_blur: false,
        enable_completion_notifications: true,
        preserve_upload_filename_for_3mf: true,
        enable_solver_cache_grid_selection: true,
        solver_cache_grid_resolution: 1024,
        svg_pixels_per_mm: 18.4,
        material_delta_e00_tolerance: 1.1,
        auto_replace_gradient_banding: true,
      });

    expect(settingsStoreModule.useSettingsStore.getState()).toMatchObject({
      language: "en",
      theme: "dark",
      lastLutName: "Custom - shared",
      lastBedLabel: "180×180 mm",
      enableBlur: false,
      enableCompletionNotifications: true,
      preserveUploadFilenameFor3mf: true,
      enableSolverCacheGridSelection: true,
      solverCacheGridResolution: 1024,
      svgPixelsPerMm: 18.4,
      materialDeltaE00Tolerance: 1.1,
      autoReplaceGradientBanding: true,
    });
  });

  it("persists the desktop default save folder through backend sync", async () => {
    const { settingsStoreModule, systemApi } = await loadStores();
    const store = settingsStoreModule.useSettingsStore;

    expect(store.getState().generatedFileDirectory).toBe("");
    store.getState().setGeneratedFileDirectory("  D:\\Prints\\Lumina  ");
    expect(store.getState().generatedFileDirectory).toBe("D:\\Prints\\Lumina");

    await store.getState().syncToBackend();
    expect(systemApi.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ generated_file_directory: "D:\\Prints\\Lumina" }),
    );
  });

  it("hydrates the default save folder only for a fresh origin", async () => {
    const { settingsStoreModule } = await loadStores();

    const fresh = settingsStoreModule.deriveBackendDeviceSettingsPatch(
      settingsStoreModule.DEFAULT_SETTINGS,
      { generated_file_directory: "D:\\Prints" },
      {},
    );
    expect(fresh.generatedFileDirectory).toBe("D:\\Prints");

    const local = settingsStoreModule.deriveBackendDeviceSettingsPatch(
      settingsStoreModule.DEFAULT_SETTINGS,
      { generated_file_directory: "D:\\Prints" },
      { generatedFileDirectory: "" },
    );
    expect(local.generatedFileDirectory).toBeUndefined();
  });

  it("keeps an origin-local preference when hydrating shared settings", async () => {
    const { settingsStoreModule } = await loadStores();

    const patch = settingsStoreModule.deriveBackendDeviceSettingsPatch(
      settingsStoreModule.DEFAULT_SETTINGS,
      { theme: "dark", language: "en" },
      { theme: "light" },
    );

    expect(patch.theme).toBeUndefined();
    expect(patch.language).toBe("en");
  });

  it("hydrates backend device_profile_id when there is no persisted choice", async () => {
    const { settingsStoreModule } = await loadStores();

    settingsStoreModule.useSettingsStore
      .getState()
      .hydrateDeviceSettingsFromBackend({
        device_profile_id: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
      });

    expect(settingsStoreModule.useSettingsStore.getState().deviceProfileId).toBe(
      "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
    );
  });

  it("keeps backend device_profile_id after hydrating related device fields", async () => {
    const { settingsStoreModule } = await loadStores();

    settingsStoreModule.useSettingsStore
      .getState()
      .hydrateDeviceSettingsFromBackend({
        printer_model: "bambu-p1s",
        slicer_software: "BambuStudio",
        nozzle_size: "0.2",
        device_profile_id: "BambuStudio:bbl:bambu-lab-p1s:0.2",
      });

    expect(settingsStoreModule.useSettingsStore.getState()).toMatchObject({
      printerModel: "bambu-p1s",
      slicerSoftware: "BambuStudio",
      nozzleSize: "0.2",
      deviceProfileId: "BambuStudio:bbl:bambu-lab-p1s:0.2",
    });
  });

  it("hydrates backend custom slicer path fields into the store", async () => {
    const { settingsStoreModule } = await loadStores();

    settingsStoreModule.useSettingsStore
      .getState()
      .hydrateDeviceSettingsFromBackend({
        custom_slicer_path: "/Applications/OrcaSlicer.app",
        custom_slicer_id: "orca_slicer",
      });

    expect(
      settingsStoreModule.useSettingsStore.getState().customSlicerPath,
    ).toBe("/Applications/OrcaSlicer.app");
    expect(settingsStoreModule.useSettingsStore.getState().customSlicerId).toBe(
      "orca_slicer",
    );
  });

  it("deriveBackendDeviceSettingsPatch respects persisted snapshot for base-layer modifier", async () => {
    const { settingsStoreModule } = await loadStores();

    const patch = settingsStoreModule.deriveBackendDeviceSettingsPatch(
      settingsStoreModule.DEFAULT_SETTINGS,
      {
        enable_base_layer_height_modifier: false,
      },
      {
        enableBaseLayerHeightModifier: true,
      },
    );

    expect(patch).toEqual({});
  });

  it("hydrates backend enable_base_layer_height_modifier=false into the store", async () => {
    const { settingsStoreModule } = await loadStores();

    settingsStoreModule.useSettingsStore
      .getState()
      .hydrateDeviceSettingsFromBackend({
        enable_base_layer_height_modifier: false,
      });

    expect(
      settingsStoreModule.useSettingsStore.getState()
        .enableBaseLayerHeightModifier,
    ).toBe(false);
  });

  it("does not overwrite a persisted base-layer modifier choice during hydration", async () => {
    localStorage.setItem(
      "lumina-settings",
      JSON.stringify({
        state: {
          enableBaseLayerHeightModifier: true,
        },
      }),
    );

    const { settingsStoreModule } = await loadStores();

    settingsStoreModule.useSettingsStore
      .getState()
      .hydrateDeviceSettingsFromBackend({
        enable_base_layer_height_modifier: false,
      });

    expect(
      settingsStoreModule.useSettingsStore.getState()
        .enableBaseLayerHeightModifier,
    ).toBe(true);
  });

  it("submitGenerate includes device and high-fidelity SVG settings", async () => {
    const { settingsStoreModule, converterStoreModule, converterApi } =
      await loadStores();

    vi.mocked(converterApi.convertGenerate).mockResolvedValue({
      status: "ok",
      message: "done",
      download_url: "/api/files/model",
      preview_3d_url: "/api/files/model.glb",
      threemf_disk_path: "E:/tmp/model.3mf",
    });

    settingsStoreModule.useSettingsStore.setState({
      enableBaseLayerHeightModifier: false,
      enableWipeTowerAutoPlacement: false,
      svgPixelsPerMm: 18.5,
      preserveUploadFilenameFor3mf: true,
    });
    converterStoreModule.useConverterStore.setState({
      ...converterStoreModule.DEFAULT_STATE,
      sessionId: "sess-1",
      lut_name: "test-lut",
      source_version: "legacy",
    });

    await converterStoreModule.useConverterStore.getState().submitGenerate();

    expect(converterApi.convertGenerate).toHaveBeenCalledWith(
      "sess-1",
      expect.objectContaining({
        enable_base_layer_height_modifier: false,
        enable_wipe_tower_auto_placement: false,
        svg_pixels_per_mm: 18.5,
      }),
      true,
    );
  });
});
