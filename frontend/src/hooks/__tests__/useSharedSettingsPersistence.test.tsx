import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UserSettings } from "../../api/types";

vi.mock("../../api/system", () => ({
  getSettings: vi.fn(),
  saveSettings: vi.fn().mockResolvedValue({
    status: "success",
    message: "Settings saved",
  }),
}));

vi.mock("../../stores/generatedArtifactInvalidation", () => ({
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

const SHARED_SETTINGS: UserSettings = {
  language: "en",
  theme: "dark",
  last_lut: "",
  last_modeling_mode: "high-fidelity",
  last_color_mode: "4-Color (RYBW)",
  last_slicer: "",
  last_bed_label: "256×256 mm",
  palette_mode: "swatch",
  enable_crop_modal: true,
  enable_blur: true,
  enable_fancy_loading: true,
  enable_witty_loading: true,
  enable_completion_notifications: false,
  enable_smooth_vector_preview: true,
  preserve_upload_filename_for_3mf: false,
  printer_model: "bambu-h2d",
  slicer_software: "BambuStudio",
  device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.4",
  build_plate_id: "",
  build_plate_selections: {},
  custom_slicer_path: "",
  custom_slicer_id: "",
  nozzle_size: "0.4",
  enable_base_layer_height_modifier: true,
  enable_wipe_tower_auto_placement: true,
  enable_solver_cache_grid_selection: false,
  solver_cache_grid_resolution: 64,
  svg_pixels_per_mm: 10,
  material_delta_e00_tolerance: 0.5,
  auto_replace_gradient_banding: false,
};

describe("useSharedSettingsPersistence", () => {
  it("persists edits made while the initial shared save is pending", async () => {
    const systemApi = await import("../../api/system");
    vi.mocked(systemApi.getSettings).mockResolvedValue({ status: "success", settings: SHARED_SETTINGS });
    let finishSave!: () => void;
    vi.mocked(systemApi.saveSettings).mockImplementationOnce(() => new Promise(resolve => {
      finishSave = () => resolve({ status: "success", message: "Settings saved" });
    }));
    const { useSharedSettingsPersistence } = await import("../useSharedSettingsPersistence");
    const { useSettingsStore } = await import("../../stores/settingsStore");
    const { unmount } = renderHook(() => useSharedSettingsPersistence());
    try {
      await waitFor(() => expect(systemApi.saveSettings).toHaveBeenCalledTimes(1));
      act(() => useSettingsStore.getState().setTheme("light"));
      await waitFor(() => expect(systemApi.saveSettings).toHaveBeenCalledWith(
        expect.objectContaining({ theme: "light" }),
      ));
    } finally {
      finishSave();
      unmount();
    }
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    localStorage.clear();
  });

  it("hydrates once, then persists later changes from a changing port origin", async () => {
    const systemApi = await import("../../api/system");
    vi.mocked(systemApi.getSettings).mockResolvedValue({
      status: "success",
      settings: SHARED_SETTINGS,
    });
    const [{ useSharedSettingsPersistence }, { useSettingsStore }] =
      await Promise.all([
        import("../useSharedSettingsPersistence"),
        import("../../stores/settingsStore"),
      ]);

    const { unmount } = renderHook(() => useSharedSettingsPersistence());
    await waitFor(() => {
      expect(useSettingsStore.getState().theme).toBe("dark");
      expect(systemApi.saveSettings).toHaveBeenCalled();
    });
    vi.mocked(systemApi.saveSettings).mockClear();

    act(() => {
      useSettingsStore.getState().setTheme("light");
    });

    await waitFor(() => {
      expect(systemApi.saveSettings).toHaveBeenCalledWith(
        expect.objectContaining({ theme: "light", language: "en" }),
      );
    });
    unmount();
  });

  it("copies existing origin-local preferences into shared storage", async () => {
    localStorage.setItem(
      "lumina-settings",
      JSON.stringify({
        state: { language: "zh", theme: "light" },
        version: 1,
      }),
    );
    const systemApi = await import("../../api/system");
    vi.mocked(systemApi.getSettings).mockResolvedValue({
      status: "success",
      settings: SHARED_SETTINGS,
    });
    const { useSharedSettingsPersistence } = await import(
      "../useSharedSettingsPersistence"
    );

    const { unmount } = renderHook(() => useSharedSettingsPersistence());

    await waitFor(() => {
      expect(systemApi.saveSettings).toHaveBeenCalledWith(
        expect.objectContaining({ language: "zh", theme: "light" }),
      );
    });
    unmount();
  });
});
