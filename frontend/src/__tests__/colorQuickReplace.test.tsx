import type { HTMLAttributes, ReactNode } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SimilarRecipesResponse } from "../api/types";
import ColorQuickReplacePanel from "../components/colorQuickReplace/ColorQuickReplacePanel";
import SelectionToolPicker from "../components/sections/SelectionToolPicker";
import { normalizeReferenceHex } from "../hooks/useSimilarRecipes";
import { useEyedropperStore } from "../stores/eyedropperStore";
import {
  DEFAULT_STATE,
  MAX_COLOR_RANGE_TOLERANCE,
  useConverterStore,
  type SelectionDocument,
} from "../stores/converter";

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: HTMLAttributes<HTMLDivElement> & { children?: ReactNode }) => (
      <div {...props}>{children}</div>
    ),
    button: ({ children, whileHover: _h, whileTap: _t, transition: _tr, ...props }: HTMLAttributes<HTMLButtonElement> & {
      children?: ReactNode;
      whileHover?: unknown;
      whileTap?: unknown;
      transition?: unknown;
    }) => <button {...props}>{children}</button>,
  },
  AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>("../api/converter");
  return {
    ...actual,
    fetchSimilarRecipes: vi.fn(),
    mutateEditorSelection: vi.fn(),
  };
});

const converterApi = await import("../api/converter");
const fetchSimilarRecipes = vi.mocked(converterApi.fetchSimilarRecipes);
const mutateEditorSelection = vi.mocked(converterApi.mutateEditorSelection);

const REPLACE_BUTTON_NAME = /把选区替换成这个颜色|Replace selection with this color/;

function selectionDocument(overrides: Partial<SelectionDocument> = {}): SelectionDocument {
  return {
    selection_revision: 2,
    content_revision: 1,
    selected_pixel_count: 120,
    selected_component_count: 3,
    selected_color_hexes: ["#c80000"],
    region_ids: ["__editor_selection__:2"],
    components: [],
    contours: [],
    can_undo: true,
    can_redo: false,
    ...overrides,
  };
}

const RESPONSE: SimilarRecipesResponse = {
  status: "ok",
  target_color: "#c80000",
  layer_order: "Top2Bottom",
  predictive_available: true,
  items: [
    { hex: "#ca0202", rgb: [202, 2, 2], delta_e00: 0.8, recipe: [1, 1, 0], source: "lut", in_image: true },
    { hex: "#c40606", rgb: [196, 6, 6], delta_e00: 2.4, recipe: [1, 0, 1], source: "predictive", in_image: false },
  ],
};

describe("normalizeReferenceHex", () => {
  it("normalises valid colours and rejects others", () => {
    expect(normalizeReferenceHex("FF8800")).toBe("#ff8800");
    expect(normalizeReferenceHex(" #AbCdEf ")).toBe("#abcdef");
    expect(normalizeReferenceHex("#fff")).toBeNull();
    expect(normalizeReferenceHex(null)).toBeNull();
  });
});

describe("colour-range selection store wiring", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useConverterStore.setState({ ...DEFAULT_STATE, sessionId: "s1", selectionDocument: selectionDocument() });
  });

  it("clamps the tolerance to the supported range", () => {
    const { setColorRangeTolerance } = useConverterStore.getState();
    setColorRangeTolerance(-3);
    expect(useConverterStore.getState().colorRangeTolerance).toBe(0);
    setColorRangeTolerance(999);
    expect(useConverterStore.getState().colorRangeTolerance).toBe(MAX_COLOR_RANGE_TOLERANCE);
    setColorRangeTolerance(4.26);
    expect(useConverterStore.getState().colorRangeTolerance).toBe(4.3);
  });

  it("forwards the tolerance with the colour-range mutation", async () => {
    mutateEditorSelection.mockResolvedValue(selectionDocument({ selection_revision: 3 }));
    await useConverterStore.getState().applySelectionMutation({
      operation: "color-range-toggle",
      x: 4,
      y: 5,
      colorTolerance: 7.5,
    });
    expect(mutateEditorSelection).toHaveBeenCalledWith(
      expect.objectContaining({
        session_id: "s1",
        operation: "color-range-toggle",
        x: 4,
        y: 5,
        color_tolerance: 7.5,
      }),
    );
  });

  it("treats the colour-range tool as a shared-selection tool", () => {
    useConverterStore.getState().setSelectionTool("color-range");
    expect(useConverterStore.getState().selectionMode).toBe("multi-select");
  });
});

