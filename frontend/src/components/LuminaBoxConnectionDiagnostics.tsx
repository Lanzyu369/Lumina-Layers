import { useState } from "react";
import { useI18n } from "../i18n/context";
import type { LuminaBoxSerialDiagnosticSnapshot } from "../stores/luminaBoxSerialStore";
import { downloadLuminaBoxSerialDiagnostics, formatLuminaBoxSerialDiagnostics } from "../utils/luminaBoxSerialDiagnostics";
import Button from "./ui/Button";
import { StatusBanner, wellClass } from "./ui/panelPrimitives";

export default function LuminaBoxConnectionDiagnostics({ snapshot }: { snapshot: LuminaBoxSerialDiagnosticSnapshot }) {
  const { t } = useI18n();
  const [text, setText] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<"saved" | "failed" | "restart" | null>(null);
  const save = async () => {
    setText(formatLuminaBoxSerialDiagnostics(snapshot));
    setSaving(true);
    setResult(null);
    try {
      if (await downloadLuminaBoxSerialDiagnostics(snapshot) === "saved") setResult("saved");
    } catch (error: unknown) {
      setResult(error instanceof Error && error.message === "desktop_restart_required" ? "restart" : "failed");
    } finally { setSaving(false); }
  };
  return (
    <div className="space-y-3" data-testid="lumina-box-connection-diagnostics">
      <div className="flex flex-wrap gap-2">
        <Button label={t("lumina_box_serial_diagnostics_view")} size="sm" variant="secondary"
          onClick={() => setText(formatLuminaBoxSerialDiagnostics(snapshot))} data-testid="lumina-box-diagnostics-view" />
        <Button label={t("lumina_box_serial_diagnostics")} size="sm" variant="secondary" loading={saving}
          onClick={() => void save()} data-testid="lumina-box-diagnostics-save" />
      </div>
      {result ? <StatusBanner tone={result === "saved" ? "info" : "warning"}>
        {t(result === "saved" ? "lumina_box_serial_diagnostics_saved"
          : result === "restart" ? "lumina_box_serial_diagnostics_restart" : "lumina_box_serial_diagnostics_failed")}
      </StatusBanner> : null}
      {text !== null ? <div className="space-y-2">
        <p className="text-xs text-slate-500 dark:text-slate-400">{t("lumina_box_serial_diagnostics_copy_hint")}</p>
        <textarea readOnly value={text} rows={12} onFocus={(event) => event.currentTarget.select()}
          aria-label={t("lumina_box_serial_diagnostics_view")} data-testid="lumina-box-diagnostics-text"
          className={`${wellClass} w-full resize-y px-3 py-2 font-mono text-xs text-slate-900 dark:text-slate-100`} />
      </div> : null}
    </div>
  );
}
