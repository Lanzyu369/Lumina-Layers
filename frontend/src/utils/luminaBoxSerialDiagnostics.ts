import type { LuminaBoxSerialDiagnosticSnapshot } from "../stores/luminaBoxSerialStore";

/** Format a connection trace without including sample measurements.
 * 整理连接过程记录，不包含样片测量数据。 */
export function formatLuminaBoxSerialDiagnostics(snapshot: LuminaBoxSerialDiagnosticSnapshot): string {
  return JSON.stringify({
    version: 1, status: snapshot.status, mode: snapshot.mode, captureId: snapshot.captureId,
    receivedBytes: snapshot.receivedBytes, appliedCount: snapshot.receivedCount,
    pendingCount: snapshot.pendingCount, lastHeartbeatAt: snapshot.lastHeartbeatAt,
    issue: snapshot.issue, lastError: snapshot.lastError, trace: snapshot.trace,
  }, null, 2);
}

type DiagnosticSaveResult = { status: "saved" | "cancelled" | "error"; error?: string };
type DiagnosticDesktopBridge = { saveConnectionDiagnostics?: (text: string) => Promise<DiagnosticSaveResult> };

/** Save diagnostics through the trusted desktop bridge or a browser download.
 * 通过受信桌面桥接或浏览器下载保存诊断。 */
export async function downloadLuminaBoxSerialDiagnostics(
  snapshot: LuminaBoxSerialDiagnosticSnapshot,
): Promise<"saved" | "cancelled"> {
  const text = formatLuminaBoxSerialDiagnostics(snapshot);
  const desktop = (window as Window & { electronAPI?: DiagnosticDesktopBridge }).electronAPI;
  if (desktop) {
    if (!desktop.saveConnectionDiagnostics) throw new Error("desktop_restart_required");
    const result = await desktop.saveConnectionDiagnostics(text);
    if (result.status === "error") throw new Error(result.error ?? "save_failed");
    return result.status;
  }
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "lumina-box-connection.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return "saved";
}
