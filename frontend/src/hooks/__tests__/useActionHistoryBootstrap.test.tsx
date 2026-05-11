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
