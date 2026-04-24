import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GradientGroupsPanel from "../components/sections/GradientGroupsPanel";
import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import type { GradientGroupItem } from "../api/types";

// The store's ``selectGradientGroupColors`` calls ``apiColorHighlight`` as a
// best-effort preview refresh; stub it so tests don't hit the network.
// 这里替换掉 apiColorHighlight，避免测试里触发真实的网络请求。
const colorHighlightMock = vi.hoisted(() => vi.fn());
const replaceColorMock = vi.hoisted(() => vi.fn());
const regionReplaceMock = vi.hoisted(() => vi.fn());

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>(
    "../api/converter",
  );
  return {
    ...actual,
    colorHighlight: colorHighlightMock,
    replaceColor: replaceColorMock,
    regionReplace: regionReplaceMock,
  };
});

function _makeGroup(
  overrides: Partial<GradientGroupItem> = {},
): GradientGroupItem {
  return {
    group_index: 1,
    total_pixel_count: 500_000,
    material_colour_count: 2,
    material_colours: [
      { hex: "#D2AEB4", rgb: [210, 174, 180], pixel_count: 300_000 },
      { hex: "#CB9994", rgb: [203, 153, 148], pixel_count: 200_000 },
    ],
    representative_hex: "#D2AEB4",
    representative_rgb: [210, 174, 180],
    boundary_pair_count: 1,
    regions: [
      {
        region_index: 1,
        pixel_count: 350_000,
        bbox: [0, 0, 100, 100],
        centroid: [50, 50],
        material_breakdown: [
          { hex: "#D2AEB4", rgb: [210, 174, 180], pixel_count: 210_000 },
          { hex: "#CB9994", rgb: [203, 153, 148], pixel_count: 140_000 },
        ],
      },
      {
        region_index: 2,
        pixel_count: 150_000,
        bbox: [120, 50, 200, 150],
        centroid: [160, 100],
        material_breakdown: [
          { hex: "#D2AEB4", rgb: [210, 174, 180], pixel_count: 90_000 },
          { hex: "#CB9994", rgb: [203, 153, 148], pixel_count: 60_000 },
        ],
      },
    ],
    ...overrides,
  };
}

function _resetStores(
  overrides: Partial<ReturnType<typeof useConverterStore.getState>> = {},
) {
  useConverterStore.setState({
    source_version: "material",
    sessionId: "sess-test",
    gradientGroups: [_makeGroup()],
    gradientGroupsLoading: false,
    gradientGroupsError: null,
    gradientGroupsSessionId: "sess-test",
    gradientSelection: null,
    selectedColor: null,
    selectionMode: "current",
    selectedColors: new Set<string>(),
    selectedRegions: [],
    regionData: null,
    replacePreviewLoading: false,
    colorRemapMap: {},
    remapHistory: [],
    previewImageUrl: "/api/files/preview.png",
    ...overrides,
  });
  useSettingsStore.setState({ autoReplaceGradientBanding: false });
}

