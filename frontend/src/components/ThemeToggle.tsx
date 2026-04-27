import { useEffect } from "react";
import { useSettingsStore } from "../stores/settingsStore";
import { useI18n } from "../i18n/context";

export function ThemeToggle() {
  const { t } = useI18n();
  const theme = useSettingsStore((s) => s.theme);
  const setTheme = useSettingsStore((s) => s.setTheme);

  // Initialize dark class on mount based on current theme
  useEffect(() => {
    if (theme === "dark") {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [theme]);

  const handleToggle = () => {
    setTheme(theme === "light" ? "dark" : "light");
  };

  return (
    <button
      onClick={handleToggle}
      aria-label={t("app_toggle_theme")}
      className="px-3 py-1 rounded text-sm font-medium bg-slate-200 text-slate-700 hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600 transition-colors"
    >
      {theme === "light" ? "🌙" : "☀️"}
    </button>
  );
}
