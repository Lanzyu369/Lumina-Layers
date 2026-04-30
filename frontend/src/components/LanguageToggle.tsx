import { useSettingsStore } from "../stores/settingsStore";
import { useI18n } from "../i18n/context";

export function LanguageToggle() {
  const { t } = useI18n();
  const language = useSettingsStore((s) => s.language);
  const setLanguage = useSettingsStore((s) => s.setLanguage);

  const handleToggle = () => {
    setLanguage(language === "zh" ? "en" : "zh");
  };

  return (
    <button
      onClick={handleToggle}
      aria-label={t("app_toggle_language")}
      className="px-3 py-1 rounded text-sm font-medium bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors"
    >
      {language === "zh" ? "EN" : "中"}
    </button>
  );
}
