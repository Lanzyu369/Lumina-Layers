import { validateBeadProject } from "./project";
import type {
  BeadCell,
  BeadProject,
  RgbColor,
} from "./types";

export type BeadEditorTool =
  | "paint"
  | "erase"
  | "eyedropper"
  | "fill"
  | "support";

export interface BeadCellPatch {
  index: number;
  before: BeadCell;
  after: BeadCell;
}

interface BeadIssuePatch {
  index: number;
  before: boolean;
  after: boolean;
}

export interface BeadEditHistoryEntry {
  cellPatches: BeadCellPatch[];
  issuePatches: BeadIssuePatch[];
  beforeUpdatedAt: string;
  afterUpdatedAt: string;
}

export interface BeadEditorState {
  present: BeadProject;
  past: BeadEditHistoryEntry[];
  future: BeadEditHistoryEntry[];
  activeTool: BeadEditorTool;
  activePaletteIndex: number;
  selectedCellIndex: number | null;
  selectedIssueIndex: number | null;
}

export type BeadEditorAction =
  | {
      type: "apply-tool";
      tool?: BeadEditorTool;
      cellIndex: number;
      paletteIndex?: number;
      updatedAt?: string;
    }
  | { type: "set-tool"; tool: BeadEditorTool }
  | { type: "set-palette"; paletteIndex: number }
  | { type: "select-cell"; cellIndex: number | null }
  | { type: "select-issue"; issueIndex: number | null }
  | {
      type: "set-issue-resolved";
      issueIndex: number;
      resolved: boolean;
      updatedAt?: string;
    }
  | {
      type: "set-compression";
      compression: number;
      updatedAt?: string;
    }
  | {
      type: "set-bead-pitch";
      beadPitchMm: number;
      updatedAt?: string;
    }
  | {
      type: "add-palette-color";
      color: RgbColor;
      updatedAt?: string;
    }
  | { type: "undo" }
  | { type: "redo" };

function cellsEqual(left: BeadCell, right: BeadCell): boolean {
  if (left.kind !== right.kind) {
    return false;
  }
  return (
    left.kind !== "color" ||
    (right.kind === "color" &&
      left.paletteIndex === right.paletteIndex)
  );
}

function isValidCellIndex(
  project: BeadProject,
  cellIndex: number,
): boolean {
  return (
    Number.isInteger(cellIndex) &&
    cellIndex >= 0 &&
    cellIndex < project.cells.length
  );
}

function isValidPaletteIndex(
  project: BeadProject,
  paletteIndex: number,
): boolean {
  return (
    Number.isInteger(paletteIndex) &&
    paletteIndex >= 0 &&
    paletteIndex < project.palette.length
  );
}

function cellForTool(
  project: BeadProject,
  tool: Exclude<BeadEditorTool, "eyedropper" | "fill">,
  paletteIndex: number,
): BeadCell | null {
  if (tool === "erase") {
    return { kind: "empty" };
  }
  if (tool === "support") {
    return { kind: "transparent-support" };
  }
  return isValidPaletteIndex(project, paletteIndex)
    ? { kind: "color", paletteIndex }
    : null;
}

function connectedRegion(
  project: BeadProject,
  startIndex: number,
): number[] {
  const target = project.cells[startIndex];
  const visited = new Uint8Array(project.cells.length);
  const queue = [startIndex];
  const region: number[] = [];
  visited[startIndex] = 1;

  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const index = queue[cursor];
    region.push(index);
    const row = Math.floor(index / project.columns);
    const column = index % project.columns;
    const neighbours = [
      row > 0 ? index - project.columns : -1,
      row + 1 < project.rows ? index + project.columns : -1,
      column > 0 ? index - 1 : -1,
      column + 1 < project.columns ? index + 1 : -1,
    ];
    for (const neighbour of neighbours) {
      if (
        neighbour >= 0 &&
        !visited[neighbour] &&
        cellsEqual(project.cells[neighbour], target)
      ) {
        visited[neighbour] = 1;
        queue.push(neighbour);
      }
    }
  }

  return region;
}

