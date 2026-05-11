import apiClient from "./client";
import type {
  ActionEntry,
  AdvancedParams,
  SessionRingEntry,
} from "../types/actionHistory";

export interface FinalArtifactRef {
  session_id: string | null;
  /** Backend-provided download URL (often ``/api/files/<file_id>``). */
  download_url: string | null;
  /** Artifact classification, best-effort. */
  artifact_type: "3mf" | "zip" | "share_card" | null;
  /** Server path on disk if the frontend knows it (e.g. batch output dir). */
  disk_path: string | null;
  /** Which workstream originated the artifact. */
  source: "converter" | "single_stage" | "puzzle" | "vector" | "batch" | null;
}

export interface OriginalImageRef {
  session_id: string | null;
  /** Best-known filename shown to the user when they uploaded the image. */
  filename: string | null;
  source: "converter" | "single_stage" | null;
}

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
  material_backing_material_dir_name: string | null;
  recent_client_logs: ReadonlyArray<unknown>;
  /**
   * Recent user actions with workflow snapshots; populated by the
   * reproducible-bug-reports pipeline (Req 5.x). Backwards compatible:
   * omitting the field is legal for older clients.
   */
  action_history?: ReadonlyArray<ActionEntry>;
  /**
   * Recent session ids seen by the frontend (Req 6.x). Lets developers grep
   * structured server logs even after the live sessions were cleaned up.
   */
  session_history?: ReadonlyArray<SessionRingEntry>;
  /**
   * Reference to the user's original uploaded image (Req 2.x). No file bytes
   * — the backend retrieves the image through the FileRegistry by
   * ``session_id``.
   */
  active_original_image_ref?: OriginalImageRef | null;
  /**
   * Reference to the most recent generation artifact (Req 3.x). No file
   * bytes; the backend resolves the artifact through FileRegistry.
   */
  active_final_artifact_ref?: FinalArtifactRef | null;
  /**
   * Advanced generation parameters grouped by feature (Req 3.1). Present
   * only when the active tab is "converter"; ``null`` otherwise. Optional
   * for backward compatibility with clients that predate this field.
   *
   * 高级生成参数，按特性分组（Req 3.1）。仅在 converter Tab 激活时有值，
   * 其它情况为 ``null``。为兼容旧客户端保留 optional 语义。
   */
  advanced_params?: AdvancedParams | null;
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
  /**
   * Email delivery state.
   *
   * - ``sent``: SMTP accepted the message during synchronous submit.
   * - ``pending``: email will be sent later in the background task; local
   *   email is configured but the delivery result is not known yet at the
   *   moment this response is returned.
   * - ``failed``: SMTP rejected the message or the background task crashed
   *   before sending.
   * - ``unconfigured``: SMTP is not set up; no email will be attempted.
   *
   * 邮件投递状态。``sent`` 表示同步提交时 SMTP 已接受；``pending`` 表示
   * 邮件还在后台任务中排队；``failed`` 表示已尝试但失败；
   * ``unconfigured`` 表示本机未配置邮件。
   */
  email_status: "sent" | "pending" | "unconfigured" | "failed";
  relay_available: boolean;
  /**
   * Assembly status of the ticket directory. The synchronous submit path
   * returns ``in_progress`` so the UI can show a non-blocking status; the
   * background task later updates ``ticket.json`` to ``done`` or
   * ``partial_failed``. Optional for backward compatibility with clients
   * mocking older responses.
   *
   * 工单装配状态。同步路径返回 ``in_progress``，后台任务后续写入 ``done``
   * 或 ``partial_failed``。为旧客户端/测试 mock 兼容留 optional。
   */
  assembly_status?: "in_progress" | "done" | "partial_failed" | null;
}

export interface BugReportRelayResponse {
  forwarded: boolean;
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

export async function relayBugReport(
  ticketId: string,
  payload: BugReportRequestPayload,
): Promise<BugReportRelayResponse> {
  const { data } = await apiClient.post<BugReportRelayResponse>(
    "/feedback/bug-report/relay",
    {
      ticket_id: ticketId,
      request_payload: payload,
    },
  );
  return data;
}
