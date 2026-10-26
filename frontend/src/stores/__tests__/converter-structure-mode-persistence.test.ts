import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ColorMode, ModelingMode, StructureMode } from "../../api/types";
import type { ConverterState } from "../converter";

const STORAGE_KEY = "lumina_structureMode";

async function startConverter() {
  vi.resetModules();
  return (await import("../converter")).useConverterStore;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("structure mode preference", () => {
  it.each([StructureMode.SINGLE_SIDED, StructureMode.DOUBLE_SIDED])(
    "remembers a manual %s choice after restarting the converter",
    async (mode) => {
      const store = await startConverter();
      store.getState().setStructureMode(mode);

      expect(localStorage.getItem(STORAGE_KEY)).toBe(mode);
      const restarted = await startConverter();
      expect(restarted.getState().structure_mode).toBe(mode);
    },
  );

  it.each([null, "", "invalid", "single-sided"])(
    "defaults to single-sided when the saved preference is %s",
    async (saved) => {
      if (saved !== null) localStorage.setItem(STORAGE_KEY, saved);
      const store = await startConverter();
      expect(store.getState().structure_mode).toBe(StructureMode.SINGLE_SIDED);
    },
  );

  it("starts normally if reading browser storage fails", async () => {
    const getItem = localStorage.getItem.bind(localStorage);
    vi.spyOn(localStorage, "getItem").mockImplementation((key) => {
      if (key === STORAGE_KEY) throw new Error("Storage unavailable");
      return getItem(key);
    });
    const store = await startConverter();
    expect(store.getState().structure_mode).toBe(StructureMode.SINGLE_SIDED);
  });

  it("still switches modes and invalidates the download if saving fails", async () => {
    const store = await startConverter();
    store.setState({ downloadUrl: "/api/files/old.3mf", threemfDiskPath: "/old.3mf" });
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("Storage unavailable");
    });

    expect(() => store.getState().setStructureMode(StructureMode.SINGLE_SIDED)).not.toThrow();
    expect(store.getState()).toMatchObject({
      structure_mode: StructureMode.SINGLE_SIDED,
      downloadUrl: null,
      threemfDiskPath: null,
    });
  });

  it.each<[string, Partial<ConverterState>]>([
    ["fridge magnets", { enable_fridge_magnet: true }],
    ["model surfaces", { modelSurfaceEnabled: true }],
    ["vector relief", { enable_relief: true, modeling_mode: ModelingMode.VECTOR }],
    ["5-color extended", { color_mode: ColorMode.FIVE_COLOR_EXT }],
  ])("keeps the saved preference when %s requires a single side", async (_, constraint) => {
    const store = await startConverter();
    store.getState().setStructureMode(StructureMode.DOUBLE_SIDED);
    store.setState(constraint);
    store.getState().setStructureMode(StructureMode.SINGLE_SIDED);

    expect(store.getState().structure_mode).toBe(StructureMode.SINGLE_SIDED);
    expect(localStorage.getItem(STORAGE_KEY)).toBe(StructureMode.DOUBLE_SIDED);
    const restarted = await startConverter();
    expect(restarted.getState().structure_mode).toBe(StructureMode.DOUBLE_SIDED);
  });
});
