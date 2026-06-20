import { fireEvent, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BasicSettings from "../components/sections/BasicSettings";
import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import * as importFlow from "../recipe/importFlow";

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>(
    "../api/converter",
  );
  return {
    ...actual,
    fetchLutList: vi.fn().mockResolvedValue({ luts: [] }),
  };
});

vi.mock("../api/lut", async () => {
  const actual = await vi.importActual<typeof import("../api/lut")>(
    "../api/lut",
  );
  return {
    ...actual,
    fetchLutCatalog: vi.fn().mockResolvedValue({
      legacy_groups: [],
      native_brand_groups: [],
    }),
    fetchLutDetailsCatalog: vi.fn().mockResolvedValue({ groups: [] }),
  };
});

vi.mock("../api/extractor", async () => {
  const actual = await vi.importActual<typeof import("../api/extractor")>(
    "../api/extractor",
  );
  return {
    ...actual,
    listGradientCardMaterials: vi.fn().mockResolvedValue({
      status: "success",
      message: "ok",
      materials: [],
    }),
  };
});

vi.mock("../recipe/importFlow", async () => {
  const actual = await vi.importActual<typeof import("../recipe/importFlow")>(
    "../recipe/importFlow",
  );
  return {
    ...actual,
    prepareImport: vi.fn(),
  };
});

const mockPrepareImport = vi.mocked(importFlow.prepareImport);
const RAW_HTTP_STATUS_PATTERN =
  /Request failed with status code|status code\s+\d{3}/i;

function getShareCardInput(): HTMLInputElement {
  const input = Array.from(
    document.querySelectorAll<HTMLInputElement>('input[type="file"]'),
  ).find((candidate) => candidate.accept.includes("image/png"));
  if (!input) {
    throw new Error("share-card input not found");
  }
  return input;
}

describe("BasicSettings recipe import visible errors", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({ language: "zh" });
    useConverterStore.setState({
      imageFile: null,
      imagePreviewUrl: null,
      previewImageUrl: null,
      batchMode: false,
      batchFiles: [],
      error: null,
    });
  });

  it("normalizes raw HTTP status text when recipe import preparation fails", async () => {
    mockPrepareImport.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    render(<BasicSettings />);

    const file = new File(["{}"], "broken.lumina.json", {
      type: "application/json",
    });
    fireEvent.change(getShareCardInput(), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(mockPrepareImport).toHaveBeenCalledWith(file);
    });
    await waitFor(() => {
      const error = useConverterStore.getState().error;
      expect(error).toBeTruthy();
      expect(error).not.toMatch(RAW_HTTP_STATUS_PATTERN);
      expect(error).toBe("导入失败：服务器发生内部错误。请使用请求 ID 查看日志。");
    });
  });

  it("preserves readable recipe import validation errors", async () => {
    mockPrepareImport.mockRejectedValueOnce(
      new Error("Invalid .lumina.json: failed to parse JSON"),
    );

    render(<BasicSettings />);

    const file = new File(["not-json"], "broken.lumina.json", {
      type: "application/json",
    });
    fireEvent.change(getShareCardInput(), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(mockPrepareImport).toHaveBeenCalledWith(file);
    });
    await waitFor(() => {
      expect(useConverterStore.getState().error).toBe(
        "导入失败：Invalid .lumina.json: failed to parse JSON",
      );
    });
  });
});
