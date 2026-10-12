import { useState } from "react";
import { useI18n } from "../../i18n/context";
import { useSettingsStore } from "../../stores/settingsStore";
import {
  canPickGeneratedFileDirectory,
  pickGeneratedFileDirectory,
} from "../../integrations/electron";
import Button from "../ui/Button";
import HelpDot from "../ui/HelpDot";

/**
 * Desktop-only setting for the folder generated-file save dialogs open in.
 * 仅桌面版显示：生成文件保存对话框默认打开的文件夹。
 *
 * Browsers cannot control where downloads land, so the row is hidden there.
 * 浏览器无法控制下载位置，因此网页版不显示此项。
 */
export default function GeneratedFileDirectorySetting() {
  const { t } = useI18n();
  const directory = useSettingsStore((s) => s.generatedFileDirectory);
  const setDirectory = useSettingsStore((s) => s.setGeneratedFileDirectory);
  const [picking, setPicking] = useState(false);
  const [pickFailed, setPickFailed] = useState(false);

  if (!canPickGeneratedFileDirectory()) {
    return null;
  }

  const handleChoose = async () => {
    setPicking(true);
    setPickFailed(false);
    try {
      const chosen = await pickGeneratedFileDirectory();
      if (chosen) setDirectory(chosen);
    } catch {
      setPickFailed(true);
    } finally {
      setPicking(false);
    }
  };

  return (
    <div
      data-testid="settings-generated-file-directory-section"
      className="flex flex-col gap-3 border-t border-slate-200/60 pt-5 dark:border-slate-700/60"
    >
      <div className="min-w-0">
        <h3 className="flex items-center gap-1.5 text-base font-semibold text-slate-900 dark:text-slate-50">
          <span>{t("settings.generated_file_directory_heading")}</span>
          <HelpDot
            title={t("settings.generated_file_directory_heading")}
            description={t("settings.generated_file_directory_description")}
          />
        </h3>
      </div>
      <p
        data-testid="settings-generated-file-directory-value"
        className="break-all rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:text-slate-200"
        title={directory || undefined}
      >
        {directory || t("settings.generated_file_directory_system_default")}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          label={t("settings.generated_file_directory_choose")}
          variant="secondary"
          size="sm"
          onClick={() => void handleChoose()}
          disabled={picking}
          loading={picking}
        />
        <Button
          label={t("settings.generated_file_directory_reset")}
          variant="secondary"
          size="sm"
          onClick={() => setDirectory("")}
          disabled={picking || !directory}
        />
      </div>
      {pickFailed && (
        <p role="alert" className="text-xs text-red-500 dark:text-red-400">
          {t("settings.generated_file_directory_pick_failed")}
        </p>
      )}
    </div>
  );
}
