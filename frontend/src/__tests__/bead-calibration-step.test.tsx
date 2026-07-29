import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { translations } from "../i18n/translations";
import {
  BeadCalibrationStep,
  type BeadCalibrationDraft,
} from "../workshop/modules/bead/BeadCalibrationStep";
import type { WorkshopRaster } from "../workshop/types";

const t = (key: string) => translations[key]?.zh ?? key;

function raster(width = 40, height = 40): WorkshopRaster {
  return {
    width,
    height,
    data: new Uint8ClampedArray(width * height * 4),
  };
}

function initialDraft(
  overrides: Partial<BeadCalibrationDraft> = {},
): BeadCalibrationDraft {
  return {
    inputMode: "hard-pixel",
    rows: 4,
    columns: 4,
    geometry: {
      originX: 0,
      originY: 0,
      cellWidth: 10,
      cellHeight: 10,
    },
    orientation: {
      rotation: 0,
      flipHorizontal: false,
      flipVertical: false,
    },
    emptySelection: null,
    transparentSupportSampleCellIndex: null,
    ...overrides,
  };
}

function Harness({
  draft = initialDraft(),
  onRecognize = vi.fn(),
}: {
  draft?: BeadCalibrationDraft;
  onRecognize?: () => void;
}) {
  const [value, setValue] = useState(draft);
  return (
    <BeadCalibrationStep
      source={raster()}
      fileName="pattern.png"
      classification={{
        mode: "hard-pixel",
        confidence: 0.91,
        scores: {
          "numbered-grid": 0.1,
          "hard-pixel": 0.91,
          "ring-preview": 0.2,
        },
      }}
      draft={value}
      busy={false}
      translate={t}
      onChange={setValue}
      onRecognize={onRecognize}
      onOpenCrop={vi.fn()}
      canCrop
    />
  );
}

describe("BeadCalibrationStep", () => {
  beforeEach(() => {
    vi.spyOn(
      HTMLCanvasElement.prototype,
      "getContext",
    ).mockReturnValue(null);
  });

  it("requires an explicit empty-cell decision before recognition", () => {
    const onRecognize = vi.fn();
    render(<Harness onRecognize={onRecognize} />);

    const recognize = screen.getByRole("button", {
      name: "识别拼豆矩阵",
    });
    expect(recognize).toBeDisabled();

    fireEvent.click(
      screen.getByRole("button", { name: "图中没有空位" }),
    );
    expect(recognize).toBeEnabled();
    fireEvent.click(recognize);
    expect(onRecognize).toHaveBeenCalledTimes(1);
  });

  it("maps a source-canvas pick to a row-major empty sample", () => {
    render(<Harness />);
    fireEvent.click(
      screen.getByRole("button", { name: "选择一个空位" }),
    );
    const canvas = screen.getByRole("img", {
      name: "拼豆图纸网格校准",
    });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 400,
      bottom: 400,
      width: 400,
      height: 400,
      toJSON: () => ({}),
    });

    fireEvent.pointerDown(canvas, {
      clientX: 250,
      clientY: 150,
    });

    expect(screen.getByText("空位样本：第 7 格")).toBeInTheDocument();
  });

  it("updates orientation and rejects a visibly non-square grid", () => {
    render(
      <Harness
        draft={initialDraft({
          geometry: {
            originX: 0,
            originY: 0,
            cellWidth: 10,
            cellHeight: 7,
          },
        })}
      />,
    );

    expect(
      screen.getByText("当前网格不是正方形，请调整行列或原点。"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "识别拼豆矩阵" }),
    ).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "旋转 90°" }));
    expect(
      screen.getByRole("button", { name: "旋转 90°" }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