describe("ColorQuickReplacePanel", () => {
  const replaceSharedSelectionColor = vi.fn<(hex: string) => Promise<boolean>>();
  const applyCustomRecipeOverride = vi.fn<
    (regionIds: string[], recipe: number[], layerOrder?: string) => Promise<void>
  >();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    replaceSharedSelectionColor.mockResolvedValue(true);
    applyCustomRecipeOverride.mockResolvedValue(undefined);
    fetchSimilarRecipes.mockResolvedValue(RESPONSE);
    useConverterStore.setState({
      ...DEFAULT_STATE,
      sessionId: "s1",
      previewImageUrl: "/api/files/preview.png",
      hasManualPreview: true,
      source_version: "legacy",
      selectionDocument: selectionDocument(),
      replaceSharedSelectionColor,
      applyCustomRecipeOverride,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  async function renderPanel() {
    render(<ColorQuickReplacePanel />);
    await act(async () => {
      vi.advanceTimersByTime(250);
    });
  }

  it("recommends recipes for the selected colour", async () => {
    await renderPanel();
    expect(fetchSimilarRecipes).toHaveBeenCalledWith(
      expect.objectContaining({ session_id: "s1", target_color: "#c80000" }),
      expect.any(AbortSignal),
    );
    const items = screen.getAllByTestId("quick-replace-recipe-item");
    expect(items).toHaveLength(2);
    // Only colours already printed in the image carry the "in image" hint.
    expect(within(items[0]).getByTestId("quick-replace-in-image")).toBeInTheDocument();
    expect(within(items[1]).queryByTestId("quick-replace-in-image")).toBeNull();
  });

  it("applies a measured LUT recipe through shared-selection replacement", async () => {
    await renderPanel();
    const [lutItem] = screen.getAllByTestId("quick-replace-recipe-item");
    fireEvent.click(within(lutItem).getByRole("button"));
    expect(replaceSharedSelectionColor).toHaveBeenCalledWith("ca0202");
    expect(applyCustomRecipeOverride).not.toHaveBeenCalled();
  });

  it("applies a predictive recipe as a Top2Bottom recipe override on the selection", async () => {
    await renderPanel();
    const items = screen.getAllByTestId("quick-replace-recipe-item");
    fireEvent.click(within(items[1]).getByRole("button"));
    expect(applyCustomRecipeOverride).toHaveBeenCalledWith(
      ["__editor_selection__:2"],
      [1, 0, 1],
      "Top2Bottom",
    );
    expect(replaceSharedSelectionColor).not.toHaveBeenCalled();
  });

  it("disables apply buttons without a selection", async () => {
    useConverterStore.setState({
      selectionDocument: selectionDocument({ selected_component_count: 0, selected_color_hexes: [] }),
    });
    render(<ColorQuickReplacePanel />);
    fireEvent.change(screen.getByTestId("quick-replace-target-hex"), { target: { value: "#c80000" } });
    await act(async () => {
      vi.advanceTimersByTime(250);
    });
    for (const item of screen.getAllByTestId("quick-replace-recipe-item")) {
      expect(within(item).getByRole("button")).toBeDisabled();
    }
  });

  it("uses target colour B and replaces with its nearest printable recipe", async () => {
    await renderPanel();
    fetchSimilarRecipes.mockResolvedValue({ ...RESPONSE, target_color: "#00ff00" });
    fireEvent.change(screen.getByTestId("quick-replace-target-hex"), { target: { value: "00FF00" } });
    await act(async () => {
      vi.advanceTimersByTime(250);
    });
    expect(fetchSimilarRecipes).toHaveBeenLastCalledWith(
      expect.objectContaining({ target_color: "#00ff00" }),
      expect.any(AbortSignal),
    );
    expect(within(screen.getByTestId("quick-replace-nearest-printable")).getByText(/#ca0202/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: REPLACE_BUTTON_NAME }));
    expect(replaceSharedSelectionColor).toHaveBeenCalledWith("ca0202");
  });

  it("suggests image colors for material archives and applies them by region replace", async () => {
    fetchSimilarRecipes.mockResolvedValue({
      ...RESPONSE,
      predictive_available: false,
      items: [
        { hex: "#c80000", rgb: [200, 0, 0], delta_e00: 0, recipe: [1, 1], source: "image", in_image: true },
        { hex: "#cc0402", rgb: [204, 4, 2], delta_e00: 1.9, recipe: [2, 1], source: "image", in_image: true },
      ],
    });
    useConverterStore.setState({ source_version: "material" });
    await renderPanel();
    const items = screen.getAllByTestId("quick-replace-recipe-item");
    expect(items).toHaveLength(2);
    expect(within(items[1]).getByTestId("quick-replace-in-image")).toBeInTheDocument();
    fireEvent.click(within(items[1]).getByRole("button"));
    expect(replaceSharedSelectionColor).toHaveBeenCalledWith("cc0402");
    expect(applyCustomRecipeOverride).not.toHaveBeenCalled();
  });

  it("replaces with exactly B for material archives", async () => {
    useConverterStore.setState({ source_version: "material" });
    await renderPanel();
    fireEvent.change(screen.getByTestId("quick-replace-target-hex"), { target: { value: "#123456" } });
    expect(screen.queryByTestId("quick-replace-nearest-printable")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: REPLACE_BUTTON_NAME }));
    expect(replaceSharedSelectionColor).toHaveBeenCalledWith("123456");
  });

  it("fills target colour B from an eyedropper pick on the image", async () => {
    useEyedropperStore.setState({ active: false, lastPick: null });
    await renderPanel();
    fireEvent.click(screen.getByTestId("quick-replace-eyedropper"));
    expect(useEyedropperStore.getState().active).toBe(true);
    act(() => {
      useEyedropperStore.getState().complete("1E3CC8");
    });
    expect(screen.getByTestId("quick-replace-target-hex")).toHaveValue("#1e3cc8");
    await act(async () => {
      vi.advanceTimersByTime(250);
    });
    expect(fetchSimilarRecipes).toHaveBeenLastCalledWith(
      expect.objectContaining({ target_color: "#1e3cc8" }),
      expect.any(AbortSignal),
    );
  });

  it("cancels the eyedropper with Esc and when the card collapses", async () => {
    useEyedropperStore.setState({ active: false, lastPick: null });
    await renderPanel();
    fireEvent.click(screen.getByTestId("quick-replace-eyedropper"));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(useEyedropperStore.getState().active).toBe(false);
    fireEvent.click(screen.getByTestId("quick-replace-eyedropper"));
    fireEvent.click(screen.getByRole("button", { expanded: true }));
    expect(useEyedropperStore.getState().active).toBe(false);
  });

  it("does not request suggestions while collapsed", async () => {
    await renderPanel();
    fetchSimilarRecipes.mockClear();
    fireEvent.click(screen.getByRole("button", { expanded: true }));
    expect(screen.queryByTestId("quick-replace-target-hex")).toBeNull();
    act(() => {
      useConverterStore.setState({ selectionDocument: selectionDocument({ selected_color_hexes: ["#00ff00"] }) });
    });
    await act(async () => {
      vi.advanceTimersByTime(250);
    });
    expect(fetchSimilarRecipes).not.toHaveBeenCalled();
  });
});

describe("SelectionToolPicker", () => {
  it("shows the tolerance control only for the colour-range tool", () => {
    useConverterStore.setState({ ...DEFAULT_STATE, selectionTool: "point" });
    render(<SelectionToolPicker />);
    expect(screen.queryByTestId("color-range-tolerance-control")).toBeNull();
    act(() => {
      useConverterStore.getState().setSelectionTool("color-range");
    });
    expect(screen.getByTestId("color-range-tolerance-control")).toBeInTheDocument();
  });
});
