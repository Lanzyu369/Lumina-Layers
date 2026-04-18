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
  const artifactModule = await import("../stores/generatedArtifactInvalidation");

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

    expect(settingsStoreModule.DEFAULT_SETTINGS.enableBaseLayerHeightModifier).toBe(
      true,
    );
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
    expect(artifactModule.invalidateGeneratedArtifacts).toHaveBeenCalledTimes(1);
  });

  it("syncToBackend includes enable_base_layer_height_modifier payload field", async () => {
    const { settingsStoreModule, systemApi } = await loadStores();

    settingsStoreModule.useSettingsStore.setState({
      enableBaseLayerHeightModifier: false,
    });

    await settingsStoreModule.useSettingsStore.getState().syncToBackend();

    expect(systemApi.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        enable_base_layer_height_modifier: false,
      }),
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
