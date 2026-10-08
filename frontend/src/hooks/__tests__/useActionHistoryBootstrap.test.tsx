/**
 * Integration tests for ``useActionHistoryBootstrap`` against the real
 * Zustand stores. Proves that the ``subscribeWithSelector`` middleware is
 * correctly installed and that every documented trigger actually lands
 * in ``actionHistoryStore.history``.
 *
 * 对 ``useActionHistoryBootstrap`` 做集成测试，覆盖每个 trigger 都真实
 * 进入 ``actionHistoryStore.history``，证明 ``subscribeWithSelector``
 * middleware 已正确安装。
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useConverterStore } from "../../stores/converter";
import { useWidgetStore } from "../../stores/widgetStore";
import { useActionHistoryStore } from "../../stores/actionHistoryStore";
import { useActionHistoryBootstrap } from "../useActionHistoryBootstrap";

function resetStores(): void {
  useActionHistoryStore.getState()._resetForTests();
  useConverterStore.setState({
    color_mode: "4-Color (RYBW)" as never,
    lut_name: "",
    source_version: "legacy" as never,
    selectedMaterialDirNames: [],
    materialLayerCount: 5 as never,
    materialLayerHeightMm: 0.08 as never,
    imageFile: null,
    previewImageUrl: null as unknown as string | null,
    downloadUrl: null,
  } as never);
  useWidgetStore.setState({
    activeTab: "converter" as never,
    activeConverterSubTab: "core" as never,
  } as never);
}

describe("useActionHistoryBootstrap", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetStores();
  });

  afterEach(() => {
    vi.useRealTimers();
    resetStores();
  });

  it("color_mode change produces a color_mode_change entry", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    try {
      act(() => {
        useConverterStore.setState({
          color_mode: "8-Color Max" as never,
        } as never);
      });
      const history = useActionHistoryStore.getState().history;
      expect(history.map((e) => e.action_type)).toContain("color_mode_change");
    } finally {
      unmount();
    }
  });

  it("lut_name change produces a lut_change entry", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    try {
      act(() => {
        useConverterStore.setState({ lut_name: "Lumina_Default" } as never);
      });
      expect(
        useActionHistoryStore
          .getState()
          .history.map((e) => e.action_type),
      ).toContain("lut_change");
    } finally {
      unmount();
    }
  });

  it("selectedMaterialDirNames change produces a material_selection_change entry", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    try {
      act(() => {
        useConverterStore.setState({
          selectedMaterialDirNames: ["BrandA"],
        } as never);
      });
      expect(
        useActionHistoryStore
          .getState()
          .history.map((e) => e.action_type),
      ).toContain("material_selection_change");
    } finally {
      unmount();
    }
  });

  it("captures Lumina Box as a material archive without legacy LUT or color-mode state", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    try {
      act(() => {
        useConverterStore.setState({
          source_version: "lumina_box",
          color_mode: "8-Color Max",
          lut_name: "StaleLegacyLut",
          selectedMaterialDirNames: ["lb/blue", "lb/white"],
          materialLayerCount: 8,
          materialLayerHeightMm: 0.04,
          materialBackingMaterialDirName: "lb/white",
          materialDynamicLayerCountEnabled: true,
          materialMinLayerCount: 5,
          materialMaxLayerCount: 8,
        } as never);
      });

      const entry = useActionHistoryStore
        .getState()
        .history.find((item) => item.action_type === "source_version_change");
      expect(entry?.snapshot).toMatchObject({
        source_version: "lumina_box",
        color_mode: null,
        lut_name: null,
        selected_material_dir_names: ["lb/blue", "lb/white"],
        material_layer_count: 8,
        material_layer_height_mm: 0.04,
        material_backing_material_dir_name: "lb/white",
      });
      expect(entry?.snapshot.advanced_params).toMatchObject({
        generation: {
          material_dynamic_layer_count_enabled: true,
          material_min_layer_count: 5,
          material_max_layer_count: 8,
          material_backing_material_dir_name: "lb/white",
        },
      });
    } finally {
      unmount();
    }
  });

  it("previewImageUrl going from null to a value produces a preview entry", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    try {
      act(() => {
        useConverterStore.setState({
          previewImageUrl: "blob:http://localhost/abc",
        } as never);
      });
      expect(
        useActionHistoryStore
          .getState()
          .history.map((e) => e.action_type),
      ).toContain("preview");
    } finally {
      unmount();
    }
  });

  it("downloadUrl going from null to a value produces a generate entry", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    try {
      act(() => {
        useConverterStore.setState({
          downloadUrl: "/api/files/abc",
        } as never);
      });
      expect(
        useActionHistoryStore
          .getState()
          .history.map((e) => e.action_type),
      ).toContain("generate");
    } finally {
      unmount();
    }
  });

  it("activeTab change produces a switch_tab entry", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    try {
      act(() => {
        useWidgetStore.setState({ activeTab: "extractor" as never } as never);
      });
      expect(
        useActionHistoryStore
          .getState()
          .history.map((e) => e.action_type),
      ).toContain("switch_tab");
    } finally {
      unmount();
    }
  });

  it("slider commit (layer count) debounces into a single material_param_commit", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    try {
      act(() => {
        // Simulate a slider drag: many rapid changes inside the debounce window.
        for (let n = 6; n <= 10; n += 1) {
          useConverterStore.setState({ materialLayerCount: n as never } as never);
        }
        // Advance past the slider commit debounce (180 ms).
        vi.advanceTimersByTime(200);
      });
      const commits = useActionHistoryStore
        .getState()
        .history.filter((e) => e.action_type === "material_param_commit");
      expect(commits).toHaveLength(1);
    } finally {
      unmount();
    }
  });

  it("unmount removes subscriptions so later state changes do not record", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    unmount();
    act(() => {
      useConverterStore.setState({
        color_mode: "6-Color (CMYWGK 1296)" as never,
      } as never);
    });
    expect(useActionHistoryStore.getState().history).toEqual([]);
  });
});

/**
 * Tests for advanced_params snapshot population and the six tracked
 * feature-toggle subscriptions added by the
 * feedback-advanced-params-capture spec (tasks 3.3 and 3.4).
 *
 * 针对 feedback-advanced-params-capture 规格里新增的 advanced_params 快照
 * 字段以及 6 个功能开关订阅的集成测试（任务 3.3 / 3.4）。
 */
