import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { translations } from "../i18n/translations";
import {
  createBeadEditorState,
  type BeadEditorAction,
} from "../workshop/modules/bead/editorReducer";
import { BeadEditorStep } from "../workshop/modules/bead/BeadEditorStep";
import { createBeadProject } from "../workshop/modules/bead/project";
import { renderBeadProject } from "../workshop/modules/bead/renderer";

const t = (key: string) => translations[key]?.zh ?? key;

function project() {
  return createBeadProject({
    projectId: "editor-ui",
    moduleVersion: "1.0.0",
    now: "2026-07-30T00:00:00.000Z",
    rows: 2,
    columns: 2,
    palette: [
      [230, 40, 50],
      [20, 120, 210],
    ],
    cells: [
      { kind: "empty" },
      { kind: "color", paletteIndex: 0 },
      { kind: "transparent-support" },
      { kind: "color", paletteIndex: 1 },
    ],
    confidenceIssues: [
      {
        cellIndex: 1,
        confidence: 0.4,
        reasons: ["overlay-obstruction"],
        resolved: false,
      },
    ],
  });
}

describe("BeadEditorStep", () => {
  beforeEach(() => {
    vi.spyOn(
      HTMLCanvasElement.prototype,
      "getContext",
    ).mockReturnValue(null);
  });

  it("exposes matrix tools, confidence review, views, and pressure control", () => {
    const currentProject = project();
    const state = createBeadEditorState(currentProject);
    const dispatch = vi.fn<(action: BeadEditorAction) => void>();
    const pressure = renderBeadProject(currentProject, {
      compression: 50,
      pixelsPerCell: 12,
    });
    render(
      <BeadEditorStep
        state={state}
        renderResult={pressure}
        renderBusy={false}
        sourceRaster={{
          width: 2,
          height: 2,
          data: new Uint8ClampedArray(16),
        }}
        translate={t}
        dispatch={dispatch}
        onNewProject={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "编辑拼豆矩阵" }),
    ).toBeInTheDocument();
    for (const name of ["画笔", "橡皮", "吸管", "填充", "透明支撑"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }

    fireEvent.click(screen.getByRole("button", { name: "橡皮" }));
    expect(dispatch).toHaveBeenCalledWith({
      type: "set-tool",
      tool: "erase",
    });
    fireEvent.click(screen.getByRole("button", { name: "撤销" }));
    expect(dispatch).toHaveBeenCalledWith({ type: "undo" });

    fireEvent.click(screen.getByRole("button", { name: "下一个待复核格" }));
    expect(dispatch).toHaveBeenCalledWith({
      type: "select-issue",
      issueIndex: 0,
    });

    fireEvent.click(screen.getByRole("button", { name: "压合预览" }));
    expect(
      screen.getByRole("img", { name: "拼豆压合预览" }),
    ).toBeInTheDocument();

    fireEvent.change(
      screen.getByRole("slider", { name: "压合程度" }),
      { target: { value: "84" } },
    );
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "set-compression",
        compression: 84,
      }),
    );
    expect(screen.getByText("5.2 × 5.2 mm")).toBeInTheDocument();
  });

  it("maps a matrix pointer to a bounded edit action", () => {
    const state = createBeadEditorState(project());
    const dispatch = vi.fn<(action: BeadEditorAction) => void>();
    render(
      <BeadEditorStep
        state={state}
        renderResult={null}
        renderBusy={false}
        sourceRaster={null}
        translate={t}
        dispatch={dispatch}
        onNewProject={vi.fn()}
      />,
    );
    const canvas = screen.getByRole("img", {
      name: "可编辑拼豆矩阵",
    });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 200,
      bottom: 200,
      width: 200,
      height: 200,
      toJSON: () => ({}),
    });

    fireEvent.pointerDown(canvas, {
      clientX: 150,
      clientY: 50,
    });
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "apply-tool",
        cellIndex: 1,
        tool: "paint",
      }),
    );

    dispatch.mockClear();
    fireEvent.pointerDown(canvas, {
      clientX: 250,
      clientY: 50,
    });
    expect(dispatch).not.toHaveBeenCalled();
  });
});
