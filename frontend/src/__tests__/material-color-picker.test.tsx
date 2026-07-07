import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MaterialColorPicker from "../components/sections/MaterialColorPicker";
import { useConverterStore } from "../stores/converter";
import type { MaterialColorSuggestionsResponse } from "../api/types";

const fetchMaterialColorSuggestionsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/materialCache", async () => {
  const actual = await vi.importActual<typeof import("../api/materialCache")>(
    "../api/materialCache",
  );
  return {
    ...actual,
    fetchMaterialColorSuggestions: fetchMaterialColorSuggestionsMock,
  };
});

function _resetStore() {
  useConverterStore.setState({
    source_version: "material",
    selectedMaterialDirNames: ["red", "blue", "white"],
    materialLayerCount: 5,
    materialLayerHeightMm: 0.08,
    materialSuggestions: null,
    materialSuggestionsLoading: false,
    materialSuggestionsTargetHex: null,
    materialSuggestionsError: null,
    selectedColor: null,
    selectionMode: "current",
    selectedColors: new Set<string>(),
    selectedRegions: [],
    pendingReplacement: null,
    replacePreviewLoading: false,
  });
}

function _stubResponse(
  targetHex: string,
  overrides: Partial<MaterialColorSuggestionsResponse> = {},
): MaterialColorSuggestionsResponse {
  const cleaned = targetHex.replace(/^#/, "").toUpperCase();
  return {
    status: "ok",
    message: "ok",
    source: "cache",
    palette_hash: "fakehash",
    layer_count: 5,
    layer_height_mm: 0.08,
    substrate: "white",
    target_hex: `#${cleaned}`,
    target_rgb: [
      parseInt(cleaned.slice(0, 2), 16),
      parseInt(cleaned.slice(2, 4), 16),
      parseInt(cleaned.slice(4, 6), 16),
    ],
    suggestions: [
      {
        hex: `#${cleaned}`,
        rgb: [
          parseInt(cleaned.slice(0, 2), 16),
          parseInt(cleaned.slice(2, 4), 16),
          parseInt(cleaned.slice(4, 6), 16),
        ],
        delta_e: 0.5,
        recipe: [0, 1, 2, 1, 0],
        recipe_display: "[0,1,2,1,0]",
      },
      {
        hex: "#D06A38",
        rgb: [208, 106, 56],
        delta_e: 1.7,
        recipe: [0, 2, 2, 2, 0],
        recipe_display: "[0,2,2,2,0]",
      },
    ],
    ...overrides,
  };
}

describe("MaterialColorPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _resetStore();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows a hint when no materials are selected", () => {
    useConverterStore.setState({ selectedMaterialDirNames: [] });
    render(<MaterialColorPicker />);
    expect(
      screen.getByText(/select at least one material|请先在/i),
    ).toBeInTheDocument();
    // Submit button should not be rendered in the no-material state.
    expect(
      screen.queryByRole("button", { name: /suggest colors|生成建议/i }),
    ).toBeNull();
  });

  it("renders suggestions after a successful request and shows source chip", async () => {
    // Use a unique hex per test to avoid cross-test LRU cache hits at the
    // module level. (store's ``_materialSuggestCache`` lives for the whole
    // test run.)
    const target = "#123401";
    fetchMaterialColorSuggestionsMock.mockResolvedValueOnce(_stubResponse(target));

    render(<MaterialColorPicker />);
    const hexInput = screen.getByPlaceholderText(/#RRGGBB/i) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(hexInput, { target: { value: target } });
    });
    const submit = screen.getByRole("button", { name: /suggest colors|生成建议/i });
    await act(async () => {
      fireEvent.click(submit);
    });

    // Both swatches render, plus the source chip. The result-count text is
    // mixed with multiple inline spans so we instead verify the swatch count.
    expect(screen.getAllByRole("button", { name: /ΔE=/ })).toHaveLength(2);
    expect(screen.getByText(/cache hit|缓存命中/i)).toBeInTheDocument();
  });

  it("labels suggestions served from the hybrid runtime", async () => {
    const target = "#123405";
    fetchMaterialColorSuggestionsMock.mockResolvedValueOnce(
      _stubResponse(target, { source: "runtime" }),
    );

    render(<MaterialColorPicker />);
    const hexInput = screen.getByPlaceholderText(/#RRGGBB/i) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(hexInput, { target: { value: target } });
      fireEvent.click(
        screen.getByRole("button", { name: /suggest colors|生成建议/i }),
      );
    });

    expect(
      screen.getByText(/runtime hit|运行时命中/i),
    ).toBeInTheDocument();
  });

  it("submits on Enter key in the hex input", async () => {
    const target = "#123402";
    fetchMaterialColorSuggestionsMock.mockResolvedValueOnce(_stubResponse(target));
    render(<MaterialColorPicker />);

    const hexInput = screen.getByPlaceholderText(/#RRGGBB/i) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(hexInput, { target: { value: target } });
      fireEvent.keyDown(hexInput, { key: "Enter" });
    });

    expect(fetchMaterialColorSuggestionsMock).toHaveBeenCalledTimes(1);
    expect(fetchMaterialColorSuggestionsMock).toHaveBeenCalledWith(
      expect.objectContaining({
        materialDirectoryNames: ["red", "blue", "white"],
      }),
      target.toUpperCase(),
      expect.anything(),
    );
  });

  it("stages a pending replacement when a suggestion is clicked", async () => {
    const target = "#123403";
    fetchMaterialColorSuggestionsMock.mockResolvedValueOnce(_stubResponse(target));
    useConverterStore.setState({ selectedColor: "808080" });
    render(<MaterialColorPicker />);

    const hexInput = screen.getByPlaceholderText(/#RRGGBB/i) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(hexInput, { target: { value: target } });
      fireEvent.click(
        screen.getByRole("button", { name: /suggest colors|生成建议/i }),
      );
    });

    const swatches = screen.getAllByRole("button", { name: /ΔE=/ });
    await act(async () => {
      fireEvent.click(swatches[0]);
    });

    const pending = useConverterStore.getState().pendingReplacement;
    expect(pending).not.toBeNull();
    expect(pending!.mode).toBe("current");
    expect(pending!.sourceHex).toBe("808080");
    expect(pending!.targetHex).toBe(target.replace("#", "").toLowerCase());
  });

  it("stages the first achievable suggestion when submitting a target for a selected gradient group", async () => {
    const target = "#123406";
    fetchMaterialColorSuggestionsMock.mockResolvedValueOnce(
      _stubResponse(target, {
        suggestions: [
          {
            hex: "#654321",
            rgb: [101, 67, 33],
            delta_e: 0.7,
            recipe: [0, 1, 2, 1, 0],
            recipe_display: "[0,1,2,1,0]",
          },
        ],
      }),
    );
    useConverterStore.setState({
      selectionMode: "select-all",
      selectedColor: null,
      selectedColors: new Set(["d2aeb4", "cb9994"]),
    });
    render(<MaterialColorPicker />);

    const hexInput = screen.getByPlaceholderText(/#RRGGBB/i) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(hexInput, { target: { value: target } });
      fireEvent.click(
        screen.getByRole("button", { name: /suggest colors|生成建议/i }),
      );
    });

    const pending = useConverterStore.getState().pendingReplacement;
    expect(pending).not.toBeNull();
    expect(pending!.mode).toBe("select-all");
    expect(pending!.sourceHex).toBe("d2aeb4");
    expect(pending!.sourceColors).toEqual(["d2aeb4", "cb9994"]);
    expect(pending!.targetHex).toBe("654321");
    expect(
      screen.getByRole("button", { name: /confirm|确认替换/i }),
    ).toBeInTheDocument();
  });

  it("clears stale suggestions and does not stage a replacement after a failed target submit", async () => {
    const firstTarget = "#123407";
    const failedTarget = "#123408";
    fetchMaterialColorSuggestionsMock
      .mockResolvedValueOnce(_stubResponse(firstTarget))
      .mockRejectedValueOnce(new Error("boom solver"));
    useConverterStore.setState({
      selectionMode: "select-all",
      selectedColor: null,
      selectedColors: new Set(["d2aeb4", "cb9994"]),
    });
    render(<MaterialColorPicker />);

    const hexInput = screen.getByPlaceholderText(/#RRGGBB/i) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(hexInput, { target: { value: firstTarget } });
      fireEvent.click(
        screen.getByRole("button", { name: /suggest colors|生成建议/i }),
      );
    });
    expect(screen.getAllByRole("button", { name: /ΔE=/ })).toHaveLength(2);

    await act(async () => {
      fireEvent.change(hexInput, { target: { value: failedTarget } });
      fireEvent.click(
        screen.getByRole("button", { name: /suggest colors|生成建议/i }),
      );
    });

    expect(useConverterStore.getState().materialSuggestions).toBeNull();
    expect(useConverterStore.getState().pendingReplacement).toBeNull();
    expect(screen.queryByRole("button", { name: /ΔE=/ })).toBeNull();
  });

  it("clears stale pending replacement after an empty target submit", async () => {
    const firstTarget = "#123409";
    const emptyTarget = "#12340A";
    fetchMaterialColorSuggestionsMock
      .mockResolvedValueOnce(_stubResponse(firstTarget))
      .mockResolvedValueOnce(_stubResponse(emptyTarget, { suggestions: [] }));
    useConverterStore.setState({
      selectionMode: "select-all",
      selectedColor: null,
      selectedColors: new Set(["d2aeb4", "cb9994"]),
    });
    render(<MaterialColorPicker />);

    const hexInput = screen.getByPlaceholderText(/#RRGGBB/i) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(hexInput, { target: { value: firstTarget } });
      fireEvent.click(
        screen.getByRole("button", { name: /suggest colors|生成建议/i }),
      );
    });
    expect(useConverterStore.getState().pendingReplacement).not.toBeNull();

    await act(async () => {
      fireEvent.change(hexInput, { target: { value: emptyTarget } });
      fireEvent.click(
        screen.getByRole("button", { name: /suggest colors|生成建议/i }),
      );
    });

    expect(useConverterStore.getState().materialSuggestions?.suggestions).toEqual([]);
    expect(useConverterStore.getState().pendingReplacement).toBeNull();
  });

  it("surfaces error state from the store", async () => {
    const target = "#123404";
    fetchMaterialColorSuggestionsMock.mockRejectedValueOnce(
      new Error("boom solver"),
    );
    render(<MaterialColorPicker />);
    const hexInput = screen.getByPlaceholderText(/#RRGGBB/i) as HTMLInputElement;

    await act(async () => {
      fireEvent.change(hexInput, { target: { value: target } });
      fireEvent.click(
        screen.getByRole("button", { name: /suggest colors|生成建议/i }),
      );
    });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("boom solver");
  });

  it("accepts short-form #ABC hex and normalises it before submit", async () => {
    fetchMaterialColorSuggestionsMock.mockResolvedValueOnce(_stubResponse("#112233"));
    render(<MaterialColorPicker />);

    const hexInput = screen.getByPlaceholderText(/#RRGGBB/i) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(hexInput, { target: { value: "#123" } });
      fireEvent.click(
        screen.getByRole("button", { name: /suggest colors|生成建议/i }),
      );
    });

    expect(fetchMaterialColorSuggestionsMock).toHaveBeenCalledWith(
      expect.anything(),
      "#112233",
      expect.anything(),
    );
  });

  it("disables the submit button for invalid hex input", () => {
    render(<MaterialColorPicker />);
    const hexInput = screen.getByPlaceholderText(/#RRGGBB/i) as HTMLInputElement;
    fireEvent.change(hexInput, { target: { value: "nope" } });
    const submit = screen.getByRole("button", {
      name: /suggest colors|生成建议/i,
    }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });
});
