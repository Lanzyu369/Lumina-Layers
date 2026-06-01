import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import { colorcheckerPrepareSource } from "../api/extractor";
import { createPreviewResource } from "../api/system";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

const mockPost = vi.mocked(apiClient.post);

const previewResourceResponse = {
  resource_id: "source-raw",
  preview_id: "preview-raw",
  preview_url: "/api/files/preview-raw",
  full_width: 6000,
  full_height: 4000,
  preview_width: 1800,
  preview_height: 1200,
  source_type: "raw",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("createPreviewResource", () => {
  it("keeps the default bounded-preview timeout for generic callers", async () => {
    mockPost.mockResolvedValueOnce({ data: previewResourceResponse });

    const file = new File(["png"], "chart.png", { type: "image/png" });

    await createPreviewResource(file, "colorchecker");

    expect(mockPost).toHaveBeenCalledOnce();
    const [url, formData, config] = mockPost.mock.calls[0];
    expect(url).toBe("/system/preview-resources");
    expect(formData).toBeInstanceOf(FormData);
    expect((formData as FormData).get("file")).toBe(file);
    expect((formData as FormData).get("context")).toBe("colorchecker");
    expect(config).toMatchObject({
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 120_000,
    });
  });
});

describe("colorcheckerPrepareSource", () => {
  it("uses the long extractor timeout for large RAW/DNG source uploads", async () => {
    mockPost.mockResolvedValueOnce({ data: previewResourceResponse });

    const file = new File(["raw"], "chart.dng", {
      type: "image/x-adobe-dng",
    });

    const result = await colorcheckerPrepareSource(file);

    expect(mockPost).toHaveBeenCalledOnce();
    const [url, formData, config] = mockPost.mock.calls[0];
    expect(url).toBe("/system/preview-resources");
    expect((formData as FormData).get("file")).toBe(file);
    expect((formData as FormData).get("context")).toBe("colorchecker");
    expect(config).toMatchObject({
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 3_600_000,
    });
    expect(result).toEqual({
      colorchecker_source_file_id: "source-raw",
      source_preview_file_id: "preview-raw",
      source_preview_url: "/api/files/preview-raw",
      full_width: 6000,
      full_height: 4000,
      preview_width: 1800,
      preview_height: 1200,
      source_type: "raw",
    });
  });
});
