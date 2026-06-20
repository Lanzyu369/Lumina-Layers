import { describe, it, expect, beforeEach, vi } from "vitest";
import { mergeCustomSlicer, useSlicerStore } from "../slicerStore";
import type { SlicerInfo } from "../../api/types";
import { DEFAULT_SETTINGS, useSettingsStore } from "../settingsStore";

/**
 * Slicer_Store 单元测试
 * Validates: Requirements 4.2, 4.3, 4.4, 4.5
 */

vi.mock("../../api/slicer", () => ({
  detectSlicers: vi.fn(),
  launchSlicer: vi.fn(),
  validateCustomSlicerPath: vi.fn(),
}));

import {
  detectSlicers as apiDetectSlicers,
  launchSlicer as apiLaunchSlicer,
  validateCustomSlicerPath as apiValidateCustomSlicerPath,
} from "../../api/slicer";

const mockDetect = vi.mocked(apiDetectSlicers);
const mockLaunch = vi.mocked(apiLaunchSlicer);
const mockValidateCustomPath = vi.mocked(apiValidateCustomSlicerPath);

const RAW_HTTP_STATUS_PATTERN = /Request failed with status code|status code\s+\d{3}/i;

const MOCK_SLICERS: SlicerInfo[] = [
  { id: "bambu_studio", display_name: "Bambu Studio", exe_path: null },
  { id: "orca_slicer", display_name: "OrcaSlicer", exe_path: null },
  { id: "anycubic_slicer_next", display_name: "Anycubic Slicer Next", exe_path: null },
];

function resetStore(): void {
  useSlicerStore.setState({
    slicers: [],
    selectedSlicerId: null,
    isDetecting: false,
    isLaunching: false,
    isValidatingCustomPath: false,
    launchMessage: null,
    customPathMessage: null,
    customPathError: null,
    error: null,
  });
}

describe("detectSlicers", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  });

  it("成功时更新 slicers 列表并自动选中第一个", async () => {
    mockDetect.mockResolvedValue({ slicers: MOCK_SLICERS });

    await useSlicerStore.getState().detectSlicers();

    const state = useSlicerStore.getState();
    expect(state.slicers).toEqual(MOCK_SLICERS);
    expect(state.selectedSlicerId).toBe("bambu_studio");
    expect(state.isDetecting).toBe(false);
    expect(state.error).toBeNull();
  });

  it("失败时设置 error 状态", async () => {
    mockDetect.mockRejectedValue(new Error("网络错误"));

    await useSlicerStore.getState().detectSlicers();

    const state = useSlicerStore.getState();
    expect(state.slicers).toEqual([]);
    expect(state.isDetecting).toBe(false);
    expect(state.error).toBe("网络错误");
  });

  it("失败且非 Error 实例时使用默认错误消息", async () => {
    mockDetect.mockRejectedValue("unknown");

    await useSlicerStore.getState().detectSlicers();

    expect(useSlicerStore.getState().error).toBe("切片软件检测失败");
  });

  it("失败时不展示原始 HTTP 状态码错误", async () => {
    mockDetect.mockRejectedValue(
      new Error("Request failed with status code 500"),
    );

    await useSlicerStore.getState().detectSlicers();

    const error = useSlicerStore.getState().error;
    expect(error).toBeTruthy();
    expect(error).not.toMatch(RAW_HTTP_STATUS_PATTERN);
    expect(error).toBe("服务器发生内部错误。请使用请求 ID 查看日志。");
  });

  it("检测到空列表时 selectedSlicerId 为 null", async () => {
    mockDetect.mockResolvedValue({ slicers: [] });

    await useSlicerStore.getState().detectSlicers();

    const state = useSlicerStore.getState();
    expect(state.slicers).toEqual([]);
    expect(state.selectedSlicerId).toBeNull();
  });

  it("当前导出软件为 Anycubic 时优先选中 Anycubic Slicer Next", async () => {
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      slicerSoftware: "AnycubicSlicerNext",
      lastSlicerId: "bambu_studio",
    });
    mockDetect.mockResolvedValue({ slicers: MOCK_SLICERS });

    await useSlicerStore.getState().detectSlicers();

    expect(useSlicerStore.getState().selectedSlicerId).toBe("anycubic_slicer_next");
  });

  it("合并已保存的手动切片软件路径", async () => {
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      customSlicerPath: "/Applications/Bambu Studio.app",
      customSlicerId: "bambu_studio",
      lastSlicerId: "bambu_studio",
    });
    mockDetect.mockResolvedValue({ slicers: [] });
    mockValidateCustomPath.mockResolvedValue({
      status: "success",
      message: "已识别 Bambu Studio",
      slicer: {
        id: "bambu_studio",
        display_name: "Bambu Studio",
        exe_path: null,
        source: "custom_macos_app",
      },
    });

    await useSlicerStore.getState().detectSlicers();

    expect(useSlicerStore.getState().slicers[0]).toMatchObject({
      id: "bambu_studio",
      source: "custom_macos_app",
    });
    expect(useSlicerStore.getState().selectedSlicerId).toBe("bambu_studio");
  });

  it("合并手动路径时保留其他未暴露路径的自动切片软件", () => {
    const result = mergeCustomSlicer(
      [
        {
          id: "orca_slicer",
          display_name: "OrcaSlicer",
          exe_path: null,
        },
        {
          id: "anycubic_slicer_next",
          display_name: "Anycubic Slicer Next",
          exe_path: null,
        },
      ],
      {
        id: "bambu_studio",
        display_name: "Bambu Studio",
        exe_path: null,
        source: "custom_macos_app",
      },
    );

    expect(result.map((slicer) => slicer.id)).toEqual([
      "bambu_studio",
      "orca_slicer",
      "anycubic_slicer_next",
    ]);
  });
});

