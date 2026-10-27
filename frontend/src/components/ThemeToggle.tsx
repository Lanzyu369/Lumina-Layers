import { useSettingsStore } from "../stores/settingsStore";
import { useI18n } from "../i18n/context";
import { HeaderMenuItem } from "./ui/HeaderMenuItem";

/**
 * Header menu row that turns dark mode on or off.
 * 顶栏菜单中的深色模式开关项。
 */
export function ThemeToggle() {
  const { t } = useI18n();
  const theme = useSettingsStore((s) => s.theme);
  const setTheme = useSettingsStore((s) => s.setTheme);
  const isDark = theme === "dark";

  return (
    <HeaderMenuItem
      testId="header-menu-theme"
      label={t("header_menu_dark_mode")}
      pressed={isDark}
      onSelect={() => setTheme(isDark ? "light" : "dark")}
      trailing={<SwitchIndicator on={isDark} />}
      icon={
        <svg
          data-testid="theme-icon-moon"
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
      }
    />
  );
}

function SwitchIndicator({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors duration-200 ${
        on ? "bg-blue-600" : "bg-slate-300 dark:bg-slate-600"
      }`}
    >
      <span
        className={`h-3 w-3 rounded-full bg-slate-50 transition-transform duration-200 ${
          on ? "translate-x-3.5" : "translate-x-0.5"
        }`}
      />
    </span>
  );
}
