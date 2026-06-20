import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { LutDetailsResponse } from "../api/types";
import LutDetailsPanel from "../components/LutDetailsPanel";
import { useLutDetailsStore } from "../stores/lutDetailsStore";

const mockFetchLutDetailsCatalog = vi.fn();
const mockFetchLutDetails = vi.fn();

vi.mock("../api/lut", () => ({
  fetchLutDetailsCatalog: (...args: unknown[]) => mockFetchLutDetailsCatalog(...args),
  fetchLutDetails: (...args: unknown[]) => mockFetchLutDetails(...args),
}));

const CATALOG = [
  {
    manufacturer: "Bambu Lab",
    items: [
      {
        name: "Bambu Lab - PLA - Test",
        path: "lut-ref/fp-1.json",
        fingerprint: "fp-1",
        color_mode: "4-Color (RYBW)",
        source_kind: "legacy_lookup",
        manufacturer: "Bambu Lab",
        material_type: "PLA",
        manufacturer_source: "metadata",
        material_source: "folder",
        search_tokens: ["bambulab", "pla", "test"],
      },
    ],
  },
  {
    manufacturer: "Aliz",
    items: [
      {
        name: "Aliz - PETG - Test",
        path: "lut-ref/fp-2.json",
        fingerprint: "fp-2",
        color_mode: "4-Color (CMYW)",
        source_kind: "legacy_lookup",
        manufacturer: "Aliz",
        material_type: "PETG",
        manufacturer_source: "folder",
        material_source: "folder",
        search_tokens: ["aliz", "petg", "test"],
      },
    ],
  },
];

function buildDetail(
  name: string,
  fingerprint: string,
  path: string,
  overrides: Partial<LutDetailsResponse> = {},
): LutDetailsResponse {
  return {
    name,
    path,
    fingerprint,
    manufacturer: name.startsWith("Aliz") ? "Aliz" : "Bambu Lab",
    manufacturer_source: name.startsWith("Aliz") ? "folder" : "metadata",
    material_type: name.startsWith("Aliz") ? "PETG" : "PLA",
    material_source: "folder",
    color_mode: name.startsWith("Aliz") ? "4-Color (CMYW)" : "4-Color (RYBW)",
    color_count: 4,
    source_kind: "legacy_lookup",
    schema_version: "1.0",
    capabilities: ["legacy_lookup"],
    supported_modes: [],
    raw_metadata: { batch_code: fingerprint },
    palette: [
      {
        color: "White",
        material: "PLA Basic",
        hex_color: "#FFFFFF",
        color_name: "White",
      },
    ],
    coverage_stats: {
      entry_count: 4,
      plotted_point_count: 4,
      l_range: { min: 0, max: 100 },
      a_range: { min: -40, max: 60 },
      b_range: { min: -50, max: 50 },
      r_range: { min: 0, max: 255 },
      g_range: { min: 0, max: 255 },
      b_rgb_range: { min: 0, max: 255 },
    },
    lab_points: [
      { x: -10, y: 20, hex_color: "#FFFFFF", rgb: [255, 255, 255], label: "1" },
    ],
    lab_points_3d: [
      { l: 62, a: -14, b: 18, hex_color: "#ff3366", rgb: [255, 51, 102], label: "1" },
    ],
    lab_hull: [
      { x: -10, y: 20 },
      { x: 0, y: 10 },
      { x: 10, y: -20 },
    ],
    rgb_points: [
      { x: 0.2, y: -0.1, hex_color: "#FFFFFF", rgb: [255, 255, 255], label: "1" },
    ],
    max_color_layers: 5,
    layer_height_mm: 0.08,
    line_width_mm: 0.42,
    base_layers: 10,
    base_channel_idx: 0,
    layer_order: "Top2Bottom",
    ...overrides,
  };
}

const DETAIL_A = buildDetail("Bambu Lab - PLA - Test", "fp-1", "lut-ref/fp-1.json");
const DETAIL_B = buildDetail("Aliz - PETG - Test", "fp-2", "lut-ref/fp-2.json");

function setUnloadedCatalogState() {
  useLutDetailsStore.setState({
    catalog: CATALOG,
    catalogLoading: false,
    selectedManufacturer: "",
    selectedLutName: "Bambu Lab - PLA - Test",
    loadedLutName: "",
    query: "",
    detailLoading: false,
    error: null,
    errorKind: null,
    detail: null,
    hasLoadedDetail: false,
    isSelectionDirty: false,
    canLoadSelectedLut: true,
  });
}

