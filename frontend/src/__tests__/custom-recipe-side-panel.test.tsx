import { fireEvent, render, screen, within } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RecipeHistoryItem } from "../api/types";
import CustomRecipeSidePanel from "../components/ui/CustomRecipeSidePanel";

vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
}));

const palette = [
  { color: "W", hex: "ffffff" },
  { color: "R", hex: "ff0000" },
];

function historyItem(
  id: string,
  recipe: number[] = [0, 1],
): RecipeHistoryItem {
  return {
    id,
    recipe,
    layerOrder: "Top2Bottom",
    predictedRgb: [10, 20, 30],
    predictedLab: [40, 50, 60],
    hex: "#0A141E",
    fromModel: true,
    createdAtMs: 1000,
  };
}

function renderPanel(
  overrides: Partial<React.ComponentProps<typeof CustomRecipeSidePanel>> = {},
) {
  const props: React.ComponentProps<typeof CustomRecipeSidePanel> = {
    palette,
    regionIds: ["r1"],
    history: [],
    onApplyHistory: vi.fn(),
    ...overrides,
  };
  return {
    ...render(<CustomRecipeSidePanel {...props} />),
    props,
  };
}

describe("CustomRecipeSidePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders an empty history state", () => {
    renderPanel({ history: [] });

    expect(screen.getByText("recipe_custom_history_empty")).toBeInTheDocument();
  });

  it("renders history rows and applies the selected entry", () => {
    const onApplyHistory = vi.fn();
    const items = [historyItem("A@Top2Bottom"), historyItem("B@Top2Bottom")];
    renderPanel({ history: items, onApplyHistory });

    const row = screen.getByTestId("recipe-history-row-A@Top2Bottom");
    expect(within(row).getAllByTestId(/recipe-history-layer-/)).toHaveLength(
      items[0].recipe.length,
    );

    fireEvent.click(row);

    expect(onApplyHistory).toHaveBeenCalledOnce();
    expect(onApplyHistory).toHaveBeenCalledWith(items[0].id);
  });

  it("disables history rows when no region is selected", () => {
    renderPanel({ history: [historyItem("A@Top2Bottom")], regionIds: [] });

    expect(screen.getByTestId("recipe-history-row-A@Top2Bottom")).toBeDisabled();
  });
});
