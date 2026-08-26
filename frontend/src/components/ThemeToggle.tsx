import { useEffect } from "react";
import { useSettingsStore } from "../stores/settingsStore";
import { useI18n } from "../i18n/context";
import { HEADER_ICON_BUTTON_CLASS } from "./ui/headerControls";
import { HeaderTooltip } from "./ui/HeaderTooltip";

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
    <HeaderTooltip label={t("app_toggle_theme")}>
      <button
        type="button"
        onClick={handleToggle}
        aria-label={t("app_toggle_theme")}
        className={HEADER_ICON_BUTTON_CLASS}
      >
        {theme === "light" ? (
          <svg
            data-testid="theme-icon-moon"
            aria-hidden="true"
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" />
          </svg>
        ) : (
          <svg
            data-testid="theme-icon-sun"
            aria-hidden="true"
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2" />
            <path d="M12 20v2" />
            <path d="m4.93 4.93 1.41 1.41" />
            <path d="m17.66 17.66 1.41 1.41" />
            <path d="M2 12h2" />
            <path d="M20 12h2" />
            <path d="m6.34 17.66-1.41 1.41" />
            <path d="m19.07 4.93-1.41 1.41" />
          </svg>
        )}
      </button>
    </HeaderTooltip>
  );
}
