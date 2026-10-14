import { useSettingsStore } from "../stores/settingsStore";
import { useI18n } from "../i18n/context";
import { HeaderMenuItem } from "./ui/HeaderMenuItem";

/**
 * Header menu row that switches the interface language.
 * 顶栏菜单中的界面语言切换项。
 */
export function LanguageToggle() {
  const { t } = useI18n();
  const language = useSettingsStore((s) => s.language);
  const setLanguage = useSettingsStore((s) => s.setLanguage);
  const targetLanguage = language === "zh" ? "en" : "zh";

  return (
    <HeaderMenuItem
      testId="header-menu-language"
      label={t("app_toggle_language")}
      onSelect={() => setLanguage(targetLanguage)}
      trailing={
        <span
          lang={targetLanguage}
          className="shrink-0 text-xs font-medium text-slate-500 dark:text-slate-400"
        >
          {t("header_menu_language_target")}
        </span>
      }
      icon={
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18" />
          <path d="M12 3a13.5 13.5 0 0 1 0 18 13.5 13.5 0 0 1 0-18Z" />
        </svg>
      }
    />
  );
}