function patchesForTool(
  project: BeadProject,
  tool: Exclude<BeadEditorTool, "eyedropper">,
  cellIndex: number,
  paletteIndex: number,
): BeadCellPatch[] {
  const replacement = cellForTool(
    project,
    tool === "fill" ? "paint" : tool,
    paletteIndex,
  );
  if (!replacement) {
    return [];
  }
  const indices =
    tool === "fill"
      ? connectedRegion(project, cellIndex)
      : [cellIndex];
  return indices.flatMap((index) => {
    const before = project.cells[index];
    return cellsEqual(before, replacement)
      ? []
      : [{ index, before, after: replacement }];
  });
}

function issuePatchesForCells(
  project: BeadProject,
  changedCellIndices: ReadonlySet<number>,
): BeadIssuePatch[] {
  return project.confidenceIssues.flatMap((issue, index) =>
    changedCellIndices.has(issue.cellIndex) && !issue.resolved
      ? [{ index, before: false, after: true }]
      : [],
  );
}

function applyHistoryEntry(
  project: BeadProject,
  entry: BeadEditHistoryEntry,
  direction: "forward" | "backward",
): BeadProject {
  const cells = project.cells.slice();
  for (const patch of entry.cellPatches) {
    cells[patch.index] =
      direction === "forward" ? patch.after : patch.before;
  }
  const confidenceIssues = project.confidenceIssues.map((issue) => ({
    ...issue,
  }));
  for (const patch of entry.issuePatches) {
    const issue = confidenceIssues[patch.index];
    if (issue) {
      issue.resolved =
        direction === "forward" ? patch.after : patch.before;
    }
  }
  return validateBeadProject({
    ...project,
    cells,
    confidenceIssues,
    updatedAt:
      direction === "forward"
        ? entry.afterUpdatedAt
        : entry.beforeUpdatedAt,
  });
}

function commitHistoryEntry(
  state: BeadEditorState,
  entry: BeadEditHistoryEntry,
): BeadEditorState {
  return {
    ...state,
    present: applyHistoryEntry(state.present, entry, "forward"),
    past: [...state.past, entry],
    future: [],
  };
}

function applyEyedropper(
  state: BeadEditorState,
  cellIndex: number,
): BeadEditorState {
  const cell = state.present.cells[cellIndex];
  if (cell.kind === "color") {
    return {
      ...state,
      activeTool: "paint",
      activePaletteIndex: cell.paletteIndex,
      selectedCellIndex: cellIndex,
    };
  }
  return {
    ...state,
    activeTool:
      cell.kind === "transparent-support" ? "support" : "erase",
    selectedCellIndex: cellIndex,
  };
}

export function createBeadEditorState(
  project: BeadProject,
): BeadEditorState {
  const present = validateBeadProject(project);
  return {
    present,
    past: [],
    future: [],
    activeTool: "paint",
    activePaletteIndex: 0,
    selectedCellIndex: null,
    selectedIssueIndex: null,
  };
}

