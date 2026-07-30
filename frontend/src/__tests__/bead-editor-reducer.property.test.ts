import fc from "fast-check";
import { describe, expect, it } from "vitest";

import {
  beadEditorReducer,
  createBeadEditorState,
  type BeadEditorAction,
} from "../workshop/modules/bead/editorReducer";
import {
  createBeadProject,
  validateBeadProject,
} from "../workshop/modules/bead/project";

describe("bead editor reducer properties", () => {
  it("keeps projects valid and redo restores the exact matrix after arbitrary edits", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 8 }),
        fc.integer({ min: 1, max: 8 }),
        fc.array(
          fc.record({
            tool: fc.constantFrom(
              "paint" as const,
              "erase" as const,
              "support" as const,
              "fill" as const,
            ),
            cellSeed: fc.nat(),
            paletteSeed: fc.nat(),
          }),
          { minLength: 1, maxLength: 30 },
        ),
        (rows, columns, generatedActions) => {
          const project = createBeadProject({
            projectId: "property-editor",
            moduleVersion: "1.0.0",
            now: "2026-07-30T00:00:00.000Z",
            rows,
            columns,
            palette: [
              [0, 0, 0],
              [255, 255, 255],
              [240, 40, 50],
            ],
          });
          let state = createBeadEditorState(project);

          for (const generated of generatedActions) {
            const action: BeadEditorAction = {
              type: "apply-tool",
              tool: generated.tool,
              cellIndex: generated.cellSeed % (rows * columns),
              paletteIndex: generated.paletteSeed % project.palette.length,
            };
            state = beadEditorReducer(state, action);
            expect(validateBeadProject(state.present)).toBe(state.present);
            expect(state.present.cells).toHaveLength(rows * columns);
          }

          if (state.past.length === 0) {
            return;
          }
          const beforeUndo = structuredClone(state.present);
          const undone = beadEditorReducer(state, { type: "undo" });
          const redone = beadEditorReducer(undone, { type: "redo" });

          expect(redone.present).toEqual(beforeUndo);
          expect(validateBeadProject(redone.present)).toBe(redone.present);
        },
      ),
      { numRuns: 60 },
    );
  });
});
