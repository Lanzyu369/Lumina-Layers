import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("../client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import apiClient from "../client";
import {
  getBugReportStatus,
  resubmitBugReport,
  submitBugReport,
} from "../feedback";

function makePayload() {
  return {
    description: "Preview failed",
    user_email: "user@example.com",
    context: {
      url: "http://localhost:5174/",
      user_agent: "pytest",
      screen_width: 1280,
      screen_height: 720,
      device_pixel_ratio: 1,
      app_version: "2.0.0",
      language: "zh" as const,
      theme: "light" as const,
      active_tab: "converter",
      active_session_ids: {
        converter: "session-1",
        single_stage: null,
      },
      color_mode: "4-Color (RYBW)",
      lut_name: "Test LUT",
      source_version: "legacy" as const,
      selected_native_brand_key: null,
      selected_native_db_names: [],
      selected_material_dir_names: [],
      material_layer_count: null,
      material_layer_height_mm: null,
      material_backing_material_dir_name: null,
      recent_client_logs: [],
    },
    screenshot_data_url: null,
  };
}

describe("submitBugReport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the payload to /feedback/bug-report", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        ticket_id: "abc12345",
        submission_status: "pending",
        dump_path: "feedback/abc12345.json",
      },
    });

    const payload = makePayload();

    const result = await submitBugReport(payload);

    expect(apiClient.post).toHaveBeenCalledWith("/feedback/bug-report", payload);
    expect(result).toEqual({
      ticket_id: "abc12345",
      submission_status: "pending",
      dump_path: "feedback/abc12345.json",
    });
  });

  it("uses multipart form data for an exact converter source image", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        ticket_id: "LUM-202608-deadbeef",
        submission_status: "pending",
        dump_path: "feedback/2026-08/LUM-202608-deadbeef",
        original_image_status: "attached",
      },
    });
    const payload = makePayload();
    const original = new File(["<svg/>"], "source.svg", {
      type: "image/svg+xml",
    });

    await submitBugReport(payload, original);

    expect(apiClient.post).toHaveBeenCalledTimes(1);
    const [path, body] = vi.mocked(apiClient.post).mock.calls[0];
    expect(path).toBe("/feedback/bug-report");
    expect(body).toBeInstanceOf(FormData);
    const form = body as FormData;
    expect(JSON.parse(String(form.get("request_payload")))).toEqual(payload);
    const uploaded = form.get("original_image") as File;
    expect(uploaded.name).toBe("source.svg");
    expect(uploaded.type).toBe("image/svg+xml");
    expect(await uploaded.text()).toBe("<svg/>");
    expect(form.has("original_image_omission_reason")).toBe(false);
  });

  it("omits a source image over 100 MiB but keeps the report payload", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        ticket_id: "LUM-202608-deadbeef",
        submission_status: "pending",
        dump_path: "feedback/2026-08/LUM-202608-deadbeef",
        original_image_status: "too_large",
      },
    });
    const payload = makePayload();
    const oversized = new File(["x"], "oversized.png", { type: "image/png" });
    Object.defineProperty(oversized, "size", {
      configurable: true,
      value: 100 * 1024 * 1024 + 1,
    });

    await submitBugReport(payload, oversized);

    const form = vi.mocked(apiClient.post).mock.calls[0][1] as FormData;
    expect(form.get("request_payload")).not.toBeNull();
    expect(form.has("original_image")).toBe(false);
    expect(form.get("original_image_omission_reason")).toBe("too_large");
  });

  it("reads upload status for a ticket", async () => {
    const status = {
      ticket_id: "LUM-202609-deadbeef",
      assembly_status: "done",
      submission_status: "submitted",
      error_type: null,
      uploaded_attachments: ["original.png"],
      held_back_attachments: [],
    };
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: status });

    const result = await getBugReportStatus("LUM-202609-deadbeef");

    expect(apiClient.get).toHaveBeenCalledWith(
      "/feedback/bug-report/LUM-202609-deadbeef/status",
    );
    expect(result).toEqual(status);
  });

  it("asks the backend to retry a failed upload", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: { ticket_id: "LUM-202609-deadbeef", submission_status: "submitted" },
    });

    await resubmitBugReport("LUM-202609-deadbeef");

    expect(apiClient.post).toHaveBeenCalledWith(
      "/feedback/bug-report/LUM-202609-deadbeef/resubmit",
    );
  });

  it("rethrows non-2xx failures", async () => {
    const error = new Error("boom");
    vi.mocked(apiClient.post).mockRejectedValueOnce(error);

    await expect(
      submitBugReport({
        description: "Preview failed",
        user_email: null,
        context: {
          url: "",
          user_agent: "",
          screen_width: 0,
          screen_height: 0,
          device_pixel_ratio: 1,
          app_version: "2.0.0",
          language: "en",
          theme: "dark",
          active_tab: "converter",
          active_session_ids: { converter: null, single_stage: null },
          color_mode: null,
          lut_name: null,
          source_version: null,
          selected_native_brand_key: null,
          selected_native_db_names: [],
          selected_material_dir_names: [],
          material_layer_count: null,
          material_layer_height_mm: null,
          material_backing_material_dir_name: null,
          recent_client_logs: [],
        },
        screenshot_data_url: null,
      }),
    ).rejects.toBe(error);
  });
});