export function beadEditorReducer(
  state: BeadEditorState,
  action: BeadEditorAction,
): BeadEditorState {
  if (action.type === "set-tool") {
    return action.tool === state.activeTool
      ? state
      : { ...state, activeTool: action.tool };
  }
  if (action.type === "set-palette") {
    return isValidPaletteIndex(state.present, action.paletteIndex) &&
      action.paletteIndex !== state.activePaletteIndex
      ? {
          ...state,
          activePaletteIndex: action.paletteIndex,
          activeTool: "paint",
        }
      : state;
  }
  if (action.type === "set-compression") {
    if (
      !Number.isInteger(action.compression) ||
      action.compression < 0 ||
      action.compression > 100 ||
      action.compression === state.present.compression
    ) {
      return state;
    }
    return {
      ...state,
      present: validateBeadProject({
        ...state.present,
        compression: action.compression,
        updatedAt: action.updatedAt ?? state.present.updatedAt,
      }),
    };
  }
  if (action.type === "set-bead-pitch") {
    if (
      !Number.isFinite(action.beadPitchMm) ||
      action.beadPitchMm < 0.5 ||
      action.beadPitchMm > 10 ||
      action.beadPitchMm === state.present.beadPitchMm
    ) {
      return state;
    }
    return {
      ...state,
      present: validateBeadProject({
        ...state.present,
        beadPitchMm: action.beadPitchMm,
        updatedAt: action.updatedAt ?? state.present.updatedAt,
      }),
    };
  }
  if (action.type === "add-palette-color") {
    if (
      action.color.length !== 3 ||
      action.color.some(
        (channel) =>
          !Number.isInteger(channel) ||
          channel < 0 ||
          channel > 255,
      )
    ) {
      return state;
    }
    const existingIndex = state.present.palette.findIndex(
      (color) =>
        color[0] === action.color[0] &&
        color[1] === action.color[1] &&
        color[2] === action.color[2],
    );
    if (existingIndex >= 0) {
      return {
        ...state,
        activeTool: "paint",
        activePaletteIndex: existingIndex,
      };
    }
    if (state.present.palette.length >= 256) {
      return state;
    }
    const activePaletteIndex = state.present.palette.length;
    return {
      ...state,
      activeTool: "paint",
      activePaletteIndex,
      present: validateBeadProject({
        ...state.present,
        palette: [
          ...state.present.palette,
          [...action.color] as RgbColor,
        ],
        updatedAt: action.updatedAt ?? state.present.updatedAt,
      }),
    };
  }
  if (action.type === "select-cell") {
    if (
      action.cellIndex !== null &&
      !isValidCellIndex(state.present, action.cellIndex)
    ) {
      return state;
    }
    return action.cellIndex === state.selectedCellIndex
      ? state
      : { ...state, selectedCellIndex: action.cellIndex };
  }
  if (action.type === "select-issue") {
    if (action.issueIndex === null) {
      return state.selectedIssueIndex === null
        ? state
        : { ...state, selectedIssueIndex: null };
    }
    const issue = state.present.confidenceIssues[action.issueIndex];
    return issue
      ? {
          ...state,
          selectedIssueIndex: action.issueIndex,
          selectedCellIndex: issue.cellIndex,
        }
      : state;
  }
  if (action.type === "undo") {
    const entry = state.past[state.past.length - 1];
    return entry
      ? {
          ...state,
          present: applyHistoryEntry(
            state.present,
            entry,
            "backward",
          ),
          past: state.past.slice(0, -1),
          future: [entry, ...state.future],
        }
      : state;
  }
  if (action.type === "redo") {
    const entry = state.future[0];
    return entry
      ? {
          ...state,
          present: applyHistoryEntry(
            state.present,
            entry,
            "forward",
          ),
          past: [...state.past, entry],
          future: state.future.slice(1),
        }
      : state;
  }
  if (action.type === "set-issue-resolved") {
    const issue = state.present.confidenceIssues[action.issueIndex];
    if (!issue || issue.resolved === action.resolved) {
      return state;
    }
    return commitHistoryEntry(state, {
      cellPatches: [],
      issuePatches: [
        {
          index: action.issueIndex,
          before: issue.resolved,
          after: action.resolved,
        },
      ],
      beforeUpdatedAt: state.present.updatedAt,
      afterUpdatedAt: action.updatedAt ?? state.present.updatedAt,
    });
  }

  if (!isValidCellIndex(state.present, action.cellIndex)) {
    return state;
  }
  const tool = action.tool ?? state.activeTool;
  if (tool === "eyedropper") {
    return applyEyedropper(state, action.cellIndex);
  }
  const paletteIndex =
    action.paletteIndex ?? state.activePaletteIndex;
  const cellPatches = patchesForTool(
    state.present,
    tool,
    action.cellIndex,
    paletteIndex,
  );
  if (cellPatches.length === 0) {
    return state;
  }
  const issuePatches = issuePatchesForCells(
    state.present,
    new Set(cellPatches.map((patch) => patch.index)),
  );
  return {
    ...commitHistoryEntry(state, {
      cellPatches,
      issuePatches,
      beforeUpdatedAt: state.present.updatedAt,
      afterUpdatedAt: action.updatedAt ?? state.present.updatedAt,
    }),
    selectedCellIndex: action.cellIndex,
  };
}
