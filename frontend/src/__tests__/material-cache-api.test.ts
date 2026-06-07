import { beforeEach, describe, expect, it, vi } from "vitest";

import apiClient from "../api/client";
import {
  buildMaterialSolverRuntime,
  deleteMaterialSolverRuntime,
  fetchMaterialSolverRuntimeDetails,
  fetchMaterialSolverRuntimeStatus,
  type MaterialSolverCacheKey,
} from "../api/materialCache";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

const mockPost = vi.mocked(apiClient.post);

const cacheKey: MaterialSolverCacheKey = {
  materialDirectoryNames: ["mat-a", "mat-b"],
  layerCount: 8,
  layerHeightMm: 0.04,
  substrate: "white",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("material solver runtime API client", () => {
  it.each([
    [
      "status",
      fetchMaterialSolverRuntimeStatus,
      "/extractor/material-solver-runtime/status",
    ],
    [
      "build",
      buildMaterialSolverRuntime,
      "/extractor/material-solver-runtime/build",
    ],
    [
      "delete",
      deleteMaterialSolverRuntime,
      "/extractor/material-solver-runtime/delete",
    ],
  ])("posts %s requests with candidate_budget", async (_name, fn, endpoint) => {
    mockPost.mockResolvedValueOnce({
      data: { status: "ok", message: "ok", cached: false },
    });

    await fn(cacheKey, { candidateBudget: 8_388_608 });

    expect(mockPost).toHaveBeenCalledOnce();
    const [url, formData, config] = mockPost.mock.calls[0];
    expect(url).toBe(endpoint);
    expect(formData).toBeInstanceOf(FormData);

    const fd = formData as FormData;
    expect(fd.get("material_directory_names")).toBe(
      JSON.stringify(["mat-a", "mat-b"]),
    );
    expect(fd.get("layer_count")).toBe("8");
    expect(fd.get("layer_height_mm")).toBe("0.04");
    expect(fd.get("substrate")).toBe("white");
    expect(fd.get("candidate_budget")).toBe("8388608");
    expect(config).toMatchObject({ timeout: 3_600_000 });
  });

  it("posts details requests with candidate_budget and max_points", async () => {
    mockPost.mockResolvedValueOnce({
      data: { status: "ok", message: "details", lab_points: [] },
    });

    await fetchMaterialSolverRuntimeDetails(cacheKey, {
      candidateBudget: 4_194_304,
      maxPoints: 512,
    });

    expect(mockPost).toHaveBeenCalledOnce();
    const [url, formData, config] = mockPost.mock.calls[0];
    expect(url).toBe("/extractor/material-solver-runtime/details");
    expect(formData).toBeInstanceOf(FormData);

    const fd = formData as FormData;
    expect(fd.get("candidate_budget")).toBe("4194304");
    expect(fd.get("max_points")).toBe("512");
    expect(config).toMatchObject({ timeout: 3_600_000 });
  });
});
