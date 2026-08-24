import { useSettingsStore } from "../stores/settingsStore";
import { useI18n } from "../i18n/context";
import { HEADER_ICON_BUTTON_CLASS } from "./ui/headerControls";

export function LanguageToggle() {
  const { t } = useI18n();
  const language = useSettingsStore((s) => s.language);
  const setLanguage = useSettingsStore((s) => s.setLanguage);

  const handleToggle = () => {
    setLanguage(language === "zh" ? "en" : "zh");
  };

  return (
    <button
      type="button"
      onClick={handleToggle}
      aria-label={t("app_toggle_language")}
      title={t("app_toggle_language")}
      className={`${HEADER_ICON_BUTTON_CLASS} text-xs font-semibold`}
    >
      {language === "zh" ? "EN" : "中"}
    </button>
  );
}
