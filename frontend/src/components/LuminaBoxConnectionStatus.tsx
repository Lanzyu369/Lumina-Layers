import { useI18n } from "../i18n/context";
import Button from "./ui/Button";

export default function LuminaBoxConnectionStatus({ status, onConnect, onDisconnect, disabled, reconnectAttempt, maxReconnectAttempts }: {
  status: "connected" | "connecting" | "disconnected" | "disconnecting" | "handshaking" | "recovering";
  onConnect: () => void;
  onDisconnect: () => void;
  disabled?: boolean;
  reconnectAttempt?: number;
  maxReconnectAttempts?: number;
}) {
  const { t } = useI18n();

  const statusConfig: Record<string, { color: string; bgColor: string; label: string }> = {
    connected: {
      color: "text-green-600 dark:text-green-400",
      bgColor: "bg-green-50 dark:bg-green-900/20",
      label: t("lumina_box_connection_status_good"),
    },
    connecting: {
      color: "text-blue-600 dark:text-blue-400",
      bgColor: "bg-blue-50 dark:bg-blue-900/20",
      label: reconnectAttempt && maxReconnectAttempts
        ? t("lumina_box_reconnecting_attempt").replace("{attempt}", String(reconnectAttempt)).replace("{max}", String(maxReconnectAttempts))
        : t("lumina_box_material_connecting"),
    },
    handshaking: {
      color: "text-blue-600 dark:text-blue-400",
      bgColor: "bg-blue-50 dark:bg-blue-900/20",
      label: t("lumina_box_serial_handshaking"),
    },
    recovering: {
      color: "text-yellow-600 dark:text-yellow-400",
      bgColor: "bg-yellow-50 dark:bg-yellow-900/20",
      label: t("lumina_box_serial_recovering"),
    },
    disconnected: {
      color: "text-slate-500 dark:text-slate-400",
      bgColor: "bg-slate-50 dark:bg-slate-800/50",
      label: t("lumina_box_connection_status_disconnected"),
    },
    disconnecting: {
      color: "text-slate-600 dark:text-slate-400",
      bgColor: "bg-slate-50 dark:bg-slate-800/50",
      label: t("lumina_box_serial_disconnecting"),
    },
  };

  const config = statusConfig[status] || statusConfig.disconnected;

  return (
    <div className="flex flex-wrap items-center gap-3" data-testid="lumina-box-connection-status">
      <div className={`flex items-center gap-2 rounded-lg px-3 py-2 ${config.bgColor}`}>
        <div className={`h-2 w-2 rounded-full ${status === "connected" ? "bg-green-500" : status === "disconnected" ? "bg-slate-400" : "bg-blue-500"}`} />
        <span className={`text-sm font-medium ${config.color}`} role="status">
          {config.label}
        </span>
      </div>
      {status === "disconnected" ? (
        <Button
          label={t("lumina_box_serial_connect")}
          size="sm"
          disabled={disabled}
          onClick={onConnect}
        />
      ) : (
        <Button
          label={t("lumina_box_serial_disconnect")}
          size="sm"
          variant="secondary"
          disabled={status === "disconnecting"}
          onClick={onDisconnect}
        />
      )}
    </div>
  );
}
