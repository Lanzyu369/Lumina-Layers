import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/system", () => ({
  getSettings: vi.fn(),
  saveSettings: vi.fn(),
}));

vi.mock("../stores/generatedArtifactInvalidation", () => ({
  invalidateGeneratedArtifacts: vi.fn(),
  registerGeneratedArtifactInvalidator: vi.fn(),
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

  it("syncToBackend includes device slicer payload fields", async () => {
    const { settingsStoreModule, systemApi } = await loadStores();

    settingsStoreModule.useSettingsStore.setState({
      enableBaseLayerHeightModifier: false,
      customSlicerPath: "/Applications/Bambu Studio.app",
      customSlicerId: "bambu_studio",
    });

    await settingsStoreModule.useSettingsStore.getState().syncToBackend();

    expect(systemApi.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        enable_base_layer_height_modifier: false,
        custom_slicer_path: "/Applications/Bambu Studio.app",
        custom_slicer_id: "bambu_studio",
      }),
    );
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

  it("submitGenerate includes enable_base_layer_height_modifier from settingsStore", async () => {
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
      }),
    );
  });
});
