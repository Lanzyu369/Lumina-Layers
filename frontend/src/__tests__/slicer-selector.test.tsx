import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { launchSlicer } from "../api/slicer";
import SlicerSelector from "../components/sections/SlicerSelector";
import { I18nProvider } from "../i18n/context";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { useSlicerStore } from "../stores/slicerStore";

vi.mock("../api/slicer", () => ({
  detectSlicers: vi.fn().mockResolvedValue({
    slicers: [
      {
        id: "bambu_studio",
        display_name: "Bambu Studio",
        exe_path: "/Applications/Bambu Studio.app",
      },
      {
        id: "orca_slicer",
        display_name: "OrcaSlicer",
        exe_path: "/Applications/OrcaSlicer.app",
      },
    ],
  }),
  launchSlicer: vi.fn().mockResolvedValue({
    status: "success",
    message: "opened",
  }),
  validateCustomSlicerPath: vi.fn(),
}));

describe("SlicerSelector settings linkage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      slicerSoftware: "OrcaSlicer",
      lastSlicerId: "bambu_studio",
    });
    useSlicerStore.setState({
      slicers: [
        {
          id: "bambu_studio",
          display_name: "Bambu Studio",
          exe_path: "/Applications/Bambu Studio.app",
        },
        {
          id: "orca_slicer",
          display_name: "OrcaSlicer",
          exe_path: "/Applications/OrcaSlicer.app",
        },
      ],
      selectedSlicerId: "bambu_studio",
      isDetecting: false,
      isLaunching: false,
      isValidatingCustomPath: false,
      launchMessage: null,
      customPathMessage: null,
      customPathError: null,
      error: null,
      detectSlicers: vi.fn().mockResolvedValue(undefined),
    });
  });

  it("prefers the slicer selected in settings over stale selectedSlicerId", async () => {
    render(
      <I18nProvider>
        <SlicerSelector
          threemfDiskPath="/tmp/calibration.3mf"
          downloadUrl="/api/files/calibration"
          canSubmit
          onAutoGenerate={async () => "/tmp/calibration.3mf"}
        />
      </I18nProvider>,
    );

    const openButton = screen.getByRole("button", {
      name: "在 OrcaSlicer 中打开",
    });
    expect(openButton).toBeInTheDocument();
  });

  it("does not fall back to Bambu Studio when the settings slicer is missing", async () => {
    useSlicerStore.setState({
      slicers: [
        {
          id: "bambu_studio",
          display_name: "Bambu Studio",
          exe_path: "/Applications/Bambu Studio.app",
        },
      ],
      selectedSlicerId: "bambu_studio",
    });

    render(
      <I18nProvider>
        <SlicerSelector
          threemfDiskPath="/tmp/calibration.3mf"
          downloadUrl="/api/files/calibration"
          canSubmit
          onAutoGenerate={async () => "/tmp/calibration.3mf"}
        />
      </I18nProvider>,
    );

    expect(
      screen.getByText("当前导出格式为 OrcaSlicer，但本机未检测到对应切片软件"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "在 Bambu Studio 中打开" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载 3MF" })).toBeInTheDocument();
  });

  it("launches with an explicit settings-linked slicer id", async () => {
    await useSlicerStore
      .getState()
      .launchSlicer("/tmp/calibration.3mf", "orca_slicer");

    expect(vi.mocked(launchSlicer)).toHaveBeenCalledWith({
      slicer_id: "orca_slicer",
      file_path: "/tmp/calibration.3mf",
    });
  });
});
