import type { WorkshopRecipeSource } from "../../workshop/contracts";

export function createBeadRecipeSourceFixture(): WorkshopRecipeSource {
  return {
    manifestSchemaVersion: 1,
    moduleId: "lumina.bead-pattern",
    moduleVersion: "1.0.0",
    projectSchemaVersion: "bead-project/v1",
    renderSchemaVersion: "bead-render/v1",
    payload: {
      payloadVersion: "bead-recipe/v1",
      rows: 2,
      columns: 3,
      palette: [
        [230, 40, 50],
        [20, 120, 210],
      ],
      cellsRle: [
        [0, 1],
        [-2, 1],
        [-1, 1],
        [1, 2],
        [-1, 1],
      ],
      calibration: {
      inputMode: "ring-preview",
        orientation: {
          rotation: 90,
          flipHorizontal: true,
          flipVertical: false,
        },
      },
      beadPitchMm: 2.6,
      compression: 73,
    },
  };
}
