import apiClient from "./client";

export interface BugReportContextPayload {
  url: string;
  user_agent: string;
  screen_width: number;
  screen_height: number;
  device_pixel_ratio: number;
  app_version: string;
  language: "zh" | "en";
  theme: "light" | "dark";
  active_tab: string;
  active_session_ids: {
    converter: string | null;
    single_stage: string | null;
  };
  color_mode: string | null;
  lut_name: string | null;
  source_version: "legacy" | "native" | "material" | null;
  selected_native_brand_key: string | null;
  selected_native_db_names: string[];
  selected_material_dir_names: string[];
  material_layer_count: number | null;
  material_layer_height_mm: number | null;
  recent_client_logs: ReadonlyArray<unknown>;
}

export interface BugReportRequestPayload {
  description: string;
  user_email: string | null;
  context: BugReportContextPayload;
  screenshot_data_url: string | null;
}

export interface BugReportResponse {
  ticket_id: string;
  emailed: boolean;
  dump_path: string;
}

export async function submitBugReport(
  payload: BugReportRequestPayload,
): Promise<BugReportResponse> {
  const { data } = await apiClient.post<BugReportResponse>(
    "/feedback/bug-report",
    payload,
  );
  return data;
}
