import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LabPointCloud3D, { clearLabPointCloud3DHullCacheForTests } from "../LabPointCloud3D";

const originalWorker = globalThis.Worker;
const originalResizeObserver = globalThis.ResizeObserver;

class MockWorker {
  onmessage: ((event: MessageEvent) => void) | null = null;

  onerror: ((event: ErrorEvent) => void) | null = null;

  postMessage = vi.fn();

  terminate = vi.fn();
}

class MockResizeObserver {
  callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }

  observe(target: Element) {
    this.callback(
      [
        {
          target,
          contentRect: {
            width: 600,
            height: 0,
            x: 0,
            y: 0,
            top: 0,
            right: 600,
            bottom: 0,
            left: 0,
            toJSON: () => ({}),
          },
        } as ResizeObserverEntry,
      ],
      this as unknown as ResizeObserver,
    );
  }

  unobserve() {}

  disconnect() {}
}

describe("LabPointCloud3D", () => {
  beforeEach(() => {
    clearLabPointCloud3DHullCacheForTests();
    Object.defineProperty(globalThis, "Worker", {
      configurable: true,
      writable: true,
      value: MockWorker,
    });
    Object.defineProperty(globalThis, "ResizeObserver", {
      configurable: true,
      writable: true,
      value: MockResizeObserver,
    });
  });

  afterEach(() => {
    Object.defineProperty(globalThis, "Worker", {
      configurable: true,
      writable: true,
      value: originalWorker,
    });
    Object.defineProperty(globalThis, "ResizeObserver", {
      configurable: true,
      writable: true,
      value: originalResizeObserver,
    });
  });

  it("derives the 3d viewport height from the current column width", async () => {
    render(
      <LabPointCloud3D
        dataTestId="lab-3d"
        points={[
          { l: 62, a: -14, b: 18, hex_color: "#ff3366", rgb: [255, 51, 102], label: "1" },
          { l: 71, a: 22, b: 9, hex_color: "#33ccff", rgb: [51, 204, 255], label: "2" },
          { l: 48, a: 12, b: -24, hex_color: "#6633ff", rgb: [102, 51, 255], label: "3" },
          { l: 54, a: -20, b: -16, hex_color: "#11aa66", rgb: [17, 170, 102], label: "4" },
        ]}
        emptyMessage="暂无点位数据"
        loadingHullMessage="正在生成 3D 外壳..."
        hullErrorMessage="3D 外壳生成失败，已仅显示点云。"
        axisXLabel="X = a*"
        axisYLabel="Y = L*"
        axisZLabel="Z = b*"
        referenceSliceToggleLabel="参考切片"
        referenceSliceStatusTemplate="参考切片 · L* {lightness}"
        referenceSliceSliderLabel="参考切片 L*"
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("lab-3d-viewport")).toHaveStyle({ height: "492px" });
    });
  });

  it("keeps the reference slice off by default and toggles it on with the current L* layer", async () => {
    render(
      <LabPointCloud3D
        dataTestId="lab-3d"
        points={[
          { l: 62, a: -14, b: 18, hex_color: "#ff3366", rgb: [255, 51, 102], label: "1" },
          { l: 71, a: 22, b: 9, hex_color: "#33ccff", rgb: [51, 204, 255], label: "2" },
          { l: 48, a: 12, b: -24, hex_color: "#6633ff", rgb: [102, 51, 255], label: "3" },
          { l: 54, a: -20, b: -16, hex_color: "#11aa66", rgb: [17, 170, 102], label: "4" },
        ]}
        emptyMessage="暂无点位数据"
        loadingHullMessage="正在生成 3D 外壳..."
        hullErrorMessage="3D 外壳生成失败，已仅显示点云。"
        axisXLabel="X = a*"
        axisYLabel="Y = L*"
        axisZLabel="Z = b*"
        referenceSliceToggleLabel="参考切片"
        referenceSliceStatusTemplate="参考切片 · L* {lightness}"
        referenceSliceSliderLabel="参考切片 L*"
      />,
    );

    const toggle = screen.getByRole("button", { name: "参考切片" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByTestId("lab-3d-reference-slice")).not.toBeInTheDocument();

    toggle.click();

    await waitFor(() => {
      expect(toggle).toHaveAttribute("aria-pressed", "true");
    });
    expect(screen.getByTestId("lab-3d-reference-slice")).toBeInTheDocument();
    expect(screen.getByText("参考切片 · L* 59.5")).toBeInTheDocument();
    expect(document.querySelector("planegeometry")?.getAttribute("args")).toBe("240,240");
  });

  it("moves the reference slice along the L axis when the slider changes", async () => {
    render(
      <LabPointCloud3D
        dataTestId="lab-3d"
        points={[
          { l: 62, a: -14, b: 18, hex_color: "#ff3366", rgb: [255, 51, 102], label: "1" },
          { l: 71, a: 22, b: 9, hex_color: "#33ccff", rgb: [51, 204, 255], label: "2" },
          { l: 48, a: 12, b: -24, hex_color: "#6633ff", rgb: [102, 51, 255], label: "3" },
          { l: 54, a: -20, b: -16, hex_color: "#11aa66", rgb: [17, 170, 102], label: "4" },
        ]}
        emptyMessage="暂无点位数据"
        loadingHullMessage="正在生成 3D 外壳..."
        hullErrorMessage="3D 外壳生成失败，已仅显示点云。"
        axisXLabel="X = a*（-绿 / +红）"
        axisYLabel="Y = L*（暗 → 亮）"
        axisZLabel="Z = b*（-蓝 / +黄）"
        referenceSliceToggleLabel="参考切片"
        referenceSliceStatusTemplate="参考切片 · L* {lightness}"
        referenceSliceSliderLabel="参考切片 L*"
      />,
    );

    const toggle = screen.getByRole("button", { name: "参考切片" });
    toggle.click();

    await waitFor(() => {
      expect(screen.getByText("参考切片 · L* 59.5")).toBeInTheDocument();
    });

    const slider = screen.getByRole("slider", { name: "参考切片 L*" });
    fireEvent.change(slider, { target: { value: "80" } });

    await waitFor(() => {
      expect(screen.getByText("参考切片 · L* 80.0")).toBeInTheDocument();
    });
  });

  it("renders axis labels that explain the meaning of the three Lab axes", () => {
    render(
      <LabPointCloud3D
        dataTestId="lab-3d"
        points={[
          { l: 62, a: -14, b: 18, hex_color: "#ff3366", rgb: [255, 51, 102], label: "1" },
          { l: 71, a: 22, b: 9, hex_color: "#33ccff", rgb: [51, 204, 255], label: "2" },
          { l: 48, a: 12, b: -24, hex_color: "#6633ff", rgb: [102, 51, 255], label: "3" },
          { l: 54, a: -20, b: -16, hex_color: "#11aa66", rgb: [17, 170, 102], label: "4" },
        ]}
        emptyMessage="暂无点位数据"
        loadingHullMessage="正在生成 3D 外壳..."
        hullErrorMessage="3D 外壳生成失败，已仅显示点云。"
        axisXLabel="X = a*（-绿 / +红）"
        axisYLabel="Y = L*（暗 → 亮）"
        axisZLabel="Z = b*（-蓝 / +黄）"
        referenceSliceToggleLabel="参考切片"
        referenceSliceStatusTemplate="参考切片 · L* {lightness}"
        referenceSliceSliderLabel="参考切片 L*"
      />,
    );

    expect(screen.getByText("X = a*（-绿 / +红）")).toBeInTheDocument();
    expect(screen.getByText("Y = L*（暗 → 亮）")).toBeInTheDocument();
    expect(screen.getByText("Z = b*（-蓝 / +黄）")).toBeInTheDocument();
  });
});
