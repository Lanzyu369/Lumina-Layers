import { describe, expect, it } from "vitest";

import workshopPanelSource from "../workshop/WorkshopPanel.tsx?raw";

describe("WorkshopPanel package boundary", () => {
  it("does not import the obsolete in-tree bead implementation", () => {
    expect(workshopPanelSource).not.toMatch(
      /modules\/bead|WorkshopModuleDefinition|ComponentType module entries/,
    );
  });

  it("renders installed modules only through the sandbox frame", () => {
    expect(workshopPanelSource).toMatch(/WorkshopFrame/);
    expect(workshopPanelSource).not.toMatch(
      /OFFICIAL_WORKSHOP_MODULES|validateWorkshopModules/,
    );
  });
});
