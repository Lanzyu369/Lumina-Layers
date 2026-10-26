import type { ErrorTicketPromptInfo } from "../stores/errorTicketPromptStore";

export type Translate = (key: string) => string;

/**
 * Build the bug-report description pre-filled after the user accepts the
 * prompt: a line asking what they were doing, then the captured error.
 * 用户接受提示后预填到工单描述中的文本：先请用户补充操作，再附自动记录的错误。
 */
export function buildErrorTicketDescription(
  info: ErrorTicketPromptInfo,
  t: Translate,
): string {
  const kindLabel =
    info.kind === "api"
      ? `${t("error_ticket_preset_kind_api")}${info.statusCode != null ? ` (HTTP ${info.statusCode})` : ""}`
      : t("error_ticket_preset_kind_client");
  const lines = [
    t("error_ticket_preset_intro"),
    "",
    t("error_ticket_preset_header"),
    `${t("error_ticket_preset_kind_label")}: ${kindLabel}`,
  ];
  if (info.path) {
    lines.push(`${t("error_ticket_preset_path_label")}: ${info.path}`);
  }
  if (info.requestId) {
    lines.push(`${t("error_ticket_preset_request_id_label")}: ${info.requestId}`);
  }
  lines.push(`${t("error_ticket_preset_message_label")}: ${info.message}`);
  lines.push(`${t("error_ticket_preset_time_label")}: ${new Date(info.occurredAt).toISOString()}`);
  return lines.join("\n");
}
