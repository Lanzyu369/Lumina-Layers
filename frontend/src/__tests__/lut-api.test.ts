import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import { fetchLutDetails, fetchLutDetailsCatalog } from "../api/lut";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

const mockGet = vi.mocked(apiClient.get);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("lut details api", () => {
  it("fetchLutDetailsCatalog loads the grouped catalog", async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        groups: [
          {
            manufacturer: "Bambu Lab",
            items: [
              {
                name: "Bambu Lab - PLA - RYBW",
                path: "lut-ref/fp-a.json",
                color_mode: "4-Color (RYBW)",
                source_kind: "legacy_lookup",
                manufacturer: "Bambu Lab",
                material_type: "PLA",
                manufacturer_source: "metadata",
                material_source: "folder",
                search_tokens: ["bambulab", "pla", "rybw"],
              },
            ],
          },
        ],
      },
    });

    const result = await fetchLutDetailsCatalog();

    expect(mockGet).toHaveBeenCalledWith("/lut/details/catalog");
    expect(result.groups[0].manufacturer).toBe("Bambu Lab");
    expect(result.groups[0].items[0]).toMatchObject({
      material_type: "PLA",
      search_tokens: ["bambulab", "pla", "rybw"],
    });
  });

  it("can suppress client logs for background catalog probes", async () => {
    mockGet.mockResolvedValueOnce({ data: { groups: [] } });

    const result = await fetchLutDetailsCatalog({ suppressClientLog: true });

    expect(mockGet).toHaveBeenCalledWith("/lut/details/catalog", {
      suppressClientLog: true,
    });
    expect(result.groups).toEqual([]);
  });

  it("fetchLutDetails loads one detail payload", async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        name: "Bambu Lab - PLA - RYBW",
        path: "lut-ref/fp-a.json",
        manufacturer: "Bambu Lab",
        manufacturer_source: "metadata",
        material_type: "PLA",
        material_source: "folder",
        color_mode: "4-Color (RYBW)",
        color_count: 4,
        source_kind: "legacy_lookup",
        schema_version: "1.0",
        capabilities: ["legacy_lookup"],
        supported_modes: [],
        raw_metadata: {},
        palette: [],
        coverage_stats: {
          entry_count: 4,
          plotted_point_count: 4,
          l_range: { min: 0, max: 100 },
          a_range: { min: -40, max: 60 },
          b_range: { min: -50, max: 50 },
          r_range: { min: 0, max: 255 },
          g_range: { min: 0, max: 255 },
          b_rgb_range: { min: 0, max: 255 },
        },
        lab_points: [],
        lab_points_3d: [],
        lab_hull: [],
        rgb_points: [],
        max_color_layers: 5,
        layer_height_mm: 0.08,
        line_width_mm: 0.42,
        base_layers: 10,
        base_channel_idx: 0,
        layer_order: "Top2Bottom",
      },
    });

    const result = await fetchLutDetails("Bambu Lab - PLA - RYBW");

    expect(mockGet).toHaveBeenCalledWith("/lut/Bambu%20Lab%20-%20PLA%20-%20RYBW/details");
    expect(result).toMatchObject({
      color_count: 4,
      manufacturer: "Bambu Lab",
      lab_points_3d: [],
      coverage_stats: {
        entry_count: 4,
      },
      raw_metadata: {},
    });
  });
});
