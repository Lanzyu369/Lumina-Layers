import { describe, expect, it } from "vitest";

import {
  beadEditorReducer,
  createBeadEditorState,
} from "../workshop/modules/bead/editorReducer";
import { createBeadProject } from "../workshop/modules/bead/project";
import type {
  BeadCell,
  BeadProject,
} from "../workshop/modules/bead/types";

const NOW = "2026-07-30T00:00:00.000Z";

function makeProject(
  cells: BeadCell[] = Array.from(
    { length: 3 * 4 },
    () => ({ kind: "empty" }) as const,
  ),
): BeadProject {
  return createBeadProject({
    projectId: "editor",
    moduleVersion: "1.0.0",
    now: NOW,
    rows: 3,
    columns: 4,
    palette: [
      [230, 40, 50],
      [20, 120, 210],
    ],
    cells,
    confidenceIssues: [
      {
        cellIndex: 3,
        confidence: 0.4,
        reasons: ["overlay-obstruction"],
        resolved: false,
      },
    ],
  });
}

describe("bead editor reducer", () => {
  it("paints, erases, and places transparent support with reversible patches", () => {
    let state = createBeadEditorState(makeProject());

    state = beadEditorReducer(state, {
      type: "apply-tool",
      tool: "paint",
      cellIndex: 3,
      paletteIndex: 1,
      updatedAt: "2026-07-30T00:01:00.000Z",
    });
    expect(state.present.cells[3]).toEqual({
      kind: "color",
      paletteIndex: 1,
    });
    expect(state.present.confidenceIssues[0]?.resolved).toBe(true);
    expect(state.past).toHaveLength(1);

    state = beadEditorReducer(state, { type: "undo" });
    expect(state.present.cells[3]).toEqual({ kind: "empty" });
    expect(state.present.confidenceIssues[0]?.resolved).toBe(false);

    state = beadEditorReducer(state, { type: "redo" });
    expect(state.present.cells[3]).toEqual({
      kind: "color",
      paletteIndex: 1,
    });
    expect(state.present.confidenceIssues[0]?.resolved).toBe(true);

    state = beadEditorReducer(state, {
      type: "apply-tool",
      tool: "erase",
      cellIndex: 3,
    });
    expect(state.present.cells[3]).toEqual({ kind: "empty" });

    state = beadEditorReducer(state, {
      type: "apply-tool",
      tool: "support",
      cellIndex: 3,
    });
    expect(state.present.cells[3]).toEqual({
      kind: "transparent-support",
    });
  });

  it("flood-fills only the four-neighbour connected target region", () => {
    const cells: BeadCell[] = [
      { kind: "color", paletteIndex: 0 },
      { kind: "color", paletteIndex: 0 },
      { kind: "empty" },
      { kind: "color", paletteIndex: 0 },
      { kind: "color", paletteIndex: 0 },
      { kind: "empty" },
      { kind: "color", paletteIndex: 0 },
      { kind: "empty" },
      { kind: "empty" },
      { kind: "empty" },
      { kind: "empty" },
      { kind: "color", paletteIndex: 0 },
    ];
    let state = createBeadEditorState(makeProject(cells));

    state = beadEditorReducer(state, {
      type: "apply-tool",
      tool: "fill",
      cellIndex: 0,
      paletteIndex: 1,
    });

    expect(state.present.cells).toEqual([
      { kind: "color", paletteIndex: 1 },
      { kind: "color", paletteIndex: 1 },
      { kind: "empty" },
      { kind: "color", paletteIndex: 0 },
      { kind: "color", paletteIndex: 1 },
      { kind: "empty" },
      { kind: "color", paletteIndex: 0 },
      { kind: "empty" },
      { kind: "empty" },
      { kind: "empty" },
      { kind: "empty" },
      { kind: "color", paletteIndex: 0 },
    ]);
    expect(state.past[0]?.cellPatches).toHaveLength(3);

    state = beadEditorReducer(state, { type: "undo" });
    expect(state.present.cells).toEqual(cells);
  });

  it("uses the eyedropper without adding undo history", () => {
    const cells = makeProject().cells.slice();
    cells[5] = { kind: "color", paletteIndex: 1 };
    let state = createBeadEditorState(makeProject(cells));

    state = beadEditorReducer(state, {
      type: "apply-tool",
      tool: "eyedropper",
      cellIndex: 5,
    });

    expect(state.activePaletteIndex).toBe(1);
    expect(state.activeTool).toBe("paint");
    expect(state.selectedCellIndex).toBe(5);
    expect(state.past).toEqual([]);
  });

  it("does not create history for unchanged or invalid edits and clears redo after a new edit", () => {
    let state = createBeadEditorState(makeProject());

    const unchanged = beadEditorReducer(state, {
      type: "apply-tool",
      tool: "erase",
      cellIndex: 0,
    });
    expect(unchanged).toBe(state);

    state = beadEditorReducer(state, {
      type: "apply-tool",
      tool: "paint",
      cellIndex: 0,
      paletteIndex: 0,
    });
    state = beadEditorReducer(state, { type: "undo" });
    expect(state.future).toHaveLength(1);

    state = beadEditorReducer(state, {
      type: "apply-tool",
      tool: "support",
      cellIndex: 1,
    });
    expect(state.future).toEqual([]);
    expect(
      beadEditorReducer(state, {
        type: "apply-tool",
        tool: "paint",
        cellIndex: 999,
        paletteIndex: 999,
      }),
    ).toBe(state);
  });

  it("selects and explicitly resolves confidence issues", () => {
    let state = createBeadEditorState(makeProject());

    state = beadEditorReducer(state, {
      type: "select-issue",
      issueIndex: 0,
    });
    expect(state.selectedIssueIndex).toBe(0);
    expect(state.selectedCellIndex).toBe(3);

    state = beadEditorReducer(state, {
      type: "set-issue-resolved",
      issueIndex: 0,
      resolved: true,
    });
    expect(state.present.confidenceIssues[0]?.resolved).toBe(true);

    state = beadEditorReducer(state, { type: "undo" });
    expect(state.present.confidenceIssues[0]?.resolved).toBe(false);
  });
});
