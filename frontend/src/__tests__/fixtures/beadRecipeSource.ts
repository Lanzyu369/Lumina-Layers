import {
  createBeadProject,
  createBeadRecipeSource,
} from "../../workshop/modules/bead/project";
import type { WorkshopRecipeSource } from "../../workshop/types";

export function createBeadRecipeSourceFixture(): WorkshopRecipeSource {
  const project = createBeadProject({
    projectId: "share-card-bead",
    moduleVersion: "1.0.0",
    now: "2026-07-30T00:00:00.000Z",
    rows: 2,
    columns: 3,
    palette: [
      [230, 40, 50],
      [20, 120, 210],
    ],
    cells: [
      { kind: "color", paletteIndex: 0 },
      { kind: "transparent-support" },
      { kind: "empty" },
      { kind: "color", paletteIndex: 1 },
      { kind: "color", paletteIndex: 1 },
      { kind: "empty" },
    ],
    calibration: {
      inputMode: "ring-preview",
      crop: null,
      origin: { x: 0, y: 0 },
      orientation: {
        rotation: 90,
        flipHorizontal: true,
        flipVertical: false,
      },
      emptySelection: { kind: "none" },
      transparentSupportSampleCellIndex: 1,
    },
    beadPitchMm: 2.6,
    compression: 73,
  });
  return createBeadRecipeSource(project);
}
