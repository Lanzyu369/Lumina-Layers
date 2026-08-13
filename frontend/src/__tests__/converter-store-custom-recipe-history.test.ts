import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PreviewResponse, RecipeHistoryItem } from "../api/types";

const convertPreviewMock = vi.hoisted(() => vi.fn());

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>(
    "../api/converter",
  );
  return {
    ...actual,
    convertPreview: convertPreviewMock,
  };
});

async function loadStore() {
  const mod = await import("../stores/converter");
  return mod.useConverterStore;
}

function makeHistoryItem(
  overrides: Partial<RecipeHistoryItem> = {},
): RecipeHistoryItem {
  const id = overrides.id ?? "1-2-3@Top2Bottom";
  return {
    id,
    recipe: [1, 2, 3],
    layerOrder: "Top2Bottom",
    predictedRgb: [10, 20, 30],
    predictedLab: [11, 22, 33],
    hex: "#0A141E",
    fromModel: true,
    createdAtMs: 1000,
    ...overrides,
  };
}

function previewResponse(): PreviewResponse {
  return {
    session_id: "session-new",
    status: "ok",
    message: "ok",
    preview_url: "/api/files/preview-new.png",
    preview_glb_url: null,
    palette: [],
    dimensions: { width: 100, height: 80 },
    warnings: [],
  };
}

describe("converter store custom recipe history", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    vi.spyOn(console, "log").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("moves duplicate pushes to the top and keeps only the latest item", async () => {
    const useConverterStore = await loadStore();
    const firstA = makeHistoryItem({ id: "A@Top2Bottom", createdAtMs: 1 });
    const b = makeHistoryItem({ id: "B@Top2Bottom", createdAtMs: 2 });
    const secondA = makeHistoryItem({ id: "A@Top2Bottom", createdAtMs: 3 });

    useConverterStore.getState().pushCustomRecipeHistory(firstA);
    useConverterStore.getState().pushCustomRecipeHistory(b);
    useConverterStore.getState().pushCustomRecipeHistory(secondA);

    expect(
      useConverterStore.getState().customRecipeHistory.map((item) => item.id),
    ).toEqual(["A@Top2Bottom", "B@Top2Bottom"]);
    expect(useConverterStore.getState().customRecipeHistory[0]).toEqual(
      secondA,
    );
  });

  it("keeps only the ten most recent unique entries", async () => {
    const useConverterStore = await loadStore();

    for (let index = 0; index < 12; index += 1) {
      useConverterStore.getState().pushCustomRecipeHistory(
        makeHistoryItem({
          id: `recipe-${index}@Top2Bottom`,
          recipe: [index],
          createdAtMs: index,
        }),
      );
    }

    const ids = useConverterStore
      .getState()
      .customRecipeHistory.map((item) => item.id);
    expect(ids).toHaveLength(10);
    expect(ids).toEqual([
      "recipe-11@Top2Bottom",
      "recipe-10@Top2Bottom",
      "recipe-9@Top2Bottom",
      "recipe-8@Top2Bottom",
      "recipe-7@Top2Bottom",
      "recipe-6@Top2Bottom",
      "recipe-5@Top2Bottom",
      "recipe-4@Top2Bottom",
      "recipe-3@Top2Bottom",
      "recipe-2@Top2Bottom",
    ]);
  });

  it("clears recipe history", async () => {
    const useConverterStore = await loadStore();

    for (let index = 0; index < 3; index += 1) {
      useConverterStore.getState().pushCustomRecipeHistory(
        makeHistoryItem({ id: `recipe-${index}@Top2Bottom` }),
      );
    }
    useConverterStore.getState().clearCustomRecipeHistory();

    expect(useConverterStore.getState().customRecipeHistory).toEqual([]);
  });

  it("keeps reusable recipe history after a successful submitPreview", async () => {
    const useConverterStore = await loadStore();
    convertPreviewMock.mockResolvedValueOnce(previewResponse());
    const historyItem = makeHistoryItem();
    useConverterStore.setState({
      imageFile: new File(["image"], "preview.png", { type: "image/png" }),
      lut_name: "demo-lut",
      customRecipeHistory: [historyItem],
    });

    await useConverterStore.getState().submitPreview();

    expect(useConverterStore.getState().customRecipeHistory).toEqual([
      historyItem,
    ]);
    expect(useConverterStore.getState().recipe_overrides).toEqual([]);
  });

  it("sets an error when applying a missing recipe history entry", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      customRecipeHistory: [makeHistoryItem({ id: "known@Top2Bottom" })],
      error: null,
    });

    await useConverterStore
      .getState()
      .applyCustomRecipeFromHistory("missing@Top2Bottom", ["region-1"]);

    expect(useConverterStore.getState().error).toBe(
      "Custom recipe history entry not found",
    );
  });

  it("applies an existing recipe history entry to the requested regions", async () => {
    const useConverterStore = await loadStore();
    const entry = makeHistoryItem({
      id: "3-2-1@Bottom2Top",
      recipe: [3, 2, 1],
      layerOrder: "Bottom2Top",
    });
    useConverterStore.setState({
      customRecipeHistory: [entry],
    });
    const applySpy = vi
      .spyOn(useConverterStore.getState(), "applyCustomRecipeOverride")
      .mockResolvedValue(undefined);

    await useConverterStore
      .getState()
      .applyCustomRecipeFromHistory(entry.id, ["region-a", "region-b"]);

    // 4th arg (virtuals) is ``undefined`` for all-native history entries.
    expect(applySpy).toHaveBeenCalledWith(
      ["region-a", "region-b"],
      entry.recipe,
      entry.layerOrder,
      undefined,
    );
  });

  it("forwards virtualMaterials from the history entry when replaying", async () => {
    // Regression: history replay must round-trip virtualMaterials through
    // ``applyCustomRecipeOverride`` so the backend validator accepts
    // ``recipe[i] >= LUT.N`` and the worker pipeline extends the palette.
    // Without this the second-use-from-history path silently 422s on sparse
    // LUTs, and ``state.recipe_overrides`` loses the virtuals — leading to
    // the same "3MF missing object / transparent-channel collapse" symptom
    // users saw during the first-apply flow.
    // 历史重放也得带上 virtualMaterials：丢了会让 ``recipe[i] >= LUT.N``
    // 被 422，worker 无法扩展 ctx["slot_names"]，重现同一组"3MF 缺对象 /
    // 透明失效"的症状。
    const useConverterStore = await loadStore();
    const entry = makeHistoryItem({
      id: "4-0-0-0-0-4@Top2Bottom",
      recipe: [4, 0, 0, 0, 0, 4],
      layerOrder: "Top2Bottom",
      virtualMaterials: [{ name: "Black", hex: "#111111" }],
    });
    useConverterStore.setState({
      customRecipeHistory: [entry],
    });
    const applySpy = vi
      .spyOn(useConverterStore.getState(), "applyCustomRecipeOverride")
      .mockResolvedValue(undefined);

    await useConverterStore
      .getState()
      .applyCustomRecipeFromHistory(entry.id, ["region-a"]);

    expect(applySpy).toHaveBeenCalledWith(
      ["region-a"],
      entry.recipe,
      entry.layerOrder,
      [{ name: "Black", hex: "#111111" }],
    );
  });
});
