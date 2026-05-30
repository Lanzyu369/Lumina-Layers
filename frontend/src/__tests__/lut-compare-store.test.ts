import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFetchLutInfo = vi.fn();
const mockCompareLuts = vi.fn();
const mockFetchLutList = vi.fn();

vi.mock("../api/lut", () => ({
  fetchLutInfo: (...args: unknown[]) => mockFetchLutInfo(...args),
  compareLuts: (...args: unknown[]) => mockCompareLuts(...args),
}));

vi.mock("../api/converter", () => ({
  fetchLutList: (...args: unknown[]) => mockFetchLutList(...args),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
}));

import { useLutCompareStore } from "../stores/lutCompareStore";

describe("useLutCompareStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useLutCompareStore.setState({
      lutList: [],
      lutListLoading: false,
      lutAName: "",
      lutBName: "",
      lutAInfo: null,
      lutBInfo: null,
      lutAInfoLoading: false,
      lutBInfoLoading: false,
      comparing: false,
      compareResult: null,
      error: null,
    });
  });

  it("clears stale list-load errors after a successful retry", async () => {
    mockFetchLutList.mockRejectedValueOnce(new Error("first load failed"));
    await useLutCompareStore.getState().fetchLutList();

    expect(useLutCompareStore.getState().error).toBe("first load failed");

    mockFetchLutList.mockResolvedValueOnce({
      luts: [
        { name: "LUT A", color_mode: "4-Color (RYBW)", path: "/fake/a.json" },
      ],
    });
    await useLutCompareStore.getState().fetchLutList();

    const state = useLutCompareStore.getState();
    expect(state.error).toBeNull();
    expect(state.lutList).toHaveLength(1);
    expect(state.lutList[0].name).toBe("LUT A");
  });
});