describe("validateAndSaveCustomSlicerPath", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  });

  it("校验成功时保存手动路径并选中切片软件", async () => {
    mockValidateCustomPath.mockResolvedValue({
      status: "success",
      message: "已识别 OrcaSlicer",
      slicer: {
        id: "orca_slicer",
        display_name: "OrcaSlicer",
        exe_path: null,
        source: "custom_macos_app",
      },
    });

    await useSlicerStore
      .getState()
      .validateAndSaveCustomSlicerPath("  /Applications/OrcaSlicer.app  ");

    expect(useSettingsStore.getState().customSlicerPath).toBe(
      "/Applications/OrcaSlicer.app",
    );
    expect(useSettingsStore.getState().customSlicerId).toBe("orca_slicer");
    expect(useSettingsStore.getState().lastSlicerId).toBe("orca_slicer");
    expect(useSlicerStore.getState().selectedSlicerId).toBe("orca_slicer");
    expect(useSlicerStore.getState().customPathMessage).toBe("已识别 OrcaSlicer");
  });

  it("校验失败时设置 customPathError", async () => {
    mockValidateCustomPath.mockRejectedValue(new Error("未识别"));

    await useSlicerStore
      .getState()
      .validateAndSaveCustomSlicerPath("/Applications/Notes.app");

    expect(useSlicerStore.getState().customPathError).toBe("未识别");
    expect(useSettingsStore.getState().customSlicerPath).toBe("");
  });

  it("校验失败时不展示原始 HTTP 状态码错误", async () => {
    mockValidateCustomPath.mockRejectedValue(
      new Error("Request failed with status code 422"),
    );

    await useSlicerStore
      .getState()
      .validateAndSaveCustomSlicerPath("/Applications/Notes.app");

    const error = useSlicerStore.getState().customPathError;
    expect(error).toBeTruthy();
    expect(error).not.toMatch(RAW_HTTP_STATUS_PATTERN);
    expect(error).toBe("请求缺少必填数据或包含无效值。");
    expect(useSettingsStore.getState().customSlicerPath).toBe("");
  });
});

