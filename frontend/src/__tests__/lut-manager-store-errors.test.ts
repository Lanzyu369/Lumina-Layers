import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFetchLutInfo = vi.fn();
const mockMergeLuts = vi.fn();
const mockFetchLutList = vi.fn();

vi.mock("../api/lut", () => ({
  fetchLutInfo: (...args: unknown[]) => mockFetchLutInfo(...args),
  mergeLuts: (...args: unknown[]) => mockMergeLuts(...args),
  compareLuts: vi.fn(),
}));

vi.mock("../api/converter", () => ({
  fetchLutList: (...args: unknown[]) => mockFetchLutList(...args),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
}));

import { useLutManagerStore } from "../stores/lutManagerStore";

function expectVisibleErrorLanguage(error: string | null): void {
  expect(error).toBeTruthy();
  expect(error).not.toMatch(/Request failed/i);
  expect(error).not.toMatch(/status code\s+\d{3}/i);
}

describe("useLutManagerStore visible error language", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useLutManagerStore.setState({
      lutList: [],
      lutListLoading: false,
      primaryName: "",
      primaryInfo: null,
      primaryLoading: false,
      secondaryNames: [],
      secondaryInfos: new Map(),
      filteredSecondaryOptions: [],
      dedupThreshold: 3.0,
      merging: false,
      mergeResult: null,
      error: null,
    });
  });

  it("normalizes list load status errors", async () => {
    mockFetchLutList.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    await useLutManagerStore.getState().fetchLutList();

    expectVisibleErrorLanguage(useLutManagerStore.getState().error);
  });

  it("normalizes primary info status errors", async () => {
    mockFetchLutInfo.mockRejectedValueOnce(
      new Error("Request failed with status code 402"),
    );

    await useLutManagerStore.getState().selectPrimary("Primary LUT");

    expectVisibleErrorLanguage(useLutManagerStore.getState().error);
  });

  it("normalizes merge status errors", async () => {
    mockMergeLuts.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );
    useLutManagerStore.setState({
      primaryName: "Primary LUT",
      secondaryNames: ["Secondary LUT"],
    });

    await useLutManagerStore.getState().executeMerge();

    expectVisibleErrorLanguage(useLutManagerStore.getState().error);
  });
});
