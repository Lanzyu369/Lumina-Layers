import { beforeEach, describe, expect, it, vi } from "vitest";
import { tRuntime } from "../i18n/runtime";

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

function makeAxiosLikeError(
  message: string,
  status: number,
  data: unknown,
): Error & { response: { status: number; data: unknown; headers: Record<string, string> } } {
  return Object.assign(new Error(message), {
    response: { status, data, headers: {} },
  });
}

function expectVisibleErrorLanguage(error: string | null): void {
  expect(error).toBeTruthy();
  expect(error).not.toMatch(/Request failed/i);
  expect(error).not.toMatch(/status code\s+\d{3}/i);
}

function expectMissingLutMessage(error: string | null): void {
  expect(error).toBe(tRuntime("lut_error_missing_refresh"));
  expect(error).not.toMatch(/LUT not found/i);
}

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

  it("normalizes list load status errors", async () => {
    mockFetchLutList.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    await useLutCompareStore.getState().fetchLutList();

    expectVisibleErrorLanguage(useLutCompareStore.getState().error);
  });

  it("normalizes LUT info status errors", async () => {
    mockFetchLutInfo.mockRejectedValueOnce(
      new Error("Request failed with status code 402"),
    );

    await useLutCompareStore.getState().selectLutA("LUT A");

    expectVisibleErrorLanguage(useLutCompareStore.getState().error);
  });

  it("normalizes missing LUT A backend details", async () => {
    mockFetchLutInfo.mockRejectedValueOnce(
      makeAxiosLikeError(
        "Request failed with status code 404",
        404,
        { detail: "LUT not found: stale-a" },
      ),
    );

    await useLutCompareStore.getState().selectLutA("stale-a");

    expectMissingLutMessage(useLutCompareStore.getState().error);
  });

  it("normalizes second LUT info status errors", async () => {
    mockFetchLutInfo.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    await useLutCompareStore.getState().selectLutB("LUT B");

    expectVisibleErrorLanguage(useLutCompareStore.getState().error);
  });

  it("normalizes missing LUT B backend details", async () => {
    mockFetchLutInfo.mockRejectedValueOnce(
      makeAxiosLikeError(
        "Request failed with status code 404",
        404,
        { detail: "LUT not found: stale-b" },
      ),
    );

    await useLutCompareStore.getState().selectLutB("stale-b");

    expectMissingLutMessage(useLutCompareStore.getState().error);
  });

  it("normalizes compare status errors", async () => {
    mockCompareLuts.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );
    useLutCompareStore.setState({
      lutAName: "LUT A",
      lutBName: "LUT B",
    });

    await useLutCompareStore.getState().executeCompare();

    expectVisibleErrorLanguage(useLutCompareStore.getState().error);
  });

  it("normalizes missing LUT backend details from compare failures", async () => {
    mockCompareLuts.mockRejectedValueOnce(
      makeAxiosLikeError(
        "Request failed with status code 404",
        404,
        { detail: "LUT not found: stale-compare" },
      ),
    );
    useLutCompareStore.setState({
      lutAName: "LUT A",
      lutBName: "stale-compare",
    });

    await useLutCompareStore.getState().executeCompare();

    expectMissingLutMessage(useLutCompareStore.getState().error);
  });
});