describe("GradientGroupsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _resetStores();
    colorHighlightMock.mockResolvedValue({
      preview_url: "/api/files/highlighted.png",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing when not in material-archive mode", () => {
    _resetStores({ source_version: "legacy" });
    const { container } = render(<GradientGroupsPanel />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when gradientGroups is null (not fetched yet)", () => {
    _resetStores({ gradientGroups: null });
    const { container } = render(<GradientGroupsPanel />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when gradientGroups is an empty list (no banding)", () => {
    _resetStores({ gradientGroups: [] });
    const { container } = render(<GradientGroupsPanel />);
    expect(container.firstChild).toBeNull();
  });

  it("renders loading state while fetching", () => {
    _resetStores({ gradientGroupsLoading: true, gradientGroups: null });
    render(<GradientGroupsPanel />);
    expect(screen.getByText(/loading gradient groups|正在读取/i)).toBeInTheDocument();
  });

  it("renders error state when the fetch failed", () => {
    _resetStores({
      gradientGroupsError: "boom",
      gradientGroups: null,
    });
    render(<GradientGroupsPanel />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("boom");
  });

  it("renders a group row with material count and select button", () => {
    render(<GradientGroupsPanel />);
    expect(screen.getByTestId("gradient-groups-panel")).toBeInTheDocument();
    expect(screen.getByText(/2 (colors|种颜色)/i)).toBeInTheDocument();
    // Both select-group and flatten-all buttons are present.
    expect(
      screen.getByRole("button", { name: /select all|选中整组/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /flatten all|一键去除/i }),
    ).toBeInTheDocument();
  });

  it("select-group writes lowercase hexes into selectedColors and flips to select-all", () => {
    render(<GradientGroupsPanel />);
    fireEvent.click(
      screen.getByRole("button", { name: /select all|选中整组/i }),
    );

    const state = useConverterStore.getState();
    expect(state.selectionMode).toBe("select-all");
    expect(Array.from(state.selectedColors).sort()).toEqual(
      ["cb9994", "d2aeb4"].sort(),
    );
    expect(state.selectedRegions).toEqual([]);
    expect(state.selectedColor).toBeNull();
    // Source stamp identifies which panel row initiated the multi-select.
    // 记录点击来源，供按钮排它性高亮判断。
    expect(state.gradientSelection).toEqual({
      kind: "group",
      groupIndex: 1,
    });
    // The store triggers a single highlight call for the whole set. No
    // scope is passed because the source is a whole group — the backend
    // will scan the full canvas, which is correct for this scope.
    // 整组批量不传 scope，让后端全图扫描。
    expect(colorHighlightMock).toHaveBeenCalledTimes(1);
    expect(colorHighlightMock).toHaveBeenCalledWith(
      "sess-test",
      expect.arrayContaining(["cb9994", "d2aeb4"]),
      undefined,
    );
  });

  it("expands regions and select-region writes the region's breakdown with a region-scoped source", () => {
    render(<GradientGroupsPanel />);
    // Expand regions for the only group on screen.
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    // Two "select region" buttons are now visible (one per region).
    const regionBtns = screen.getAllByRole("button", {
      name: /select region|选中区域/i,
    });
    expect(regionBtns).toHaveLength(2);
    fireEvent.click(regionBtns[0]);

    const state = useConverterStore.getState();
    expect(state.selectionMode).toBe("select-all");
    expect(Array.from(state.selectedColors).sort()).toEqual(
      ["cb9994", "d2aeb4"].sort(),
    );
    // Key disambiguator: even when the region breakdown happens to equal
    // the enclosing group's material set, the source must be "region".
    // 关键：就算 region.breakdown 与整组 hex 一致，source 也必须是 region。
    expect(state.gradientSelection).toEqual({
      kind: "region",
      groupIndex: 1,
      regionIndex: 1,
    });
    // And the highlight call carries (group_index, region_index) so the
    // backend clips the preview overlay to the region's *exact* pixel
    // mask — a rectangular bbox is not precise enough: a region's bbox
    // routinely contains other same-colour pixels that belong to other
    // regions of the same group, which is exactly the "clicking a
    // sub-region lights up the whole group" bug the user reported.
    // 高亮请求传 (group_index, region_index) 让后端按精确像素 mask 裁剪，
    // 矩形 bbox 不够精细——bbox 内常常包含其它同色区域的像素，
    // 这正是 "点小分组却把整组点亮" 的 bug。
    const scopeCall = colorHighlightMock.mock.calls.at(-1);
    expect(scopeCall?.[2]).toEqual({
      gradientGroupIndex: 1,
      gradientRegionIndex: 1,
    });
  });

  it("flatten-all button invokes applyAutoGradientReplace", async () => {
    replaceColorMock.mockResolvedValue({
      preview_url: "/api/files/flattened.png",
      preview_3d_url: null,
    });
    render(<GradientGroupsPanel />);
    // Wrapped in ``act`` so the async store update (colorRemapMap + followup
    // submitReplacePreview) completes before the assertion, preventing the
    // "not wrapped in act" warning from React.
    // 用 act 包裹：等待异步 action 内部的状态更新落地再断言。
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /flatten all|一键去除/i }),
      );
    });

    const state = useConverterStore.getState();
    // colorRemapMap now carries the non-representative -> representative pair.
    expect(state.colorRemapMap).toMatchObject({ cb9994: "d2aeb4" });
  });

  it("shows the auto-replaced banner when the setting is enabled", () => {
    useSettingsStore.setState({ autoReplaceGradientBanding: true });
    render(<GradientGroupsPanel />);
    expect(
      screen.getByText(/auto-replaced|已按设置自动替换/i),
    ).toBeInTheDocument();
  });

  it("highlights the group row only when gradientSelection identifies it as the origin", () => {
    // Pure selectedColors match is no longer enough — the store also needs
    // gradientSelection to point at this group. This prevents the old bug
    // where selecting a region whose breakdown equals the group's material
    // set would leave the group button highlighted.
    // 单纯 selectedColors 匹配不再能高亮整组按钮，必须 gradientSelection 也指向本组。
    _resetStores({
      selectionMode: "select-all",
      selectedColors: new Set(["d2aeb4", "cb9994"]),
      gradientSelection: { kind: "group", groupIndex: 1 },
    });
    render(<GradientGroupsPanel />);
    const btn = screen.getByRole("button", { name: /select all|选中整组/i });
    expect(btn.className).toMatch(/bg-blue-/);
  });

  it("does NOT highlight the group button when gradientSelection points at a region", () => {
    // Regression for the reported bug: group A's material_colours were
    // {d2aeb4, cb9994} and the single region inside had the identical
    // breakdown, so the legacy "every hex in selectedColors" rule lit up
    // *both* the group button and the region button at once.
    // 关键回归：即使 selectedColors 与整组 hex 完全一致，只要来源是 region，
    // 整组按钮必须保持灰色。
    _resetStores({
      selectionMode: "select-all",
      selectedColors: new Set(["d2aeb4", "cb9994"]),
      gradientSelection: {
        kind: "region",
        groupIndex: 1,
        regionIndex: 1,
      },
    });
    render(<GradientGroupsPanel />);
    const groupBtn = screen.getByRole("button", {
      name: /select all|选中整组/i,
    });
    expect(groupBtn.className).not.toMatch(/bg-blue-/);
  });

  it("switching from a group to one of its regions moves the highlight", async () => {
    // End-to-end flow through the real store: first click the group's
    // select button (gradientSelection becomes {group, 1}), then expand
    // and click region 1's select button (gradientSelection should flip
    // to {region, 1, 1}). The group button must dim and the region
    // button must light up.
    // 全链路：先选整组 → 再选组内区域 1 → 整组按钮变灰、区域按钮变蓝。
    render(<GradientGroupsPanel />);

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /select all|选中整组/i }),
      );
    });
    // At this point the group button is blue.
    const groupBtn1 = screen.getByRole("button", {
      name: /select all|选中整组/i,
    });
    expect(groupBtn1.className).toMatch(/bg-blue-/);

    // Expand and click region 1's "select region" button.
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    const regionBtns = screen.getAllByRole("button", {
      name: /select region|选中区域/i,
    });
    await act(async () => {
      fireEvent.click(regionBtns[0]);
    });

    // Group button no longer blue; region button now blue.
    const groupBtn2 = screen.getByRole("button", {
      name: /select all|选中整组/i,
    });
    expect(groupBtn2.className).not.toMatch(/bg-blue-/);
    expect(regionBtns[0].className).toMatch(/bg-blue-/);

    // Sanity: the store recorded the region-scoped source.
    const state = useConverterStore.getState();
    expect(state.gradientSelection).toEqual({
      kind: "region",
      groupIndex: 1,
      regionIndex: 1,
    });
  });

  it("per-group Flatten button calls regionReplace with group-only scope", async () => {
    regionReplaceMock.mockResolvedValue({
      preview_url: "/api/files/flattened.png",
      preview_glb_url: null,
      color_contours: null,
      message: "Region replaced",
    });
    render(<GradientGroupsPanel />);
    // Two Flatten-style buttons on screen: the panel-level "Flatten all
    // gradients" and the per-group "Flatten". Pick the per-group one by
    // its shorter label.
    // 面板上有两个去海带纹按钮，按文本长度取短的那一个。
    const flattenButtons = screen.getAllByRole("button", {
      name: /^flatten$|^去海带纹$/i,
    });
    expect(flattenButtons).toHaveLength(1);
    await act(async () => {
      fireEvent.click(flattenButtons[0]);
    });

    // Now uses spatially-scoped regionReplace instead of colorRemapMap.
    // 现在走空间受限的 regionReplace 而非全图 colorRemapMap。
    expect(regionReplaceMock).toHaveBeenCalledWith(
      "sess-test",
      "#d2aeb4",
      { gradientGroupIndex: 1 },
    );
    const state = useConverterStore.getState();
    expect(state.colorRemapMap).toEqual({});
  });

  it("per-region Flatten button calls regionReplace with region scope", async () => {
    regionReplaceMock.mockResolvedValue({
      preview_url: "/api/files/region-flattened.png",
      preview_glb_url: null,
      color_contours: null,
      message: "Region replaced",
    });
    // Region breakdowns differ so we can verify region-scoped call.
    // 构造区域不同的 breakdown，验证 region 按钮只影响自己那部分。
    _resetStores({
      gradientGroups: [
        {
          group_index: 1,
          total_pixel_count: 500_000,
          material_colour_count: 3,
          material_colours: [
            { hex: "#AAAAAA", rgb: [170, 170, 170], pixel_count: 250_000 },
            { hex: "#BBBBBB", rgb: [187, 187, 187], pixel_count: 150_000 },
            { hex: "#CCCCCC", rgb: [204, 204, 204], pixel_count: 100_000 },
          ],
          representative_hex: "#AAAAAA",
          representative_rgb: [170, 170, 170],
          boundary_pair_count: 2,
          regions: [
            {
              region_index: 1,
              pixel_count: 300_000,
              bbox: [0, 0, 100, 100],
              centroid: [50, 50],
              material_breakdown: [
                { hex: "#AAAAAA", rgb: [170, 170, 170], pixel_count: 200_000 },
                { hex: "#BBBBBB", rgb: [187, 187, 187], pixel_count: 100_000 },
              ],
            },
            {
              region_index: 2,
              pixel_count: 200_000,
              bbox: [120, 50, 200, 150],
              centroid: [160, 100],
              material_breakdown: [
                { hex: "#AAAAAA", rgb: [170, 170, 170], pixel_count: 50_000 },
                { hex: "#CCCCCC", rgb: [204, 204, 204], pixel_count: 150_000 },
              ],
            },
          ],
        },
      ],
    });
    render(<GradientGroupsPanel />);
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    // After expanding, 2 per-region Flatten buttons show up alongside the
    // per-group Flatten — the per-region ones are inside the region list.
    const allFlatten = screen.getAllByRole("button", {
      name: /^flatten$|^去海带纹$/i,
    });
    // 1 per-group + 2 per-region = 3.
    expect(allFlatten).toHaveLength(3);
    await act(async () => {
      fireEvent.click(allFlatten[1]); // First region's Flatten button.
    });

    // Spatially-scoped: regionReplace called with region scope, not colorRemapMap.
    // 空间受限替换：走 regionReplace 而非 colorRemapMap。
    expect(regionReplaceMock).toHaveBeenCalledWith(
      "sess-test",
      "#aaaaaa",
      { gradientGroupIndex: 1, gradientRegionIndex: 1 },
    );
    const state = useConverterStore.getState();
    expect(state.colorRemapMap).toEqual({});
  });

  it("stale highlight response is discarded when the selection changed mid-flight", async () => {
    // Control the first highlight call's resolution so a later click can
    // supersede it before it settles.
    // 手动控制第一次 highlight 的 resolve 时机，制造竞态。
    const deferredA: { resolve: (v: { preview_url: string }) => void } = {
      resolve: () => {},
    };
    const promiseA = new Promise<{ preview_url: string }>((res) => {
      deferredA.resolve = res;
    });
    colorHighlightMock.mockReturnValueOnce(promiseA);
    colorHighlightMock.mockResolvedValueOnce({
      preview_url: "/api/files/highlight-B.png",
    });

    const groupA = _makeGroup({
      group_index: 1,
      material_colours: [
        { hex: "#AAAAAA", rgb: [170, 170, 170], pixel_count: 100 },
        { hex: "#A1A1A1", rgb: [161, 161, 161], pixel_count: 80 },
      ],
      regions: [],
    });
    const groupB = _makeGroup({
      group_index: 2,
      material_colours: [
        { hex: "#BBBBBB", rgb: [187, 187, 187], pixel_count: 100 },
        { hex: "#B1B1B1", rgb: [177, 177, 177], pixel_count: 80 },
      ],
      regions: [],
    });
    _resetStores({ gradientGroups: [groupA, groupB] });

    const { selectGradientGroupColors } = useConverterStore.getState();
    // 1. Click group A (triggers promiseA, still pending).
    act(() => {
      selectGradientGroupColors(["#AAAAAA", "#A1A1A1"]);
    });
    expect(useConverterStore.getState().selectedColors.size).toBe(2);

    // 2. Click group B (supersedes A's selection).
    act(() => {
      selectGradientGroupColors(["#BBBBBB", "#B1B1B1"]);
    });
    expect(useConverterStore.getState().selectedColors).toEqual(
      new Set(["bbbbbb", "b1b1b1"]),
    );

    // 3. Resolve A's stale highlight last — this must NOT overwrite the
    //    preview URL because selectedColors no longer matches A.
    await act(async () => {
      deferredA.resolve({ preview_url: "/api/files/highlight-A.png" });
      await Promise.resolve();
      await Promise.resolve();
    });

    const previewUrl = useConverterStore.getState().previewImageUrl;
    expect(previewUrl).not.toContain("highlight-A.png");
  });

  it("manual toggleColorInSelection clears the region-scoped gradientSelection", () => {
    // Users who first click a region button and then tweak the multi-select
    // by clicking palette tiles end up with a selection that no longer
    // matches the region's exact colour list. The palette should recover
    // its normal selected-tile rendering in that case; the mechanism is
    // ``toggleColorInSelection`` dropping ``gradientSelection`` on any
    // manual edit so downstream consumers like ``PalettePanel`` stop
    // suppressing selection borders.
    // 用户手动在调色板上 toggle 色块时，gradientSelection 应被清除，
    // 让 PalettePanel 恢复常规选中态渲染。
    const { selectGradientGroupColors, toggleColorInSelection } =
      useConverterStore.getState();

    act(() => {
      selectGradientGroupColors(["#D2AEB4", "#CB9994"], {
        kind: "region",
        groupIndex: 1,
        regionIndex: 1,
      });
    });
    expect(useConverterStore.getState().gradientSelection).toEqual({
      kind: "region",
      groupIndex: 1,
      regionIndex: 1,
    });

    act(() => {
      toggleColorInSelection("AABBCC");
    });

    // Manual multi-select edit must erase the region-scoped stamp so the
    // palette no longer hides selection indicators.
    // 手动编辑多选必须清除区域来源标记，让调色板恢复正常选中态。
    expect(useConverterStore.getState().gradientSelection).toBeNull();
  });
});
