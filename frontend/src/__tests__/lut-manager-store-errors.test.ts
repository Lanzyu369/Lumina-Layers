import { beforeEach, describe, expect, it, vi } from "vitest";
import { tRuntime } from "../i18n/runtime";

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

  it("normalizes missing primary LUT backend details", async () => {
    mockFetchLutInfo.mockRejectedValueOnce(
      makeAxiosLikeError(
        "Request failed with status code 404",
        404,
        { detail: "LUT not found: stale-primary" },
      ),
    );

    await useLutManagerStore.getState().selectPrimary("stale-primary");

    expectMissingLutMessage(useLutManagerStore.getState().error);
  });

  it("keeps non-missing-LUT backend details readable", async () => {
    mockFetchLutInfo.mockRejectedValueOnce(
      makeAxiosLikeError(
        "Request failed with status code 422",
        422,
        { detail: "Primary LUT must use a compatible color mode" },
      ),
    );

    await useLutManagerStore.getState().selectPrimary("Primary LUT");

    expect(useLutManagerStore.getState().error).toBe(
      "Primary LUT must use a compatible color mode",
    );
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

  it("normalizes missing LUT backend details from merge failures", async () => {
    mockMergeLuts.mockRejectedValueOnce(
      makeAxiosLikeError(
        "Request failed with status code 404",
        404,
        { detail: "LUT not found: stale-secondary" },
      ),
    );
    useLutManagerStore.setState({
      primaryName: "Primary LUT",
      secondaryNames: ["stale-secondary"],
    });

    await useLutManagerStore.getState().executeMerge();

    expectMissingLutMessage(useLutManagerStore.getState().error);
  });
});