function setLoadedState(
  overrides: Partial<ReturnType<typeof useLutDetailsStore.getState>> = {},
) {
  useLutDetailsStore.setState({
    catalog: CATALOG,
    catalogLoading: false,
    selectedManufacturer: "",
    selectedLutName: "Bambu Lab - PLA - Test",
    loadedLutName: "Bambu Lab - PLA - Test",
    query: "",
    detailLoading: false,
    error: null,
    errorKind: null,
    detail: DETAIL_A,
    hasLoadedDetail: true,
    isSelectionDirty: false,
    canLoadSelectedLut: true,
    ...overrides,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useLutDetailsStore.setState({
    catalog: [],
    catalogLoading: false,
    selectedManufacturer: "",
    selectedLutName: "",
    loadedLutName: "",
    query: "",
    detailLoading: false,
    error: null,
    errorKind: null,
    detail: null,
    hasLoadedDetail: false,
    isSelectionDirty: false,
    canLoadSelectedLut: false,
  });
});

describe("LutDetailsPanel", () => {
  it("renders the lightweight selector state before any LUT detail is loaded", async () => {
    mockFetchLutDetailsCatalog.mockResolvedValueOnce({ groups: CATALOG });

    render(<LutDetailsPanel />);

    await waitFor(() => {
      expect(mockFetchLutDetailsCatalog).toHaveBeenCalled();
    });

    expect(screen.getByTestId("lut-details-panel")).toBeInTheDocument();
    expect(screen.getByTestId("lut-details-layout")).toBeInTheDocument();
    expect(screen.getByTestId("lut-details-primary-column")).toContainElement(screen.getByTestId("lut-details-selection-card"));
    expect(screen.getByTestId("lut-details-secondary-column")).toBeInTheDocument();
    expect(screen.getByLabelText("筛选 LUT")).toBeInTheDocument();
    expect(screen.getByTestId("lut-details-manufacturer-dropdown")).toBeInTheDocument();
    expect(screen.getByTestId("lut-details-lut-dropdown")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "加载 LUT" })).toBeInTheDocument();
    expect(screen.getByText("选择 LUT 后点击加载。")).toBeInTheDocument();
    expect(screen.getByText("摘要")).toBeInTheDocument();
    expect(screen.getByText("类型化元数据")).toBeInTheDocument();
    expect(screen.getByText("调色板")).toBeInTheDocument();
    expect(screen.getByText("Lab 图")).toBeInTheDocument();
    expect(screen.queryByTestId("lut-details-loaded-view")).not.toBeInTheDocument();
    expect(screen.queryByTestId("lut-details-lab-chart")).not.toBeInTheDocument();
    expect(screen.getAllByText("请选择一个 LUT。").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("暂无点位数据").length).toBeGreaterThanOrEqual(1);
    expect(mockFetchLutDetails).not.toHaveBeenCalled();
  });

  it("loads and renders the heavy detail view only after clicking the load button", async () => {
    setUnloadedCatalogState();
    mockFetchLutDetailsCatalog.mockResolvedValueOnce({ groups: CATALOG });
    mockFetchLutDetails.mockResolvedValueOnce(DETAIL_A);

    render(<LutDetailsPanel />);

    await waitFor(() => {
      expect(mockFetchLutDetailsCatalog).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "加载 LUT" })).not.toBeDisabled();
    });
    expect(screen.queryByTestId("lut-details-loaded-view")).not.toBeInTheDocument();

    await useLutDetailsStore.getState().loadSelectedLut();

    await waitFor(() => {
      expect(mockFetchLutDetails).toHaveBeenCalledWith("Bambu Lab - PLA - Test");
    });
    await waitFor(() => {
      expect(screen.getByTestId("lut-details-loaded-view")).toBeInTheDocument();
    });

    expect(screen.getByTestId("lut-details-primary-column")).toContainElement(screen.getByTestId("lut-details-selection-card"));
    expect(screen.getByTestId("lut-details-primary-column")).toContainElement(screen.getByText("摘要"));
    expect(screen.getByTestId("lut-details-secondary-column")).toContainElement(screen.getByTestId("lut-details-lab-chart"));
    expect(screen.getByText("摘要")).toBeInTheDocument();
    expect(screen.getByText("公开引用")).toBeInTheDocument();
    expect(screen.getByText("lut-ref/fp-1.json")).toBeInTheDocument();
    expect(screen.getByTestId("lut-details-lab-chart")).toBeInTheDocument();
    expect(screen.getByTestId("lut-details-rgb-chart")).toBeInTheDocument();
    expect(screen.getByTestId("lut-details-hue-lightness-chart")).toBeInTheDocument();
    expect(screen.getByTestId("lut-details-hue-chroma-chart")).toBeInTheDocument();
    expect(screen.getByTestId("lut-details-raw-metadata")).toHaveTextContent("batch_code");
  });

  it("keeps the loaded detail visible and shows a pending-change banner when the selection changes", async () => {
    setLoadedState();
    mockFetchLutDetailsCatalog.mockResolvedValueOnce({ groups: CATALOG });

    render(<LutDetailsPanel />);

    const loadedView = screen.getByTestId("lut-details-loaded-view");
    fireEvent.change(screen.getByLabelText("筛选 LUT"), { target: { value: "aliz" } });

    await waitFor(() => {
      expect(useLutDetailsStore.getState().selectedLutName).toBe("Aliz - PETG - Test");
    });

    expect(screen.getByTestId("lut-details-loaded-view")).toBe(loadedView);
    expect(screen.getByText("Bambu Lab - PLA - Test")).toBeInTheDocument();
    expect(screen.getByText("当前显示的是已加载 LUT，点击加载后更新。")).toBeInTheDocument();
    expect(mockFetchLutDetails).not.toHaveBeenCalled();
  });

  it("switches to the new detail only after the user clicks load again", async () => {
    setLoadedState({
      selectedLutName: "Aliz - PETG - Test",
      loadedLutName: "Bambu Lab - PLA - Test",
      detail: DETAIL_A,
      hasLoadedDetail: true,
      isSelectionDirty: true,
    });
    mockFetchLutDetailsCatalog.mockResolvedValueOnce({ groups: CATALOG });
    mockFetchLutDetails.mockResolvedValueOnce(DETAIL_B);

    render(<LutDetailsPanel />);

    await waitFor(() => {
      expect(mockFetchLutDetailsCatalog).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "加载 LUT" })).not.toBeDisabled();
    });
    await useLutDetailsStore.getState().loadSelectedLut();

    await waitFor(() => {
      expect(mockFetchLutDetails).toHaveBeenCalledWith("Aliz - PETG - Test");
    });
    await waitFor(() => {
      expect(screen.getByText("Aliz - PETG - Test")).toBeInTheDocument();
    });

    expect(screen.queryByText("当前显示的是已加载 LUT，点击加载后更新。")).not.toBeInTheDocument();
  });

  it("keeps the old detail visible when loading the newly selected LUT fails", async () => {
    setLoadedState({
      selectedLutName: "Aliz - PETG - Test",
      loadedLutName: "Bambu Lab - PLA - Test",
      detail: DETAIL_A,
      hasLoadedDetail: true,
      isSelectionDirty: true,
    });
    mockFetchLutDetailsCatalog.mockResolvedValueOnce({ groups: CATALOG });
    mockFetchLutDetails.mockRejectedValueOnce(new Error("detail failed"));

    render(<LutDetailsPanel />);

    await waitFor(() => {
      expect(mockFetchLutDetailsCatalog).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "加载 LUT" })).not.toBeDisabled();
    });
    await useLutDetailsStore.getState().loadSelectedLut();

    await waitFor(() => {
      expect(screen.getByText("detail failed")).toBeInTheDocument();
    });

    expect(screen.getByTestId("lut-details-loaded-view")).toBeInTheDocument();
    expect(screen.getByText("Bambu Lab - PLA - Test")).toBeInTheDocument();
    expect(screen.getByText("当前显示的是已加载 LUT，点击加载后更新。")).toBeInTheDocument();
  });

  it("retries the selected LUT detail load from the error banner", async () => {
    setLoadedState({
      selectedLutName: "Aliz - PETG - Test",
      loadedLutName: "Bambu Lab - PLA - Test",
      detail: DETAIL_A,
      hasLoadedDetail: true,
      isSelectionDirty: true,
    });
    mockFetchLutDetailsCatalog.mockResolvedValueOnce({ groups: CATALOG });
    mockFetchLutDetails
      .mockRejectedValueOnce(new Error("detail failed"))
      .mockResolvedValueOnce(DETAIL_B);

    render(<LutDetailsPanel />);

    await waitFor(() => {
      expect(mockFetchLutDetailsCatalog).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "加载 LUT" })).not.toBeDisabled();
    });
    await useLutDetailsStore.getState().loadSelectedLut();
    await waitFor(() => {
      expect(screen.getByText("detail failed")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("重试"));

    await waitFor(() => {
      expect(mockFetchLutDetails).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(screen.getByText("Aliz - PETG - Test")).toBeInTheDocument();
    });
  });

  it("does not create heavy reference assets while the panel is still unloaded", async () => {
    const createObjectUrl = URL.createObjectURL;
    const createObjectUrlMock = vi.fn(() => "blob:mock");
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrlMock,
    });

    try {
      mockFetchLutDetailsCatalog.mockResolvedValueOnce({ groups: CATALOG });
      render(<LutDetailsPanel />);

      await waitFor(() => {
        expect(mockFetchLutDetailsCatalog).toHaveBeenCalled();
      });
      expect(createObjectUrlMock).not.toHaveBeenCalled();
    } finally {
      Object.defineProperty(URL, "createObjectURL", {
        configurable: true,
        value: createObjectUrl,
      });
    }
  });

  it("shows the no-match banner after an empty catalog finishes loading", async () => {
    mockFetchLutDetailsCatalog.mockResolvedValueOnce({ groups: [] });

    render(<LutDetailsPanel />);

    await waitFor(() => {
      expect(screen.getByText("没有匹配的 LUT，请调整筛选条件。")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "加载 LUT" })).toBeDisabled();
  });
});