describe("useActionHistoryBootstrap — advanced_params", () => {
  const TRACKED_TOGGLE_FIELDS = [
    "enable_relief",
    "enable_outline",
    "enable_cloisonne",
    "enable_fridge_magnet",
    "puzzleEnabled",
    "largeFormatEnabled",
  ] as const;

  function resetTrackedToggles(): void {
    // resetStores() above does not touch the 6 tracked toggles, so restore
    // them to their false defaults between tests to avoid cross-test leakage.
    // resetStores() 不覆盖这 6 个开关，这里显式回到 false 默认值以免串扰。
    const reset: Record<string, boolean> = {};
    for (const field of TRACKED_TOGGLE_FIELDS) reset[field] = false;
    useConverterStore.setState(reset as never);
  }

  beforeEach(() => {
    vi.useFakeTimers();
    resetStores();
    resetTrackedToggles();
    // Clear history again: the toggle reset above may have produced entries
    // if a prior test left them non-default.
    // 开关重置可能产生条目，这里再清一次历史。
    useActionHistoryStore.getState()._resetForTests();
  });

  afterEach(() => {
    resetTrackedToggles();
    vi.useRealTimers();
    resetStores();
  });

  it("snapshot on the converter tab includes a non-null full advanced_params", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    try {
      act(() => {
        useConverterStore.setState({ enable_relief: true } as never);
      });
      const history = useActionHistoryStore.getState().history;
      expect(history).toHaveLength(1);
      const entry = history[0];
      expect(entry.action_type).toBe("advanced_param_change");
      expect(entry.snapshot.active_tab).toBe("converter");
      const ap = entry.snapshot.advanced_params;
      expect(ap).not.toBeNull();
      // Full shape: all 11 groups must be present as objects.
      // 完整形态：11 个分组必须均为对象。
      expect(ap).toMatchObject({
        dimensions: expect.any(Object),
        generation: expect.any(Object),
        relief: expect.objectContaining({ enable_relief: true }),
        outline: expect.any(Object),
        cloisonne: expect.any(Object),
        coating: expect.any(Object),
        loop: expect.any(Object),
        fridge_magnet: expect.any(Object),
        puzzle: expect.any(Object),
        large_format: expect.any(Object),
        color_replacement: expect.any(Object),
      });
    } finally {
      unmount();
    }
  });

  it("snapshot on a non-converter tab has advanced_params: null", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    try {
      act(() => {
        useWidgetStore.setState({ activeTab: "extractor" as never } as never);
      });
      const switchEntry = useActionHistoryStore
        .getState()
        .history.find((e) => e.action_type === "switch_tab");
      expect(switchEntry).toBeDefined();
      expect(switchEntry!.snapshot.active_tab).toBe("extractor");
      expect(switchEntry!.snapshot.advanced_params).toBeNull();
    } finally {
      unmount();
    }
  });

  it.each(TRACKED_TOGGLE_FIELDS.map((f) => [f] as const))(
    "toggling %s produces exactly one advanced_param_change with the correct from/to",
    (field) => {
      const { unmount } = renderHook(() => useActionHistoryBootstrap());
      try {
        act(() => {
          useConverterStore.setState({ [field]: true } as never);
        });
        const entries = useActionHistoryStore
          .getState()
          .history.filter((e) => e.action_type === "advanced_param_change");
        expect(entries).toHaveLength(1);
        expect(entries[0].changed_fields).toEqual({
          [field]: { from: false, to: true },
        });
      } finally {
        unmount();
      }
    },
  );

  it("setting a toggle to its existing value produces zero entries", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    try {
      act(() => {
        // enable_relief is already false after reset; re-setting false is a no-op.
        // enable_relief 复位后为 false；再次 setState 为 false 不应产生条目。
        useConverterStore.setState({ enable_relief: false } as never);
      });
      const entries = useActionHistoryStore
        .getState()
        .history.filter((e) => e.action_type === "advanced_param_change");
      expect(entries).toEqual([]);
    } finally {
      unmount();
    }
  });

  it("two toggles flipped in the same setState produce two separate entries", () => {
    const { unmount } = renderHook(() => useActionHistoryBootstrap());
    try {
      act(() => {
        // subscribeWithSelector fires once per selector whose value changed,
        // so a single setState with two fields yields two entries.
        // subscribeWithSelector 按"值真正变化的 selector"逐个触发，因此
        // 单次 setState 改两个字段会产生两条独立记录。
        useConverterStore.setState({
          enable_relief: true,
          enable_outline: true,
        } as never);
      });
      const entries = useActionHistoryStore
        .getState()
        .history.filter((e) => e.action_type === "advanced_param_change");
      expect(entries).toHaveLength(2);
      const changedKeys = entries
        .flatMap((e) => Object.keys(e.changed_fields ?? {}))
        .sort();
      expect(changedKeys).toEqual(["enable_outline", "enable_relief"]);
      const reliefEntry = entries.find(
        (e) => e.changed_fields && "enable_relief" in e.changed_fields,
      );
      const outlineEntry = entries.find(
        (e) => e.changed_fields && "enable_outline" in e.changed_fields,
      );
      expect(reliefEntry?.changed_fields).toEqual({
        enable_relief: { from: false, to: true },
      });
      expect(outlineEntry?.changed_fields).toEqual({
        enable_outline: { from: false, to: true },
      });
    } finally {
      unmount();
    }
  });
});
