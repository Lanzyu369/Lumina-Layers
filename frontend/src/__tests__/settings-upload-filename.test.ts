import { beforeEach, describe, expect, it } from "vitest";
import { ModelingMode } from "../api/types";
import { useConverterStore, DEFAULT_STATE } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

const DOWNLOAD_URL = "/api/files/generated-3mf";
const DISK_PATH = "E:/tmp/generated.3mf";
const MODEL_URL = "/api/files/generated.glb";
const PREVIEW_GLB_URL = "/api/files/preview.glb";

describe("preserve uploaded filename setting", () => {
  beforeEach(() => {
    localStorage.clear();
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    useConverterStore.setState({
      ...DEFAULT_STATE,
      downloadUrl: DOWNLOAD_URL,
      threemfDiskPath: DISK_PATH,
      modelUrl: MODEL_URL,
      previewGlbUrl: PREVIEW_GLB_URL,
    });
  });

  it("ships disabled and persists an explicit opt-in locally", () => {
    expect(DEFAULT_SETTINGS.preserveUploadFilenameFor3mf).toBe(false);
    expect(
      useSettingsStore.getState().preserveUploadFilenameFor3mf,
    ).toBe(false);

    useSettingsStore.getState().setPreserveUploadFilenameFor3mf(true);

    const raw = localStorage.getItem("lumina-settings");
    expect(raw).toBeTruthy();
    const persisted = JSON.parse(raw ?? "{}");
    expect(persisted.state.preserveUploadFilenameFor3mf).toBe(true);
  });

  it("clears only a stale ordinary 3MF download and keeps previews", () => {
    useSettingsStore.getState().setPreserveUploadFilenameFor3mf(true);

    const state = useConverterStore.getState();
    expect(state.downloadUrl).toBeNull();
    expect(state.threemfDiskPath).toBeNull();
    expect(state.modelUrl).toBe(MODEL_URL);
    expect(state.previewGlbUrl).toBe(PREVIEW_GLB_URL);
  });

  it.each([
    ["batch", { batchMode: true }],
    ["puzzle", { puzzleEnabled: true }],
    ["large format", { largeFormatEnabled: true }],
    ["generated color card", { modeling_mode: ModelingMode.COLOR_CARD }],
  ])("keeps an excluded %s download", (_label, workflowState) => {
    useConverterStore.setState(workflowState);

    useSettingsStore.getState().setPreserveUploadFilenameFor3mf(true);

    const state = useConverterStore.getState();
    expect(state.downloadUrl).toBe(DOWNLOAD_URL);
    expect(state.threemfDiskPath).toBe(DISK_PATH);
  });

  it("does not invalidate a later download when the setting value is unchanged", () => {
    useSettingsStore.getState().setPreserveUploadFilenameFor3mf(true);
    useConverterStore.setState({
      downloadUrl: DOWNLOAD_URL,
      threemfDiskPath: DISK_PATH,
    });

    useSettingsStore.getState().setPreserveUploadFilenameFor3mf(true);

    expect(useConverterStore.getState().downloadUrl).toBe(DOWNLOAD_URL);
    expect(useConverterStore.getState().threemfDiskPath).toBe(DISK_PATH);
  });
});
