import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("../client", () => ({
  default: {
    post: vi.fn(),
  },
}));

import apiClient from "../client";
import { relayBugReport, submitBugReport } from "../feedback";

describe("submitBugReport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the payload to /feedback/bug-report", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        ticket_id: "abc12345",
        emailed: false,
        email_status: "unconfigured",
        relay_available: false,
        dump_path: "feedback/abc12345.json",
      },
    });

    const payload = {
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

    const result = await submitBugReport(payload);

    expect(apiClient.post).toHaveBeenCalledWith("/feedback/bug-report", payload);
    expect(result).toEqual({
      ticket_id: "abc12345",
      emailed: false,
      email_status: "unconfigured",
      relay_available: false,
      dump_path: "feedback/abc12345.json",
    });
  });

  it("posts confirmed payloads to /feedback/bug-report/relay", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: { forwarded: true },
    });

    const payload = {
      description: "Preview failed",
      user_email: null,
      context: {
        url: "",
        user_agent: "",
        screen_width: 0,
        screen_height: 0,
        device_pixel_ratio: 1,
        app_version: "2.0.0",
        language: "en" as const,
        theme: "dark" as const,
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
    };

    const result = await relayBugReport("abc12345", payload);

    expect(apiClient.post).toHaveBeenCalledWith("/feedback/bug-report/relay", {
      ticket_id: "abc12345",
      request_payload: payload,
    });
    expect(result).toEqual({ forwarded: true });
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