describe("setSelectedSlicerId", () => {
  beforeEach(() => {
    resetStore();
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  });

  it("更新 selectedSlicerId 为指定值", () => {
    useSlicerStore.getState().setSelectedSlicerId("orca_slicer");
    expect(useSlicerStore.getState().selectedSlicerId).toBe("orca_slicer");
  });

  it("设置为 null 清除选中", () => {
    useSlicerStore.getState().setSelectedSlicerId("bambu_studio");
    useSlicerStore.getState().setSelectedSlicerId(null);
    expect(useSlicerStore.getState().selectedSlicerId).toBeNull();
  });

  it("同步更新 settingsStore 中的 slicerSoftware 以驱动生成请求", () => {
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
    });

    useSlicerStore.getState().setSelectedSlicerId("orca_slicer");

    expect(useSlicerStore.getState().selectedSlicerId).toBe("orca_slicer");
    expect(useSettingsStore.getState().slicerSoftware).toBe("OrcaSlicer");
    expect(useSettingsStore.getState().lastSlicerId).toBe("orca_slicer");
    expect(useSettingsStore.getState().deviceProfileId).toBe("");
  });
});

describe("launchSlicer", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  it("成功时设置 launchMessage", async () => {
    useSlicerStore.setState({ selectedSlicerId: "bambu_studio" });
    mockLaunch.mockResolvedValue({
      status: "success",
      message: "已在 Bambu Studio 中打开",
    });

    await useSlicerStore.getState().launchSlicer("/output/model.3mf");

    const state = useSlicerStore.getState();
    expect(state.launchMessage).toBe("已在 Bambu Studio 中打开");
    expect(state.isLaunching).toBe(false);
    expect(state.error).toBeNull();
    expect(mockLaunch).toHaveBeenCalledWith({
      slicer_id: "bambu_studio",
      file_path: "/output/model.3mf",
    });
  });

  it("手动路径选中时随 launch 请求发送 slicer_path", async () => {
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      customSlicerPath: "/Applications/Bambu Studio.app",
      customSlicerId: "bambu_studio",
    });
    useSlicerStore.setState({
      selectedSlicerId: "bambu_studio",
      slicers: [
        {
          id: "bambu_studio",
          display_name: "Bambu Studio",
          exe_path: "/Applications/Bambu Studio.app",
          source: "custom_macos_app",
        },
      ],
    });
    mockLaunch.mockResolvedValue({
      status: "success",
      message: "已在 Bambu Studio 中打开",
    });

    await useSlicerStore.getState().launchSlicer("/output/model.3mf");

    expect(mockLaunch).toHaveBeenCalledWith({
      slicer_id: "bambu_studio",
      file_path: "/output/model.3mf",
      slicer_path: "/Applications/Bambu Studio.app",
    });
  });

  it("失败时设置 error 状态", async () => {
    useSlicerStore.setState({ selectedSlicerId: "bambu_studio" });
    mockLaunch.mockRejectedValue(new Error("启动失败"));

    await useSlicerStore.getState().launchSlicer("/output/model.3mf");

    const state = useSlicerStore.getState();
    expect(state.error).toBe("启动失败");
    expect(state.isLaunching).toBe(false);
    expect(state.launchMessage).toBeNull();
  });

  it("启动失败时不展示原始 HTTP 状态码错误", async () => {
    useSlicerStore.setState({ selectedSlicerId: "bambu_studio" });
    mockLaunch.mockRejectedValue(
      new Error("Request failed with status code 500"),
    );

    await useSlicerStore.getState().launchSlicer("/output/model.3mf");

    const state = useSlicerStore.getState();
    expect(state.error).toBeTruthy();
    expect(state.error).not.toMatch(RAW_HTTP_STATUS_PATTERN);
    expect(state.error).toBe("服务器发生内部错误。请使用请求 ID 查看日志。");
    expect(state.isLaunching).toBe(false);
    expect(state.launchMessage).toBeNull();
  });

  it("未选择切片软件时直接设置 error 不调用 API", async () => {
    await useSlicerStore.getState().launchSlicer("/output/model.3mf");

    expect(useSlicerStore.getState().error).toBe("请先选择切片软件");
    expect(mockLaunch).not.toHaveBeenCalled();
  });
});
